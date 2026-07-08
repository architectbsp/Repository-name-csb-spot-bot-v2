from app.core.stopwatch.stopwatch import Stopwatch


def test_stopwatch():
    sw = Stopwatch()

    assert not sw.is_running()

    sw.start()

    assert sw.is_running()

    elapsed = sw.stop()

    assert elapsed >= 0
    assert not sw.is_running()
