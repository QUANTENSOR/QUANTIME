"""Massive 适配器的归一化（QNT-47 阶段 1，关键路径：外部接入）。

全部离线：fixture 是**手写合成**的响应（`fixtures/massive/`，`synthetic: true`），
按官方文档的 Response Attributes 表与 Sample Response 写。适配器本身不出网。
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from quantime_core.allowlist import MASSIVE_REST
from quantime_core.paths import assert_scope
from quantime_data.sources import massive

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "massive"


def load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ---- 标识符 ----


@pytest.mark.parametrize("ticker", ["AAPL", "SPY", "BRK.B", "A", "GOOGL"])
def test_equity_tickers_accepted(ticker):
    assert massive.assert_equity_ticker(ticker) == ticker


@pytest.mark.parametrize(
    "ticker",
    ["", "aapl", "AAPL/../X", "AA PL", "AAPL?x=1", "O:AAPL211119C00085000", "AAPL\n"],
)
def test_bad_equity_tickers_rejected(ticker):
    with pytest.raises(ValueError):
        massive.assert_equity_ticker(ticker)


@pytest.mark.parametrize(
    "ticker",
    ["O:AAPL211119C00085000", "O:SPY241220P00720000", "O:A211119C00085000"],
)
def test_option_tickers_accepted(ticker):
    assert massive.assert_option_ticker(ticker) == ticker


@pytest.mark.parametrize(
    "ticker",
    [
        "AAPL211119C00085000",  # 缺 O: 前缀
        "O:AAPL211119X00085000",  # 既非 C 也非 P
        "O:AAPL211119C0008500",  # 行权价位数不足
        "O:AAPL21119C00085000",  # 日期位数不足
        "O:aapl211119C00085000",
    ],
)
def test_bad_option_tickers_rejected(ticker):
    with pytest.raises(ValueError):
        massive.assert_option_ticker(ticker)


def test_option_scope_is_a_lossless_bijection_and_path_legal():
    """OCC ticker 含 `:`，而 `assert_scope` 的字符集不含它——映射必须无损且合法。"""
    ticker = "O:AAPL211119C00085000"
    scope = massive.option_scope(ticker)
    assert ":" not in scope
    assert_scope(scope)  # 不抛即为湖路径可用
    assert massive.option_ticker_from_scope(scope) == ticker


def test_raw_option_ticker_is_not_a_legal_scope():
    """反证：上一条不是空集通过——直接拿 ticker 当 scope 确实会被路径规范拒绝。"""
    from quantime_core.paths import PathSpecError

    with pytest.raises(PathSpecError):
        assert_scope("O:AAPL211119C00085000")


# ---- URL ----


def test_urls_use_the_allowlisted_host_and_never_carry_a_key():
    urls = [
        massive.equity_daily_bars_url("AAPL", dt.date(2024, 1, 1), dt.date(2024, 1, 31)),
        massive.option_daily_bars_url(
            "O:AAPL211119C00085000", dt.date(2021, 9, 1), dt.date(2021, 11, 19)
        ),
        massive.splits_url("AAPL"),
        massive.dividends_url("AAPL", start=dt.date(2020, 1, 1)),
        massive.option_contracts_url("AAPL", expiration_date=dt.date(2021, 11, 19)),
    ]
    for url in urls:
        assert url.startswith(f"https://{MASSIVE_REST.host}/"), url
        lowered = url.lower()
        for banned in ("apikey", "api_key", "token=", "access_key", "bearer"):
            assert banned not in lowered, f"URL 里出现疑似凭据: {url}"


def test_daily_bars_are_requested_unadjusted():
    """只存未复权价：复权口径会随新事件改变昨天的数字，而湖只 insert。"""
    url = massive.equity_daily_bars_url("AAPL", "2024-01-01", "2024-01-31")
    assert "adjusted=false" in url
    assert "adjusted=true" not in url


def test_daily_bars_request_ascending_order():
    url = massive.equity_daily_bars_url("AAPL", "2024-01-01", "2024-01-31")
    assert "sort=asc" in url


def test_option_contracts_url_defaults_to_active_chain():
    url = massive.option_contracts_url("AAPL")
    assert "expired=false" in url
    assert "underlying_ticker=AAPL" in url


def test_url_builders_reject_malformed_dates():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        massive.equity_daily_bars_url("AAPL", "2024-1-1", "2024-01-31")
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        massive.equity_daily_bars_url("AAPL", "2024-01-01", "../../etc")


def test_year_chunks_align_to_calendar_years():
    got = massive.year_chunks(dt.date(2022, 5, 3), dt.date(2024, 2, 9))
    assert got == [
        (dt.date(2022, 5, 3), dt.date(2022, 12, 31)),
        (dt.date(2023, 1, 1), dt.date(2023, 12, 31)),
        (dt.date(2024, 1, 1), dt.date(2024, 2, 9)),
    ]


def test_year_chunks_single_day_and_reject_inverted_range():
    assert massive.year_chunks(dt.date(2024, 3, 1), dt.date(2024, 3, 1)) == [
        (dt.date(2024, 3, 1), dt.date(2024, 3, 1))
    ]
    with pytest.raises(ValueError, match="区间非法"):
        massive.year_chunks(dt.date(2024, 3, 2), dt.date(2024, 3, 1))


# ---- 日线归一化 ----


def test_equity_daily_normalizes_to_the_declared_schema():
    table = massive.normalize_equity_daily(load("equity-daily-AAPL-2024-01.json"), ticker="AAPL")
    assert table.schema == massive.EQUITY_DAILY_SCHEMA
    assert table.num_rows == 5
    assert table.column("ticker").to_pylist() == ["AAPL"] * 5
    assert table.column("close")[0].as_py() == pytest.approx(185.64)
    assert table.column("window_start")[0].as_py() == dt.datetime(2024, 1, 2, 5, tzinfo=dt.UTC)


def test_equity_daily_sorts_and_keeps_missing_optionals_null():
    """上游行序不保证；`vw`/`n` 缺失记 null（0 是一个真实的值，不能拿来冒充未知）。"""
    table = massive.normalize_equity_daily(
        load("equity-daily-AAPL-unsorted-with-nulls.json"), ticker="AAPL"
    )
    times = table.column("window_start").to_pylist()
    assert times == sorted(times), "行序未本地排序，确定性写入会随上游行序漂移"
    # 第三行（t=1704344400000 最大）缺 vw / n。
    assert table.column("vwap")[2].as_py() is None
    assert table.column("trade_count")[2].as_py() is None
    # `otc` 缺失即 false（文档：为 false 时该字段被省略），显式给 true 的那行为 true。
    assert table.column("otc").to_pylist() == [False, True, False]


def test_equity_daily_with_no_results_is_an_empty_table_not_an_error():
    """区间内无合格成交是正常情况（文档明说不产出 bar），不是失败。"""
    table = massive.normalize_equity_daily(load("equity-daily-AAPL-empty.json"), ticker="AAPL")
    assert table.num_rows == 0
    assert table.schema == massive.EQUITY_DAILY_SCHEMA


def test_option_daily_derives_the_underlying_from_the_occ_ticker():
    table = massive.normalize_option_daily(
        load("option-daily-AAPL211119C00085000.json"), ticker="O:AAPL211119C00085000"
    )
    assert table.schema == massive.OPTION_DAILY_SCHEMA
    assert table.num_rows == 3
    assert set(table.column("underlying_ticker").to_pylist()) == {"AAPL"}
    assert table.column("volume").to_pylist() == [2.0, 12.0, 31.0]


def test_option_daily_rejects_an_equity_ticker():
    with pytest.raises(ValueError, match="OCC"):
        massive.normalize_option_daily(load("equity-daily-AAPL-2024-01.json"), ticker="AAPL")


# ---- 公司行动 ----


def test_splits_normalize_sorted_by_execution_date():
    table = massive.normalize_splits(load("splits-AAPL.json"), ticker="AAPL")
    assert table.schema == massive.SPLIT_SCHEMA
    assert table.column("execution_date").to_pylist() == [
        dt.date(2005, 2, 28),
        dt.date(2020, 8, 31),
    ]
    assert table.column("split_to").to_pylist() == [2.0, 4.0]
    assert table.column("historical_adjustment_factor")[1].as_py() == pytest.approx(0.25)


def test_dividends_normalize_with_nullable_optional_dates():
    table = massive.normalize_dividends(load("dividends-AAPL.json"), ticker="AAPL")
    assert table.schema == massive.DIVIDEND_SCHEMA
    assert table.column("ex_dividend_date").to_pylist() == [
        dt.date(2025, 5, 12),
        dt.date(2025, 8, 11),
    ]
    # 第一行（2025-05-12）缺这几项。
    assert table.column("declaration_date")[0].as_py() is None
    assert table.column("record_date")[0].as_py() is None
    assert table.column("historical_adjustment_factor")[0].as_py() is None
    assert table.column("cash_amount")[1].as_py() == pytest.approx(0.26)


def test_corporate_actions_refuse_rows_for_another_ticker():
    """混入他股的行必须失败：按 ticker 分区的湖里，一行错位就是一条假事件。"""
    payload = load("splits-AAPL.json").replace(b'"ticker": "AAPL"', b'"ticker": "MSFT"', 1)
    with pytest.raises(massive.SourceFormatError, match="他股"):
        massive.normalize_splits(payload, ticker="AAPL")


# ---- 期权合约参考 ----


def test_option_contracts_normalize_sorted_by_ticker():
    table = massive.normalize_option_contracts(
        load("option-contracts-AAPL-2021-11-19.json"), underlying="AAPL"
    )
    assert table.schema == massive.OPTION_CONTRACT_SCHEMA
    assert table.column("ticker").to_pylist() == [
        "O:AAPL211119C00085000",
        "O:AAPL211119C00090000",
        "O:AAPL211119P00085000",
    ]
    assert table.column("contract_type").to_pylist() == ["call", "call", "put"]
    assert table.column("strike_price").to_pylist() == [85.0, 90.0, 85.0]
    assert table.column("correction")[0].as_py() is None  # 该行文档允许省略


def test_additional_underlyings_is_stored_as_canonical_json():
    """嵌套结构存成键排序的 JSON 文本：schema 固定，且同输入同字节（§4.2）。"""
    table = massive.normalize_option_contracts(
        load("option-contracts-AAPL-2021-11-19.json"), underlying="AAPL"
    )
    values = table.column("additional_underlyings").to_pylist()
    assert values[0] is None and values[1] is None
    decoded = json.loads(values[2])
    assert decoded == [
        {"amount": 44, "type": "equity", "underlying": "VMW"},
        {"amount": 6.53, "type": "currency", "underlying": "USD"},
    ]
    # 键排序 + 无空格 → 逐字节确定。
    assert values[2].startswith('[{"amount":44,')


def test_option_contracts_refuse_another_underlying():
    payload = load("option-contracts-AAPL-2021-11-19.json").replace(
        b'"underlying_ticker": "AAPL"', b'"underlying_ticker": "MSFT"', 1
    )
    with pytest.raises(massive.SourceFormatError, match="他股"):
        massive.normalize_option_contracts(payload, underlying="AAPL")


# ---- 失败路径：宁可失败也不猜 ----


def test_not_authorized_status_fails_instead_of_returning_an_empty_table():
    """无权限的响应长得像「0 条结果」。当成空表会把一次失败的摄取写成一个真空 batch。"""
    with pytest.raises(massive.SourceFormatError, match="NOT_AUTHORIZED"):
        massive.normalize_equity_daily(load("error-not-authorized.json"), ticker="AAPL")


def test_missing_required_field_fails_rather_than_defaulting():
    payload = load("equity-daily-AAPL-2024-01.json").replace(b'"c": 185.64,', b"", 1)
    with pytest.raises(massive.SourceFormatError, match="缺字段"):
        massive.normalize_equity_daily(payload, ticker="AAPL")


def test_non_json_payload_fails():
    with pytest.raises(massive.SourceFormatError, match="JSON"):
        massive.normalize_equity_daily(b"<html>503</html>", ticker="AAPL")


def test_results_must_be_an_array():
    with pytest.raises(massive.SourceFormatError, match="results"):
        massive.normalize_equity_daily(b'{"status":"OK","results":{"c":1}}', ticker="AAPL")


def test_delayed_status_is_accepted():
    """低档位返回 DELAYED（15 分钟延迟）是正常的，不该被当成错误。"""
    payload = load("equity-daily-AAPL-2024-01.json").replace(
        b'"status": "OK"', b'"status": "DELAYED"'
    )
    assert massive.normalize_equity_daily(payload, ticker="AAPL").num_rows == 5


# ---- 分页 ----


def test_next_page_url_is_returned_verbatim_for_the_caller_to_re_gate():
    url = massive.next_page_url(load("paged-splits-AAPL-page1.json"))
    assert url is not None and url.startswith("https://")


def test_next_page_url_is_none_on_the_last_page():
    assert massive.next_page_url(load("splits-AAPL.json")) is None


# ---- 文档化的常量 ----


def test_free_tier_interval_matches_the_documented_five_per_minute():
    assert pytest.approx(60.0 / 5) == massive.FREE_TIER_MIN_INTERVAL


def test_source_and_version_are_stable_literals():
    """`source`/`source_version` 进每一行 provenance；改动它们等于让历史批次不可比。"""
    assert massive.SOURCE == "massive"
    assert massive.SOURCE_VERSION.startswith("massive-rest-")


def test_daily_step_is_deliberately_unset():
    """美股交易日不等距（周末+假日+半日市）。伪造 1 天步长会把每个周末报成缺口。"""
    assert massive.FREQ_STEP["1d"] is None
