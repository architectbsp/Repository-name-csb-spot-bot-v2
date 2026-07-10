import threading
import time

from app.core.scheduler.scheduler import Scheduler


class Worker:
    def __init__(self, scheduler: Scheduler, interval: float = 0.1):
        self._scheduler = scheduler
        self._interval = interval
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while self._running:
            try:
                print("[Worker] tick")
                self._scheduler.tick()
            except Exception:
                # Worker must stay alive; scheduler handles retries.
                pass

            time.sleep(self._interval)

    def stop(self) -> None:
        self._running = False

        if self._thread is not None:
            self._thread.join(timeout=1)

        self._thread = None
