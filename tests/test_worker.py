import time
from datetime import datetime, timedelta

from app.core.scheduler.job import Job
from app.core.scheduler.scheduler import Scheduler
from app.core.worker import Worker


def test_worker_start_stop():
    scheduler = Scheduler()

    worker = Worker(
        scheduler=scheduler,
        interval=0.01,
    )

    worker.start()

    assert worker._running

    worker.stop()

    assert not worker._running


def test_worker_tick_failure_is_logged_and_notifies():
    scheduler = Scheduler()
    errors: list[BaseException] = []

    def boom() -> None:
        raise RuntimeError("tick-boom")

    job = Job(name="boom", interval=0.01, callback=boom)
    job.next_run = datetime.now() - timedelta(seconds=1)
    scheduler.register(job)
    scheduler.start()

    worker = Worker(
        scheduler,
        interval=0.01,
        on_error=errors.append,
    )
    worker.start()
    deadline = time.time() + 2.0
    while time.time() < deadline and not errors:
        time.sleep(0.02)

    assert errors, "worker must notify on_error for job failures"
    assert worker.is_thread_alive()
    assert worker.error_count >= 1
    assert worker.last_error is not None
    assert "RuntimeError" in worker.last_error
    health = worker.health()
    assert health.error_count >= 1
    assert health.last_error is not None
    assert job.last_error is not None

    worker.stop()
    assert not worker._running


def test_worker_survives_repeated_job_failures():
    scheduler = Scheduler()
    calls = {"n": 0}

    def boom() -> None:
        calls["n"] += 1
        raise ValueError("again")

    job = Job(name="boom", interval=0.01, callback=boom)
    job.next_run = datetime.now() - timedelta(seconds=1)
    scheduler.register(job)
    scheduler.start()

    worker = Worker(scheduler, interval=0.01)
    worker.start()
    deadline = time.time() + 1.0
    while time.time() < deadline and calls["n"] < 3:
        time.sleep(0.02)
    assert worker.is_thread_alive()
    worker.stop()
    assert calls["n"] >= 3
    assert worker.error_count >= 3


def test_scheduler_run_job_records_last_error():
    scheduler = Scheduler()

    def boom() -> None:
        raise RuntimeError("x")

    job = Job(name="fail", interval=1, callback=boom)
    raised = False
    try:
        scheduler.run_job(job)
    except RuntimeError:
        raised = True
    assert raised
    assert job.last_error is not None
    assert "RuntimeError" in job.last_error
