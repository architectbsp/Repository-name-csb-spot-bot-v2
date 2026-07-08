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
