"""需 key 的只读行情出口（QNT-47；对称于 `transport.PublicTransport`）。

Massive 的数据要 API key 才取得到，所以它走不了公共只读出口。但「需要凭据」**不等于**
「是交易出口」：本出口与下单毫无关系，它的白名单里一个下单/账户端点都没有，
`allowlist.assert_trading_host` 对本出口的 host 显式 fail-closed。三类 host 互不放行
（`core/allowlist.py`）。

三道闸，逐请求，任一不过就**不发出请求**：

1. **host 闸**：`allowlist.assert_credentialed_readonly_host(host)`。公共只读 host、交易 host、
   未登记 host 一律拒绝。
2. **路径闸**：`canonical_path`（与公共出口共用：拒绝百分号编码、`.`/`..` 段、空段、
   反斜杠、空白与控制字符，使校验的字符串与发送的字符串逐字节相同），再按
   `KEYED_READONLY_PATHS` **精确匹配** + `KEYED_READONLY_PATH_PATTERNS` 的**参数化模板
   匹配**。聚合端点的路径里嵌着 ticker 与日期，无法穷举，所以用一条锚定的正则
   （`^...$`，各段字符集显式给出）而不是前缀——前缀匹配会让
   `/v2/aggs/ticker/AAPL/range/1/day/../../..` 这种形态有可乘之机，正则则要求整条路径
   逐段合规。白名单而非黑名单：漏一个新端点只是少取一类数据（fail-closed）。
3. **凭据闸**：key 只进 `Authorization: Bearer` 请求头，**永不进 URL**。`?apiKey=` 这种
   写法会把凭据写进代理日志、访问日志、`next_url` 回显和异常里的 URL；请求头不会。
   query 先按 `parse_qsl` **解码**（百分号、`+`，再多解一层防双重编码）再判键名，
   解码后的键（去掉 `_`/`-`，大小写不敏感）命中凭据形态（`apikey` / `token` /
   `accesstoken` / `authorization` / `key` …）就拒绝；带 fragment 的 URL 直接拒。
   **未过闸的 URL 一律不可信**：异常 / 日志 / `repr` 只给 `transport.redact_untrusted`
   的形态（`scheme://host/<path sha256:…>`，路径任何一段都不回显）——那时 URL 里
   可能正拼着 key，而 key 完全可以只由「安全」字符组成。过闸之后也只回显白名单
   **模板**（`describe_trusted`），不回显实参与 query。

限流：免费 / Basic 档对未订阅资产类限 5 请求/分钟，超限 HTTP 429（官方知识库）。
本出口默认按 `massive.FREE_TIER_MIN_INTERVAL`（12 秒）节流，退避与重试**复用**
`transport.Throttled`——不在这里复制第二份退避实现：一份被改坏而另一份照绿，
正是变异验证要抓的漂移。

凭据来源：只从环境变量 `MASSIVE_API_KEY` 读，该变量由
`op run --env-file=docs/ops/massive.env.tpl` 注入（AGENTS.md §3）。取不到即
`CredentialUnavailableError`「凭据不可用」，**没有任何回退**：无 key 时安静地降级成
匿名请求会把「取到的是什么」变成运行时的偶然。
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, unquote_plus, urlsplit

from quantime_core.allowlist import (
    HostEntry,
    HostNotAllowedError,
    assert_credentialed_readonly_host,
)

from .sources import massive
from .transport import (
    Response,
    Throttled,
    TransportBoundaryError,
    canonical_path,
    describe_trusted,
    path_digest,
    redact_untrusted,
)

#: 本出口的日志只记白名单模板形态的 URL 与字节数，从不记请求头、query 或 key。
log = logging.getLogger(__name__)

#: 环境变量名。值由 `op run` 注入；仓库里只有 `*.tpl` 允许出现 `op://` 引用。
API_KEY_ENV = "MASSIVE_API_KEY"

#: 放行的**固定**路径（精确等值匹配）。逐条都是只读数据端点。
KEYED_READONLY_PATHS: frozenset[str] = frozenset(
    {
        "/v3/reference/options/contracts",  # 期权合约参考
        "/stocks/v1/splits",  # 拆股
        "/stocks/v1/dividends",  # 分红
    }
)

#: 放行的**参数化**路径模板（整条路径锚定匹配，逐段限定字符集）。
#:
#: 只有日线聚合需要模板：`/v2/aggs/ticker/<ticker>/range/1/day/<from>/<to>`。
#: `multiplier` 固定 `1`、`timespan` 固定 `day`——本卡只做日线，把它们写死而不是放开成
#: `[0-9]+/[a-z]+`，等于把「不小心拉了分钟线」这件事挡在出口上。
#: 收尾用 `\Z` 而非 `$`（`$` 会放过结尾换行，见 `sources/massive.py` 同处注释）。
KEYED_READONLY_PATH_TEMPLATES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "/v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}",
        re.compile(
            r"^/v2/aggs/ticker/"
            r"(?:[A-Z][A-Z0-9.]{0,15}|O:[A-Z][A-Z0-9]{0,5}[0-9]{6}[CP][0-9]{8})"
            r"/range/1/day/[0-9]{4}-[0-9]{2}-[0-9]{2}/[0-9]{4}-[0-9]{2}-[0-9]{2}\Z"
        ),
    ),
)

#: 只取正则的视图（守卫与测试按正则扫）。每条模板的占位符形式只用于回显：过闸后的
#: 日志/异常里出现的是 `{ticker}` 而不是实参（QNT-47 返修 #2）。
KEYED_READONLY_PATH_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    pattern for _, pattern in KEYED_READONLY_PATH_TEMPLATES
)

#: 兼容 `PUBLIC_READONLY_PREFIXES` 的形态：守卫用它一次扫全集（模板取其正则原文）。
KEYED_READONLY_ALL: tuple[str, ...] = (
    *sorted(KEYED_READONLY_PATHS),
    *(p.pattern for p in KEYED_READONLY_PATH_PATTERNS),
)

#: query 里一旦出现这些键，说明有人把凭据拼进了 URL。key 只走请求头。
#: 比较口径：**解码后**的键，小写，去掉 `_` 与 `-`（所以 `api_key` / `API-KEY` / `apiKey`
#: 都归一成 `apikey`）。
_CREDENTIAL_QUERY_KEYS: frozenset[str] = frozenset(
    {
        "apikey",
        "key",
        "token",
        "accesstoken",
        "accesskey",
        "authorization",
        "auth",
        "bearer",
        "secret",
        "password",
        "credential",
    }
)


class CredentialUnavailableError(RuntimeError):
    """凭据不可用——`op` 未注入或值为空。**无回退**，调用方必须失败退出。"""


@dataclass(frozen=True, slots=True)
class KeyedRequest:
    """一个已过闸的请求：URL + 要带的请求头 + 可回显形态 `shown`。

    凭据在 `headers` 里，不在 `url` 里；但 `url` 本身也不回显——`repr`/`str` 只用构造时
    就定下的 `shown`：`build_request` 给白名单模板形态，直接构造时（未经过闸）默认
    `redact_untrusted(url)`，即 host + 路径哈希。
    """

    url: str
    headers: dict[str, str]
    shown: str = field(default="")

    def __post_init__(self) -> None:
        if not self.shown:
            object.__setattr__(self, "shown", redact_untrusted(self.url))

    def __repr__(self) -> str:
        return f"KeyedRequest(url={self.shown!r}, headers=<redacted {len(self.headers)} 项>)"

    __str__ = __repr__


#: opener 契约：`(url, headers) -> Response`。默认实现在 `cli.py`（那里才 import httpx）。
KeyedOpener = Callable[[str, dict[str, str]], Response]


def read_api_key(env: dict[str, str] | None = None) -> str:
    """从环境读 key 并 `.strip()`（AGENTS.md §3）。取不到即失败，没有回退。

    `env` 可注入，所以测试不必碰进程环境。
    """
    source = os.environ if env is None else env
    raw = source.get(API_KEY_ENV)
    if raw is None:
        raise CredentialUnavailableError(
            f"凭据不可用：环境变量 {API_KEY_ENV} 未设置。"
            f"请用 `op run --env-file=docs/ops/massive.env.tpl -- <命令>` 注入"
            f"（{massive.CREDENTIAL_POINTER}）。无 key 时本出口不做任何匿名回退。"
        )
    key = raw.strip()
    if not key:
        raise CredentialUnavailableError(
            f"凭据不可用：环境变量 {API_KEY_ENV} 为空（`.strip()` 后无内容）。"
        )
    return key


def _normalise_query_key(raw: str) -> str:
    """凭据键的比较口径：解码两层（防双重编码），小写，去掉 `_` `-` 与空白。"""
    key = unquote_plus(unquote_plus(raw))
    return re.sub(r"[\s_-]", "", key).lower()


def split_keyed_url(url: str) -> tuple[str, str]:
    """拆出 `(host, path)` 并做闸之前的形态校验。

    只接受 https（凭据绝不走明文）；带 `user:pass@` 或 fragment 的 URL 直接拒绝；query
    **解码后**出现疑似凭据的键直接拒绝——key 只走请求头。

    本函数跑在所有闸**之前**，所以它的每一条错误信息都只用 `redact_untrusted(url)`，
    绝不回显原始 URL 的路径、query 或 fragment。
    """
    shown = redact_untrusted(url)
    try:
        parts = urlsplit(url)
        hostname = parts.hostname
    except ValueError:
        raise TransportBoundaryError(f"URL 无法解析，拒绝发出请求: {shown}") from None
    if parts.scheme != "https":
        raise TransportBoundaryError(f"带凭据的出口只允许 https: {shown}")
    if parts.username or parts.password:
        raise TransportBoundaryError("URL 不得携带凭据（key 只走 Authorization 头）")
    if not hostname:
        raise TransportBoundaryError(f"URL 无 host: {shown}")
    if parts.fragment or "#" in url:
        raise TransportBoundaryError(f"不接受带 fragment 的 URL（只读数据端点不需要）: {shown}")
    if ".." in parts.query or any(ord(c) < 0x20 or ord(c) == 0x7F for c in parts.query):
        raise TransportBoundaryError(f"query 含点段或控制字符，拒绝发出请求: {shown}")
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    for raw_key, _ in pairs:
        if _normalise_query_key(raw_key) in _CREDENTIAL_QUERY_KEYS:
            raise TransportBoundaryError(
                f"query 里出现疑似凭据的参数——API key 只走 Authorization 头，"
                f"绝不进 URL（URL 会落进代理/访问日志）: {shown}"
            )
    return hostname, parts.path


def keyed_path_template(path: str) -> str | None:
    """路径在白名单内则返回其**回显模板**（精确路径即自身，参数化路径给占位符），否则 `None`。"""
    path = canonical_path(path)
    if path in KEYED_READONLY_PATHS:
        return path
    for template, pattern in KEYED_READONLY_PATH_TEMPLATES:
        if pattern.fullmatch(path):
            return template
    return None


def assert_keyed_readonly_path(path: str) -> str:
    """路径闸：先规范化校验，再按精确集合 / 参数化模板放行。"""
    if keyed_path_template(path) is not None:
        return path
    raise TransportBoundaryError(
        f"路径不在需 key 的只读白名单内，拒绝发出请求: {path_digest(path)}"
        f"（新增端点须先进 KEYED_READONLY_PATHS/PATH_TEMPLATES，且必须是只读数据端点；"
        f"任何账户/交易/订单端点一律不得加入）"
    )


def gate_keyed_url(url: str) -> tuple[HostEntry, str]:
    """三道闸里的前两道一起过，返回 `(条目, 回显形态)`。

    host 闸的原异常**不**挂在 `__cause__` 上：它的消息原样回显 host，而未过闸的 host
    同样不可信（`<key>.evil.test`）。
    """
    host, path = split_keyed_url(url)
    try:
        entry = assert_credentialed_readonly_host(host)
    except HostNotAllowedError:
        raise TransportBoundaryError(
            f"host 不在 allowlist 或不是需 key 的只读数据 host（credentialed_readonly），"
            f"拒绝发出请求: {redact_untrusted(url)}"
        ) from None
    assert_keyed_readonly_path(path)
    template = keyed_path_template(path)
    assert template is not None  # 上一行已放行
    return entry, describe_trusted(host, template)


def assert_keyed_readonly_url(url: str) -> HostEntry:
    """三道闸里的前两道一起过（凭据闸在 `KeyedTransport` 组装请求头时守）。"""
    return gate_keyed_url(url)[0]


class KeyedTransport(Throttled):
    """需 key 的只读 HTTP 出口：逐请求三道闸 + 节流退避（退避实现复用 `Throttled`）。

    `api_key` 由调用方传入（`read_api_key()` 的结果），本类不自己读环境——这样测试
    不需要设环境变量，也让「凭据从哪来」只有一条路径。
    """

    def __init__(
        self,
        opener: KeyedOpener,
        *,
        api_key: str,
        min_interval: float = massive.FREE_TIER_MIN_INTERVAL,
        **kw,
    ) -> None:
        super().__init__(min_interval=min_interval, **kw)
        if not api_key or api_key != api_key.strip():
            raise CredentialUnavailableError("api_key 为空或含首尾空白（应为 `.strip()` 后的值）")
        self._opener = opener
        self._api_key = api_key

    def __repr__(self) -> str:
        # 不回显 key、opener 或任何请求内容。
        return f"KeyedTransport(min_interval={self._min_interval!r}, api_key=<redacted>)"

    __str__ = __repr__

    def build_request(self, url: str) -> KeyedRequest:
        """过闸并组装请求。**公开**是为了让 CLI 在真正发出之前再验一次规范化后的 URL。"""
        _, shown = gate_keyed_url(url)
        return KeyedRequest(
            url=url, headers={"Authorization": f"Bearer {self._api_key}"}, shown=shown
        )

    def get(self, url: str) -> bytes:
        """取一个需 key 的只读 URL 的正文。

        三道闸 → 节流 → 发出 → 按状态码退避重试。429（超限）与 5xx 走退避；
        重试用尽抛 `RateLimitedError`，404 抛 `FileNotFoundError`——绝不静默返回空。
        """
        request = self.build_request(url)
        log.debug("keyed GET %s", request.shown)
        body = self._request(
            request.shown, lambda: self._opener(request.url, dict(request.headers))
        )
        log.debug("keyed GET %s -> %d 字节", request.shown, len(body))
        return body
