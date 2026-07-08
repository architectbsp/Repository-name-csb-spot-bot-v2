from app.core.retry_policy.retry_policy import RetryPolicy


def test_retry_policy():
    policy = RetryPolicy(3, 1)

    assert policy.max_attempts() == 3
    assert policy.delay() == 1
    assert not policy.is_last_attempt(2)
    assert policy.is_last_attempt(3)
