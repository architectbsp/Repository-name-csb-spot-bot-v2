from datetime import datetime, timedelta

from app.core.scheduler.job import Job
from app.core.scheduler.scheduler import Scheduler


def test_scheduler_register_unregister():
    scheduler = Scheduler()

    job = Job(
        name="job",
        interval=1,
        callback=lambda: None,
    )

    scheduler.register(job)

    assert scheduler.has_job("job")

    scheduler.unregister("job")

    assert not scheduler.has_job("job")


def test_scheduler_run_job():
    called = []

    scheduler = Scheduler()

    job = Job(
        name="job",
        interval=1,
        callback=lambda: called.append(True),
    )

    job.enabled = True
    job.next_run = datetime.now() - timedelta(seconds=1)

    scheduler.run_job(job)

    assert called == [True]
    assert job.last_run is not None
