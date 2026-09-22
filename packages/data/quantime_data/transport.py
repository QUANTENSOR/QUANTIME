"""公共只读 HTTP 出口（ADR-0003 §3.3「`DataSource` 唯一 HTTP 出口 `PublicTransport.get`」）。

对称于交易侧的 `PaperTransport`：**每个请求**重新校验 host 与路径，任一不满足就不发出请求。
两道闸互相独立——

1. **host 闸**：`allowlist.assert_public_readonly_host(host)`。未登记 host、以及登记为
   `public_readonly=False` 的交易 host，一律拒绝（`core/allowlist.py` 的两个断言互不放行）。
2. **路径闸**：先把路径化到无歧义形式（`canonical_path`：拒绝百分号编码、`.`/`..` 段、
   空段 `//`、反斜杠与控制字符），再按类别放行——REST 端点 `PUBLIC_READONLY_REST_PATHS`
   **精确匹配**，归档文件树 `PUBLIC_READONLY_ARCHIVE_PREFIXES` 按前缀。白名单而非黑名单：
   黑名单漏一个新端点就等于放行，白名单漏一个只是少取一类数据（fail-closed）。
   拒绝歧义输入而不是「折叠后放行」，是因为校验的字符串必须与最终发送的字符串逐字节
   相同——否则客户端/服务端各自的规范化差异就是一条绕过（verify-a R1 P1-2）。
   下单 / 账户 / 资金 / User Data Stream 路径都不在白名单内，因此**不可能**从本出口发出
   （被拒的具体端点逐条列在 `tests/test_transport.py` 的参数化用例里）。

限流：现货公共 REST 按 IP weight 计费，超限 429、反复则 418 IP ban（2 分钟–3 天）——
所以退避不是可选的礼貌，是避免被 ban 的硬要求
（`docs/research/crypto-market-and-binance-public-api.md` §4.1）。
本出口实现「最小请求间隔 + 429/418/5xx 指数退避（含 jitter，尊重 `Retry-After`）」，
重试用尽即抛 `RateLimitedError`，绝不静默返回空结果。

时钟、休眠与底层 opener 全部可注入，因此全部行为可离线测试：真正的网络只在
`cli.py` 组装默认 opener 时才出现。
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from quantime_core.allowlist import HostEntry, HostNotAllowedError, assert_public_readonly_host

#: 归档文件树的允许前缀。Vision 归档是按 symbol/freq/日期展开的目录树，文件名无法穷举，
#: 所以这一类只能按前缀放行——但前缀之后的部分已被 `_canonical_path` 规范化过
#: （无 `..`、无空段、无百分号编码），因此前缀匹配不再能被 `/data/spot/monthly/../../api/v3/account`
#: 这类输入穿过（verify-a R1 P1-2）。
PUBLIC_READONLY_ARCHIVE_PREFIXES: tuple[str, ...] = (
    "/data/spot/daily/",
    "/data/spot/monthly/",
    "/data/futures/um/daily/",
    "/data/futures/um/monthly/",
)

#: REST 端点：**逐个精确匹配**，不做前缀匹配。端点是有限可枚举的，前缀匹配在这里只会
#: 放行本不该放行的后缀（`/api/v3/account` 恰好以 `/api/v3/a` 开头这类近亲风险），
#: 所以白名单收紧成等值比较。任何下单 / 账户 / 资金 / User Data Stream 路径都不在此列
#: （ADR-0001 D1.8）。
PUBLIC_READONLY_REST_PATHS: frozenset[str] = frozenset(
    {
        "/api/v3/ping",
        "/api/v3/time",
        "/api/v3/exchangeInfo",
        "/api/v3/klines",
        "/api/v3/uiKlines",
        "/api/v3/avgPrice",
        "/api/v3/ticker",
        "/api/v3/ticker/24hr",
        "/api/v3/ticker/price",
        "/api/v3/ticker/bookTicker",
    }
)

#: 兼容旧名：出口放行的全部路径（归档前缀 + REST 精确路径）。守卫用它一次扫全集。
PUBLIC_READONLY_PREFIXES: tuple[str, ...] = (
    *PUBLIC_READONLY_ARCHIVE_PREFIXES,
    *sorted(PUBLIC_READONLY_REST_PATHS),
)

#: 路径里一律不接受的字符：百分号（编码歧义）、反斜杠（某些栈当分隔符）、空白与控制字符。
#: 归档路径只含 `[A-Za-z0-9._/-]`，REST 端点同理，所以这不是权衡，是把可能性关掉。
_FORBIDDEN_PATH_CHARS = ("%", "\\", " ", "\t", "\r", "\n")

#: 退避阶梯（秒）。首次重试 1s，其后翻倍；长度即最大重试次数。
BACKOFF_SCHEDULE: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0)

#: 触发退避重试的状态码。429 = 超限，418 = 已被 IP ban（必须退避而不是继续打）。
RETRYABLE_STATUS: frozenset[int] = frozenset({418, 429, 500, 502, 503, 504})

#: 同一出口两次请求之间的最小间隔（秒）——粗粒度的 IP weight 保护。
MIN_REQUEST_INTERVAL = 0.2

#: 退避上限：即便 `Retry-After` 报了一个荒谬的大值，也不在一次摄取里睡这么久。
MAX_BACKOFF = 60.0


class TransportBoundaryError(RuntimeError):
    """请求未通过 host 闸或路径闸——请求**不发出**（fail-closed）。"""


class RateLimitedError(RuntimeError):
    """退避重试用尽仍被限流／服务端错误。调用方必须让摄取失败，不得当成空结果。"""


@dataclass(frozen=True, slots=True)
class Response:
    """opener 的最小响应契约（只取状态码、正文与 `Retry-After`）。

    刻意**不携带请求头**：录制 fixture 时无关字段一律不落盘（卡要求），
    正文字节才是数据。
    """

    status: int
    content: bytes
    retry_after: float | None = None


#: opener 契约：`url -> Response`。默认实现在 `cli.py`（那里才 import httpx）。
Opener = Callable[[str], Response]


def split_public_url(url: str) -> tuple[str, str]:
    """拆出 `(host, path)` 并做两道闸之前的形态校验。

    只接受 https；带凭据（`user:pass@`）的 URL 直接拒绝——公共只读出口不该出现凭据。
    """
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise TransportBoundaryError(f"公共只读出口只允许 https: {url!r}")
    if parts.username or parts.password:
        raise TransportBoundaryError("公共只读出口不得携带凭据（ADR-0001 D1.8）")
    if not parts.hostname:
        raise TransportBoundaryError(f"URL 无 host: {url!r}")
    if parts.fragment:
        raise TransportBoundaryError(f"公共只读出口不接受带 fragment 的 URL: {url!r}")
    # query 不参与路由，但别的栈可能把它再拼回路径；点段与控制字符一律不放行。
    if ".." in parts.query or any(ord(c) < 0x20 for c in parts.query):
        raise TransportBoundaryError(f"query 含点段或控制字符，拒绝发出请求: {url!r}")
    return parts.hostname, parts.path


def canonical_path(path: str) -> str:
    """把 URL 路径化到**无歧义形式**，任何歧义输入直接拒绝——不做「修正后放行」。

    HTTP 客户端与服务端各自会对路径做规范化：httpx 会把白名单端点后面跟的 `..` 段就地
    折掉，于是发出去的是**上一级**的某个路径；而 `%2e%2e` 它原样发出、留给服务端去折。
    「校验原始字符串、发送规范化字符串」这个缝隙足以让一个白名单外的路径从本出口发出
    ——verify-a R1 P1-2 复现到的就是这条（被拒的具体形态逐条列在
    `tests/test_transport.py` 的参数化用例里）。

    这里不追着各家的折叠规则跑，而是**只接受本来就规范的路径**：不含百分号编码、无 `.` /
    `..` 段、无空段（`//`）、无反斜杠与空白。这样「校验的字符串」与「发送的字符串」必然
    逐字节相同，中间不存在可被利用的规范化差异。
    """
    if not path.startswith("/"):
        raise TransportBoundaryError(f"路径必须以 / 开头: {path!r}")
    for ch in _FORBIDDEN_PATH_CHARS:
        if ch in path:
            raise TransportBoundaryError(
                f"路径含歧义字符 {ch!r}，拒绝发出请求（百分号编码/反斜杠/空白一律不接受）: {path!r}"
            )
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in path):
        raise TransportBoundaryError(f"路径含控制字符，拒绝发出请求: {path!r}")
    segments = path.split("/")[1:]
    for seg in segments:
        if seg in ("", ".", ".."):
            raise TransportBoundaryError(
                f"路径含空段或点段（`//`、`.`、`..`），拒绝发出请求: {path!r}"
            )
    return path


def assert_public_readonly_path(path: str) -> str:
    """路径闸：先规范化校验，再按类别放行——归档按前缀，REST **精确匹配**。"""
    path = canonical_path(path)
    if path in PUBLIC_READONLY_REST_PATHS:
        return path
    if any(path.startswith(prefix) for prefix in PUBLIC_READONLY_ARCHIVE_PREFIXES):
        return path
    raise TransportBoundaryError(
        f"路径不在公共只读白名单内，拒绝发出请求: {path!r}"
        f"（新增端点须先进 PUBLIC_READONLY_REST_PATHS/ARCHIVE_PREFIXES，且必须无需 API key）"
    )


def assert_public_readonly_url(url: str) -> HostEntry:
    """两道闸一起过：host 必须是 `public_readonly=True` 条目，路径必须在白名单内。

    allowlist 的 `HostNotAllowedError` 在这里统一转成 `TransportBoundaryError`：
    调用方只需捕获一个「请求被出口拒绝」的类型，不必分辨是哪道闸拦下的。
    原异常经 `from` 保留在 `__cause__` 里。
    """
    host, path = split_public_url(url)
    try:
        entry = assert_public_readonly_host(host)
    except HostNotAllowedError as exc:
        raise TransportBoundaryError(str(exc)) from exc
    assert_public_readonly_path(path)
    return entry


class PublicTransport:
    """公共只读 HTTP 出口：逐请求校验 + 限流退避。

    `sleep` / `monotonic` / `jitter` 可注入，测试因此无需真的等待，也无需网络。
    """

    def __init__(
        self,
        opener: Opener,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        jitter: Callable[[], float] = random.random,
        min_interval: float = MIN_REQUEST_INTERVAL,
        backoff: tuple[float, ...] = BACKOFF_SCHEDULE,
    ) -> None:
        self._opener = opener
        self._sleep = sleep
        self._monotonic = monotonic
        self._jitter = jitter
        self._min_interval = min_interval
        self._backoff = backoff
        self._last_request_at: float | None = None
        #: 供测试与运维核对：实际睡过的秒数序列。
        self.sleeps: list[float] = []

    def _pace(self) -> None:
        """两次请求之间保持 `min_interval`（IP weight 的粗粒度保护）。"""
        if self._last_request_at is None:
            return
        elapsed = self._monotonic() - self._last_request_at
        remaining = self._min_interval - elapsed
        if remaining > 0:
            self._nap(remaining)

    def _nap(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._sleep(seconds)

    def _backoff_seconds(self, attempt: int, retry_after: float | None) -> float:
        """第 `attempt` 次重试前的等待：`Retry-After` 优先，否则指数阶梯 + jitter。"""
        base = self._backoff[attempt]
        if retry_after is not None and retry_after > base:
            base = retry_after
        return min(base + self._jitter() * base * 0.1, MAX_BACKOFF)

    def get(self, url: str) -> bytes:
        """取一个公共只读 URL 的正文。

        顺序：两道闸（任一不过 → 请求不发出）→ 节流 → 发出 → 按状态码决定退避重试。
        非重试类错误状态码直接抛 `RateLimitedError` 的兄弟：这里统一用 `RateLimitedError`
        仅限限流/5xx；4xx（如 404 缺文件）交给调用方按语义处理，故原样抛 `FileNotFoundError`。
        """
        assert_public_readonly_url(url)
        last_status: int | None = None
        for attempt in range(len(self._backoff) + 1):
            self._pace()
            response = self._opener(url)
            self._last_request_at = self._monotonic()
            if response.status == 200:
                return response.content
            if response.status == 404:
                raise FileNotFoundError(f"上游无此文件（404）: {url}")
            last_status = response.status
            if response.status not in RETRYABLE_STATUS:
                raise RateLimitedError(f"上游返回 HTTP {response.status}: {url}")
            if attempt == len(self._backoff):
                break
            self._nap(self._backoff_seconds(attempt, response.retry_after))
        raise RateLimitedError(
            f"退避重试 {len(self._backoff)} 次后仍为 HTTP {last_status}（最后一次）: {url}"
        )
