"""失败重试（QNT-45 第 2 项）——**源无关**的退避策略。

`transport.PublicTransport` 已经在单个 HTTP 请求内按状态码退避（429/5xx + `Retry-After`）。
这一层管的是它之上的事：一个归档整体取失败（退避用尽、连接断、超时）时，隔一段时间**整件
重来**，直到次数上限或总时长上限。两层各管各的，不互相替代——前者答「这一次请求要不要再
等一下」，后者答「这个文件今天还要不要再试」。

哪些异常该重试是**语义判断**，不是分类学：

* 上游 404（`FileNotFoundError`）→ 不重试。那不是失败，是这段区间上游就没有归档。
* 校验不过 / 区间非法（`IngestError`）→ 不重试。重试一百次得到的还是同样可疑的字节。
* 限流、5xx、连接与超时（`RateLimitedError`、`OSError` 及其子类）→ 重试。

策略可注入 `sleep` / `monotonic`，所以测试里既不等待也不出网。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .spec import IngestError
from .transport import RateLimitedError

#: 默认：首次等 1s，每次翻倍，单次不超过 60s，最多试 4 次，整体不超过 300s。
DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MULTIPLIER = 2.0
DEFAULT_MAX_DELAY = 60.0
DEFAULT_MAX_TOTAL_SECONDS = 300.0

#: 可重试的异常。`RateLimitedError` 是 transport 退避用尽后的信号；
#: `OSError` 覆盖连接重置 / DNS / 超时（`TimeoutError` 在 3.3+ 是 `OSError` 子类）。
RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (RateLimitedError, OSError)

#: **绝不**重试的异常，即使它恰好是上面某一类的子类。
#: `FileNotFoundError` 是 `OSError` 的子类，但它在摄取语义里表示「上游整档不存在」——
#: 那是覆盖不全，要如实记账并交给补采白名单，不是靠重试能解决的故障。
NON_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (FileNotFoundError, IngestError)


class RetryExhaustedError(RuntimeError):
    """重试次数或总时长用尽，最后一次仍然失败。原异常在 `__cause__` 里。"""


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """指数退避参数。两个上限都可配（卡要求「可配置次数上限与总时长」）。

    `max_attempts` 是**总尝试次数**（含第一次），`>= 1`；`max_total_seconds` 是本次
    重试预算的墙钟上限——预算耗尽就不再起新的尝试，哪怕次数还没用完。没有总时长上限时，
    一个卡在限流里的 symbol 能把 timer 的整个窗口占满，后面的 symbol 一个都轮不上。
    """

    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    base_delay: float = DEFAULT_BASE_DELAY
    multiplier: float = DEFAULT_MULTIPLIER
    max_delay: float = DEFAULT_MAX_DELAY
    max_total_seconds: float = DEFAULT_MAX_TOTAL_SECONDS

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts 至少为 1")
        if self.base_delay < 0 or self.max_delay < 0 or self.max_total_seconds < 0:
            raise ValueError("退避参数不得为负")
        if self.multiplier < 1:
            raise ValueError("multiplier 至少为 1（否则退避会越来越短）")

    def delay_for(self, attempt: int) -> float:
        """第 `attempt` 次失败之后、下一次尝试之前等待的秒数（`attempt` 从 1 起）。

        指数阶梯 `base * multiplier**(attempt-1)`，封顶 `max_delay`。不加 jitter：
        jitter 属于 `transport` 那一层（单请求限流），这一层要的是**可复现的日志**
        ——运维看到的等待序列每次都一样，才好判断「今天比昨天更差」。
        """
        if attempt < 1:
            raise ValueError("attempt 从 1 起")
        return min(self.base_delay * (self.multiplier ** (attempt - 1)), self.max_delay)


@dataclass(slots=True)
class RetryRecorder:
    """记录一次运行里实际发生的重试——报告里的「重试次数」直接取自它。"""

    attempts: int = 0
    slept: list[float] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def retries(self) -> int:
        """重试次数 = 尝试次数 - 成功那一次（第一次不算重试）。"""
        return len(self.slept)

    @property
    def total_slept(self) -> float:
        return sum(self.slept)


def is_retryable(exc: BaseException) -> bool:
    """该异常值不值得再试一次——`NON_RETRYABLE_EXCEPTIONS` 优先于可重试类。"""
    if isinstance(exc, NON_RETRYABLE_EXCEPTIONS):
        return False
    return isinstance(exc, RETRYABLE_EXCEPTIONS)


def retry_call[T](
    fn: Callable[[], T],
    *,
    policy: RetryPolicy,
    recorder: RetryRecorder | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    label: str = "",
) -> T:
    """调用 `fn`，失败则按 `policy` 退避重试。

    退避**必须**发生：去掉 `sleep` 这一步，重试就退化成对限流中的上游连打 N 次，
    既拿不到数据又加重限流（QNT-45 变异点 a）。
    """
    recorder = recorder if recorder is not None else RetryRecorder()
    started = monotonic()
    last: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        recorder.attempts += 1
        try:
            return fn()
        except BaseException as exc:  # noqa: BLE001 —— 立刻按语义分流，不吞
            if not is_retryable(exc):
                raise
            last = exc
            recorder.reasons.append(f"{label or 'call'}: {type(exc).__name__}: {exc}")
            if attempt >= policy.max_attempts:
                break
            wait = policy.delay_for(attempt)
            elapsed = monotonic() - started
            if elapsed + wait > policy.max_total_seconds:
                recorder.reasons.append(
                    f"{label or 'call'}: 重试预算耗尽"
                    f"（已用 {elapsed:.1f}s + 需等 {wait:.1f}s > {policy.max_total_seconds:.1f}s）"
                )
                break
            recorder.slept.append(wait)
            sleep(wait)
    raise RetryExhaustedError(
        f"{label or 'call'}：重试 {recorder.attempts} 次后仍失败（{type(last).__name__}: {last}）"
    ) from last


@dataclass(slots=True)
class RetryContext:
    """把「策略 + 记账 + 时钟」绑成一个可注入对象，摄取链路只认它。

    `ingest.fetch_files` 收到 `retry=None` 就一次都不重试（纯函数式的老行为，单测用）；
    收到一个 context 就每个归档都过退避。时钟可注入，所以重试测试既不等待也不出网。
    """

    policy: RetryPolicy = field(default_factory=RetryPolicy)
    recorder: RetryRecorder = field(default_factory=RetryRecorder)
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic

    def run[T](self, fn: Callable[[], T], *, label: str = "") -> T:
        return retry_call(
            fn,
            policy=self.policy,
            recorder=self.recorder,
            sleep=self.sleep,
            monotonic=self.monotonic,
            label=label,
        )

    @property
    def retries(self) -> int:
        return self.recorder.retries

    def log_lines(self) -> list[str]:
        """重试日志（进运行记录与报告）：每行一次失败与它之后的等待。"""
        lines: list[str] = []
        for i, reason in enumerate(self.recorder.reasons):
            wait = self.recorder.slept[i] if i < len(self.recorder.slept) else None
            lines.append(reason if wait is None else f"{reason} → 退避 {wait:g}s 后重试")
        return lines
