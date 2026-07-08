from datetime import timedelta

from app.core.timer.timer import Timer


def test_timer_lifecycle():
    timer = Timer(timedelta(seconds=1))

    assert timer.is_idle()

    timer.start()

    assert timer.is_started()
    assert timer.is_running()

    timer.stop()

    assert timer.is_idle()


def test_timer_remaining():
    timer = Timer(timedelta(seconds=5))

    assert timer.remaining() == timedelta(seconds=5)
