"""
R5 -- durable ClientOrderId registry for execution idempotency.

Every logical BUY/SELL gets one ``client_order_id`` that is persisted
*before* the exchange submit and reused across:
  - in-process REST retries (network / insufficient-funds policy)
  - process restart while a submit is still PENDING / AMBIGUOUS

Sidecar JSON only -- does not touch the SQLite schema.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = frozenset({"PENDING", "SUBMITTED", "AMBIGUOUS"})


@dataclass(slots=True)
class ClientOrderRecord:
    client_order_id: str
    exchange: str
    symbol: str
    side: str
    quantity: str
    status: str
    exchange_order_id: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0

    def is_active(self) -> bool:
        return self.status in _ACTIVE_STATUSES


def new_client_order_id() -> str:
    """Opaque, exchange-safe id (Binance newClientOrderId length limit)."""
    return f"csb{uuid.uuid4().hex}"[:32]


class ClientOrderRegistry:
    """Thread-safe in-memory + optional JSON sidecar registry."""

    def __init__(self, store_path: str | Path | None = None) -> None:
        self._lock = threading.Lock()
        self._store_path: Path | None = Path(store_path) if store_path else None
        self._by_id: dict[str, ClientOrderRecord] = {}
        # One active logical order per market key (exchange:symbol).
        self._active_by_market: dict[str, str] = {}
        self._load()

    def set_store_path(self, path: str | Path | None) -> None:
        with self._lock:
            self._store_path = Path(path) if path else None
            self._load_unlocked()

    def begin_logical_trade(
        self,
        *,
        market_key: str,
        exchange: str,
        symbol: str,
        side: str,
        quantity: Any,
    ) -> str:
        """
        Return the client_order_id for this logical trade.

        If an active (PENDING/SUBMITTED/AMBIGUOUS) record already exists
        for ``market_key``, reuse it so retries and restarts stay
        idempotent. Otherwise allocate a fresh id and persist PENDING
        *before* the caller submits to the exchange.
        """
        qty = str(quantity)
        now = time.time()
        with self._lock:
            existing_id = self._active_by_market.get(market_key)
            if existing_id:
                record = self._by_id.get(existing_id)
                if record is not None and record.is_active():
                    record.updated_at = now
                    self._persist_unlocked()
                    return record.client_order_id

            cid = new_client_order_id()
            record = ClientOrderRecord(
                client_order_id=cid,
                exchange=str(exchange),
                symbol=str(symbol),
                side=str(side),
                quantity=qty,
                status="PENDING",
                created_at=now,
                updated_at=now,
            )
            self._by_id[cid] = record
            self._active_by_market[market_key] = cid
            self._persist_unlocked()
            return cid

    def mark_submitted(
        self,
        client_order_id: str,
        exchange_order_id: str | None = None,
    ) -> None:
        with self._lock:
            record = self._by_id.get(client_order_id)
            if record is None:
                return
            # Preserve AMBIGUOUS; only attach venue order id.
            if record.status != "AMBIGUOUS":
                record.status = "SUBMITTED"
            if exchange_order_id:
                record.exchange_order_id = str(exchange_order_id)
            record.updated_at = time.time()
            self._persist_unlocked()

    def mark_completed(
        self,
        client_order_id: str,
        *,
        market_key: str | None = None,
        exchange_order_id: str | None = None,
    ) -> None:
        with self._lock:
            record = self._by_id.get(client_order_id)
            if record is not None:
                record.status = "COMPLETED"
                if exchange_order_id:
                    record.exchange_order_id = str(exchange_order_id)
                record.updated_at = time.time()
            self._clear_active_unlocked(market_key, client_order_id)
            self._persist_unlocked()

    def mark_failed(
        self,
        client_order_id: str,
        *,
        market_key: str | None = None,
    ) -> None:
        with self._lock:
            record = self._by_id.get(client_order_id)
            if record is not None:
                record.status = "FAILED"
                record.updated_at = time.time()
            self._clear_active_unlocked(market_key, client_order_id)
            self._persist_unlocked()

    def mark_ambiguous(self, client_order_id: str) -> None:
        with self._lock:
            record = self._by_id.get(client_order_id)
            if record is None:
                return
            record.status = "AMBIGUOUS"
            record.updated_at = time.time()
            self._persist_unlocked()

    def clear_market(self, market_key: str) -> None:
        """Drop active binding (e.g. after operator clear_quarantine)."""
        with self._lock:
            cid = self._active_by_market.pop(market_key, None)
            if cid and cid in self._by_id:
                record = self._by_id[cid]
                if record.is_active():
                    record.status = "FAILED"
                    record.updated_at = time.time()
            self._persist_unlocked()

    def get(self, client_order_id: str) -> ClientOrderRecord | None:
        with self._lock:
            return self._by_id.get(client_order_id)

    def get_active_for_market(self, market_key: str) -> ClientOrderRecord | None:
        with self._lock:
            cid = self._active_by_market.get(market_key)
            if not cid:
                return None
            record = self._by_id.get(cid)
            if record is None or not record.is_active():
                return None
            return record

    def _clear_active_unlocked(
        self,
        market_key: str | None,
        client_order_id: str,
    ) -> None:
        if market_key and self._active_by_market.get(market_key) == client_order_id:
            self._active_by_market.pop(market_key, None)
            return
        for key, cid in list(self._active_by_market.items()):
            if cid == client_order_id:
                self._active_by_market.pop(key, None)

    def _load(self) -> None:
        with self._lock:
            self._load_unlocked()

    def _load_unlocked(self) -> None:
        path = self._store_path
        if path is None or not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception(
                "[CLIENT_ORDER] Failed loading registry path=%s", path
            )
            return

        records = raw.get("records") if isinstance(raw, dict) else None
        if not isinstance(records, dict):
            return

        by_id: dict[str, ClientOrderRecord] = {}
        for cid, payload in records.items():
            if not isinstance(payload, dict):
                continue
            try:
                by_id[str(cid)] = ClientOrderRecord(
                    client_order_id=str(payload.get("client_order_id") or cid),
                    exchange=str(payload.get("exchange") or ""),
                    symbol=str(payload.get("symbol") or ""),
                    side=str(payload.get("side") or ""),
                    quantity=str(payload.get("quantity") or ""),
                    status=str(payload.get("status") or "FAILED"),
                    exchange_order_id=(
                        str(payload["exchange_order_id"])
                        if payload.get("exchange_order_id") is not None
                        else None
                    ),
                    created_at=float(payload.get("created_at") or 0.0),
                    updated_at=float(payload.get("updated_at") or 0.0),
                )
            except Exception:
                logger.exception(
                    "[CLIENT_ORDER] Skipping corrupt record cid=%s", cid
                )

        active: dict[str, str] = {}
        raw_active = raw.get("active_by_market") if isinstance(raw, dict) else None
        if isinstance(raw_active, dict):
            for market, cid in raw_active.items():
                cid_s = str(cid)
                record = by_id.get(cid_s)
                if record is not None and record.is_active():
                    active[str(market)] = cid_s

        self._by_id = by_id
        self._active_by_market = active

    def _persist_unlocked(self) -> None:
        path = self._store_path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "records": {
                    cid: asdict(record) for cid, record in self._by_id.items()
                },
                "active_by_market": dict(self._active_by_market),
            }
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            tmp.replace(path)
        except Exception:
            logger.exception(
                "[CLIENT_ORDER] Failed persisting registry path=%s", path
            )
