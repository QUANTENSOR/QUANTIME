"""需 key 的只读出口：三道闸 + 节流退避（QNT-47 关键路径：外部接入与凭据）。

全部离线：opener 是假的，不碰网络；key 是假的，不碰 `op`、不读进程环境。
"""

from __future__ import annotations

import datetime as dt

import pytest
from quantime_core.allowlist import (
    BINANCE_VISION_ARCHIVE,
    MASSIVE_REST,
    MASSIVE_REST_LEGACY,
)
from quantime_data.keyed_transport import (
    API_KEY_ENV,
    KEYED_READONLY_ALL,
    KEYED_READONLY_PATHS,
    CredentialUnavailableError,
    KeyedRequest,
    KeyedTransport,
    assert_keyed_readonly_path,
    assert_keyed_readonly_url,
    read_api_key,
    split_keyed_url,
)
from quantime_data.sources import massive
from quantime_data.transport import (
    BACKOFF_SCHEDULE,
    RateLimitedError,
    Response,
    TransportBoundaryError,
)

HOST = MASSIVE_REST.host
LEGACY = MASSIVE_REST_LEGACY.host
FAKE_KEY = "test-key-not-a-real-credential"
GOOD_URL = f"https://{HOST}/v2/aggs/ticker/AAPL/range/1/day/2024-01-01/2024-01-31?adjusted=false"


class FakeOpener:
    """按脚本回放状态码；记录 (url, headers)。"""

    def __init__(self, *responses: Response) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: dict[str, str]) -> Response:
        self.calls.append((url, dict(headers)))
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


def _clock():
    """单调时钟：每次调用前进 1000 秒，使节流永不触发（节流另有专测）。"""
    state = {"t": 0.0}

    def now() -> float:
        state["t"] += 1000.0
        return state["t"]

    return now


def make_transport(*responses: Response, **kw) -> tuple[KeyedTransport, FakeOpener]:
    opener = FakeOpener(*responses)
    kw.setdefault("monotonic", _clock())
    transport = KeyedTransport(
        opener,
        api_key=FAKE_KEY,
        sleep=lambda _s: None,
        jitter=lambda: 0.0,
        **kw,
    )
    return transport, opener


# ---- 闸 1：host ----


def test_massive_hosts_pass_the_host_gate():
    for host in (HOST, LEGACY):
        url = f"https://{host}/stocks/v1/splits?ticker=AAPL"
        assert assert_keyed_readonly_url(url).credentialed_readonly is True


def test_public_readonly_host_is_rejected_by_the_keyed_gate():
    """公共只读 host 不该走带凭据的出口——三类 host 互不放行。"""
    with pytest.raises(TransportBoundaryError, match="不是需 key 的只读数据 host"):
        assert_keyed_readonly_url(f"https://{BINANCE_VISION_ARCHIVE.host}/stocks/v1/splits")


@pytest.mark.parametrize(
    "host",
    [
        "api.binance.com",  # 主网交易 host
        "api.massive.com.attacker.test",  # 后缀伪装
        "evil-api.massive.com",  # 前缀伪装
        "api.polygon.io.evil.test",
        "localhost",
    ],
)
def test_hosts_outside_the_allowlist_are_rejected(host):
    with pytest.raises(TransportBoundaryError, match="不在 allowlist|不是需 key"):
        assert_keyed_readonly_url(f"https://{host}/stocks/v1/splits")


def test_plaintext_http_is_rejected_because_the_request_carries_a_credential():
    with pytest.raises(TransportBoundaryError, match="https"):
        assert_keyed_readonly_url(f"http://{HOST}/stocks/v1/splits")


def test_userinfo_in_url_is_rejected():
    with pytest.raises(TransportBoundaryError, match="不得携带凭据"):
        assert_keyed_readonly_url(f"https://user:secret@{HOST}/stocks/v1/splits")


# ---- 闸 2：路径（放行） ----


@pytest.mark.parametrize("path", sorted(KEYED_READONLY_PATHS))
def test_every_declared_fixed_path_is_accepted(path):
    assert assert_keyed_readonly_path(path) == path


@pytest.mark.parametrize(
    "path",
    [
        "/v2/aggs/ticker/AAPL/range/1/day/2024-01-01/2024-01-31",
        "/v2/aggs/ticker/BRK.B/range/1/day/2020-01-01/2020-12-31",
        "/v2/aggs/ticker/O:AAPL211119C00085000/range/1/day/2021-09-01/2021-11-19",
    ],
)
def test_daily_aggregate_paths_are_accepted(path):
    assert assert_keyed_readonly_path(path) == path


def test_every_url_the_adapter_builds_passes_its_own_egress_gate():
    """适配器与出口不得各自漂移：凡是 `massive.py` 能拼出来的，闸必须放行。"""
    urls = [
        massive.equity_daily_bars_url("AAPL", dt.date(2024, 1, 1), dt.date(2024, 1, 31)),
        massive.option_daily_bars_url(
            "O:AAPL211119C00085000", dt.date(2021, 9, 1), dt.date(2021, 11, 19)
        ),
        massive.splits_url("AAPL"),
        massive.dividends_url("AAPL", start=dt.date(2020, 1, 1)),
        massive.option_contracts_url("AAPL", expiration_date=dt.date(2021, 11, 19)),
        massive.option_contracts_url("SPY"),
    ]
    for url in urls:
        assert_keyed_readonly_url(url)


# ---- 闸 2：路径（拒绝）——卡要求的「账户/交易类端点被拒绝」测试 ----


@pytest.mark.parametrize(
    "path",
    [
        # Massive/Polygon 自身没有下单端点，但白名单是**白**的：任何长得像账户/交易/
        # 订单/资金的路径都必须被拒，无论它是否真实存在。将来若上游新增这类端点，
        # 这些用例就是那道拦住「顺手加进白名单」的墙。
        "/v2/orders",
        "/v3/order",
        "/v1/account",
        "/v3/accounts/balance",
        "/v2/positions",
        "/api/v3/order/test",
        "/v1/trading/orders",
        "/v2/withdraw",
        "/v1/transfer",
        "/v3/reference/options/contracts/../../../v2/orders",
        "/stocks/v1/splits/../../v2/orders",
        "/v2/aggs/ticker/AAPL/range/1/day/2024-01-01/2024-01-31/../../../../orders",
    ],
)
def test_account_and_trading_shaped_paths_are_rejected(path):
    with pytest.raises(TransportBoundaryError):
        assert_keyed_readonly_path(path)


def test_trading_shaped_url_is_rejected_end_to_end_even_on_an_allowed_host():
    with pytest.raises(TransportBoundaryError, match="不在需 key 的只读白名单"):
        assert_keyed_readonly_url(f"https://{HOST}/v2/orders?symbol=AAPL")


def test_no_whitelisted_path_looks_like_a_trading_endpoint():
    """白名单自检：放行集合里不得出现账户/交易/资金词根。"""
    banned = ("order", "account", "position", "balance", "withdraw", "transfer", "trading")
    for entry in KEYED_READONLY_ALL:
        lowered = entry.lower()
        for word in banned:
            assert word not in lowered, f"白名单条目 {entry!r} 含交易类词根 {word!r}"


@pytest.mark.parametrize(
    "path",
    [
        "/v3/reference/options/contracts/",  # 尾斜杠：不是同一条路径
        "/V3/reference/options/contracts",  # 大小写
        "/v3/reference/options/contract",  # 近似名
        "/v2/aggs/ticker/AAPL/range/1/minute/2024-01-01/2024-01-31",  # 分钟线：本卡不放行
        "/v2/aggs/ticker/AAPL/range/5/day/2024-01-01/2024-01-31",  # multiplier≠1
        "/v2/aggs/ticker/aapl/range/1/day/2024-01-01/2024-01-31",  # 小写 ticker
        "/v2/aggs/ticker/AAPL/range/1/day/2024-01-01",  # 少一段
        "/v2/aggs/ticker/AAPL/range/1/day/2024-01-01/2024-01-31/extra",  # 多一段
        "/v2/aggs/ticker//range/1/day/2024-01-01/2024-01-31",  # 空段
        "/v2/snapshot/locale/us/markets/stocks/tickers",  # 未登记的只读端点也拒
        "",
        "/",
    ],
)
def test_near_miss_paths_are_rejected_fail_closed(path):
    with pytest.raises(TransportBoundaryError):
        assert_keyed_readonly_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "/stocks/v1/%73plits",  # 百分号编码绕过
        "/stocks/v1/splits%00",
        "/stocks\\v1/splits",
        "/stocks/v1/splits\n",
        "/stocks/v1/ splits",
        "/stocks/v1/./splits",
    ],
)
def test_ambiguous_paths_are_rejected_before_normalisation_can_hide_them(path):
    """校验的串必须与发出的串逐字节相同——所以有歧义的形态一律拒，而不是先规范化。"""
    with pytest.raises(TransportBoundaryError):
        assert_keyed_readonly_path(path)


def test_trailing_newline_in_an_aggregate_path_is_rejected():
    """`$` 锚定会放过结尾换行；一个换行足以在请求行里另起一行。"""
    with pytest.raises(TransportBoundaryError):
        assert_keyed_readonly_path("/v2/aggs/ticker/AAPL/range/1/day/2024-01-01/2024-01-31\n")


# ---- 闸 3：凭据 ----


@pytest.mark.parametrize("bad", ["apiKey", "api_key", "token", "access_key", "key"])
def test_a_key_shaped_query_parameter_is_rejected(bad):
    """key 进 URL 就会进代理日志、访问日志和异常信息；它只该在请求头里。"""
    url = f"https://{HOST}/stocks/v1/splits?ticker=AAPL&{bad}=abc123"
    with pytest.raises(TransportBoundaryError, match="疑似凭据"):
        assert_keyed_readonly_url(url)


def test_a_key_shaped_query_parameter_is_rejected_in_first_position():
    with pytest.raises(TransportBoundaryError, match="疑似凭据"):
        assert_keyed_readonly_url(f"https://{HOST}/stocks/v1/splits?apiKey=abc123")


def test_a_lookalike_query_key_is_not_over_rejected():
    """`ticker=` 里含 `key` 的子串，但它不是凭据键——闸按键名边界判，不做子串匹配。"""
    assert_keyed_readonly_url(f"https://{HOST}/stocks/v1/splits?ticker=AAPL&order=asc")


def test_read_api_key_strips_whitespace():
    assert read_api_key({API_KEY_ENV: "  secret-value\n"}) == "secret-value"


def test_read_api_key_missing_fails_with_the_documented_message():
    with pytest.raises(CredentialUnavailableError, match="凭据不可用"):
        read_api_key({})


@pytest.mark.parametrize("value", ["", "   ", "\n\t "])
def test_read_api_key_empty_fails_with_no_fallback(value):
    """空值不得退化成匿名请求——否则「取到的是什么」变成运行时的偶然。"""
    with pytest.raises(CredentialUnavailableError, match="凭据不可用"):
        read_api_key({API_KEY_ENV: value})


def test_read_api_key_error_message_never_contains_the_value():
    try:
        read_api_key({API_KEY_ENV: "   "})
    except CredentialUnavailableError as exc:
        assert "   " not in str(exc).replace(API_KEY_ENV, "")


def test_transport_refuses_an_unstripped_key():
    with pytest.raises(CredentialUnavailableError):
        KeyedTransport(FakeOpener(Response(200, b"")), api_key=" leading-space")


def test_transport_refuses_an_empty_key():
    with pytest.raises(CredentialUnavailableError):
        KeyedTransport(FakeOpener(Response(200, b"")), api_key="")


def test_the_key_travels_in_the_authorization_header_only():
    transport, opener = make_transport(Response(200, b"body"))
    assert transport.get(GOOD_URL) == b"body"
    url, headers = opener.calls[0]
    assert headers["Authorization"] == f"Bearer {FAKE_KEY}"
    assert FAKE_KEY not in url


def test_keyed_request_repr_does_not_leak_the_key():
    """这个对象可能被打进日志或异常回溯——`repr` 必须打码。"""
    request = KeyedRequest(url=GOOD_URL, headers={"Authorization": f"Bearer {FAKE_KEY}"})
    assert FAKE_KEY not in repr(request)
    assert "redacted" in repr(request)


def test_boundary_errors_never_echo_the_key():
    transport, _ = make_transport(Response(200, b""))
    try:
        transport.get(f"https://{HOST}/v2/orders")
    except TransportBoundaryError as exc:
        assert FAKE_KEY not in str(exc)


# ---- 状态码：退避与失败 ----


def test_429_is_retried_with_the_documented_backoff():
    naps: list[float] = []
    opener = FakeOpener(Response(429, b""), Response(429, b""), Response(200, b"ok"))
    transport = KeyedTransport(
        opener,
        api_key=FAKE_KEY,
        sleep=naps.append,
        monotonic=_clock(),
        jitter=lambda: 0.0,
    )
    assert transport.get(GOOD_URL) == b"ok"
    assert len(opener.calls) == 3
    assert naps == [BACKOFF_SCHEDULE[0], BACKOFF_SCHEDULE[1]]


def test_retry_after_header_wins_over_the_schedule():
    naps: list[float] = []
    opener = FakeOpener(Response(429, b"", retry_after=30.0), Response(200, b"ok"))
    transport = KeyedTransport(
        opener,
        api_key=FAKE_KEY,
        sleep=naps.append,
        monotonic=_clock(),
        jitter=lambda: 0.0,
    )
    assert transport.get(GOOD_URL) == b"ok"
    assert naps == [30.0]


def test_exhausted_retries_raise_rather_than_return_empty():
    transport, opener = make_transport(Response(429, b""))
    with pytest.raises(RateLimitedError):
        transport.get(GOOD_URL)
    assert len(opener.calls) == len(BACKOFF_SCHEDULE) + 1


def test_404_is_a_missing_resource_not_a_rate_limit():
    transport, _ = make_transport(Response(404, b""))
    with pytest.raises(FileNotFoundError):
        transport.get(GOOD_URL)


def test_401_is_not_retried_because_a_bad_key_will_not_fix_itself():
    transport, opener = make_transport(Response(401, b""))
    with pytest.raises(RateLimitedError):
        transport.get(GOOD_URL)
    assert len(opener.calls) == 1


def test_5xx_is_retried():
    opener = FakeOpener(Response(503, b""), Response(200, b"ok"))
    transport = KeyedTransport(
        opener, api_key=FAKE_KEY, sleep=lambda _s: None, monotonic=_clock(), jitter=lambda: 0.0
    )
    assert transport.get(GOOD_URL) == b"ok"


# ---- 节流 ----


def test_requests_are_paced_at_the_free_tier_interval():
    """免费档 5 请求/分钟 → 相邻请求至少隔 12 秒，否则第 6 个必然 429。"""
    naps: list[float] = []
    # 时钟消费顺序：第 1 次请求发出后记 0.0；第 2 次请求的节流读到 1.0。
    ticks = iter([0.0, 1.0, 13.0])
    opener = FakeOpener(Response(200, b"ok"))
    transport = KeyedTransport(
        opener,
        api_key=FAKE_KEY,
        sleep=naps.append,
        monotonic=lambda: next(ticks),
        jitter=lambda: 0.0,
    )
    transport.get(GOOD_URL)
    transport.get(GOOD_URL)
    assert naps and naps[0] == pytest.approx(massive.FREE_TIER_MIN_INTERVAL - 1.0)


def test_the_default_interval_is_the_free_tier_not_the_paid_one():
    """默认必须是保守的那一档：拿错默认值的代价是被上游限流甚至封。"""
    transport, _ = make_transport(Response(200, b""))
    assert transport._min_interval == pytest.approx(massive.FREE_TIER_MIN_INTERVAL)


# ---- 分页回来的 URL 也要重新过闸 ----


def test_a_next_url_from_the_payload_is_re_gated_not_trusted():
    """`next_url` 是上游给的字符串。信任它等于把白名单的决定权交给上游。"""
    hostile = f"https://{HOST}/v2/orders?cursor=abc"
    with pytest.raises(TransportBoundaryError):
        assert_keyed_readonly_url(hostile)
    offhost = "https://api.massive.com.evil.test/stocks/v1/splits?cursor=abc"
    with pytest.raises(TransportBoundaryError):
        assert_keyed_readonly_url(offhost)


def test_a_legitimate_next_url_passes():
    assert_keyed_readonly_url(f"https://{HOST}/stocks/v1/splits?ticker=AAPL&cursor=abc123")


def test_split_keyed_url_returns_host_and_path():
    assert split_keyed_url(f"https://{HOST}/stocks/v1/splits?ticker=AAPL") == (
        HOST,
        "/stocks/v1/splits",
    )


# ---- 返修 #1（verify-b P1 ×2）：解码后判键 + 凭据检查前不回显 URL ----

import logging  # noqa: E402
import secrets  # noqa: E402

from quantime_data.transport import redact_url  # noqa: E402


def _fake_key() -> str:
    return f"FAKEKEY_{secrets.token_hex(8)}"


def _assert_rejected_before_opener(url: str) -> TransportBoundaryError:
    """断言被闸拒绝，且 opener 零调用——请求根本没发出。"""
    transport, opener = make_transport(Response(200, b"should-not-be-fetched"))
    with pytest.raises(TransportBoundaryError) as info:
        transport.get(url)
    assert opener.calls == [], f"被拒的 URL 仍到了 opener: {opener.calls!r}"
    return info.value


@pytest.mark.parametrize(
    "query",
    [
        "api%4Bey={k}",  # verify-b 复现：%4B = K
        "%61piKey={k}",  # %61 = a
        "APIKEY={k}",
        "api_key={k}",
        "API-KEY={k}",
        "api%254Bey={k}",  # 双重编码：%25 = %，解一层得 api%4Bey
        "api+key={k}",  # `+` 解码为空格
        "ticker=AAPL&access_token={k}",
        "Authorization=Bearer%20{k}",
        "token={k}",
        "key={k}",
        "apiKey=",  # 空值也拒：键本身就说明有人在往 URL 里拼凭据
    ],
)
def test_credential_shaped_query_keys_are_rejected_after_decoding(query):
    key = _fake_key()
    url = f"https://{HOST}/stocks/v1/splits?{query.format(k=key)}"
    exc = _assert_rejected_before_opener(url)
    assert key not in str(exc)


def test_a_fragment_is_rejected_even_when_it_is_the_only_carrier_of_the_key():
    key = _fake_key()
    exc = _assert_rejected_before_opener(f"https://{HOST}/stocks/v1/splits#apiKey={key}")
    assert "fragment" in str(exc)
    assert key not in str(exc)


def test_an_empty_fragment_is_rejected_too():
    _assert_rejected_before_opener(f"https://{HOST}/stocks/v1/splits?ticker=AAPL#")


def test_rejections_before_the_credential_check_never_echo_the_key(caplog):
    """凭据检查之前的每一种拒绝（scheme / host / fragment / 路径 / 凭据键）都不得回显 key。"""
    key = _fake_key()
    caplog.set_level(logging.DEBUG)
    transport, opener = make_transport(Response(200, b""))
    urls = [
        f"https://{HOST}/stocks/v1/splits?apiKey={key}#frag",  # 卡里点名的那条
        f"http://{HOST}/stocks/v1/splits?apiKey={key}",
        f"https://evil.test/stocks/v1/splits?apiKey={key}",
        f"https://{HOST}/v2/orders?apiKey={key}",
        f"https://{HOST}/stocks/v1/splits?x=1&api%4Bey={key}",
        f"https://{HOST}/stocks/v1/{key}",  # key 甚至拼进了路径
        f"https://{HOST}/stocks/v1/splits?q=..{key}",
    ]
    for url in urls:
        with pytest.raises(TransportBoundaryError) as info:
            transport.get(url)
        for text in (str(info.value), repr(info.value)):
            assert key not in text, f"异常回显了 key: {text}"
    assert opener.calls == []
    assert key not in repr(transport) and key not in str(transport)
    assert FAKE_KEY not in repr(transport)
    for record in caplog.records:
        assert key not in record.getMessage()
        assert FAKE_KEY not in record.getMessage()


def test_the_success_path_logs_no_bearer_value_and_no_query(caplog):
    caplog.set_level(logging.DEBUG, logger="quantime_data.keyed_transport")
    transport, opener = make_transport(Response(200, b"body"))
    url = f"{GOOD_URL}&limit=5000"
    assert transport.get(url) == b"body"
    assert opener.calls, "成功路径没到 opener"
    messages = [r.getMessage() for r in caplog.records]
    assert messages, "成功路径没有 debug 日志——本条断言成了空集通过"
    for message in messages:
        assert FAKE_KEY not in message
        assert "Bearer" not in message
        assert "?" not in message and "adjusted=" not in message


def test_keyed_request_repr_hides_query_and_bearer():
    key = _fake_key()
    request = KeyedRequest(url=f"{GOOD_URL}&cursor=abc", headers={"Authorization": f"Bearer {key}"})
    for text in (repr(request), str(request)):
        assert key not in text and "Bearer" not in text
        assert "?" not in text and "cursor" not in text


def test_http_errors_after_the_gate_do_not_echo_the_query():
    transport, _ = make_transport(Response(401, b""))
    with pytest.raises(RateLimitedError) as info:
        transport.get(f"{GOOD_URL}&cursor=opaque-token-ish")
    assert "cursor" not in str(info.value) and "?" not in str(info.value)


def test_redact_url_keeps_only_scheme_host_path():
    assert (
        redact_url(f"https://{HOST}/stocks/v1/splits?apiKey=x#y")
        == f"https://{HOST}/stocks/v1/splits"
    )


def test_redact_url_hashes_paths_outside_the_safe_charset():
    shown = redact_url(f"https://{HOST}/stocks/%41piKey%3Dsecret")
    assert "secret" not in shown and "sha256:" in shown


def test_a_lookalike_key_that_is_not_a_credential_still_passes():
    """解码后判键不应误伤正常参数：`ticker` / `cursor` / `sort` 都含子串但不是凭据键。"""
    assert_keyed_readonly_url(
        f"https://{HOST}/stocks/v1/splits?ticker=AAPL&cursor=abc&sort=execution_date.asc"
    )
