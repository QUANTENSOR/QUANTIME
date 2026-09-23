"""退避重试（QNT-45 第 2 项）——时钟注入，测试既不等待也不出网。

卡验收关心三件事：失败会重试、重试**之间有退避**、两个上限（次数 / 总时长）都拦得住。
变异点 (a)「去掉退避」必须在这里变红。
"""

from __future__ import annotations

import pytest
from quantime_data.retry import (
    RetryContext,
    RetryExhaustedError,
    RetryPolicy,
    RetryRecorder,
    is_retryable,
    retry_call,
)
from quantime_data.spec import IngestError
from quantime_data.transport import RateLimitedError


class FakeClock:
    """`sleep` 只推进读数，不真的等——重试测试因此是毫秒级的。"""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def monotonic(self) -> float:
        return self.now


def _flaky(failures: int, exc: BaseException | None = None):
    """前 `failures` 次抛限流，之后回 `"ok"`。"""
    state = {"n": 0}

    def call() -> str:
        state["n"] += 1
        if state["n"] <= failures:
            raise exc or RateLimitedError(f"429 第 {state['n']} 次")
        return "ok"

    return call, state


# ---- 退避阶梯 ----


def test_delay_grows_exponentially_and_is_capped():
    policy = RetryPolicy(base_delay=1.0, multiplier=2.0, max_delay=8.0)
    assert [policy.delay_for(i) for i in range(1, 6)] == [1.0, 2.0, 4.0, 8.0, 8.0]


def test_delay_for_rejects_attempt_zero():
    with pytest.raises(ValueError):
        RetryPolicy().delay_for(0)


@pytest.mark.parametrize(
    "kw",
    [{"max_attempts": 0}, {"base_delay": -1}, {"max_delay": -1}, {"multiplier": 0.5}],
)
def test_nonsensical_policies_are_rejected_at_construction(kw):
    """退避参数写错就是"不退避"——构造期拒绝，不等到线上才发现。"""
    with pytest.raises(ValueError):
        RetryPolicy(**kw)


# ---- 重试确实发生，且**之间有退避** ----


def test_a_transient_failure_is_retried_and_then_succeeds():
    clock = FakeClock()
    call, state = _flaky(2)
    recorder = RetryRecorder()
    got = retry_call(
        call,
        policy=RetryPolicy(base_delay=1.0, multiplier=2.0),
        recorder=recorder,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        label="BTCUSDT-1d-2026-08.zip",
    )
    assert got == "ok"
    assert state["n"] == 3
    assert recorder.retries == 2


def test_every_retry_is_preceded_by_an_exponential_wait():
    """变异点 (a)：删掉 `sleep(wait)` 这一步，本用例立刻变红。

    没有退避的"重试"是对限流中的上游连打 N 次——既拿不到数据，还把限流拖长。
    """
    clock = FakeClock()
    call, _ = _flaky(3)
    retry_call(
        call,
        policy=RetryPolicy(max_attempts=4, base_delay=1.0, multiplier=2.0),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    assert clock.slept == [1.0, 2.0, 4.0]
    assert clock.monotonic() == pytest.approx(7.0)


def test_a_call_that_succeeds_first_try_never_sleeps():
    clock = FakeClock()
    recorder = RetryRecorder()
    assert (
        retry_call(
            lambda: "ok",
            policy=RetryPolicy(),
            recorder=recorder,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )
        == "ok"
    )
    assert clock.slept == []
    assert recorder.retries == 0
    assert recorder.attempts == 1


# ---- 两个上限 ----


def test_attempt_cap_stops_and_raises_with_the_last_cause():
    clock = FakeClock()
    call, state = _flaky(99)
    with pytest.raises(RetryExhaustedError) as err:
        retry_call(
            call,
            policy=RetryPolicy(max_attempts=3, base_delay=1.0),
            sleep=clock.sleep,
            monotonic=clock.monotonic,
            label="kline",
        )
    assert state["n"] == 3
    assert clock.slept == [1.0, 2.0]  # 最后一次失败之后不再等
    assert isinstance(err.value.__cause__, RateLimitedError)


def test_total_time_budget_stops_before_starting_a_wait_it_cannot_afford():
    """次数还没用完，但墙钟预算不够下一次等待——就地停手。

    没有这个上限，一个卡在限流里的 symbol 能把 timer 的整个窗口占满，
    后面的 symbol 一个都轮不上。
    """
    clock = FakeClock()
    call, state = _flaky(99)
    with pytest.raises(RetryExhaustedError):
        retry_call(
            call,
            policy=RetryPolicy(
                max_attempts=10, base_delay=1.0, multiplier=2.0, max_total_seconds=5.0
            ),
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )
    assert clock.slept == [1.0, 2.0]  # 再等 4s 会超过 5s 预算
    assert state["n"] == 3
    assert clock.monotonic() <= 5.0


# ---- 什么值得重试 ----


def test_upstream_404_is_not_retried():
    """整档缺失不是故障——重试它只会每天白打一轮，并把真正的缺口淹没。"""
    assert is_retryable(FileNotFoundError("404")) is False
    clock = FakeClock()
    calls = {"n": 0}

    def call():
        calls["n"] += 1
        raise FileNotFoundError("404")

    with pytest.raises(FileNotFoundError):
        retry_call(call, policy=RetryPolicy(), sleep=clock.sleep, monotonic=clock.monotonic)
    assert calls["n"] == 1
    assert clock.slept == []


def test_a_checksum_mismatch_is_not_retried():
    """字节对不上 `.CHECKSUM` 是确定性错误，重试同一个坏归档没有意义。"""
    assert is_retryable(IngestError("sha256 不符")) is False
    with pytest.raises(IngestError):
        retry_call(
            lambda: (_ for _ in ()).throw(IngestError("sha256 不符")),
            policy=RetryPolicy(),
            sleep=lambda _: None,
        )


def test_rate_limit_and_network_errors_are_retryable():
    assert is_retryable(RateLimitedError("429")) is True
    assert is_retryable(ConnectionResetError("peer reset")) is True
    assert is_retryable(TimeoutError("read timeout")) is True


def test_a_programming_error_is_not_swallowed_as_a_network_blip():
    with pytest.raises(TypeError):
        retry_call(
            lambda: (_ for _ in ()).throw(TypeError("bug")),
            policy=RetryPolicy(),
            sleep=lambda _: None,
        )


# ---- 记账 ----


def test_the_context_accumulates_retries_across_several_archives():
    """一次运行里跨归档累加——报告的「重试次数」取的就是它。"""
    clock = FakeClock()
    ctx = RetryContext(
        policy=RetryPolicy(base_delay=1.0), sleep=clock.sleep, monotonic=clock.monotonic
    )
    for name, failures in (("a.zip", 1), ("b.zip", 2)):
        call, _ = _flaky(failures)
        ctx.run(call, label=name)
    assert ctx.retries == 3
    assert [ln.split(":")[0] for ln in ctx.log_lines()] == ["a.zip", "b.zip", "b.zip"]


def test_the_retry_log_records_both_the_reason_and_the_wait():
    """运维看到的就是这几行；没有等待时长就没法判断「今天比昨天更差」。"""
    clock = FakeClock()
    ctx = RetryContext(
        policy=RetryPolicy(base_delay=1.5), sleep=clock.sleep, monotonic=clock.monotonic
    )
    call, _ = _flaky(1)
    ctx.run(call, label="BTCUSDT-1d-2026-08.zip")
    (line,) = ctx.log_lines()
    assert "BTCUSDT-1d-2026-08.zip" in line
    assert "RateLimitedError" in line
    assert "退避 1.5s" in line


def test_the_log_line_for_an_exhausted_budget_says_so():
    clock = FakeClock()
    ctx = RetryContext(
        policy=RetryPolicy(max_attempts=9, base_delay=4.0, max_total_seconds=3.0),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    call, _ = _flaky(99)
    with pytest.raises(RetryExhaustedError):
        ctx.run(call, label="oi")
    assert any("重试预算耗尽" in ln for ln in ctx.log_lines())
