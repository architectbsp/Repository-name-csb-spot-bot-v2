from __future__ import annotations

import threading
from datetime import datetime, timedelta

from .job import Job


class Scheduler:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._running = False
        # R1: Worker tick vs register/unregister from engine / WatchList.
        self._lock = threading.RLock()

    def register(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.name] = job

    def unregister(self, name: str) -> None:
        with self._lock:
            self._jobs.pop(name, None)

    def get(self, name: str) -> Job | None:
        with self._lock:
            return self._jobs.get(name)

    def has_job(self, name: str) -> bool:
        with self._lock:
            return name in self._jobs

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def jobs(self) -> dict[str, Job]:
        with self._lock:
            return self._jobs.copy()

    def start(self) -> None:
        with self._lock:
            self._running = True

    def stop(self) -> None:
        with self._lock:
            self._running = False

    def schedule(self, job: Job) -> None:
        job.next_run = datetime.now() + timedelta(seconds=job.interval)

    def is_due(self, job: Job) -> bool:
        if not job.enabled:
            return False

        if job.running:
            return False

        if job.next_run is None:
            return False

        return datetime.now() >= job.next_run

    def run_job(self, job: Job) -> None:
        job.running = True

        try:
            job.callback()
            job.last_run = datetime.now()
            self.schedule(job)
        finally:
            job.running = False

    def run_pending(self) -> None:
        # Snapshot job list under lock; run callbacks outside so a job
        # may register/unregister without self-deadlock on RLock... wait,
        # RLock would allow same-thread reentry. Other threads need the
        # lock free during long callbacks (e.g. WatchList process_cooldowns).
        with self._lock:
            jobs = list(self._jobs.values())

        for job in jobs:
            if self.is_due(job):
                self.run_job(job)

    def tick(self) -> None:
        with self._lock:
            if not self._running:
                return

        self.run_pending()
