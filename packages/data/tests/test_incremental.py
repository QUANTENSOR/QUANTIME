"""增量摄取的区间推算（QNT-45 第 1 项）——水位线只来自已提交的 `ingestion_batch`。

变异点 (b)「把推算改成从头再取一遍」必须在这里变红。
"""

from __future__ import annotations

import datetime as dt

import fixture_source
import pytest
from fixture_source import NOW, FixtureFetcher, spot_1d
from quantime_core.ids import new_batch_id, new_run_id
from quantime_core.paths import AssetClass, DataType, Freq
from quantime_data import batches, incremental, ingest
from quantime_data.sources.binance_public import SOURCE
from quantime_data.spec import IngestSpec


@pytest.fixture
def fetch() -> FixtureFetcher:
    return FixtureFetcher()


def _ingest(root, fetch, start: dt.date, end: dt.date):
    return ingest.ingest_one(root, spot_1d(start, end), fetch, run_id=new_run_id(), now=NOW)


# ---- 纯函数：水位线 → 下一段区间 ----


def test_no_watermark_means_the_full_requested_range():
    spec = spot_1d(dt.date(2026, 8, 1), dt.date(2026, 8, 31))
    assert incremental.next_window(spec, None) == spec


def test_the_next_window_starts_the_day_after_the_watermark():
    """变异点 (b)：把起点改回 `spec.start`（从头再取），本用例立刻变红。

    日线摄取只跑已收盘的完整日，所以水位线当天一定取全了，**次日**起才是新的。
    """
    spec = spot_1d(dt.date(2026, 8, 1), dt.date(2026, 8, 31))
    mark = dt.datetime(2026, 8, 10, tzinfo=dt.UTC)
    narrowed = incremental.next_window(spec, mark)
    assert narrowed is not None
    assert (narrowed.start, narrowed.end) == (dt.date(2026, 8, 11), dt.date(2026, 8, 31))


def test_a_watermark_past_the_requested_end_is_an_empty_increment():
    spec = spot_1d(dt.date(2026, 8, 1), dt.date(2026, 8, 10))
    assert incremental.next_window(spec, dt.datetime(2026, 8, 10, tzinfo=dt.UTC)) is None
    assert incremental.next_window(spec, dt.datetime(2026, 9, 1, tzinfo=dt.UTC)) is None


def test_a_watermark_before_the_requested_start_does_not_widen_the_window():
    """请求 8 月、水位线停在 7 月：起点仍是 8-01，不会把 7 月补进来。

    补历史是 `backfill` 的事，日常增量不该因为水位线落后就悄悄扩大当天的取数量。
    """
    spec = spot_1d(dt.date(2026, 8, 1), dt.date(2026, 8, 31))
    narrowed = incremental.next_window(spec, dt.datetime(2026, 7, 3, tzinfo=dt.UTC))
    assert narrowed is not None
    assert (narrowed.start, narrowed.end) == (dt.date(2026, 8, 1), dt.date(2026, 8, 31))


def test_a_non_utc_watermark_is_converted_before_taking_the_date():
    """水位线带别的时区时按 UTC 取日期——否则跨时区会差出一天。"""
    spec = spot_1d(dt.date(2026, 8, 1), dt.date(2026, 8, 31))
    tz = dt.timezone(dt.timedelta(hours=9))
    mark = dt.datetime(2026, 8, 11, 6, 0, tzinfo=tz)  # = 2026-08-10 21:00 UTC
    narrowed = incremental.next_window(spec, mark)
    assert narrowed is not None
    assert narrowed.start == dt.date(2026, 8, 11)


# ---- 水位线来自湖 ----


def test_committed_coverage_is_empty_on_a_fresh_lake(root):
    assert incremental.committed_coverage(root) == {}
    assert incremental.watermark(root, fixture_source.SPOT_KLINE_SPEC, SOURCE) is None


def test_the_watermark_is_the_last_committed_timestamp(root, fetch):
    _ingest(root, fetch, dt.date(2026, 8, 1), dt.date(2026, 8, 10))
    mark = incremental.watermark(root, fixture_source.SPOT_KLINE_SPEC, SOURCE)
    assert mark == dt.datetime(2026, 8, 10, tzinfo=dt.UTC)


def test_two_batches_merge_into_one_coverage_span(root, fetch):
    _ingest(root, fetch, dt.date(2026, 8, 1), dt.date(2026, 8, 10))
    _ingest(root, fetch, dt.date(2026, 8, 11), dt.date(2026, 8, 20))
    (cov,) = incremental.committed_coverage(root).values()
    assert cov.batches == 2
    assert cov.start == dt.datetime(2026, 8, 1, tzinfo=dt.UTC)
    assert cov.end == dt.datetime(2026, 8, 20, tzinfo=dt.UTC)


def test_plan_incremental_only_asks_for_what_is_missing(root, fetch):
    _ingest(root, fetch, dt.date(2026, 8, 1), dt.date(2026, 8, 10))
    spec = spot_1d(dt.date(2026, 8, 1), dt.date(2026, 8, 31))
    narrowed = incremental.plan_incremental(root, spec, SOURCE)
    assert narrowed is not None
    assert (narrowed.start, narrowed.end) == (dt.date(2026, 8, 11), dt.date(2026, 8, 31))


def test_re_running_the_same_day_yields_an_empty_increment(root, fetch):
    """昨天已经取过 → 今天同参数再跑推不出任何新区间（因而不写第二个 batch）。"""
    _ingest(root, fetch, dt.date(2026, 8, 1), dt.date(2026, 8, 31))
    spec = spot_1d(dt.date(2026, 8, 1), dt.date(2026, 8, 31))
    assert incremental.plan_incremental(root, spec, SOURCE) is None


# ---- 键的分辨率 ----


def test_spot_and_perp_of_the_same_symbol_have_separate_watermarks(root, fetch):
    """同 symbol 的现货与永续是两条序列；共用水位线会让其中一条永远取不到数据。"""
    _ingest(root, fetch, dt.date(2026, 8, 1), dt.date(2026, 8, 31))
    perp = IngestSpec(
        datatype=DataType.KLINE,
        asset_class=AssetClass.PERP,
        symbol="BTCUSDT",
        freq=Freq.H4,
        start=dt.date(2026, 8, 1),
        end=dt.date(2026, 8, 31),
    )
    assert incremental.watermark(root, perp, SOURCE) is None


def test_another_source_name_does_not_see_this_sources_watermark(root, fetch):
    _ingest(root, fetch, dt.date(2026, 8, 1), dt.date(2026, 8, 31))
    assert incremental.watermark(root, fixture_source.SPOT_KLINE_SPEC, "massive") is None


# ---- 哪些 batch 行不算数 ----


def test_audit_report_batches_do_not_advance_the_watermark(root, fetch):
    """核查报告也是一个 batch，但它不是行情。算进水位线，行情序列就永远"已取到今天"。"""
    result = _ingest(root, fetch, dt.date(2026, 8, 1), dt.date(2026, 8, 10))
    audited = ingest.audit_result(root, result)
    ingest.commit_audit_report(
        root,
        [audited],
        run_id=new_run_id(),
        scope=result.spec.scope,
        datatype=result.spec.datatype,
        freq=result.spec.freq,
        asset_class=result.spec.asset_class,
        now=NOW,
    )
    assert incremental.watermark(root, fixture_source.SPOT_KLINE_SPEC, SOURCE) == dt.datetime(
        2026, 8, 10, tzinfo=dt.UTC
    )


def test_a_license_drop_tombstone_does_not_count_as_coverage(root, fetch, lake_kw, make_table):
    """`license_drop` 记的是「数据被删掉了」，把它当覆盖会让增量跳过真正的缺口。"""
    run_id = new_run_id()
    batch_id = new_batch_id()
    batches.commit_batch(
        root,
        make_table(source=SOURCE, batch_id=batch_id, run_id=run_id),
        source=SOURCE,
        source_version="vision-archive-v1",
        run_id=run_id,
        batch_id=batch_id,
        **lake_kw,
    )
    before = incremental.committed_coverage(root)
    batches.append_license_drop(
        root,
        source=SOURCE,
        source_version="vision-archive-v1",
        run_id=new_run_id(),
        **lake_kw,
    )
    assert incremental.committed_coverage(root) == before


# ---- 人类可读说明 ----


def test_describe_increment_tells_apart_first_run_empty_and_narrowed():
    spec = spot_1d(dt.date(2026, 8, 1), dt.date(2026, 8, 31))
    assert "首次全量" in incremental.describe_increment(spec, spec)
    assert "空增量" in incremental.describe_increment(spec, None)
    narrowed = spec.with_window(dt.date(2026, 8, 11), dt.date(2026, 8, 31))
    line = incremental.describe_increment(spec, narrowed)
    assert "2026-08-11..2026-08-31" in line
