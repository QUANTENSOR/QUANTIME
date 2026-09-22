"""公共只读出口的两道闸与限流退避（QNT-28 关键路径）。

全部离线：opener 是一个假的，不碰网络。
"""

from __future__ import annotations

import pytest
from quantime_core.allowlist import BINANCE_VISION_ARCHIVE
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


def test_403_is_not_retried():
    transport, opener = make_transport(Response(403, b""))
    with pytest.raises(RateLimitedError, match="HTTP 403"):
        transport.get(GOOD_URL)
    assert len(opener.urls) == 1


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
