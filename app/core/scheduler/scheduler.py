from __future__ import annotations

from datetime import datetime, timedelta

from .job import Job


class Scheduler:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def register(self, job: Job) -> None:
        self._jobs[job.name] = job

    def unregister(self, name: str) -> None:
        self._jobs.pop(name, None)

    def get(self, name: str) -> Job | None:
        return self._jobs.get(name)

    def has_job(self, name: str) -> bool:
        return name in self._jobs

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

    def tick(self) -> None:
        for job in self._jobs.values():
            if self.is_due(job):
                self.run_job(job)

    @property
    def jobs(self) -> dict[str, Job]:
        return self._jobs.copy()
