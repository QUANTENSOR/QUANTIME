"""需凭据的只读出口：三道闸 + 限流退避 + token 不泄漏（QNT-48 关键路径）。

全部离线：opener 是假的，不碰网络，也不需要任何真实 token。
"""

from __future__ import annotations

import json

import pytest
from quantime_core.allowlist import (
    BINANCE_VISION_ARCHIVE,
    TUSHARE_PRO_API,
    HostNotAllowedError,
    TradingBoundaryError,
    assert_credentialed_readonly_host,
    assert_trading_host,
)
from quantime_data.transport import (
    BACKOFF_SCHEDULE,
    TUSHARE_READONLY_API_NAMES,
    CredentialedTransport,
    CredentialUnavailableError,
    RateLimitedError,
    Response,
    SecretValue,
    TransportBoundaryError,
    TushareApiError,
    assert_api_names_within_authority,
    assert_credentialed_post_url,
    assert_readonly_api_name,
    is_rate_limited,
    redact,
)

HOST = TUSHARE_PRO_API.host
URL = f"https://{HOST}/"

#: 测试用的假 token。刻意取一个容易在文本里认出的形状，好断言它**没有**出现在任何输出里。
FAKE_TOKEN = "tk_SECRET_do_not_log_0123456789abcdef"


def ok_body(fields=("ts_code",), items=(("000001.SZ",),)) -> bytes:
    payload = {
        "code": 0,
        "msg": None,
        "data": {"fields": list(fields), "items": [list(i) for i in items]},
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class FakeOpener:
    """按脚本回放响应；记录 (url, body)。"""

    def __init__(self, *responses: Response) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, bytes]] = []

    def __call__(self, url: str, body: bytes) -> Response:
        self.calls.append((url, body))
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


def _clock():
    state = {"t": 0.0}

    def now() -> float:
        state["t"] += 1000.0  # 每次前进 1000s，节流永不触发（另有专测）
        return state["t"]

    return now


def make_transport(*responses: Response, token: str = FAKE_TOKEN, **kw):
    opener = FakeOpener(*responses)
    transport = CredentialedTransport(
        opener,
        SecretValue(token),
        sleep=lambda _s: None,
        monotonic=_clock(),
        jitter=lambda: 0.0,
        **kw,
    )
    return transport, opener


# ---- host 闸：三类断言互不放行 ----


def test_tushare_host_is_credentialed_readonly_not_public_not_trading():
    entry = assert_credentialed_readonly_host(HOST)
    assert entry.credentialed_readonly is True
    assert entry.public_readonly is False
    assert entry.doc_url.startswith("https://")


def test_trading_assertion_rejects_the_data_source_host():
    """ADR-0001 D1.7：需 key 的数据源**不是**交易 host，不得被当成下单出口。"""
    with pytest.raises(TradingBoundaryError, match="credentialed_readonly=True"):
        assert_trading_host(HOST)


def test_credentialed_assertion_rejects_public_readonly_host():
    """反向也必须关死：带 token 的出口不得去打无 key 的公共源。"""
    with pytest.raises(HostNotAllowedError, match="不是需凭据的只读数据源"):
        assert_credentialed_readonly_host(BINANCE_VISION_ARCHIVE.host)


def test_credentialed_assertion_rejects_unlisted_host():
    with pytest.raises(HostNotAllowedError, match="不在 allowlist"):
        assert_credentialed_readonly_host("api.tushare.pro.attacker.test")


@pytest.mark.parametrize(
    "url",
    [
        f"http://{HOST}/",  # 明文 http
        f"https://user:pw@{HOST}/",  # 凭据进 URL
        f"https://{HOST}/?token=x",  # 凭据可能被塞进 query
        f"https://{HOST}/#frag",
        f"https://{HOST}/api/v1/order",  # 路径不在白名单
        f"https://{HOST}/anything",
        "https://evil.example.test/",
    ],
)
def test_bad_urls_are_rejected_before_any_request(url):
    with pytest.raises(TransportBoundaryError):
        assert_credentialed_post_url(url)


def test_good_url_passes_both_gates():
    assert assert_credentialed_post_url(URL).host == HOST


# ---- api_name 闸：端点在 body 里，白名单就必须开在 body 上 ----


@pytest.mark.parametrize(
    "api_name",
    [
        # Tushare 侧的账户/资金/交易面接口，以及通用的下单动词——一个都不得放行。
        "user",
        "balance",
        "account",
        "order",
        "trade",
        "place_order",
        "withdraw",
        "capital",
        "token",
        "sub_account",
        # 近亲：前缀匹配会放行的形态（白名单必须是精确枚举）。
        "daily_order",
        "dailyx",
        "adj_factor_account",
        "stock_basic_trade",
    ],
)
def test_non_whitelisted_api_names_are_rejected(api_name):
    with pytest.raises(TransportBoundaryError, match="api_name 不在只读白名单"):
        assert_readonly_api_name(api_name, TUSHARE_READONLY_API_NAMES)


@pytest.mark.parametrize("api_name", sorted(TUSHARE_READONLY_API_NAMES))
def test_whitelisted_api_names_pass(api_name):
    assert assert_readonly_api_name(api_name, TUSHARE_READONLY_API_NAMES) == api_name


def test_whitelist_holds_only_the_five_readonly_endpoints():
    """白名单本身要过一遍尺子——它是放行清单，写错就是直接放行。"""
    assert {
        "stock_basic",
        "trade_cal",
        "daily",
        "adj_factor",
        "daily_basic",
    } == TUSHARE_READONLY_API_NAMES


def test_rejected_api_name_never_reaches_the_opener():
    transport, opener = make_transport(Response(200, ok_body()))
    with pytest.raises(TransportBoundaryError):
        transport.post(URL, api_name="account")
    assert opener.calls == [], "请求必须在发出之前就被拒绝"


# ---- token 不泄漏 ----


def test_secret_value_masks_repr_str_and_fstring():
    secret = SecretValue(FAKE_TOKEN)
    assert FAKE_TOKEN not in repr(secret)
    assert FAKE_TOKEN not in str(secret)
    assert FAKE_TOKEN not in f"{secret}"
    assert FAKE_TOKEN not in f"{secret!r}"
    assert FAKE_TOKEN not in f"{secret:>40}"
    assert FAKE_TOKEN not in "{}".format(secret)  # noqa: UP032 - 显式覆盖 format 路径
    assert FAKE_TOKEN not in json.dumps({"t": repr(secret)})
    assert secret.reveal() == FAKE_TOKEN


def test_secret_value_strips_and_rejects_blank():
    assert SecretValue(f"  {FAKE_TOKEN}\n").reveal() == FAKE_TOKEN
    with pytest.raises(CredentialUnavailableError):
        SecretValue("   \n")


def test_redact_scrubs_the_token_from_arbitrary_text():
    secret = SecretValue(FAKE_TOKEN)
    leaked = f'{{"api_name": "daily", "token": "{FAKE_TOKEN}"}}'
    assert FAKE_TOKEN not in redact(leaked, secret)
    assert SecretValue.MASK in redact(leaked, secret)


def test_token_appears_in_the_body_and_nowhere_else():
    transport, opener = make_transport(Response(200, ok_body()))
    transport.post(URL, api_name="daily", params={"ts_code": "000001.SZ"}, fields=["ts_code"])
    (url, body) = opener.calls[0]
    assert url == URL
    # body 里必须有明文（否则上游不认），但 URL 里绝不能有。
    assert json.loads(body)["token"] == FAKE_TOKEN
    assert FAKE_TOKEN not in url


def test_transport_rejects_a_plain_str_token():
    """明文 str 会绕过掩码与 redact——构造期就拒绝，而不是等到泄漏时。"""
    with pytest.raises(TypeError, match="SecretValue"):
        CredentialedTransport(FakeOpener(Response(200, ok_body())), FAKE_TOKEN)  # type: ignore[arg-type]


def test_upstream_exception_text_is_redacted_before_reraise():
    """第三方客户端常把请求体塞进异常消息——body 里有明文 token，必须洗掉。"""

    def exploding_opener(url: str, body: bytes):
        raise RuntimeError(f"connection reset while sending {body.decode()}")

    transport = CredentialedTransport(
        exploding_opener, SecretValue(FAKE_TOKEN), sleep=lambda _s: None, monotonic=_clock()
    )
    with pytest.raises(RuntimeError) as excinfo:
        transport.post(URL, api_name="daily", params={"ts_code": "000001.SZ"})
    rendered = f"{excinfo.value}{excinfo.value!r}"
    assert FAKE_TOKEN not in rendered
    assert SecretValue.MASK in rendered
    assert excinfo.value.__cause__ is None, "原异常带明文 body，不得挂在 __cause__ 上"


def test_api_error_message_is_redacted():
    """上游把请求原样回显进 msg 的情况（见过的真实形态）——异常文本也不得带 token。"""
    body = json.dumps({"code": 40001, "msg": f"bad token: {FAKE_TOKEN}", "data": None}).encode()
    transport, _ = make_transport(Response(200, body))
    with pytest.raises(TushareApiError) as excinfo:
        transport.post(URL, api_name="daily")
    assert FAKE_TOKEN not in f"{excinfo.value}{excinfo.value.msg}"


def test_non_json_response_body_is_not_echoed():
    """网关页可能把请求原样回显；只报字节数，不回显正文。"""
    transport, _ = make_transport(Response(200, f"<html>{FAKE_TOKEN}</html>".encode()))
    with pytest.raises(RateLimitedError) as excinfo:
        transport.post(URL, api_name="daily")
    assert FAKE_TOKEN not in str(excinfo.value)
    assert "不是 JSON" in str(excinfo.value)


# ---- 限流退避 ----


def test_http_429_is_retried_with_exponential_backoff():
    transport, opener = make_transport(
        Response(429, b"", retry_after=None), Response(200, ok_body())
    )
    transport.post(URL, api_name="daily")
    assert len(opener.calls) == 2
    assert transport.sleeps == [BACKOFF_SCHEDULE[0]]


def test_retry_after_header_wins_when_larger():
    transport, opener = make_transport(
        Response(429, b"", retry_after=7.0), Response(200, ok_body())
    )
    transport.post(URL, api_name="daily")
    assert transport.sleeps == [7.0]


def test_rate_limit_reported_inside_http_200_is_retried():
    """Tushare 在 200 里用 `code != 0` 报「每分钟最多访问该接口 N 次」。"""
    limited = json.dumps(
        {"code": 40203, "msg": "抱歉，您每分钟最多访问该接口500次", "data": None}
    ).encode()
    transport, opener = make_transport(Response(200, limited), Response(200, ok_body()))
    transport.post(URL, api_name="daily")
    assert len(opener.calls) == 2
    assert transport.sleeps == [BACKOFF_SCHEDULE[0]]


def test_rate_limit_detected_by_message_even_with_unknown_code():
    """文档没有完整错误码表，所以消息关键词也算判据——宁可多退避一次。"""
    assert is_rate_limited(99999, "访问频率过高，请稍后重试")
    assert is_rate_limited(99999, "rate limit exceeded")
    assert not is_rate_limited(40001, "token 无效")


def test_exhausted_retries_raise_and_never_return_empty():
    transport, opener = make_transport(Response(429, b""))
    with pytest.raises(RateLimitedError, match="退避重试"):
        transport.post(URL, api_name="daily")
    assert len(opener.calls) == len(BACKOFF_SCHEDULE) + 1
    assert transport.sleeps == list(BACKOFF_SCHEDULE)


def test_non_rate_limit_api_error_fails_immediately_without_retry():
    """`token 无效` 重试 5 次只是白白打上游——不是限流就直接失败。"""
    body = json.dumps({"code": 40001, "msg": "token 无效", "data": None}).encode()
    transport, opener = make_transport(Response(200, body))
    with pytest.raises(TushareApiError):
        transport.post(URL, api_name="daily")
    assert len(opener.calls) == 1
    assert transport.sleeps == []


def test_min_interval_paces_consecutive_requests():
    """节流是被 ban 的第一道防线，不是可选的礼貌。"""
    opener = FakeOpener(Response(200, ok_body()))
    ticks = iter([0.0, 0.0, 0.01, 0.01, 0.02])
    transport = CredentialedTransport(
        opener,
        SecretValue(FAKE_TOKEN),
        sleep=lambda _s: None,
        monotonic=lambda: next(ticks),
        jitter=lambda: 0.0,
        min_interval=0.5,
    )
    transport.post(URL, api_name="daily")
    transport.post(URL, api_name="adj_factor")
    assert transport.sleeps and transport.sleeps[0] > 0, "第二次请求必须被节流"


def test_code_zero_but_malformed_data_is_not_silently_accepted():
    body = json.dumps({"code": 0, "msg": None, "data": None}).encode()
    transport, _ = make_transport(Response(200, body))
    with pytest.raises(RateLimitedError, match="data 缺少 fields/items"):
        transport.post(URL, api_name="daily")


def test_request_body_is_byte_for_byte_deterministic():
    """同参数请求体逐字节确定——运维核对「发出去的是什么」时不必把 body 打出来。"""
    t1, o1 = make_transport(Response(200, ok_body()))
    t2, o2 = make_transport(Response(200, ok_body()))
    kw = {
        "api_name": "daily",
        "params": {"end_date": "20260930", "ts_code": "000001.SZ"},
        "fields": ["ts_code"],
    }
    t1.post(URL, **kw)
    t2.post(URL, **{**kw, "params": {"ts_code": "000001.SZ", "end_date": "20260930"}})
    assert o1.calls[0][1] == o2.calls[0][1]


# ---- 构造闸：调用方给的 api_names 只能是权威枚举的子集（QNT-48 返工 / verify-b P1）----


def test_caller_cannot_widen_the_gate_with_a_trading_lookalike():
    """verify-b 复现的那条路径：传 `{"daily_order"}` 必须在**构造点**就抛。

    原实现收下任意名单，这一句能跑通并真的把 `daily_order` 连同 token 发出去。
    """
    opener = FakeOpener(Response(200, ok_body()))
    with pytest.raises(TransportBoundaryError, match="超出权威只读枚举"):
        CredentialedTransport(opener, SecretValue(FAKE_TOKEN), api_names=frozenset({"daily_order"}))
    assert opener.calls == [], "构造就该失败，不该有任何请求发出"


def test_caller_cannot_append_an_unknown_name_to_the_authoritative_set():
    """超集同样拒绝——「权威枚举 + 我再加一个」是最像合规的扩权写法。"""
    with pytest.raises(TransportBoundaryError, match="dailyx"):
        CredentialedTransport(
            FakeOpener(Response(200, ok_body())),
            SecretValue(FAKE_TOKEN),
            api_names=TUSHARE_READONLY_API_NAMES | {"dailyx"},
        )


def test_narrowing_to_a_legitimate_subset_still_gates_everything_else():
    """收窄是允许的，而且必须真的生效：只许 `trade_cal` 时 `daily` 也要被拒。"""
    transport, opener = make_transport(Response(200, ok_body()), api_names=frozenset({"trade_cal"}))
    transport.post(URL, api_name="trade_cal", fields=("cal_date",))
    assert len(opener.calls) == 1

    with pytest.raises(TransportBoundaryError, match="不在只读白名单内"):
        transport.post(URL, api_name="daily", fields=("ts_code",))
    assert len(opener.calls) == 1, "被拒的请求不该发出去"


@pytest.mark.parametrize(
    "names",
    [
        frozenset({"daily_order"}),
        frozenset({"stock_basic", "account"}),
        TUSHARE_READONLY_API_NAMES | {"trade_order"},
        frozenset({"DAILY"}),  # 大小写不同就是另一个名字，不做归一化
    ],
)
def test_authority_check_rejects_anything_outside_the_enum(names):
    with pytest.raises(TransportBoundaryError):
        assert_api_names_within_authority(names)


def test_empty_api_names_is_rejected_as_a_config_error():
    """空集技术上是子集，但一个发不出任何请求的出口只可能是配错了。"""
    with pytest.raises(TransportBoundaryError, match="为空"):
        assert_api_names_within_authority(frozenset())


def test_every_authoritative_subset_is_accepted():
    """反证：收窄不能被这条校验误伤，否则源侧就没法只声明自己用的端点。"""
    import itertools

    names = sorted(TUSHARE_READONLY_API_NAMES)
    for size in range(1, len(names) + 1):
        for combo in itertools.combinations(names, size):
            assert assert_api_names_within_authority(frozenset(combo)) == frozenset(combo)


def test_default_api_names_is_the_authoritative_enum_itself():
    """默认值必须就是权威枚举——否则「默认安全」这句话本身要靠另一处定义来保证。"""
    import inspect

    sig = inspect.signature(CredentialedTransport.__init__)
    assert sig.parameters["api_names"].default is TUSHARE_READONLY_API_NAMES


# ---- 别名闸：构造时复制冻结，调用方改不动我们的名单（QNT-48 第二轮返工 / verify-b）----


def test_mutating_the_callers_set_after_construction_does_not_widen_the_gate():
    """verify-b 第二次复现的路径：校验通过的是「那一瞬间」的集合，不是我们保存的东西。

    传可变 `set`，构造后再 `.add("daily_order")`——如果保存的是调用方的引用，闸门跟着变。
    """
    names = {"daily"}
    transport, opener = make_transport(Response(200, ok_body()), api_names=names)

    names.add("daily_order")  # 构造之后再放宽

    with pytest.raises(TransportBoundaryError, match="不在只读白名单内"):
        transport.post(URL, api_name="daily_order")
    assert opener.calls == [], "被拒的请求不该发出去，更不该带上 token"

    # 原本合法的那个端点仍然能走——冻结的是快照，不是把出口一起锁死。
    transport.post(URL, api_name="daily", fields=("ts_code",))
    assert len(opener.calls) == 1


def test_transport_holds_its_own_frozenset_not_the_callers_object():
    """保存的必须是我们复制出来的 frozenset，不是传进来那个对象。"""
    names = {"daily", "trade_cal"}
    transport, _ = make_transport(Response(200, ok_body()), api_names=names)

    assert transport.api_names is not names
    assert isinstance(transport.api_names, frozenset)
    assert transport.api_names == frozenset({"daily", "trade_cal"})

    names.clear()
    assert transport.api_names == frozenset({"daily", "trade_cal"}), "清空调用方的集合不该影响出口"


def test_default_construction_also_snapshots_the_authoritative_enum():
    """默认路径同样是复制：`api_names` 不该与模块级常量是同一个对象被就地改掉的风险源。

    `TUSHARE_READONLY_API_NAMES` 本身是 frozenset（改不动），这里确认的是相等性成立，
    以及默认值没有在复制过程中被意外收窄。
    """
    transport, _ = make_transport(Response(200, ok_body()))
    assert transport.api_names == TUSHARE_READONLY_API_NAMES


def test_a_frozenset_subclass_that_lies_cannot_widen_the_gate():
    """不靠「拒绝可变类型」解决问题——类型判断挡不住会说谎的容器。

    这个子类每次 `__iter__` 都多吐一个交易近似名。复制冻结取的是构造那一刻的内容，
    之后它再怎么变都与出口无关；如果实现改成保存引用并逐次查询，这条就会红。
    """

    class Sneaky(frozenset):
        def __contains__(self, item):  # noqa: D105 - 故意对任何名字都点头
            return True

    transport, opener = make_transport(Response(200, ok_body()), api_names=Sneaky({"daily"}))
    assert type(transport.api_names) is frozenset, "必须落成纯 frozenset，不能留子类实例"

    with pytest.raises(TransportBoundaryError, match="不在只读白名单内"):
        transport.post(URL, api_name="daily_order")
    assert opener.calls == []


def test_backoff_schedule_is_snapshotted_too():
    """同类别名：调用方传 list 后 `.clear()` 不该把退避表抽掉。"""
    schedule = [0.5, 1.0]
    transport, _ = make_transport(Response(200, ok_body()), backoff=schedule)
    schedule.clear()
    assert transport._backoff == (0.5, 1.0)
