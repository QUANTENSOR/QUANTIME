"""公共只读出口的两道闸与限流退避（QNT-28 关键路径）。

全部离线：opener 是一个假的，不碰网络。
"""

from __future__ import annotations

import pytest
from quantime_core.allowlist import BINANCE_VISION_ARCHIVE, BINANCE_VISION_SPOT_MIRROR
from quantime_data import retry
from quantime_data.spec import IngestError
from quantime_data.transport import (
    BACKOFF_SCHEDULE,
    PublicTransport,
    RateLimitedError,
    Response,
    TransportBoundaryError,
    assert_public_readonly_path,
    assert_public_readonly_url,
    split_public_url,
)

ARCHIVE = BINANCE_VISION_ARCHIVE.host
MIRROR = BINANCE_VISION_SPOT_MIRROR.host
GOOD_URL = f"https://{ARCHIVE}/data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2026-08.zip"


class FakeOpener:
    """按脚本回放状态码；记录被请求的 URL。"""

    def __init__(self, *responses: Response) -> None:
        self._responses = list(responses)
        self.urls: list[str] = []

    def __call__(self, url: str) -> Response:
        self.urls.append(url)
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


def make_transport(*responses: Response, **kw) -> tuple[PublicTransport, FakeOpener]:
    opener = FakeOpener(*responses)
    transport = PublicTransport(
        opener,
        sleep=lambda _s: None,
        monotonic=_clock(),
        jitter=lambda: 0.0,
        **kw,
    )
    return transport, opener


def _clock():
    """单调时钟：每次调用前进 1000 秒，使节流永不触发（节流本身另有专测）。"""
    state = {"t": 0.0}

    def now() -> float:
        state["t"] += 1000.0
        return state["t"]

    return now


# ---- host 闸 ----


def test_unlisted_host_is_rejected_before_any_request():
    transport, opener = make_transport(Response(200, b"x"))
    with pytest.raises(TransportBoundaryError, match="不在 allowlist"):
        transport.get("https://evil.example.com/data/spot/monthly/klines/B/1d/x.zip")
    assert opener.urls == [], "请求必须在发出之前就被拒绝"


def test_lookalike_host_suffix_is_not_allowed():
    """`evil-data.binance.vision.attacker.com` 不得因后缀相似被放行。"""
    transport, opener = make_transport(Response(200, b"x"))
    with pytest.raises(TransportBoundaryError):
        transport.get(f"https://{ARCHIVE}.attacker.com/data/spot/monthly/klines/B/1d/x.zip")
    assert opener.urls == []


def test_plain_http_is_rejected():
    with pytest.raises(TransportBoundaryError, match="只允许 https"):
        split_public_url(f"http://{ARCHIVE}/data/spot/monthly/x.zip")


def test_url_with_credentials_is_rejected():
    with pytest.raises(TransportBoundaryError, match="不得携带凭据"):
        split_public_url(f"https://user:pw@{ARCHIVE}/data/spot/monthly/x.zip")


# ---- 路径闸 ----


@pytest.mark.parametrize(
    "path",
    [
        "/api/v3/order",
        "/api/v3/account",
        "/api/v3/myTrades",
        "/fapi/v1/order",
        "/fapi/v1/account",
        "/fapi/v2/balance",
        "/sapi/v1/capital/withdraw/apply",
        "/api/v3/userDataStream",
    ],
)
def test_trading_and_account_paths_are_rejected(path):
    """交易 / 账户 / 资金 / User Data 路径不在白名单，永远发不出去（ADR-0001 D1.8）。"""
    with pytest.raises(TransportBoundaryError, match="白名单"):
        assert_public_readonly_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "/data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2026-08.zip",
        "/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2026-09-15.zip",
        "/api/v3/klines",
        "/api/v3/exchangeInfo",
    ],
)
def test_public_readonly_paths_are_allowed(path):
    assert assert_public_readonly_path(path) == path


#: R1 P1-2 的反例集：这些 URL 在修复前**全部通过**路径闸（原规则对原始 path 做 startswith），
#: 而 httpx 发出去的是白名单外的路径。每一条都必须在请求发出之前被拒。
NORMALIZATION_BYPASSES = [
    # httpx 会把 `..` 段就地折掉，发出去的是上一级的路径——校验的和发送的不是同一个字符串。
    f"https://{MIRROR}/api/v3/klines/../account",
    f"https://{MIRROR}/api/v3/klines/./../account",
    f"https://{MIRROR}/api/v3/klines/../../api/v3/account",
    # 百分号编码的点段：httpx 原样发出，留给服务端去折——绕过点更隐蔽。
    f"https://{MIRROR}/api/v3/klines/%2e%2e/account",
    f"https://{MIRROR}/api/v3/klines/%2E%2E/account",
    # 编码斜杠：某些栈会先解码再路由。
    f"https://{MIRROR}/api/v3/klines%2F..%2Faccount",
    # 反斜杠。
    f"https://{MIRROR}/api/v3/klines\\..\\account",
    # 白名单端点的后缀延伸——前缀匹配的本来面目。
    f"https://{MIRROR}/api/v3/klinesX",
    # query 里夹带点段。
    f"https://{MIRROR}/api/v3/klines?symbol=../account",
    # 归档前缀下的逃逸——这批最要命：path 以合法归档前缀开头，前缀匹配（新旧规则都一样）
    # 放行它，能拦住的只有规范化校验本身。REST 那批另有精确匹配兜底，这批没有。
    f"https://{ARCHIVE}/data/spot/monthly/../../api/v3/account",
    f"https://{ARCHIVE}/data/spot/monthly/./../../api/v3/account",
    f"https://{ARCHIVE}/data/spot/monthly/%2e%2e/%2e%2e/api/v3/account",
    f"https://{ARCHIVE}/data/spot/monthly/..%2f..%2fapi/v3/account",
]

#: 另一类：原规则也拦得住，但形态歧义、不同栈解释不一致，一并关掉（纵深，不是回归）。
AMBIGUOUS_PATHS = [
    f"https://{MIRROR}//api/v3/klines",
    f"https://{MIRROR}/api/v3//account",
    f"https://{MIRROR}/api/v3%2Faccount",
]


@pytest.mark.parametrize("url", [*NORMALIZATION_BYPASSES, *AMBIGUOUS_PATHS])
def test_normalization_bypasses_are_rejected_before_any_request(url):
    """R1 P1-2：歧义路径一律在出口前拒绝，opener 收不到任何请求。

    关键在「拒绝」而不是「折叠后再判」：只要校验的字符串与最终发送的字符串可能不同，
    两者之间就有一条缝。这里把缝关掉——只接受本来就规范的路径。
    """
    transport, opener = make_transport(Response(200, b"x"))
    with pytest.raises(TransportBoundaryError):
        transport.get(url)
    assert opener.urls == [], "歧义 URL 被发了出去"


def test_the_bypass_corpus_would_have_passed_the_old_prefix_rule():
    """反例集不得是「本来就拦得住的东西」——否则这组回归形同虚设。

    这里就地重演修复前的规则（对**原始** path 做 startswith），断言每一条当时都能通过。
    集合里任何一条如果原本就会被拒，它就不是这次修复的回归证据，应挪进 `AMBIGUOUS_PATHS`。
    """
    from urllib.parse import urlsplit

    from quantime_data.transport import PUBLIC_READONLY_PREFIXES

    for url in NORMALIZATION_BYPASSES:
        path = urlsplit(url).path
        assert any(path.startswith(prefix) for prefix in PUBLIC_READONLY_PREFIXES), (
            f"{path!r} 在旧规则下本来就会被拒，它证明不了这次修复"
        )


@pytest.mark.parametrize(
    "path",
    [
        "/api/v3/klinesX",
        "/api/v3/klines/extra",
        "/api/v3/accountInfo",
        "/api/v3/pingpong",
    ],
)
def test_rest_whitelist_is_exact_match_not_prefix(path):
    """R1 P1-2：REST 端点精确匹配——白名单端点的任何后缀延伸都不放行。

    前缀匹配下 `/api/v3/klinesX` 会通过；端点是有限可枚举的，没有理由用前缀。
    """
    with pytest.raises(TransportBoundaryError, match="白名单"):
        assert_public_readonly_path(path)


def test_archive_tree_still_matches_by_prefix():
    """归档是目录树、文件名不可穷举，仍按前缀放行——但前缀之后已被规范化过。"""
    ok = "/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2026-08.zip"
    assert assert_public_readonly_path(ok) == ok


def test_a_trading_path_cannot_hide_behind_an_archive_prefix():
    """归档前缀 + 点段回退，同样拒绝——前缀放行不等于前缀之后可以为所欲为。"""
    with pytest.raises(TransportBoundaryError, match="点段"):
        assert_public_readonly_path("/data/spot/monthly/../../api/v3/account")


def test_fragment_is_rejected():
    with pytest.raises(TransportBoundaryError, match="fragment"):
        split_public_url(f"https://{MIRROR}/api/v3/klines#/../account")


def test_assert_public_readonly_url_returns_the_allowlist_entry():
    entry = assert_public_readonly_url(GOOD_URL)
    assert entry.host == ARCHIVE
    assert entry.public_readonly is True
    assert entry.doc_url, "crypto-boundaries ① 要求附官方文档链接"


# ---- 限流退避 ----


def test_429_is_retried_with_exponential_backoff_then_succeeds():
    transport, opener = make_transport(
        Response(429, b""), Response(429, b""), Response(200, b"payload")
    )
    assert transport.get(GOOD_URL) == b"payload"
    assert len(opener.urls) == 3
    assert transport.sleeps == [BACKOFF_SCHEDULE[0], BACKOFF_SCHEDULE[1]]


def test_418_ip_ban_is_backed_off_not_hammered():
    """418 = 已被 IP ban。必须退避；继续全速打会把 ban 从 2 分钟拖到 3 天。"""
    transport, _ = make_transport(Response(418, b""), Response(200, b"ok"))
    assert transport.get(GOOD_URL) == b"ok"
    assert transport.sleeps == [BACKOFF_SCHEDULE[0]]


def test_retry_after_header_overrides_a_smaller_backoff():
    transport, _ = make_transport(Response(429, b"", retry_after=30.0), Response(200, b"ok"))
    transport.get(GOOD_URL)
    assert transport.sleeps == [30.0]


def test_backoff_is_capped_even_for_an_absurd_retry_after():
    transport, _ = make_transport(Response(429, b"", retry_after=99999.0), Response(200, b"ok"))
    transport.get(GOOD_URL)
    assert transport.sleeps == [60.0]


def test_exhausting_retries_raises_and_never_returns_empty_bytes():
    """退避用尽必须报错——静默返回空结果会让摄取写出一个空/残缺 batch。"""
    transport, opener = make_transport(Response(429, b""))
    with pytest.raises(RateLimitedError, match="退避重试"):
        transport.get(GOOD_URL)
    assert len(opener.urls) == len(BACKOFF_SCHEDULE) + 1
    assert transport.sleeps == list(BACKOFF_SCHEDULE)


def test_5xx_is_retried():
    transport, _ = make_transport(Response(503, b""), Response(200, b"ok"))
    assert transport.get(GOOD_URL) == b"ok"
    assert transport.sleeps == [BACKOFF_SCHEDULE[0]]


def test_404_is_a_missing_file_not_a_rate_limit():
    """上游该月无归档是正常事实，调用方按缺档处理，不该退避重试。"""
    transport, opener = make_transport(Response(404, b""))
    with pytest.raises(FileNotFoundError):
        transport.get(GOOD_URL)
    assert len(opener.urls) == 1
    assert transport.sleeps == []


@pytest.mark.parametrize("status", [401, 403, 410, 302])
def test_a_definitive_refusal_raises_ingest_error_without_backoff(status):
    """R1：401/403/410（及不跟随的 3xx）是上游的明确答复——`IngestError`，一次、不退避。

    以 `RateLimitedError` 抛的话，外层重试会把它当限流再退避 N 轮（旧行为）。
    """
    transport, opener = make_transport(Response(status, b""))
    with pytest.raises(IngestError, match=f"HTTP {status}"):
        transport.get(GOOD_URL)
    assert len(opener.urls) == 1
    assert transport.sleeps == []
    assert not retry.is_retryable(IngestError("x"))


@pytest.mark.parametrize("status", [418, 429, 500, 502, 503, 504, 599])
def test_rate_limit_and_server_errors_back_off_then_raise_rate_limited(status):
    transport, opener = make_transport(Response(status, b""))
    with pytest.raises(RateLimitedError, match=f"HTTP {status}"):
        transport.get(GOOD_URL)
    assert len(opener.urls) == len(transport.sleeps) + 1 > 1


def test_min_interval_paces_consecutive_requests():
    """两次请求之间保持最小间隔——IP weight 的粗粒度保护。"""
    ticks = iter([0.0, 0.05, 0.05])
    opener = FakeOpener(Response(200, b"ok"))
    transport = PublicTransport(
        opener,
        sleep=lambda _s: None,
        monotonic=lambda: next(ticks),
        jitter=lambda: 0.0,
        min_interval=0.2,
    )
    transport.get(GOOD_URL)
    transport.get(GOOD_URL)
    assert transport.sleeps == [pytest.approx(0.15)]
