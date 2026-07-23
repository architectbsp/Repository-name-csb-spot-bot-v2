import threading

from app.core.scheduler.scheduler import Scheduler


class Worker:
    def __init__(self, scheduler: Scheduler, interval: float = 0.1):
        self._scheduler = scheduler
        self._interval = interval
        # R1: Event stop flag is safe across Worker thread vs UI/engine stop().
        self._stop = threading.Event()
        self._active = False
        self._thread: threading.Thread | None = None

    @property
    def _running(self) -> bool:
        """Backward-compat mirror of the active flag (tests / introspection)."""
        return self._active

    def start(self) -> None:
        if self._active:
            return

        self._stop.clear()
        self._active = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._scheduler.tick()
            except Exception:
                # Worker must stay alive; scheduler handles retries.
                pass

            # Interruptible sleep so stop() does not wait a full interval.
            self._stop.wait(self._interval)

    def stop(self) -> None:
        self._stop.set()
        self._active = False

        if self._thread is not None:
            self._thread.join(timeout=1)

        self._thread = None
