from app.core.rate_limiter.rate_limiter import RateLimiter


def test_rate_limiter():
    limiter = RateLimiter(2, 60)

    assert limiter.can_request()

    limiter.record_request()
    limiter.record_request()

    assert not limiter.can_request()
    assert limiter.request_count() == 2

    limiter.clear()

    assert limiter.request_count() == 0
