"""摄取链路集成测试（QNT-28 关键路径）——**离线**，fetch 由 fixture 提供。

覆盖卡验收：唯一性登记 → `_staging` → sha → 原子发布 → insert `ingestion_batch` 行；
同参数重跑写 `kind='rerun'` 新 batch 且历史字节不变；核查报告只 insert 不改数据。
"""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import pyarrow as pa
import pytest
from quantime_core import parquet_io
from quantime_core.ids import new_batch_id, new_run_id
from quantime_core.paths import PROVENANCE_COLUMNS, AssetClass, DataType, Freq
from quantime_data import audit, batches, ingest
from quantime_data.sources import binance_public as bp

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "binance_public"

#: 上游 URL → 录制文件名。摄取时 `fetch` 按这张表回放，永不出网。
RECORDED: dict[str, str] = {
    bp.kline_url("spot", "BTCUSDT", "1d", "2026-08"): "spot-BTCUSDT-1d-2026-08.zip",
    bp.kline_url("perp", "BTCUSDT", "4h", "2026-08"): "um-BTCUSDT-4h-2026-08.zip",
    bp.funding_url("BTCUSDT", "2026-08"): "um-BTCUSDT-fundingRate-2026-08.zip",
    bp.metrics_url("BTCUSDT", dt.date(2026, 9, 15)): "um-BTCUSDT-metrics-2026-09-15.zip",
}

NOW = dt.datetime(2026, 9, 21, 12, 0, tzinfo=dt.UTC)


def _snapshot(root: Path) -> dict[str, str]:
    """湖里每个文件的相对路径 → sha256，用于断言「一个字节都没动」。"""
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((root / "data").rglob("*"))
        if p.is_file()
    }


class FixtureFetcher:
    """离线 fetch：录制里有就回放，没有就当上游 404（缺档）。"""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        if url.endswith(".CHECKSUM"):
            name = RECORDED.get(url.removesuffix(".CHECKSUM"))
            if name is None:
                raise FileNotFoundError(url)
            return (FIXTURES / (name + ".CHECKSUM")).read_bytes()
        name = RECORDED.get(url)
        if name is None:
            raise FileNotFoundError(url)
        return (FIXTURES / name).read_bytes()


@pytest.fixture
def fetch() -> FixtureFetcher:
    return FixtureFetcher()


@pytest.fixture
def root(tmp_path) -> Path:
    return tmp_path


SPOT_KLINE_SPEC = ingest.IngestSpec(
    datatype=DataType.KLINE,
    asset_class=AssetClass.SPOT,
    symbol="BTCUSDT",
    freq=Freq.D1,
    start=dt.date(2026, 8, 1),
    end=dt.date(2026, 8, 31),
)
FUNDING_SPEC = ingest.IngestSpec(
    datatype=DataType.FUNDING,
    asset_class=AssetClass.PERP,
    symbol="BTCUSDT",
    freq=Freq.EVENT,
    start=dt.date(2026, 8, 1),
    end=dt.date(2026, 8, 31),
)
OI_SPEC = ingest.IngestSpec(
    datatype=DataType.OPEN_INTEREST,
    asset_class=AssetClass.PERP,
    symbol="BTCUSDT",
    freq=Freq.M5,
    start=dt.date(2026, 9, 15),
    end=dt.date(2026, 9, 15),
)


# ---- 计划 ----


def test_months_between_covers_the_whole_range():
    assert ingest.months_between(dt.date(2026, 11, 3), dt.date(2027, 2, 1)) == [
        "2026-11",
        "2026-12",
        "2027-01",
        "2027-02",
    ]


def test_plan_lists_one_url_per_month_for_klines():
    spec = ingest.IngestSpec(
        datatype=DataType.KLINE,
        asset_class=AssetClass.SPOT,
        symbol="BTCUSDT",
        freq=Freq.D1,
        start=dt.date(2026, 7, 1),
        end=dt.date(2026, 8, 31),
    )
    assert len(ingest.plan_urls(spec)) == 2


def test_plan_lists_one_url_per_day_for_open_interest():
    spec = ingest.IngestSpec(
        datatype=DataType.OPEN_INTEREST,
        asset_class=AssetClass.PERP,
        symbol="BTCUSDT",
        freq=Freq.M5,
        start=dt.date(2026, 9, 1),
        end=dt.date(2026, 9, 3),
    )
    assert len(ingest.plan_urls(spec)) == 3


def test_funding_on_a_spot_leg_is_rejected():
    spec = ingest.IngestSpec(
        datatype=DataType.FUNDING,
        asset_class=AssetClass.SPOT,
        symbol="BTCUSDT",
        freq=Freq.EVENT,
        start=dt.date(2026, 8, 1),
        end=dt.date(2026, 8, 31),
    )
    with pytest.raises(ingest.IngestError, match="永续"):
        ingest.plan_urls(spec)


def test_inverted_range_is_rejected():
    with pytest.raises(ingest.IngestError, match="区间非法"):
        ingest.IngestSpec(
            datatype=DataType.KLINE,
            asset_class=AssetClass.SPOT,
            symbol="BTCUSDT",
            freq=Freq.D1,
            start=dt.date(2026, 8, 31),
            end=dt.date(2026, 8, 1),
        )


# ---- 完整摄取 ----


def test_ingest_writes_lake_raw_manifest_and_ingestion_batch_row(root, fetch):
    result = ingest.ingest_one(root, SPOT_KLINE_SPEC, fetch, run_id=new_run_id(), now=NOW)
    b = result.committed

    assert (root / b.parts[0].path).is_file()
    assert (root / b.manifest_path).is_file()
    assert b.raw_files, "raw 副本必须落盘（重放只依赖本地副本，ADR-0003 §4.6）"
    assert (root / b.raw_files[0].path).is_file()

    rows = batches.read_ingestion_batch(root).to_pylist()
    assert len(rows) == 1
    assert rows[0]["batch_id"] == b.batch_id
    assert rows[0]["kind"] == "ingest"
    assert rows[0]["source"] == bp.SOURCE
    assert rows[0]["row_count"] == b.row_count
    assert rows[0]["content_sha256"] == b.content_sha256


def test_every_row_carries_the_adr_0002_provenance_columns(root, fetch):
    result = ingest.ingest_one(root, SPOT_KLINE_SPEC, fetch, run_id=new_run_id(), now=NOW)
    table = parquet_io.read_table(root / result.committed.parts[0].path)
    for column in PROVENANCE_COLUMNS:
        assert column in table.column_names
    assert set(table.column("source").to_pylist()) == {bp.SOURCE}
    assert set(table.column("batch_id").to_pylist()) == {result.committed.batch_id}
    assert set(table.column("ingested_at").to_pylist()) == {NOW}


def test_raw_copy_is_byte_identical_to_the_upstream_payload(root, fetch):
    result = ingest.ingest_one(root, SPOT_KLINE_SPEC, fetch, run_id=new_run_id(), now=NOW)
    upstream = (FIXTURES / "spot-BTCUSDT-1d-2026-08.zip").read_bytes()
    saved = (root / result.committed.raw_files[0].path).read_bytes()
    assert saved == upstream


def test_funding_and_open_interest_ingest_too(root, fetch):
    run_id = new_run_id()
    funding = ingest.ingest_one(root, FUNDING_SPEC, fetch, run_id=run_id, now=NOW)
    oi = ingest.ingest_one(root, OI_SPEC, fetch, run_id=run_id, now=NOW)
    assert funding.committed.row_count == 93
    assert oi.committed.row_count == 288
    assert {r["datatype"] for r in batches.read_ingestion_batch(root).to_pylist()} == {
        "funding",
        "open_interest",
    }


def test_checksum_mismatch_refuses_to_write_anything(root):
    """上游字节与 `.CHECKSUM` 不符 → 摄取失败，湖里不留任何东西。"""

    def tampering_fetch(url: str) -> bytes:
        payload = FixtureFetcher()(url)
        return payload if url.endswith(".CHECKSUM") else payload + b"tampered"

    with pytest.raises(ingest.IngestError, match="sha256 与上游 .CHECKSUM 不符"):
        ingest.ingest_one(root, SPOT_KLINE_SPEC, tampering_fetch, run_id=new_run_id(), now=NOW)
    assert batches.read_ingestion_batch(root).num_rows == 0
    assert not (root / "data" / "lake").exists()


def test_checksum_is_actually_verified_against_the_payload(root, fetch):
    """反证：录制的字节确实与录制的 `.CHECKSUM` 相符，核对不是空转。"""
    payload = (FIXTURES / "spot-BTCUSDT-1d-2026-08.zip").read_bytes()
    expected = bp.parse_checksum((FIXTURES / "spot-BTCUSDT-1d-2026-08.zip.CHECKSUM").read_bytes())
    assert hashlib.sha256(payload).hexdigest() == expected


def test_missing_upstream_month_is_recorded_not_fatal(root, fetch):
    """区间跨到没有归档的月份：缺档记账，已有的月份照常入湖。"""
    spec = ingest.IngestSpec(
        datatype=DataType.KLINE,
        asset_class=AssetClass.SPOT,
        symbol="BTCUSDT",
        freq=Freq.D1,
        start=dt.date(2026, 8, 1),
        end=dt.date(2026, 9, 30),
    )
    result = ingest.ingest_one(root, spec, fetch, run_id=new_run_id(), now=NOW)
    assert result.missing == ("BTCUSDT-1d-2026-09.zip",)
    assert result.committed.row_count > 0


# ---- R1 P2-3：请求区间必须真的裁剪落盘的行 ----


def _spot_1d(start: dt.date, end: dt.date) -> ingest.IngestSpec:
    return ingest.IngestSpec(
        datatype=DataType.KLINE,
        asset_class=AssetClass.SPOT,
        symbol="BTCUSDT",
        freq=Freq.D1,
        start=start,
        end=end,
    )


def _open_times(root: Path, committed) -> list[dt.datetime]:
    table = parquet_io.read_table(root / committed.parts[0].path)
    return sorted(table.column("open_time").to_pylist())


@pytest.mark.parametrize(
    ("start", "end", "expect_first", "expect_last", "expect_rows"),
    [
        # 单日：修复前提交整月 31 行（verify-a R1 P2-3 的原始反例）。
        (dt.date(2026, 8, 15), dt.date(2026, 8, 15), dt.date(2026, 8, 15), dt.date(2026, 8, 15), 1),
        # 月内首日 / 末日各一天。
        (dt.date(2026, 8, 1), dt.date(2026, 8, 1), dt.date(2026, 8, 1), dt.date(2026, 8, 1), 1),
        (dt.date(2026, 8, 31), dt.date(2026, 8, 31), dt.date(2026, 8, 31), dt.date(2026, 8, 31), 1),
        # 区间两端都在月内。
        (dt.date(2026, 8, 10), dt.date(2026, 8, 12), dt.date(2026, 8, 10), dt.date(2026, 8, 12), 3),
        # 整月：一行不裁。
        (dt.date(2026, 8, 1), dt.date(2026, 8, 31), dt.date(2026, 8, 1), dt.date(2026, 8, 31), 31),
        # 跨月请求，上游只有八月：八月整月保留，九月缺档（另见覆盖判定测试）。
        (
            dt.date(2026, 8, 20),
            dt.date(2026, 9, 10),
            dt.date(2026, 8, 20),
            dt.date(2026, 8, 31),
            12,
        ),
    ],
)
def test_only_rows_inside_the_requested_window_are_committed(
    root, fetch, start, end, expect_first, expect_last, expect_rows
):
    """落盘的行必须正好是请求区间内的那些——上游按整月给，我们按请求裁。"""
    result = ingest.ingest_one(root, _spot_1d(start, end), fetch, run_id=new_run_id(), now=NOW)
    times = _open_times(root, result.committed)
    assert len(times) == expect_rows
    assert times[0].date() == expect_first
    assert times[-1].date() == expect_last
    assert result.committed.row_count == expect_rows


def test_the_committed_range_matches_what_was_actually_written(root, fetch):
    """`ingestion_batch.range_start/range_end` 必须与落盘的行一致，不是请求的整月。

    这两者若不一致，重放时按 range 去取的段和实际存的段就对不上。
    """
    result = ingest.ingest_one(
        root,
        _spot_1d(dt.date(2026, 8, 10), dt.date(2026, 8, 12)),
        fetch,
        run_id=new_run_id(),
        now=NOW,
    )
    row = batches.read_ingestion_batch(root).to_pylist()[0]
    times = _open_times(root, result.committed)
    assert row["range_start"] == times[0]
    assert row["range_end"] == times[-1]
    assert row["range_start"].date() == dt.date(2026, 8, 10)


def test_a_fetch_whose_rows_all_fall_outside_the_window_commits_nothing(root, fetch):
    """裁完 0 行 → 不写空 batch，湖里一个字节都没有。

    正常上游不会出现这种情况（月档的行都落在它自己那个月），所以这里让 fetch 对九月的
    URL 回放**八月**的字节来构造它。钉的是裁剪之后那道「0 行不写」的闸——它在裁剪引入后
    才可能被触发，不能只靠「区间内无任何归档文件」那条早退路径兜着。
    """
    sept_url = bp.kline_url("spot", "BTCUSDT", "1d", "2026-09")
    aug = FIXTURES / RECORDED[bp.kline_url("spot", "BTCUSDT", "1d", "2026-08")]

    def misdated_fetch(url: str) -> bytes:
        if url == sept_url:
            return aug.read_bytes()
        if url == sept_url + ".CHECKSUM":
            raise FileNotFoundError(url)  # 旁路文件缺失只记为不可核对
        return fetch(url)

    spec = _spot_1d(dt.date(2026, 9, 1), dt.date(2026, 9, 30))
    with pytest.raises(ingest.IngestError, match="0 行"):
        ingest.ingest_one(root, spec, misdated_fetch, run_id=new_run_id(), now=NOW)
    assert batches.read_ingestion_batch(root).num_rows == 0
    assert not (root / "data" / "lake").exists()


def test_clip_to_window_is_a_pure_half_open_utc_window():
    """窗口语义单测：`[start 00:00, end+1d 00:00)`，两端各钉一个毫秒级邻居。

    端点上差一天就是一整根日线的进出，所以这里不依赖 fixture，直接构造边界行。
    """
    spec = _spot_1d(dt.date(2026, 8, 10), dt.date(2026, 8, 12))
    start, end = ingest.requested_window(spec)
    assert start == dt.datetime(2026, 8, 10, tzinfo=dt.UTC)
    assert end == dt.datetime(2026, 8, 13, tzinfo=dt.UTC)

    times = [
        start - dt.timedelta(microseconds=1),  # 窗口前一瞬 → 丢
        start,  # 左端点闭 → 留
        end - dt.timedelta(microseconds=1),  # 右端点前一瞬 → 留
        end,  # 右端点开 → 丢
    ]
    table = pa.table({"open_time": pa.array(times, pa.timestamp("us", tz="UTC"))})
    kept = ingest.clip_to_window(table, "open_time", spec).column("open_time").to_pylist()
    assert kept == [times[1], times[2]]


def test_clipping_happens_before_provenance_so_dropped_rows_never_enter_a_batch(root, fetch):
    """被裁掉的行从未盖过 batch_id——裁剪在盖 provenance 之前，不是落盘后再删。

    顺序反过来的话，「只 insert 不 update」就得靠删行来实现，那正是 ADR-0002 禁止的。
    """
    spec = _spot_1d(dt.date(2026, 8, 15), dt.date(2026, 8, 15))
    fetched, _ = ingest.fetch_files(spec, fetch)
    assert ingest.normalize(spec, fetched).num_rows == 1, "normalize 出来就该是裁过的"
    unclipped = pa.concat_tables(
        [bp.normalize_klines(f.payload, symbol="BTCUSDT") for f in fetched]
    )
    assert unclipped.num_rows == 31, "前提：上游那一个月确实是 31 行"


# ---- R1 P2-4：整档缺失不得判 clean ----


def test_a_partially_covered_range_is_not_clean(root, fetch):
    """请求两个月、fixture 只有八月 → `coverage='partial'`、`clean=False`。

    修复前这里是 `clean=True, gaps=0`：八月的数据内部严丝合缝，而「九月整个月没取到」
    只写进了 note 字符串，没人读（verify-a R1 P2-4）。
    """
    result = ingest.ingest_one(
        root,
        _spot_1d(dt.date(2026, 8, 1), dt.date(2026, 9, 30)),
        fetch,
        run_id=new_run_id(),
        now=NOW,
    )
    assert result.missing == ("BTCUSDT-1d-2026-09.zip",)

    audited = ingest.audit_result(root, result)
    assert audited.coverage == audit.COVERAGE_PARTIAL
    assert audited.missing_upstream == ("BTCUSDT-1d-2026-09.zip",)
    assert audited.clean is False, "少了整整一个月却判 clean"
    assert audited.gaps == (), "整档缺失不该伪装成缺口——它是覆盖问题，两者分开记"


def test_a_fully_covered_range_is_clean(root, fetch):
    """反证：区间内一个档不缺时仍然 `complete` + `clean`（否则上一条恒真）。"""
    result = ingest.ingest_one(
        root,
        _spot_1d(dt.date(2026, 8, 1), dt.date(2026, 8, 31)),
        fetch,
        run_id=new_run_id(),
        now=NOW,
    )
    audited = ingest.audit_result(root, result)
    assert result.missing == ()
    assert audited.coverage == audit.COVERAGE_COMPLETE
    assert audited.clean is True


def test_the_report_carries_coverage_and_the_missing_file_names(root, fetch):
    """报告表本身要能答「覆盖全不全、缺了哪些档」，不是只把数量塞进 note 文本。"""
    result = ingest.ingest_one(
        root,
        _spot_1d(dt.date(2026, 8, 1), dt.date(2026, 9, 30)),
        fetch,
        run_id=new_run_id(),
        now=NOW,
    )
    report = audit.report_table([ingest.audit_result(root, result)]).to_pylist()
    summary = [r for r in report if r["kind"] == "summary"]
    assert len(summary) == 1
    assert summary[0]["coverage"] == audit.COVERAGE_PARTIAL
    assert summary[0]["missing_files"] == 1
    missing_rows = [r for r in report if r["kind"] == "missing_upstream"]
    assert [r["duplicate_key"] for r in missing_rows] == ["BTCUSDT-1d-2026-09.zip"]


def test_a_range_with_no_upstream_files_writes_no_batch(root, fetch):
    spec = ingest.IngestSpec(
        datatype=DataType.KLINE,
        asset_class=AssetClass.SPOT,
        symbol="NOSUCHUSDT",
        freq=Freq.D1,
        start=dt.date(2026, 8, 1),
        end=dt.date(2026, 8, 31),
    )
    with pytest.raises(ingest.IngestError, match="无任何归档文件"):
        ingest.ingest_one(root, spec, fetch, run_id=new_run_id(), now=NOW)
    assert batches.read_ingestion_batch(root).num_rows == 0


# ---- 重跑（ADR-0002 只 insert）----


def test_rerun_writes_a_new_batch_and_leaves_history_byte_identical(root, fetch):
    """同参数重跑 → `kind='rerun'` 的新 batch；原 batch 每个字节不动。"""
    run_id = new_run_id()
    first = ingest.ingest_one(root, SPOT_KLINE_SPEC, fetch, run_id=run_id, now=NOW)
    before = (root / first.committed.parts[0].path).read_bytes()

    second = ingest.ingest_one(
        root,
        SPOT_KLINE_SPEC,
        fetch,
        run_id=run_id,
        now=NOW,
        kind="rerun",
        rerun_of=first.committed.batch_id,
    )

    assert second.committed.batch_id != first.committed.batch_id
    assert (root / first.committed.parts[0].path).read_bytes() == before
    rows = {r["batch_id"]: r for r in batches.read_ingestion_batch(root).to_pylist()}
    assert rows[first.committed.batch_id]["kind"] == "ingest"
    assert rows[second.committed.batch_id]["kind"] == "rerun"
    assert rows[second.committed.batch_id]["rerun_of"] == first.committed.batch_id


def test_rerun_of_the_same_bytes_produces_the_same_content_sha(root, fetch):
    """确定性 writer：同输入 → 同 `content_sha256`，只是 batch_id 不同。

    provenance 里的 `batch_id` 列会进 payload，所以这里比的是**归一化表**的 sha，
    而不是最终文件的 sha。
    """
    run_id = new_run_id()
    first = ingest.ingest_one(root, SPOT_KLINE_SPEC, fetch, run_id=run_id, now=NOW)
    second = ingest.ingest_one(
        root,
        SPOT_KLINE_SPEC,
        fetch,
        run_id=run_id,
        now=NOW,
        kind="rerun",
        rerun_of=first.committed.batch_id,
    )
    a = parquet_io.read_table(root / first.committed.parts[0].path).drop_columns(["batch_id"])
    b = parquet_io.read_table(root / second.committed.parts[0].path).drop_columns(["batch_id"])
    assert parquet_io.table_to_bytes(a) == parquet_io.table_to_bytes(b)


def test_rerun_without_rerun_of_is_rejected(root, fetch):
    with pytest.raises(batches.BatchWriteError, match="rerun_of"):
        ingest.ingest_one(root, SPOT_KLINE_SPEC, fetch, run_id=new_run_id(), now=NOW, kind="rerun")


def test_two_ingests_colliding_on_one_batch_id_are_stopped_by_the_lock(root, fetch, monkeypatch):
    """两次摄取撞上同一个 batch_id → 第二次在任何字节落盘之前失败。

    现实里 ULID 不会撞；这里把生成器钉死来逼出那条路径。两个 spec 的 lake 目录与 raw
    文件名都不冲突（不同 symbol、不同周期），所以「目录非空」早退检查够不着——
    能拦下它的只有 `batch_manifest` 的独占登记。
    """
    fixed = new_batch_id()
    monkeypatch.setattr(ingest, "new_batch_id", lambda: fixed)

    first = ingest.ingest_one(root, SPOT_KLINE_SPEC, fetch, run_id=new_run_id(), now=NOW)
    assert first.committed.batch_id == fixed
    before = _snapshot(root)

    other = ingest.IngestSpec(
        datatype=DataType.KLINE,
        asset_class=AssetClass.PERP,
        symbol="BTCUSDT",
        freq=Freq.H4,
        start=dt.date(2026, 8, 1),
        end=dt.date(2026, 8, 31),
    )
    with pytest.raises(batches.BatchWriteError, match="已被登记"):
        ingest.ingest_one(root, other, fetch, run_id=new_run_id(), now=NOW)

    assert _snapshot(root) == before, "第二次摄取必须不留下任何字节"


def test_staging_is_left_empty_after_ingest(root, fetch):
    ingest.ingest_one(root, SPOT_KLINE_SPEC, fetch, run_id=new_run_id(), now=NOW)
    staging = root / "data" / "_staging"
    assert not staging.exists() or not any(staging.iterdir())


# ---- 核查报告 ----


def test_audit_of_a_fresh_batch_is_clean_for_daily_klines(root, fetch):
    result = ingest.ingest_one(root, SPOT_KLINE_SPEC, fetch, run_id=new_run_id(), now=NOW)
    report = ingest.audit_result(root, result)
    assert report.duplicates == ()
    assert report.gaps == (), "完整的一个月日线不该有缺口"
    assert report.rows_audited == result.committed.row_count


def test_audit_detects_the_gap_left_by_a_missing_upstream_month(root, fetch):
    """8 月 + 9 月的区间里 9 月缺档 → 报告如实记一条缺口，数据不动。"""
    spec = ingest.IngestSpec(
        datatype=DataType.KLINE,
        asset_class=AssetClass.SPOT,
        symbol="BTCUSDT",
        freq=Freq.D1,
        start=dt.date(2026, 8, 1),
        end=dt.date(2026, 9, 30),
    )
    result = ingest.ingest_one(root, spec, fetch, run_id=new_run_id(), now=NOW)
    report = ingest.audit_result(root, result)
    assert "missing_upstream_files=1" in report.note


def test_audit_report_is_committed_through_the_same_publish_path(root, fetch):
    run_id = new_run_id()
    result = ingest.ingest_one(root, SPOT_KLINE_SPEC, fetch, run_id=run_id, now=NOW)
    report = ingest.audit_result(root, result)

    committed = ingest.commit_audit_report(
        root,
        [report],
        run_id=run_id,
        scope="BTCUSDT",
        datatype=DataType.KLINE,
        freq=Freq.D1,
        asset_class=AssetClass.SPOT,
        now=NOW,
    )
    assert audit.AUDIT_SCOPE_PREFIX in committed.batch_dir
    rows = {r["batch_id"]: r for r in batches.read_ingestion_batch(root).to_pylist()}
    assert committed.batch_id in rows, "报告也必须有 ingestion_batch 行"
    assert (root / committed.parts[0].path).is_file()


def test_audit_does_not_touch_the_audited_data(root, fetch):
    """核查只读：被核查 batch 的每个字节、以及它的 ingestion_batch 行都不变。"""
    run_id = new_run_id()
    result = ingest.ingest_one(root, SPOT_KLINE_SPEC, fetch, run_id=run_id, now=NOW)
    audited_part = root / result.committed.parts[0].path
    before = audited_part.read_bytes()
    before_row = [
        r
        for r in batches.read_ingestion_batch(root).to_pylist()
        if r["batch_id"] == result.committed.batch_id
    ]

    ingest.commit_audit_report(
        root,
        [ingest.audit_result(root, result)],
        run_id=run_id,
        scope="BTCUSDT",
        datatype=DataType.KLINE,
        freq=Freq.D1,
        asset_class=AssetClass.SPOT,
        now=NOW,
    )

    assert audited_part.read_bytes() == before
    after_row = [
        r
        for r in batches.read_ingestion_batch(root).to_pylist()
        if r["batch_id"] == result.committed.batch_id
    ]
    assert after_row == before_row


def test_audit_report_lands_in_a_separate_scope_from_the_data(root, fetch):
    """报告不得写进被核查数据的目录，否则读侧会把报告当行情读。"""
    run_id = new_run_id()
    result = ingest.ingest_one(root, SPOT_KLINE_SPEC, fetch, run_id=run_id, now=NOW)
    committed = ingest.commit_audit_report(
        root,
        [ingest.audit_result(root, result)],
        run_id=run_id,
        scope="BTCUSDT",
        datatype=DataType.KLINE,
        freq=Freq.D1,
        asset_class=AssetClass.SPOT,
        now=NOW,
    )
    assert committed.batch_dir != result.committed.batch_dir
    assert "/BTCUSDT/" not in committed.batch_dir
