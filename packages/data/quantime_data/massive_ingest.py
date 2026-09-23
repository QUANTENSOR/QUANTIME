"""QNT-47 阶段 2 摄取编排：Massive Flat Files 日线 + REST 参考数据 + 缺口报告。

两条链路都复用 QNT-27 的提交流程（唯一性登记 → raw 副本 → provenance 五列 →
`commit_batch` / `commit_meta_batch`），**没有任何 update / 覆盖路径**：

- **Flat Files**（`source='massive_flatfiles'`）：一个交易日文件 = 一个 batch，互相独立、
  各自可重放。raw 副本 = 上游 `.csv.gz` 原字节 + `object.json`（key / ETag / size / sha256 /
  LastModified）。幂等键是 **key + ETag**：已提交过的同 key 同 ETag 直接跳过；同 key 但
  ETag 变了（上游替换了文件）写 `kind='rerun'` + `rerun_of=<旧 batch>` 的**新** batch，
  旧 batch 字节不动（ADR-0002）。
- **REST 参考**（`source='massive_rest'`）：ticker 全表（active true/false）→
  `meta/instrument_meta`；拆股 + 分红 → `meta/adjust_factor`（只存因子）；ticker 变更 →
  `meta/ticker_events`。每类一个 batch，raw 副本是每一页响应的原字节。

取字节全部经注入的对象（`DayAggsBucket` / `fetch`），本模块不 import 任何网络库；
真实出口只在 `cli.py` 组装。重试：Flat Files 走 `flatfiles.retry_call`（QNT-45 退避语义的
本地实现，待并入 QNT-45 通用层）；REST 走 `KeyedTransport` 既有的 `Throttled` 退避。

缺口核查**以 Flat Files 列举出的日期集为基线**——仓库没有美股交易日历（无 calendar 模块、
未装 `exchange_calendars`），所以「应有哪些交易日」由上游文件本身回答；报告里写明这一点。
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa
from quantime_core import parquet_io
from quantime_core.ids import new_batch_id
from quantime_core.paths import (
    AssetClass,
    DataType,
    Freq,
    Market,
    MetaTable,
    meta_batch_dir,
    raw_batch_dir,
)

from . import batches
from . import flatfiles as ff
from .sources import massive

#: 取字节：`url -> bytes`（真实实现是 `KeyedTransport.get`，404 抛 `FileNotFoundError`）。
Fetcher = Callable[[str], bytes]

#: Flat Files 日线的湖 scope：整个 SIP 全市场一日一个 batch。
FLATFILES_SCOPE = "us_stocks_sip"

#: REST 参考 meta 表的 scope。
REFERENCE_SCOPE = "us_all"

#: 报告目录：`data/reports/<date>/massive/`（QNT-45 报告格式 schema v2 + `massive` 扩展段）。
REPORT_SUBDIR = "massive"
REPORT_SCHEMA_VERSION = 2

#: raw 副本里记录对象元数据的文件名。
OBJECT_META_NAME = "object.json"


class MassiveIngestError(RuntimeError):
    """摄取失败（空结果、上游与列举不符等）。"""


def stamp(
    table: pa.Table,
    *,
    source: str,
    source_version: str,
    run_id: str,
    batch_id: str,
    ingested_at: dt.datetime,
) -> pa.Table:
    """盖 ADR-0002 五列。与 `ingest.stamp_provenance` 同形，只是 source 由调用方给。"""
    n = table.num_rows
    for name, array in (
        ("source", pa.array([source] * n, pa.string())),
        ("source_version", pa.array([source_version] * n, pa.string())),
        ("ingested_at", pa.array([ingested_at] * n, pa.timestamp("us", tz="UTC"))),
        ("run_id", pa.array([run_id] * n, pa.string())),
        ("batch_id", pa.array([batch_id] * n, pa.string())),
    ):
        table = table.append_column(pa.field(name, array.type, nullable=False), array)
    return table


def _write_raw(
    root: Path, source: str, batch_id: str, files: Sequence[tuple[str, bytes]]
) -> tuple[Path, ...]:
    out_dir = root / raw_batch_dir(source, batch_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, payload in files:
        target = out_dir / name
        try:
            parquet_io.publish_bytes(target, payload, staging=batches.publish_staging(root))
        except parquet_io.AlreadyPublishedError as exc:
            raise MassiveIngestError(f"raw 副本已存在，拒绝二次写入: {target}") from exc
        written.append(target)
    return tuple(written)


def _now(now: dt.datetime | None) -> dt.datetime:
    return (now or dt.datetime.now(dt.UTC)).replace(microsecond=0)


# =========================================================================== Flat Files


@dataclass(frozen=True, slots=True)
class CommittedObject:
    """已提交的一个 Flat Files 对象（幂等索引的一项）。"""

    key: str
    etag: str
    batch_id: str


def committed_objects(root: str | os.PathLike[str]) -> dict[str, CommittedObject]:
    """扫已提交 batch 的清单，建 `key -> 最新 CommittedObject` 索引。

    「已提交」= batch 清单存在 **且** `ingestion_batch` 行存在（后者是提交的最后一步）。
    只写了 raw 或清单、没走到 insert 行的中断批次不算——它会被重新摄取为新 batch。
    同一 key 多个 batch（上游换过文件）取 batch_id 最大者（ULID 按时间单调）。
    """
    root = Path(root)
    manifest_dir = root / "data" / "meta" / "batch_manifest"
    out: dict[str, CommittedObject] = {}
    if not manifest_dir.is_dir():
        return out
    for path in sorted(manifest_dir.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("source") != ff.SOURCE:
            continue
        batch_id = str(doc["batch_id"])
        row_dir = root / meta_batch_dir(MetaTable.INGESTION_BATCH, batch_id)
        if not (row_dir / "part-0000.parquet").is_file():
            continue
        for raw in doc.get("raw", []):
            if not str(raw["path"]).endswith("/" + OBJECT_META_NAME):
                continue
            meta = json.loads((root / raw["path"]).read_text(encoding="utf-8"))
            prev = out.get(meta["key"])
            if prev is None or prev.batch_id < batch_id:
                out[meta["key"]] = CommittedObject(meta["key"], meta["etag"], batch_id)
    return out


@dataclass(frozen=True, slots=True)
class DayResult:
    """一个交易日文件的处理结果。`status` ∈ ok / skipped / failed。"""

    date: dt.date
    key: str
    status: str
    batch_id: str | None = None
    rows: int = 0
    content_sha256: str | None = None
    raw_bytes: int = 0
    raw_sha256: str | None = None
    etag: str | None = None
    kind: str | None = None
    rerun_of: str | None = None
    retries: int = 0
    elapsed_seconds: float = 0.0
    error_class: str | None = None
    error: str | None = None


def ingest_day(
    root: str | os.PathLike[str],
    bucket: ff.DayAggsBucket,
    info: ff.ObjectInfo,
    *,
    run_id: str,
    previous: CommittedObject | None = None,
    now: dt.datetime | None = None,
) -> DayResult:
    """取一个 day_aggs 对象并提交为一个新 batch。

    `previous` 是同 key 已提交的对象：ETag 相同 → 跳过（幂等）；不同 → `kind='rerun'`。
    """
    root = Path(root)
    if previous is not None and previous.etag == info.etag:
        return DayResult(
            date=info.date,
            key=info.key,
            status="skipped",
            batch_id=previous.batch_id,
            etag=info.etag,
        )
    fetched = bucket.get(info)
    table = ff.normalize_day_aggs(fetched.payload, session_date=info.date)
    if table.num_rows == 0:
        raise MassiveIngestError(f"{info.key}: 0 行，不写空 batch")

    import hashlib

    raw_sha = hashlib.sha256(fetched.payload).hexdigest()
    object_meta = {
        "bucket": ff.FLATFILES_BUCKET,
        "key": info.key,
        "etag": info.etag,
        "size": info.size,
        "last_modified": info.last_modified,
        "sha256": raw_sha,
    }
    batch_id = new_batch_id()
    claim = batches.claim_batch_id(root, batch_id)
    stamped = stamp(
        table,
        source=ff.SOURCE,
        source_version=ff.SOURCE_VERSION,
        run_id=run_id,
        batch_id=batch_id,
        ingested_at=_now(now),
    )
    raw_name = info.key.rsplit("/", 1)[-1]
    raw_paths = _write_raw(
        root,
        ff.SOURCE,
        batch_id,
        [
            (raw_name, fetched.payload),
            (OBJECT_META_NAME, (json.dumps(object_meta, sort_keys=True) + "\n").encode()),
        ],
    )
    times = table.column(ff.TIME_COLUMN).to_pylist()
    kind = "rerun" if previous is not None else "ingest"
    committed = batches.commit_batch(
        root,
        stamped,
        market=Market.US,
        asset_class=AssetClass.EQUITY,
        datatype=DataType.KLINE,
        freq=Freq.D1,
        scope=FLATFILES_SCOPE,
        source=ff.SOURCE,
        source_version=ff.SOURCE_VERSION,
        run_id=run_id,
        batch_id=batch_id,
        kind=kind,
        rerun_of=previous.batch_id if previous else None,
        raw_files=raw_paths,
        range_start=min(times),
        range_end=max(times),
        claim=claim,
    )
    return DayResult(
        date=info.date,
        key=info.key,
        status="ok",
        batch_id=committed.batch_id,
        rows=committed.row_count,
        content_sha256=committed.content_sha256,
        raw_bytes=len(fetched.payload),
        raw_sha256=raw_sha,
        etag=info.etag,
        kind=kind,
        rerun_of=committed.rerun_of,
    )


def month_prefixes(start: dt.date, end: dt.date) -> list[str]:
    """`[start, end]` 覆盖到的 `…/YYYY/MM/` 列举前缀（升序）。"""
    out: list[str] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{ff.DAY_AGGS_PREFIX}{y:04d}/{m:02d}/")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def list_range(bucket: ff.DayAggsBucket, start: dt.date, end: dt.date) -> list[ff.ObjectInfo]:
    """列出 `[start, end]` 内的全部 day_aggs 对象（按日期升序）——这也是缺口基线。"""
    out = [
        info
        for prefix in month_prefixes(start, end)
        for info in bucket.list_day_aggs(prefix)
        if start <= info.date <= end
    ]
    out.sort(key=lambda i: i.date)
    return out


@dataclass(slots=True)
class FlatFilesRun:
    start: dt.date
    end: dt.date
    listed: list[ff.ObjectInfo] = field(default_factory=list)
    days: list[DayResult] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    @property
    def gaps(self) -> list[dt.date]:
        """基线（列举到的日期）里没有已提交 batch 的日期——本次失败的那些。"""
        done = {d.date for d in self.days if d.status in ("ok", "skipped")}
        return sorted({i.date for i in self.listed} - done)

    def weekdays_absent_from_listing(self) -> list[dt.date]:
        """区间内**不在列举里**的工作日——多为美股假日，仅供人工核对（无日历，不判缺口）。"""
        listed = {i.date for i in self.listed}
        out = []
        day = self.start
        while day <= self.end:
            if day.weekday() < 5 and day not in listed:
                out.append(day)
            day += dt.timedelta(days=1)
        return out


def ingest_flatfiles(
    root: str | os.PathLike[str],
    bucket: ff.DayAggsBucket,
    *,
    start: dt.date,
    end: dt.date,
    run_id: str,
    now: dt.datetime | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    on_day: Callable[[DayResult], None] | None = None,
) -> FlatFilesRun:
    """摄取 `[start, end]`：先列举（基线），再逐日提交；单日失败不影响其余日期。"""
    if end < start:
        raise MassiveIngestError(f"区间非法: {start} > {end}")
    t0 = monotonic()
    run = FlatFilesRun(start=start, end=end)
    run.listed = list_range(bucket, start, end)
    index = committed_objects(root)
    for info in run.listed:
        d0 = monotonic()
        before = len(bucket.retries)
        try:
            result = ingest_day(
                root, bucket, info, run_id=run_id, previous=index.get(info.key), now=now
            )
        except Exception as exc:  # 单日失败记账，继续下一日
            result = DayResult(
                date=info.date,
                key=info.key,
                status="failed",
                etag=info.etag,
                error_class=type(exc).__name__,
                error=str(exc)[:300],
            )
        result = _with_timing(result, len(bucket.retries) - before, monotonic() - d0)
        run.days.append(result)
        if on_day is not None:
            on_day(result)
    run.elapsed_seconds = monotonic() - t0
    return run


def _with_timing(result: DayResult, retries: int, elapsed: float) -> DayResult:
    from dataclasses import replace

    return replace(result, retries=retries, elapsed_seconds=round(elapsed, 3))


# =========================================================================== REST 参考


@dataclass(frozen=True, slots=True)
class ReferenceBatch:
    """一个 REST 参考 batch 的结果。"""

    name: str
    meta_table: str
    batch_id: str
    rows: int
    content_sha256: str
    raw_files: int
    raw_bytes: int
    pages: int
    elapsed_seconds: float
    extra: dict[str, int] = field(default_factory=dict)


def fetch_pages(fetch: Fetcher, first_url: str, *, max_pages: int = 10_000) -> list[bytes]:
    """按 `next_url` 翻到底。`next_url` 由 `fetch`（`KeyedTransport.get`）**再过一遍闸**。"""
    pages: list[bytes] = []
    url: str | None = first_url
    while url is not None:
        if len(pages) >= max_pages:
            raise MassiveIngestError(f"翻页超过 {max_pages} 页仍未结束，疑似上游循环")
        body = fetch(url)
        pages.append(body)
        url = massive.next_page_url(body)
    return pages


def _commit_reference(
    root: Path,
    table: pa.Table,
    *,
    meta_table: MetaTable,
    raw: Sequence[tuple[str, bytes]],
    run_id: str,
    now: dt.datetime | None,
    range_start: dt.datetime | None = None,
    range_end: dt.datetime | None = None,
) -> batches.CommittedBatch:
    batch_id = new_batch_id()
    claim = batches.claim_batch_id(root, batch_id)
    stamped = stamp(
        table,
        source=massive.REST_SOURCE,
        source_version=massive.REST_SOURCE_VERSION,
        run_id=run_id,
        batch_id=batch_id,
        ingested_at=_now(now),
    )
    raw_paths = _write_raw(root, massive.REST_SOURCE, batch_id, raw)
    return batches.commit_meta_batch(
        root,
        stamped,
        meta_table=meta_table,
        market=Market.US,
        asset_class=AssetClass.EQUITY,
        scope=REFERENCE_SCOPE,
        source=massive.REST_SOURCE,
        source_version=massive.REST_SOURCE_VERSION,
        run_id=run_id,
        batch_id=batch_id,
        raw_files=raw_paths,
        range_start=range_start,
        range_end=range_end,
        claim=claim,
    )


def _day_bounds(dates: Iterable[dt.date | None]) -> tuple[dt.datetime | None, dt.datetime | None]:
    ds = [d for d in dates if d is not None]
    if not ds:
        return None, None
    return (
        dt.datetime.combine(min(ds), dt.time.min, tzinfo=dt.UTC),
        dt.datetime.combine(max(ds), dt.time.min, tzinfo=dt.UTC),
    )


def _result(
    name: str,
    meta_table: MetaTable,
    committed: batches.CommittedBatch,
    raw: Sequence[tuple[str, bytes]],
    pages: int,
    elapsed: float,
    extra: dict[str, int] | None = None,
) -> ReferenceBatch:
    return ReferenceBatch(
        name=name,
        meta_table=str(meta_table),
        batch_id=committed.batch_id,
        rows=committed.row_count,
        content_sha256=committed.content_sha256,
        raw_files=len(raw),
        raw_bytes=sum(len(b) for _, b in raw),
        pages=pages,
        elapsed_seconds=round(elapsed, 3),
        extra=extra or {},
    )


def ingest_tickers(
    root: str | os.PathLike[str],
    fetch: Fetcher,
    *,
    run_id: str,
    now: dt.datetime | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[ReferenceBatch, pa.Table]:
    """ticker 全表（active=true 与 active=false 各翻到底）→ 一个 `instrument_meta` batch。"""
    t0 = monotonic()
    raw: list[tuple[str, bytes]] = []
    parts: list[pa.Table] = []
    counts: dict[str, int] = {}
    for active in (True, False):
        label = "active" if active else "inactive"
        pages = fetch_pages(fetch, massive.tickers_url(active=active))
        for i, body in enumerate(pages, 1):
            raw.append((f"tickers-{label}-{i:04d}.json", body))
            parts.append(massive.normalize_tickers(body, active=active))
        counts[label] = sum(p.num_rows for p in parts[-len(pages) :]) if pages else 0
    table = pa.concat_tables(parts) if parts else massive.INSTRUMENT_META_SCHEMA.empty_table()
    if table.num_rows == 0:
        raise MassiveIngestError("ticker 全表 0 行，不写空 batch")
    table = table.sort_by([("symbol", "ascending"), ("instrument_id", "ascending")])
    committed = _commit_reference(
        Path(root), table, meta_table=MetaTable.INSTRUMENT_META, raw=raw, run_id=run_id, now=now
    )
    counts["with_figi"] = sum(
        1 for r in table.column("instrument_id_rule").to_pylist() if r == "figi"
    )
    return (
        _result(
            "tickers",
            MetaTable.INSTRUMENT_META,
            committed,
            raw,
            len(raw),
            monotonic() - t0,
            counts,
        ),
        table,
    )


def ingest_corporate_actions(
    root: str | os.PathLike[str],
    fetch: Fetcher,
    *,
    run_id: str,
    instrument_meta: pa.Table | None,
    start: dt.date | None = None,
    end: dt.date | None = None,
    now: dt.datetime | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> list[ReferenceBatch]:
    """全市场拆股、分红各一个 `adjust_factor` batch（只存因子与原始事件量）。"""
    resolve = massive.ticker_resolver(instrument_meta) if instrument_meta is not None else None
    out: list[ReferenceBatch] = []
    for name, url, normalize in (
        ("splits", massive.all_splits_url(start=start, end=end), massive.normalize_all_splits),
        (
            "dividends",
            massive.all_dividends_url(start=start, end=end),
            massive.normalize_all_dividends,
        ),
    ):
        t0 = monotonic()
        pages = fetch_pages(fetch, url)
        raw = [(f"{name}-{i:04d}.json", body) for i, body in enumerate(pages, 1)]
        parts = [normalize(body, resolve=resolve) for body in pages]
        table = pa.concat_tables(parts) if parts else massive.ADJUST_FACTOR_SCHEMA.empty_table()
        if table.num_rows == 0:
            continue  # 区间内无事件：不写空 batch，报告里记 0
        table = table.sort_by(
            [("ex_date", "ascending"), ("ticker", "ascending"), ("event_id", "ascending")]
        )
        lo, hi = _day_bounds(table.column("ex_date").to_pylist())
        committed = _commit_reference(
            Path(root),
            table,
            meta_table=MetaTable.ADJUST_FACTOR,
            raw=raw,
            run_id=run_id,
            now=now,
            range_start=lo,
            range_end=hi,
        )
        rules = table.column("instrument_id_rule").to_pylist()
        extra = {"unresolved_ticker": sum(1 for r in rules if r == "ticker_unresolved")}
        out.append(
            _result(
                name, MetaTable.ADJUST_FACTOR, committed, raw, len(pages), monotonic() - t0, extra
            )
        )
    return out


def figis_for_events(instrument_meta: pa.Table) -> list[str]:
    """ticker 事件要查的 composite FIGI（去重、升序）。"""
    rules = instrument_meta.column("instrument_id_rule").to_pylist()
    figis = instrument_meta.column("composite_figi").to_pylist()
    return sorted({f for f, r in zip(figis, rules, strict=True) if r == "figi" and f})


def ingest_ticker_events(
    root: str | os.PathLike[str],
    fetch: Fetcher,
    figis: Sequence[str],
    *,
    run_id: str,
    now: dt.datetime | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> ReferenceBatch | None:
    """逐 FIGI 取 ticker 变更 → 一个 `ticker_events` batch。404 = 该 FIGI 无事件（计数）。"""
    t0 = monotonic()
    raw: list[tuple[str, bytes]] = []
    parts: list[pa.Table] = []
    not_found: list[str] = []
    for figi in figis:
        try:
            body = fetch(massive.ticker_events_url(figi))
        except FileNotFoundError:
            not_found.append(figi)
            continue
        raw.append((f"events-{figi}.json", body))
        parts.append(massive.normalize_ticker_events(body, figi=figi))
    if not_found:
        raw.append(("events-not-found.json", (json.dumps(not_found) + "\n").encode()))
    table = pa.concat_tables(parts) if parts else massive.TICKER_EVENTS_SCHEMA.empty_table()
    if table.num_rows == 0:
        return None
    table = table.sort_by(
        [("composite_figi", "ascending"), ("event_date", "ascending"), ("ticker", "ascending")]
    )
    lo, hi = _day_bounds(table.column("event_date").to_pylist())
    committed = _commit_reference(
        Path(root),
        table,
        meta_table=MetaTable.TICKER_EVENTS,
        raw=raw,
        run_id=run_id,
        now=now,
        range_start=lo,
        range_end=hi,
    )
    extra = {"figis_queried": len(figis), "figis_not_found": len(not_found)}
    return _result(
        "ticker_events",
        MetaTable.TICKER_EVENTS,
        committed,
        raw,
        len(figis),
        monotonic() - t0,
        extra,
    )


# =========================================================================== 报告


def _series_for_day(d: DayResult) -> dict[str, Any]:
    """QNT-45 schema v2 的一条序列（字段名同 `report.SERIES_FIELDS`）。"""
    iso = d.date.isoformat()
    return {
        "spec": f"kline/equity/{FLATFILES_SCOPE}/1d/{iso}..{iso}",
        "source": ff.SOURCE,
        "asset_class": str(AssetClass.EQUITY),
        "datatype": str(DataType.KLINE),
        "freq": str(Freq.D1),
        "scope": FLATFILES_SCOPE,
        "range_start": iso,
        "range_end": iso,
        "batch_id": d.batch_id,
        "coverage": "failed" if d.status == "failed" else "complete",
        "rows": d.rows,
        "gaps": 0,
        "duplicates": 0,
        "missing_upstream": [],
        "retries": d.retries,
        "elapsed_seconds": d.elapsed_seconds,
        "status": "failed" if d.status == "failed" else "ok",
        "error_class": d.error_class,
        "error": d.error,
        "attempts": d.retries + 1,
        "as_of": iso,
        "missing_archives": [],
        "pending_upstream": [],
        # ---- massive 扩展 ----
        "action": d.status,
        "key": d.key,
        "etag": d.etag,
        "content_sha256": d.content_sha256,
        "raw_sha256": d.raw_sha256,
        "raw_bytes": d.raw_bytes,
        "kind": d.kind,
        "rerun_of": d.rerun_of,
    }


def build_report(
    *,
    run_id: str,
    report_date: dt.date,
    generated_at: dt.datetime,
    flatfiles: FlatFilesRun | None,
    reference: Sequence[ReferenceBatch] = (),
    failures: Sequence[str] = (),
    elapsed_seconds: float = 0.0,
) -> dict[str, Any]:
    """报告 dict：QNT-45 schema v2 的顶层字段 + `massive` 扩展段（基线说明、计数、缺口）。"""
    series = [_series_for_day(d) for d in flatfiles.days] if flatfiles else []
    failed = [s for s in series if s["status"] == "failed"]
    gaps = [d.isoformat() for d in flatfiles.gaps] if flatfiles else []
    # 分母为空（既没有日线序列也没有参考 batch）→ partial：什么都没做的运行不能显示绿。
    if failed or failures:
        coverage = "failed"
    elif series or reference:
        coverage = "complete"
    else:
        coverage = "partial"
    ref = {r.name: r for r in reference}
    tickers = ref.get("tickers")
    massive_section: dict[str, Any] = {
        "baseline": (
            "缺口基线 = Flat Files `us_stocks_sip/day_aggs_v1/` 在请求区间内列举到的日期集；"
            "仓库无美股交易日历，未用日历推断应有交易日。"
            "`weekdays_absent_from_listing` 仅供人工核对（多为假日），不计为缺口。"
        ),
        "range": ([flatfiles.start.isoformat(), flatfiles.end.isoformat()] if flatfiles else None),
        "listed_files": len(flatfiles.listed) if flatfiles else 0,
        "committed_batches": sum(1 for d in flatfiles.days if d.status == "ok") if flatfiles else 0,
        "skipped_idempotent": (
            sum(1 for d in flatfiles.days if d.status == "skipped") if flatfiles else 0
        ),
        "raw_bytes": sum(d.raw_bytes for d in flatfiles.days) if flatfiles else 0,
        "gaps": gaps,
        "weekdays_absent_from_listing": (
            [d.isoformat() for d in flatfiles.weekdays_absent_from_listing()] if flatfiles else []
        ),
        "tickers": (
            {
                "active": tickers.extra.get("active", 0),
                "inactive": tickers.extra.get("inactive", 0),
                "with_figi": tickers.extra.get("with_figi", 0),
            }
            if tickers
            else None
        ),
        "splits": ref["splits"].rows if "splits" in ref else 0,
        "dividends": ref["dividends"].rows if "dividends" in ref else 0,
        "ticker_events": ref["ticker_events"].rows if "ticker_events" in ref else 0,
        "reference_batches": [
            {
                "name": r.name,
                "meta_table": r.meta_table,
                "batch_id": r.batch_id,
                "rows": r.rows,
                "content_sha256": r.content_sha256,
                "raw_files": r.raw_files,
                "raw_bytes": r.raw_bytes,
                "pages": r.pages,
                "elapsed_seconds": r.elapsed_seconds,
                **{f"n_{k}": v for k, v in sorted(r.extra.items())},
            }
            for r in reference
        ],
    }
    sources = sorted(
        {str(s["source"]) for s in series} | ({massive.REST_SOURCE} if reference else set())
    )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_id": run_id,
        "report_date": report_date.isoformat(),
        "generated_at": generated_at.isoformat(),
        "mode": "ingest",
        "coverage": coverage,
        "sources": [
            # 一次运行只跑一个子命令（flatfiles 或 reference），分源覆盖即整体覆盖。
            {"source": s, "coverage": coverage}
            for s in sources
        ],
        "totals": {
            "series": len(series),
            "rows": sum(int(s["rows"]) for s in series) + sum(r.rows for r in reference),
            "gaps": len(gaps),
            "duplicates": 0,
            "missing_upstream": 0,
            "retries": sum(int(s["retries"]) for s in series),
            "failures": len(failures) + len(failed),
            "failed_series": len(failed),
            "pending_series": 0,
            "pending_upstream_days": 0,
            "elapsed_seconds": round(elapsed_seconds, 3),
        },
        "series": series,
        "failures": list(failures),
        "massive": massive_section,
    }


def render_markdown(report: dict[str, Any]) -> str:
    """人读版。数字全部取自 `report` dict，与 JSON 同源。"""
    t = report["totals"]
    m = report["massive"]
    assert isinstance(t, dict) and isinstance(m, dict)
    lines = [
        f"# quantime Massive 摄取报告 {report['report_date']}",
        "",
        f"- run_id: `{report['run_id']}`",
        f"- 生成时刻: {report['generated_at']}",
        f"- 整体覆盖: **{report['coverage']}**",
        f"- 区间: {m['range']}｜列举文件: {m['listed_files']}｜新提交 batch: "
        f"{m['committed_batches']}｜幂等跳过: {m['skipped_idempotent']}",
        f"- 新增行数: {t['rows']}｜raw 字节: {m['raw_bytes']}｜重试: {t['retries']}"
        f"｜失败: {t['failures']}｜耗时: {t['elapsed_seconds']}s",
        "",
        "## 缺口",
        "",
        f"> {m['baseline']}",
        "",
        f"- 缺口（基线内未提交）: {', '.join(m['gaps']) or '无'}",
        f"- 区间内不在列举里的工作日（人工核对）: "
        f"{', '.join(m['weekdays_absent_from_listing']) or '无'}",
        "",
        "## 参考数据",
        "",
    ]
    tk = m["tickers"]
    if tk:
        lines.append(
            f"- ticker: active {tk['active']}｜inactive {tk['inactive']}｜有 FIGI {tk['with_figi']}"
        )
    lines.append(
        f"- 拆股: {m['splits']}｜分红: {m['dividends']}｜ticker 变更事件: {m['ticker_events']}"
    )
    refs = m["reference_batches"]
    if refs:
        lines += [
            "",
            "| name | table | batch_id | rows | content_sha256 | raw files | raw bytes |",
            "| --- | --- | --- | ---: | --- | ---: | ---: |",
        ]
        for r in refs:
            lines.append(
                f"| {r['name']} | {r['meta_table']} | `{r['batch_id']}` | {r['rows']} "
                f"| `{r['content_sha256']}` | {r['raw_files']} | {r['raw_bytes']} |"
            )
    series = report["series"]
    assert isinstance(series, list)
    if series:
        lines += [
            "",
            "## 分日",
            "",
            "| date | action | rows | batch_id | content_sha256 | raw bytes | retries |",
            "| --- | --- | ---: | --- | --- | ---: | ---: |",
        ]
        for s in series:
            lines.append(
                f"| {s['range_start']} | {s['action']} | {s['rows']} | `{s['batch_id']}` "
                f"| `{s['content_sha256']}` | {s['raw_bytes']} | {s['retries']} |"
            )
    failures = report["failures"]
    assert isinstance(failures, list)
    failed = [s for s in series if s["status"] == "failed"]
    if failures or failed:
        lines += ["", "## 失败", ""]
        lines.extend(f"- {f}" for f in failures)
        lines.extend(f"- {s['range_start']}: {s['error_class']}: {s['error']}" for s in failed)
    return "\n".join(lines) + "\n"


def publish_report(root: str | os.PathLike[str], report: dict[str, Any]) -> tuple[Path, Path]:
    """发布到 `data/reports/<date>/massive/<run_id>.{json,md}`（只 insert，同 run 不能重写）。"""
    root = Path(root)
    out = root / "data" / "reports" / str(report["report_date"]) / REPORT_SUBDIR
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{report['run_id']}.json"
    md_path = out / f"{report['run_id']}.md"
    staging = batches.publish_staging(root)
    parquet_io.publish_text(
        json_path,
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        staging=staging,
    )
    parquet_io.publish_text(md_path, render_markdown(report), staging=staging)
    return json_path, md_path
