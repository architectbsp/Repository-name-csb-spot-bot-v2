from unittest.mock import patch

from app.core.retry_policy.retry_policy import RetryPolicy


def test_retry_policy():
    policy = RetryPolicy(3, 1)

    assert policy.max_attempts() == 3
    assert policy.delay() == 1
    assert not policy.is_last_attempt(2)
    assert policy.is_last_attempt(3)


def test_exponential_backoff_delays():
    policy = RetryPolicy(4, 10.0, backoff_factor=2.0, max_delay=50.0)

    assert policy.delay_for_attempt(1) == 10.0
    assert policy.delay_for_attempt(2) == 20.0
    assert policy.delay_for_attempt(3) == 40.0
    assert policy.delay_for_attempt(4) == 50.0  # capped


def test_execute_uses_backoff_between_attempts():
    policy = RetryPolicy(3, 0.5, backoff_factor=2.0)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    with patch("app.core.retry_policy.retry_policy.time.sleep") as sleep:
        assert policy.execute(flaky) == "ok"
        assert sleep.call_args_list[0].args[0] == 0.5
        assert sleep.call_args_list[1].args[0] == 1.0
