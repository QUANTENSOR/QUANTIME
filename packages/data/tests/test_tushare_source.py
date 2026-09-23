"""Tushare Pro 适配器：请求计划与归一化（QNT-48）——全部离线，读合成 fixture。

fixture 是**按文档手写的合成响应**（`fixtures/tushare_pro/`，`synthetic: true`），
不是录制：阶段 1 无 token。阶段 2 用脱敏真实录制替换/补充。
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from quantime_data.sources import tushare as ts
from quantime_data.transport import TUSHARE_READONLY_API_NAMES

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "tushare_pro"


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def data_of(name: str) -> dict:
    return load(name)["data"]


# ---- host / 端点边界 ----


def test_host_comes_from_the_allowlist_and_is_credentialed_readonly():
    from quantime_core.allowlist import assert_credentialed_readonly_host

    for host in ts.HOSTS:
        assert assert_credentialed_readonly_host(host).credentialed_readonly is True
    assert f"https://{ts.HOSTS[0]}/" == ts.API_URL


def test_every_endpoint_api_name_is_on_the_transport_whitelist():
    """适配器与出口白名单不得各自漂移：这里钉住两边一致。"""
    assert {ep.api_name for ep in ts.ENDPOINTS.values()} == set(TUSHARE_READONLY_API_NAMES)


def test_no_account_or_trading_endpoint_is_declared():
    banned = ("order", "account", "balance", "withdraw", "capital", "trade_", "user")
    for name, ep in ts.ENDPOINTS.items():
        assert not any(b in ep.api_name for b in banned if b != "trade_"), name
    # `trade_cal` 里的 `trade_` 是"交易日历"不是"交易"——显式确认它就是那一个。
    assert [n for n in ts.ENDPOINTS if "trade" in n] == ["trade_cal"]


# ---- 请求计划 ----


def test_ranged_endpoint_is_chunked_with_no_gap_and_no_overlap():
    reqs = ts.plan_requests(
        "daily", start=dt.date(2010, 1, 1), end=dt.date(2026, 9, 23), ts_code="000001.SZ"
    )
    assert len(reqs) > 1, "17 年区间必须切片"
    spans = [(r.params["start_date"], r.params["end_date"]) for r in reqs]
    assert spans[0][0] == "20100101" and spans[-1][1] == "20260923"
    for (_, prev_end), (next_start, _) in zip(spans, spans[1:], strict=False):
        prev = dt.datetime.strptime(prev_end, "%Y%m%d").date()
        nxt = dt.datetime.strptime(next_start, "%Y%m%d").date()
        assert nxt == prev + dt.timedelta(days=1), f"切片有缝隙/重叠: {prev} -> {nxt}"


def test_chunk_span_stays_under_the_row_cap():
    """每片 ≤ MAX_DAYS_PER_REQUEST 天，换算成交易日后远低于 6000 行上限。"""
    for lo, hi in ts.date_chunks(dt.date(2000, 1, 1), dt.date(2026, 9, 23)):
        assert (hi - lo).days + 1 <= ts.MAX_DAYS_PER_REQUEST
        assert ((hi - lo).days + 1) * 0.7 < ts.MAX_ROWS_PER_REQUEST


def test_snapshot_endpoint_is_a_single_request():
    reqs = ts.plan_requests("stock_basic")
    assert len(reqs) == 1
    assert reqs[0].params == {"list_status": "L"}


def test_trade_cal_requires_an_exchange():
    with pytest.raises(ts.SourceFormatError, match="exchange"):
        ts.plan_requests("trade_cal", start=dt.date(2026, 1, 1), end=dt.date(2026, 9, 1))
    reqs = ts.plan_requests(
        "trade_cal", start=dt.date(2026, 1, 1), end=dt.date(2026, 9, 1), exchange="SSE"
    )
    assert reqs[0].params["exchange"] == "SSE"


def test_daily_requires_a_ts_code():
    with pytest.raises(ts.SourceFormatError, match="ts_code"):
        ts.plan_requests("daily", start=dt.date(2026, 1, 1), end=dt.date(2026, 9, 1))


def test_unknown_endpoint_is_rejected():
    with pytest.raises(ts.SourceFormatError, match="未知端点"):
        ts.plan_requests("account", start=dt.date(2026, 1, 1), end=dt.date(2026, 9, 1))


def test_reversed_range_is_rejected():
    with pytest.raises(ts.SourceFormatError, match="区间非法"):
        list(ts.date_chunks(dt.date(2026, 9, 2), dt.date(2026, 9, 1)))


def test_describe_never_contains_a_token_field():
    """dry-run 打印的是计划，不是请求体——请求体里才有 token。"""
    for req in ts.plan_requests(
        "daily", start=dt.date(2026, 9, 1), end=dt.date(2026, 9, 10), ts_code="000001.SZ"
    ):
        assert "token" not in req.describe()


# ---- 归一化 ----


def test_daily_normalizes_to_the_declared_schema():
    table = ts.normalize("daily", data_of("daily"))
    assert table.schema == ts.DAILY_SCHEMA
    assert table.num_rows == 16  # 2 只票 × 8 个工作日
    assert set(table.column("ts_code").to_pylist()) == {"000001.SZ", "600000.SH"}


def test_rows_are_sorted_even_though_upstream_returns_them_reversed():
    """上游按 trade_date 倒序返回；不排序则同区间两次摄取 content_sha256 不同。"""
    raw = data_of("daily")
    first_upstream = raw["items"][0][raw["fields"].index("trade_date")]
    table = ts.normalize("daily", raw)
    dates = table.column("trade_date").to_pylist()
    codes = table.column("ts_code").to_pylist()
    assert list(zip(codes, dates, strict=True)) == sorted(zip(codes, dates, strict=True))
    assert first_upstream != dates[0].strftime("%Y%m%d"), "fixture 没有乱序，这条测试成了空转"


def test_normalization_is_byte_for_byte_repeatable():
    a = ts.normalize("daily", data_of("daily"))
    b = ts.normalize("daily", data_of("daily"))
    assert a.equals(b)


def test_columns_are_taken_by_name_not_by_position():
    """上游调换列序时，按下标解析会把 open 读成 high——那种错误几个月都发现不了。"""
    raw = data_of("daily")
    fields = list(raw["fields"])
    i, j = fields.index("open"), fields.index("close")
    shuffled_fields = list(fields)
    shuffled_fields[i], shuffled_fields[j] = shuffled_fields[j], shuffled_fields[i]
    shuffled_items = []
    for row in raw["items"]:
        r = list(row)
        r[i], r[j] = r[j], r[i]
        shuffled_items.append(r)

    baseline = ts.normalize("daily", raw)
    shuffled = ts.normalize("daily", {"fields": shuffled_fields, "items": shuffled_items})
    assert shuffled.equals(baseline), "列序变化改变了解析结果——说明是按下标取的"


def test_extra_upstream_columns_are_ignored():
    """上游加列不该打断摄取（`daily` 文档新增过 ah_vol / ah_amount）。"""
    raw = data_of("daily")
    augmented = {
        "fields": [*raw["fields"], "ah_vol", "ah_amount"],
        "items": [[*row, 1.0, 2.0] for row in raw["items"]],
    }
    assert ts.normalize("daily", augmented).equals(ts.normalize("daily", raw))


def test_missing_column_fails_loudly():
    raw = data_of("daily")
    drop = raw["fields"].index("close")
    trimmed = {
        "fields": [f for k, f in enumerate(raw["fields"]) if k != drop],
        "items": [[v for k, v in enumerate(row) if k != drop] for row in raw["items"]],
    }
    with pytest.raises(ts.SourceFormatError, match="缺少字段"):
        ts.normalize("daily", trimmed)


def test_ragged_rows_are_rejected_rather_than_misaligned():
    raw = data_of("daily")
    broken = {"fields": raw["fields"], "items": [raw["items"][0][:-1], *raw["items"][1:]]}
    with pytest.raises(ts.SourceFormatError, match="列数与 fields 不符"):
        ts.normalize("daily", broken)


def test_row_count_at_the_cap_is_treated_as_truncated():
    """6000 行封顶且上游无截断信号——接受它就是安静地丢数据。"""
    raw = data_of("daily")
    padded = {"fields": raw["fields"], "items": [raw["items"][0]] * ts.MAX_ROWS_PER_REQUEST}
    with pytest.raises(ts.SourceFormatError, match="可能被截断"):
        ts.normalize("daily", padded)


def test_just_under_the_cap_is_accepted():
    raw = data_of("daily")
    padded = {"fields": raw["fields"], "items": [raw["items"][0]] * (ts.MAX_ROWS_PER_REQUEST - 1)}
    assert ts.normalize("daily", padded).num_rows == ts.MAX_ROWS_PER_REQUEST - 1


def test_non_nullable_column_rejects_empty_upstream_value():
    raw = data_of("daily")
    col = raw["fields"].index("trade_date")
    broken = {
        "fields": raw["fields"],
        "items": [[*raw["items"][0][:col], "", *raw["items"][0][col + 1 :]]],
    }
    with pytest.raises(ts.SourceFormatError):
        ts.normalize("daily", broken)


def test_malformed_date_is_rejected():
    raw = data_of("daily")
    col = raw["fields"].index("trade_date")
    broken = {
        "fields": raw["fields"],
        "items": [[*raw["items"][0][:col], "2026-09-01", *raw["items"][0][col + 1 :]]],
    }
    with pytest.raises(ts.SourceFormatError, match="YYYYMMDD"):
        ts.normalize("daily", broken)


def test_adj_factor_carries_the_ex_rights_step():
    table = ts.normalize("adj_factor", data_of("adj_factor"))
    assert table.schema == ts.ADJ_FACTOR_SCHEMA
    factors = sorted(set(table.column("adj_factor").to_pylist()))
    assert len(factors) == 2 and factors[0] < factors[1], "复权因子应有一次跳档"


def test_daily_basic_keeps_the_minimal_field_set():
    table = ts.normalize("daily_basic", data_of("daily_basic"))
    assert table.schema == ts.DAILY_BASIC_SCHEMA
    for needed in ("total_mv", "circ_mv", "turnover_rate", "pe_ttm", "pb"):
        assert needed in table.column_names


def test_trade_cal_keeps_closed_days():
    """`is_open=0` 的行是日历的一半价值——过滤掉就没法判断"该有数据却没有"。"""
    table = ts.normalize("trade_cal", data_of("trade_cal"))
    assert table.schema == ts.TRADE_CAL_SCHEMA
    assert set(table.column("is_open").to_pylist()) == {0, 1}


def test_trade_cal_pretrade_date_may_be_null():
    table = ts.normalize("trade_cal", data_of("trade_cal"))
    assert None in table.column("pretrade_date").to_pylist()


def test_stock_basic_parses_and_leaves_delist_date_null():
    table = ts.normalize("stock_basic", data_of("stock_basic"))
    assert table.schema == ts.STOCK_BASIC_SCHEMA
    assert table.column("delist_date").to_pylist() == [None, None]
    assert table.column("list_date").to_pylist() == [dt.date(1991, 4, 3), dt.date(1999, 11, 10)]


def test_empty_result_is_an_empty_table_not_an_error():
    """区间内无数据（停牌/未上市）是正常情况，不是错误。"""
    table = ts.normalize("daily", {"fields": list(ts.DAILY_SCHEMA.names), "items": []})
    assert table.num_rows == 0 and table.schema == ts.DAILY_SCHEMA


# ---- fixture 自身的性质 ----


def test_fixtures_are_declared_synthetic_with_doc_provenance():
    manifest = json.loads((FIXTURES / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True
    assert manifest["doc_accessed"]
    assert manifest["files"]
    for entry in manifest["files"]:
        assert entry["doc_url"].startswith("https://tushare.pro/")
        assert entry["api_name"] in TUSHARE_READONLY_API_NAMES


def test_fixture_bytes_match_the_generator():
    """fixture 与生成器同步——手改 JSON 而不改生成器会让 `--check` 打红。"""
    import hashlib

    manifest = json.loads((FIXTURES / "MANIFEST.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        blob = (FIXTURES / entry["file"]).read_bytes()
        assert hashlib.sha256(blob).hexdigest() == entry["sha256"], entry["file"]
        assert len(blob) == entry["size"], entry["file"]


def test_no_response_fixture_contains_a_token_or_credential_field():
    """响应 fixture 里绝不能出现 token / 账户信息（阶段 2 的脱敏录制同样受此约束）。

    扫的是 MANIFEST 登记的**响应文件**，不含 MANIFEST 自身——它的 `note` 里写着
    「不含 token」这句说明，按字面 grep 会把那句话本身判成泄漏。
    """
    manifest = json.loads((FIXTURES / "MANIFEST.json").read_text(encoding="utf-8"))
    names = [e["file"] for e in manifest["files"]]
    assert sorted(names) == sorted(
        p.name for p in FIXTURES.glob("*.json") if p.name != "MANIFEST.json"
    )
    for name in names:
        text = (FIXTURES / name).read_text(encoding="utf-8").lower()
        for banned in ("token", "cookie", "authorization", "user_id", "account", "secret"):
            assert banned not in text, f"{name} 含 {banned!r}"
