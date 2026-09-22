"""缺口 / 重复核查（QNT-28）——**只产出报告，不改数据**。"""

from __future__ import annotations

import datetime as dt

import pyarrow as pa
import pytest
from quantime_data import audit

H = dt.timedelta(hours=1)
BASE = dt.datetime(2026, 8, 1, tzinfo=dt.UTC)


def times(*hours: int) -> list[dt.datetime]:
    return [BASE + h * H for h in hours]


# ---- 缺口 ----


def test_no_gap_in_a_contiguous_series():
    assert audit.find_gaps(times(0, 1, 2, 3), H) == ()


def test_a_single_missing_step_is_reported():
    gaps = audit.find_gaps(times(0, 1, 3, 4), H)
    assert len(gaps) == 1
    assert gaps[0].start == BASE + 1 * H
    assert gaps[0].end == BASE + 3 * H
    assert gaps[0].missing_steps == 1


def test_a_long_hole_counts_every_missing_step():
    gaps = audit.find_gaps(times(0, 10), H)
    assert gaps[0].missing_steps == 9


def test_multiple_gaps_are_all_reported():
    gaps = audit.find_gaps(times(0, 2, 3, 9), H)
    assert [g.missing_steps for g in gaps] == [1, 5]


def test_duplicate_timestamps_are_not_a_gap():
    assert audit.find_gaps(times(0, 1, 1, 2), H) == ()


def test_non_multiple_delta_still_reports_a_gap():
    """差值不是步长整数倍时也要记账，不静默吞掉。"""
    ts = [BASE, BASE + dt.timedelta(minutes=90)]
    gaps = audit.find_gaps(ts, H)
    assert len(gaps) == 1
    assert gaps[0].missing_steps == 1


def test_empty_and_single_point_series_have_no_gaps():
    assert audit.find_gaps([], H) == ()
    assert audit.find_gaps(times(0), H) == ()


def test_non_positive_step_is_rejected():
    with pytest.raises(ValueError, match="step"):
        audit.find_gaps(times(0, 1), dt.timedelta(0))


# ---- 重复 ----


def test_no_duplicates_in_distinct_keys():
    assert audit.find_duplicates(["a", "b", "c"]) == ()


def test_duplicates_are_counted_and_sorted():
    dups = audit.find_duplicates(["b", "a", "b", "b", "a"])
    assert [(d.key, d.occurrences) for d in dups] == [("a", 2), ("b", 3)]


# ---- 表级核查 ----


def build_table(ts: list[dt.datetime], symbol: str = "BTCUSDT") -> pa.Table:
    return pa.Table.from_pydict(
        {"symbol": [symbol] * len(ts), "open_time": ts, "close": [1.0] * len(ts)},
        schema=pa.schema(
            [
                pa.field("symbol", pa.string()),
                pa.field("open_time", pa.timestamp("us", tz="UTC")),
                pa.field("close", pa.float64()),
            ]
        ),
    )


def audit_it(table: pa.Table, step: dt.timedelta | None = H) -> audit.AuditResult:
    return audit.audit_table(
        table,
        scope="BTCUSDT",
        datatype="kline",
        freq="1h",
        audited_batch_id="01JBXQ8Z1ABCDEFGHJKMNPQRST",
        time_column="open_time",
        step=step,
        key_columns=("symbol", "open_time"),
    )


def test_clean_table_is_clean():
    result = audit_it(build_table(times(0, 1, 2)))
    assert result.clean
    assert result.rows_audited == 3


def test_gap_and_duplicate_are_both_found():
    result = audit_it(build_table(times(0, 1, 1, 5)))
    assert [g.missing_steps for g in result.gaps] == [3]
    assert [d.occurrences for d in result.duplicates] == [2]
    assert not result.clean


def test_unsorted_input_is_sorted_before_gap_detection():
    """行序不该影响结论——否则上游乱序会伪造出缺口。"""
    assert audit_it(build_table(times(3, 0, 2, 1))).clean


def test_step_none_skips_gap_detection_but_still_finds_duplicates():
    """funding 的间隔由上游逐行给出，不做等距检查。"""
    result = audit_it(build_table(times(0, 99, 99)), step=None)
    assert result.gaps == ()
    assert [d.occurrences for d in result.duplicates] == [2]


def test_missing_column_is_an_error_not_a_silent_pass():
    with pytest.raises(KeyError, match="open_time"):
        audit.audit_table(
            pa.table({"symbol": ["B"]}),
            scope="B",
            datatype="kline",
            freq="1h",
            audited_batch_id="01JBXQ8Z1ABCDEFGHJKMNPQRST",
            time_column="open_time",
            step=H,
            key_columns=("symbol",),
        )


# ---- 报告表 ----


def test_report_has_a_summary_row_per_result_plus_one_row_per_finding():
    results = [audit_it(build_table(times(0, 1, 1, 5))), audit_it(build_table(times(0, 1)))]
    report = audit.report_table(results)
    assert report.schema == audit.AUDIT_SCHEMA
    kinds = report.column("kind").to_pylist()
    assert kinds == ["summary", "gap", "duplicate", "summary"]


def test_report_is_deterministic_byte_for_byte():
    from quantime_core import parquet_io

    results = [audit_it(build_table(times(0, 1, 1, 5)))]
    a = parquet_io.table_to_bytes(audit.report_table(results))
    b = parquet_io.table_to_bytes(audit.report_table(results))
    assert a == b


def test_summary_row_carries_the_counts():
    report = audit.report_table([audit_it(build_table(times(0, 1, 1, 5)))])
    summary = report.slice(0, 1).to_pylist()[0]
    assert summary["kind"] == "summary"
    assert summary["missing_steps"] == 1, "缺口条数"
    assert summary["occurrences"] == 1, "重复条数"
    assert summary["rows_audited"] == 4
