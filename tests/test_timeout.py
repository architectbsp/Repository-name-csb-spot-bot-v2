from app.core.timeout.timeout import Timeout


def test_timeout_enabled():
    timeout = Timeout(5)

    assert timeout.seconds() == 5
    assert not timeout.is_disabled()


def test_timeout_disabled():
    timeout = Timeout(0)

    assert timeout.is_disabled()
