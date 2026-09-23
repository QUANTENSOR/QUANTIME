"""出口边界的异常契约（QNT-45 R1）——走**真实**链路
`cli._http_opener → PublicTransport → run_daily`。

只替换 `httpx.Client.send` 这一处（它是唯一真正碰网络的调用），其余全是生产代码：
`build_request`、出口闸、状态码分流、外层退避、运行记录与报告。单测里各层各自对，
不代表拼起来还对——这正是 verify-a 抓到的那一类问题：httpx 的 `ConnectError` 不是
`OSError`，越过出口后外层不认得它，一次网络抖动就让整次运行崩成 traceback。

全程离线：`send` 被替换后不会有任何字节离开进程。
"""

from __future__ import annotations

import httpx
import pytest
from fixture_source import NOW, SPOT_KLINE_SPEC
from quantime_core.ids import new_run_id
from quantime_data import cli, daily, runlog
from quantime_data.retry import RetryPolicy
from quantime_data.transport import PublicTransport, TransportIOError

MAX_ATTEMPTS = 3
URL = "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2026-08.zip"


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.now += s

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def sent(monkeypatch):
    """把 `httpx.Client.send` 换成剧本：`sent.reply = callable(request) -> Response | raise`。"""

    class Script:
        def __init__(self) -> None:
            self.urls: list[str] = []
            self.reply = None

    script = Script()

    def fake_send(self, request, **_kw):
        script.urls.append(str(request.url))
        return script.reply(request)

    monkeypatch.setattr(httpx.Client, "send", fake_send)
    return script


def _run(root, clock):
    transport = PublicTransport(
        cli._http_opener(),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        jitter=lambda: 0.0,
        backoff=(0.5, 1.0),
    )
    out = daily.run_daily(
        root,
        [SPOT_KLINE_SPEC],
        cli._fetcher(transport),
        run_id=new_run_id(),
        retry_policy=RetryPolicy(max_attempts=MAX_ATTEMPTS, base_delay=1.0),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        now=NOW,
    )
    return out, transport


def test_the_opener_never_lets_an_httpx_exception_cross_the_exit(sent):
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    sent.reply = refuse
    opener = cli._http_opener()
    with pytest.raises(TransportIOError) as info:
        opener(URL)
    assert isinstance(info.value, OSError)
    assert not isinstance(info.value, httpx.HTTPError)
    assert isinstance(info.value.__cause__, httpx.ConnectError)


@pytest.mark.parametrize(
    "exc",
    [httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError],
    ids=["connect", "read-timeout", "protocol"],
)
def test_a_network_failure_is_retried_up_to_the_cap_then_fails_the_run(root, clock, sent, exc):
    """R1(a)：网络层故障 → 退避重试到上限 → 序列 failed、运行记录 failed、退出码非零。"""

    def broken(request):
        raise exc("boom", request=request)

    sent.reply = broken
    out, transport = _run(root, clock)

    assert len(sent.urls) == MAX_ATTEMPTS
    assert clock.slept == [1.0, 2.0]  # 外层退避：每次重试之前都睡过
    assert transport.sleeps == []  # 内层不管网络故障，只管状态码
    assert out.exit_code != 0
    rec = runlog.read_run_log(root, out.run_id)
    assert rec["outcome"] == runlog.OUTCOME_FAILED
    (series,) = rec["series"]
    assert series["attempts"] == MAX_ATTEMPTS
    assert series["error_class"] == "RetryExhaustedError(TransportIOError)"
    (reported,) = out.report.series
    assert reported.status == "failed" and reported.coverage == "failed"
    assert reported.retries == MAX_ATTEMPTS - 1


@pytest.mark.parametrize("status", [401, 403, 410])
def test_a_definitive_refusal_is_one_request_no_backoff_and_a_failed_run(root, clock, sent, status):
    """R1(b)：403 类 → 只发 1 次、内外层都不退避、运行记录 failed。"""
    sent.reply = lambda request: httpx.Response(status, request=request)
    out, transport = _run(root, clock)

    assert len(sent.urls) == 1
    assert clock.slept == []
    assert transport.sleeps == []
    assert out.exit_code != 0
    rec = runlog.read_run_log(root, out.run_id)
    assert rec["outcome"] == runlog.OUTCOME_FAILED
    (series,) = rec["series"]
    assert (series["attempts"], series["retries"]) == (1, 0)
    assert series["error_class"] == "IngestError"
    assert f"HTTP {status}" in series["error"]


def test_a_server_error_backs_off_inside_then_outside_before_failing(root, clock, sent):
    """503 走两层退避：内层按阶梯睡完抛 `RateLimitedError`，外层再整件重来。"""
    sent.reply = lambda request: httpx.Response(503, request=request)
    out, transport = _run(root, clock)

    assert len(sent.urls) == MAX_ATTEMPTS * 3  # 每次外层尝试 = 1 + 2 次内层退避
    assert transport.sleeps == [0.5, 1.0] * MAX_ATTEMPTS
    assert out.exit_code != 0
    assert out.log.series[0].error_class == "RetryExhaustedError(RateLimitedError)"


def test_a_404_through_the_real_chain_is_recorded_missing_and_never_retried(root, clock, sent):
    sent.reply = lambda request: httpx.Response(404, request=request)
    out, transport = _run(root, clock)
    assert len(sent.urls) == 1
    assert clock.slept == [] and transport.sleeps == []
    # 唯一的归档 404 → 没有任何字节 → 序列失败（不写空 batch），但它不是被重试出来的失败。
    (series,) = out.report.series
    assert series.status == "failed" and series.retries == 0
    assert series.missing_upstream == ("BTCUSDT-1d-2026-08.zip",)
