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

本模块还有**第二个、并列的**出口 `CredentialedTransport`（QNT-48，文件末尾）：
需 token 的只读数据源（Tushare Pro）走 POST，端点在 body 的 `api_name` 里。它自带三道闸
（host `credentialed_readonly=True` / 路径精确 / `api_name` 精确枚举），与本出口
**互不放行**——`PublicTransport` 打不了 Tushare，`CredentialedTransport` 也打不了 Vision。
"""

from __future__ import annotations

import json
import random
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from quantime_core.allowlist import (
    HostEntry,
    HostNotAllowedError,
    assert_credentialed_readonly_host,
    assert_public_readonly_host,
)

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


# ---- QNT-48：需凭据的只读数据源出口（Tushare Pro）----
#
# 与上面的公共只读出口**并列而不复用**：那一条是 GET + 无凭据 + host `public_readonly=True`；
# 这一条是 POST + token 在 body + host `credentialed_readonly=True`。两个出口各自持有自己的
# 闸，`assert_public_readonly_host` / `assert_credentialed_readonly_host` 互不放行，因此
# 「带 token 的出口」不可能被复用去打无 key 源，反之亦然。
#
# Tushare 的 HTTP 接口只有**一个** URL（POST 根路径 `/`），真正区分端点的是 body 里的
# `api_name`（https://tushare.pro/document/1?doc_id=130）。所以路径白名单在这里近乎退化，
# **端点白名单必须落在 `api_name` 上**，且同样是精确枚举而非前缀/黑名单。

#: 允许 POST 的路径——精确匹配。Tushare 只用根路径。
CREDENTIALED_POST_PATHS: frozenset[str] = frozenset({"/"})

#: 允许的 `api_name`：本卡范围内的**只读数据**端点，逐个枚举。
#: 账户 / 资金 / 交易类 `api_name` 一个都不在此列，因此不可能从本出口发出
#: （被拒的具体名字逐条列在 `tests/test_tushare_transport.py` 的参数化用例里）。
TUSHARE_READONLY_API_NAMES: frozenset[str] = frozenset(
    {
        "stock_basic",
        "trade_cal",
        "daily",
        "adj_factor",
        "daily_basic",
    }
)

#: Tushare 基础积分档「每分钟 500 次」（https://tushare.pro/document/2?doc_id=27）
#: → 最小间隔 60/500 = 0.12s。高积分档更宽松，但按最严的档位节流不会错。
TUSHARE_MIN_REQUEST_INTERVAL = 0.12

#: Tushare 在 HTTP 200 里用 `code != 0` 报错。文档没有给出稳定完整的错误码表，
#: 所以限流判定用**双判据**：已知码 + 限流关键词。宁可多退避一次，也不要把限流当成数据错误
#: 一路打下去（打到被封是不可逆的）。
TUSHARE_RETRYABLE_CODES: frozenset[int] = frozenset({40203})

_RATE_LIMIT_MSG_RE = re.compile(r"每分钟|访问频率|频率过高|超过.*次|rate.?limit|too many", re.I)


class CredentialUnavailableError(RuntimeError):
    """凭据取不到——请求**不发出**，也**不回落**到无 key 路径（卡：exit 1「凭据不可用」）。"""


class TushareApiError(RuntimeError):
    """上游在 HTTP 200 里返回 `code != 0`。消息经 `redact` 洗过，绝不含 token。"""

    def __init__(self, code: int, msg: str) -> None:
        super().__init__(f"Tushare 返回 code={code}: {msg}")
        self.code = code
        self.msg = msg


class SecretValue:
    """token 的不可打印包装：`repr` / `str` / f-string 一律给出掩码。

    这不是加密，是把「顺手把 token 拼进日志或异常」这条最常见的泄漏路径**关掉**——
    Python 里泄密几乎总是经由某个 `f"...{token}..."`，而那条路径走的正是 `__format__`。
    取明文只有一个显式入口 `reveal()`，全仓库只在 `CredentialedTransport._body` 里调用一次。
    """

    __slots__ = ("_value",)

    #: 掩码文本。日志里看到它就说明包装生效了。
    MASK = "<secret:****>"

    def __init__(self, value: str) -> None:
        stripped = value.strip()  # AGENTS.md §3：`op` 注入的值读取时 .strip()
        if not stripped:
            raise CredentialUnavailableError("凭据不可用：注入的值为空")
        self._value = stripped

    def reveal(self) -> str:
        """取明文——**唯一**出口。调用点必须是即将写进请求体的那一行。"""
        return self._value

    def scrub(self, text: str) -> str:
        """把明文从任意文本里换成掩码。

        内部直接读 `self._value` 而**不**走 `reveal()`：`reveal()` 是「明文离开本类」的
        唯一出口，守卫按它的调用点计数（CI 要求全仓库恰好 1 处）。洗文本不是把明文交出去，
        不该占用那个额度，否则「唯一出口」这条守卫就永远是 2 处，也就失去了意义。
        """
        return text.replace(self._value, self.MASK)

    def __repr__(self) -> str:
        return self.MASK

    __str__ = __repr__

    def __format__(self, spec: str) -> str:
        return self.MASK


def redact(text: str, secret: SecretValue | None) -> str:
    """把 token 明文从任意文本里换成掩码——异常/日志出仓前的最后一道网。

    `SecretValue` 已经挡住了「直接拼」，但第三方库抛出的异常可能把**请求体**原样塞进
    消息里（body 里确实有明文 token）。那条路径绕过了包装，所以这里再洗一遍。
    """
    if secret is None:
        return text
    return secret.scrub(text)


#: 带凭据的 POST opener 契约：`(url, body_bytes) -> Response`。
#: 与 GET 侧一样，真实实现只在 `cli.py`，因此本模块离线可测。
PostOpener = Callable[[str, bytes], Response]


def assert_credentialed_post_path(path: str) -> str:
    """路径闸（POST 侧）：空路径视作 `/`，其余一律精确匹配白名单。

    `canonical_path` 把 `/` 当空段拒掉（对归档路径是对的），所以这里不复用它，
    而是用一套更严的规则：本出口只允许白名单里那几个**字面**路径，别的形态一律拒绝，
    连规范化的机会都不给。
    """
    if path == "":
        path = "/"
    if path in CREDENTIALED_POST_PATHS:
        return path
    raise TransportBoundaryError(
        f"路径不在需凭据出口的白名单内，拒绝发出请求: {path!r}"
        f"（允许: {sorted(CREDENTIALED_POST_PATHS)}）"
    )


def assert_credentialed_post_url(url: str) -> HostEntry:
    """两道闸：host 必须是 `credentialed_readonly=True` 条目，路径必须精确命中白名单。"""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise TransportBoundaryError(f"需凭据的出口只允许 https: {url!r}")
    if parts.username or parts.password:
        raise TransportBoundaryError("凭据只走 body，不得放进 URL（会进日志/Referer）")
    if parts.query or parts.fragment:
        raise TransportBoundaryError(f"需凭据的出口不接受 query/fragment: {url!r}")
    if not parts.hostname:
        raise TransportBoundaryError(f"URL 无 host: {url!r}")
    try:
        entry = assert_credentialed_readonly_host(parts.hostname)
    except HostNotAllowedError as exc:
        raise TransportBoundaryError(str(exc)) from exc
    assert_credentialed_post_path(parts.path)
    return entry


def assert_api_names_within_authority(api_names: frozenset[str]) -> frozenset[str]:
    """构造闸：调用方给的名单必须是权威枚举的**子集**（QNT-48 返工，verify-b P1）。

    原实现把 `api_names` 当普通默认参数收下，调用方传 `frozenset({"daily_order"})` 就能
    把交易近似名装进白名单——「默认安全、可选放宽」等于没有闸门，因为放宽不需要任何审批。
    权威枚举是 `TUSHARE_READONLY_API_NAMES`，它在本模块里，改它要过 CI 静态守卫；
    调用方只能**收窄**（源侧只用自己需要的那几个端点仍然有价值），一个字都不能加。

    在构造点抛而不是 `post` 时抛：一个白名单被悄悄放宽的进程，不该先跑起来再等某次
    请求撞上闸门——那时是否撞上取决于调用顺序，测不出来。
    """
    extra = api_names - TUSHARE_READONLY_API_NAMES
    if extra:
        raise TransportBoundaryError(
            f"api_names 超出权威只读枚举，拒绝构造: {sorted(extra)}"
            f"（权威枚举: {sorted(TUSHARE_READONLY_API_NAMES)}；"
            "调用方只能取子集，新增端点须改 transport 里的权威枚举并确认不是账户/资金/交易类）"
        )
    if not api_names:
        raise TransportBoundaryError("api_names 为空：这个出口不能发出任何请求，应是配置错误")
    return api_names


def assert_readonly_api_name(api_name: str, allowed: frozenset[str]) -> str:
    """端点闸：`api_name` 精确枚举。Tushare 的「端点」在 body 里，闸就必须开在这。"""
    if api_name not in allowed:
        raise TransportBoundaryError(
            f"api_name 不在只读白名单内，拒绝发出请求: {api_name!r}"
            f"（允许: {sorted(allowed)}；新增端点须确认它不是账户/资金/交易类）"
        )
    return api_name


def is_rate_limited(code: int, msg: str) -> bool:
    """`code != 0` 的响应里，哪些算「限流、该退避重试」。"""
    return code in TUSHARE_RETRYABLE_CODES or bool(_RATE_LIMIT_MSG_RE.search(msg))


class CredentialedTransport:
    """需凭据的只读 POST 出口：逐请求过三道闸（host / 路径 / `api_name`）+ 限流退避。

    token 由本类持有并**只在** `_body` 里拼进请求体；调用方拿不到明文，也无需知道它存在。
    异常文本一律经 `redact`，请求体从不进任何消息。

    `api_names` 只能是 `TUSHARE_READONLY_API_NAMES` 的子集，构造时校验（fail-closed）：
    调用方可以收窄到自己用得着的端点，但**放宽不了**——否则端点闸就成了调用方自选。
    """

    def __init__(
        self,
        opener: PostOpener,
        token: SecretValue,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        jitter: Callable[[], float] = random.random,
        min_interval: float = TUSHARE_MIN_REQUEST_INTERVAL,
        backoff: tuple[float, ...] = BACKOFF_SCHEDULE,
        api_names: frozenset[str] = TUSHARE_READONLY_API_NAMES,
    ) -> None:
        if not isinstance(token, SecretValue):
            raise TypeError("token 必须是 SecretValue（明文 str 会绕过掩码与 redact）")
        self._opener = opener
        self._token = token
        self._sleep = sleep
        self._monotonic = monotonic
        self._jitter = jitter
        self._min_interval = min_interval
        self._backoff = backoff
        self._api_names = assert_api_names_within_authority(api_names)
        self._last_request_at: float | None = None
        #: 供测试与运维核对：实际睡过的秒数序列。
        self.sleeps: list[float] = []

    def _pace(self) -> None:
        if self._last_request_at is None:
            return
        remaining = self._min_interval - (self._monotonic() - self._last_request_at)
        if remaining > 0:
            self._nap(remaining)

    def _nap(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._sleep(seconds)

    def _backoff_seconds(self, attempt: int, retry_after: float | None) -> float:
        base = self._backoff[attempt]
        if retry_after is not None and retry_after > base:
            base = retry_after
        return min(base + self._jitter() * base * 0.1, MAX_BACKOFF)

    def _body(self, api_name: str, params: dict[str, str], fields: Sequence[str]) -> bytes:
        """拼请求体——**全仓库唯一** `reveal()` 的地方。

        `sort_keys` + 紧凑分隔符：同参数的请求体逐字节确定，便于核对「发出去的是什么」
        而不必把 body 打出来。
        """
        payload = {
            "api_name": api_name,
            "token": self._token.reveal(),
            "params": dict(sorted(params.items())),
            "fields": ",".join(fields),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")

    def post(
        self,
        url: str,
        *,
        api_name: str,
        params: dict[str, str] | None = None,
        fields: Sequence[str] = (),
    ) -> dict[str, list]:
        """发一次只读数据请求，回传 `data`（`{"fields": [...], "items": [[...]]}`）。

        顺序：三道闸（任一不过 → 请求不发出）→ 节流 → 发出 → HTTP 状态退避
        → `code != 0` 时按限流与否决定退避或直接失败。
        """
        assert_credentialed_post_url(url)
        assert_readonly_api_name(api_name, self._api_names)
        body = self._body(api_name, params or {}, fields)

        last_detail = ""
        for attempt in range(len(self._backoff) + 1):
            self._pace()
            try:
                response = self._opener(url, body)
            except Exception as exc:  # 第三方客户端可能把 body（含明文 token）塞进消息
                raise RuntimeError(
                    f"{api_name}: 上游请求失败: {redact(str(exc), self._token)}"
                ) from None
            finally:
                self._last_request_at = self._monotonic()

            retryable, detail, data = self._classify(api_name, response)
            if data is not None:
                return data
            last_detail = detail
            if not retryable:
                raise RateLimitedError(f"{api_name}: {detail}")
            if attempt == len(self._backoff):
                break
            self._nap(self._backoff_seconds(attempt, response.retry_after))
        raise RateLimitedError(
            f"{api_name}: 退避重试 {len(self._backoff)} 次后仍失败（最后一次：{last_detail}）"
        )

    def _classify(
        self, api_name: str, response: Response
    ) -> tuple[bool, str, dict[str, list] | None]:
        """把一次响应分成「成功 / 可退避 / 直接失败」。返回 `(retryable, detail, data)`。"""
        if response.status in RETRYABLE_STATUS:
            return True, f"HTTP {response.status}", None
        if response.status != 200:
            return False, f"上游返回 HTTP {response.status}", None
        try:
            envelope = json.loads(response.content.decode("utf-8"))
        except UnicodeDecodeError, json.JSONDecodeError:
            # 刻意不回显正文：非 JSON 的响应可能是网关页，也可能把请求原样回显（含 token）。
            return False, f"响应不是 JSON（{len(response.content)} 字节）", None
        code = envelope.get("code")
        msg = redact(str(envelope.get("msg") or ""), self._token)
        if code == 0:
            data = envelope.get("data")
            if not isinstance(data, dict) or "fields" not in data or "items" not in data:
                return False, "code=0 但 data 缺少 fields/items", None
            return False, "", data
        if not isinstance(code, int):
            return False, f"响应缺少整型 code（得到 {type(code).__name__}）", None
        if is_rate_limited(code, msg):
            return True, f"限流 code={code}: {msg}", None
        raise TushareApiError(code, msg)
