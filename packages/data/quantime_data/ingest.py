"""摄取编排（ADR-0003 §3.2 `data/ingest.py`）——把「取字节」与「写批次」缝起来。

一次摄取 = 一个 `(datatype, asset_class, symbol, freq, 区间)` 的**一个 batch**：

    取 zip 字节（经 PublicTransport，唯一出网点）
      → 落 raw 副本（`data/raw/<source>/<batch_id>/`，不可变）
      → 归一化 → 盖 ADR-0002 provenance 五列
      → `batches.commit_batch`（唯一性登记 → `_staging` → sha → 原子发布 → insert 行）

本模块**没有任何 update / 覆盖路径**：重跑同参数走 `kind='rerun'` + `rerun_of`，
写的是一个全新 `batch_id` 的新目录，历史字节一个不动（ADR-0002 D2.1）。

`fetch` 是注入的（`Fetcher = url -> bytes`），所以集成测可以拿录制的 fixture 跑完整条链路，
测试与 CI 全程离线。真正的网络只在 `cli.py` 里组装。
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
from quantime_core.ids import new_batch_id
from quantime_core.paths import AssetClass, DataType, Freq, Market, raw_batch_dir

from . import audit, batches
from .sources import binance_public as bp

#: 取字节：`url -> bytes`。实现由调用方注入（离线测试传 fixture reader）。
Fetcher = Callable[[str], bytes]

MARKET = Market.CRYPTO


class IngestError(RuntimeError):
    """摄取失败（上游缺档、校验不过、区间非法）。"""


@dataclass(frozen=True, slots=True)
class IngestSpec:
    """一次摄取的完整参数——它同时是「同参数重跑」的判定依据。"""

    datatype: DataType
    asset_class: AssetClass
    symbol: str
    freq: Freq
    start: dt.date
    end: dt.date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise IngestError(f"区间非法: {self.start} > {self.end}")

    @property
    def scope(self) -> str:
        return self.symbol

    def describe(self) -> str:
        return (
            f"{self.datatype}/{self.asset_class}/{self.symbol}/{self.freq}"
            f"/{self.start.isoformat()}..{self.end.isoformat()}"
        )


@dataclass(frozen=True, slots=True)
class FetchedFile:
    """一个已取回并校验过的上游文件。"""

    url: str
    filename: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class IngestResult:
    committed: batches.CommittedBatch
    spec: IngestSpec
    files: tuple[str, ...]
    missing: tuple[str, ...]


def months_between(start: dt.date, end: dt.date) -> list[str]:
    """`[start, end]` 覆盖到的月份标签（`YYYY-MM`），升序。"""
    out: list[str] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def days_between(start: dt.date, end: dt.date) -> Iterator[dt.date]:
    day = start
    while day <= end:
        yield day
        day += dt.timedelta(days=1)


def plan_urls(spec: IngestSpec) -> list[tuple[str, str]]:
    """列出本次摄取要取的 `(url, 本地文件名)`——纯函数，便于单测与 dry-run。"""
    dtype = spec.datatype
    if dtype is DataType.KLINE:
        return [
            (u, u.rsplit("/", 1)[-1])
            for u in (
                bp.kline_url(spec.asset_class, spec.symbol, spec.freq, month)
                for month in months_between(spec.start, spec.end)
            )
        ]
    if dtype is DataType.FUNDING:
        _assert_perp(spec, "funding")
        return [
            (u, u.rsplit("/", 1)[-1])
            for u in (bp.funding_url(spec.symbol, m) for m in months_between(spec.start, spec.end))
        ]
    if dtype is DataType.OPEN_INTEREST:
        _assert_perp(spec, "open_interest")
        return [
            (u, u.rsplit("/", 1)[-1])
            for u in (bp.metrics_url(spec.symbol, d) for d in days_between(spec.start, spec.end))
        ]
    raise IngestError(f"本卡范围只含 kline / funding / open_interest，得到 {dtype}")


def _assert_perp(spec: IngestSpec, what: str) -> None:
    if AssetClass(spec.asset_class) is not AssetClass.PERP:
        raise IngestError(f"{what} 只存在于 USDT 永续（perp），得到 {spec.asset_class}")


def fetch_files(
    spec: IngestSpec, fetch: Fetcher, *, verify_checksum: bool = True
) -> tuple[tuple[FetchedFile, ...], tuple[str, ...]]:
    """取回本次摄取的全部文件。上游 404（该月/日无归档）**不是错误**，计入 `missing`。

    `verify_checksum=True` 时，每个 zip 旁的 `.CHECKSUM` 也取一次并逐字节核对
    （Vision 归档可被上游替换，下载当时的 checksum 是我们唯一的取证锚点，ADR-0003 §4.6）。
    `.CHECKSUM` 本身缺失只记为不可核对，不让摄取失败——它是旁路文件，不是数据。
    """
    import hashlib

    got: list[FetchedFile] = []
    missing: list[str] = []
    for url, filename in plan_urls(spec):
        try:
            payload = fetch(url)
        except FileNotFoundError:
            missing.append(filename)
            continue
        if verify_checksum:
            try:
                expected = bp.parse_checksum(fetch(bp.checksum_url(url)))
            except FileNotFoundError:
                expected = None
            if expected is not None:
                actual = hashlib.sha256(payload).hexdigest()
                if actual != expected:
                    raise IngestError(
                        f"{filename} 的 sha256 与上游 .CHECKSUM 不符（期望 {expected}，"
                        f"实际 {actual}）——拒绝把可疑字节写进湖"
                    )
        got.append(FetchedFile(url=url, filename=filename, payload=payload))
    return tuple(got), tuple(missing)


def requested_window(spec: IngestSpec) -> tuple[dt.datetime, dt.datetime]:
    """请求区间的 UTC 半开窗口 `[start 00:00, end+1d 00:00)`。

    `IngestSpec` 的 `start`/`end` 是**含**两端的日期，而上游归档的最小粒度是整月（K 线、
    funding）或整日（metrics）——取回来的行几乎总是比请求的区间宽。窗口在这里算一次，
    裁剪与覆盖判定都用它，两处不会各算各的。
    """
    start = dt.datetime.combine(spec.start, dt.time.min, tzinfo=dt.UTC)
    end = dt.datetime.combine(spec.end + dt.timedelta(days=1), dt.time.min, tzinfo=dt.UTC)
    return start, end


def clip_to_window(table: pa.Table, time_column: str, spec: IngestSpec) -> pa.Table:
    """只保留落在请求区间内的行（`start <= t < end+1d`，UTC）。

    不裁剪的话，`start=end=2026-08-15` 会提交整个八月 31 行——写进湖的区间与
    `ingestion_batch.range_start/range_end` 声明的区间不符，重放时读到的也不是请求的那段
    （verify-a R1 P2-3）。裁剪发生在盖 provenance **之前**，所以被丢掉的行从未进过 batch。
    """
    if table.num_rows == 0:
        return table
    start, end = requested_window(spec)
    times = table.column(time_column).to_pylist()
    keep = [i for i, t in enumerate(times) if start <= t < end]
    if len(keep) == table.num_rows:
        return table
    return table.take(pa.array(keep, pa.int64()))


def normalize(spec: IngestSpec, files: Sequence[FetchedFile]) -> pa.Table:
    """把取回的文件归一化、**裁到请求区间**并拼成一张表（按时间列升序，行序确定）。"""
    dtype = spec.datatype
    if dtype is DataType.KLINE:
        parts = [bp.normalize_klines(f.payload, symbol=spec.symbol) for f in files]
        schema, time_col = bp.KLINE_SCHEMA, "open_time"
    elif dtype is DataType.FUNDING:
        parts = [bp.normalize_funding(f.payload, symbol=spec.symbol) for f in files]
        schema, time_col = bp.FUNDING_SCHEMA, "calc_time"
    elif dtype is DataType.OPEN_INTEREST:
        parts = [bp.normalize_open_interest(f.payload, symbol=spec.symbol) for f in files]
        schema, time_col = bp.OPEN_INTEREST_SCHEMA, "create_time"
    else:  # pragma: no cover —— plan_urls 已先行拒绝
        raise IngestError(f"不支持的 datatype: {dtype}")
    if not parts:
        return schema.empty_table()
    return clip_to_window(pa.concat_tables(parts).sort_by(time_col), time_col, spec)


def stamp_provenance(
    table: pa.Table, *, run_id: str, batch_id: str, ingested_at: dt.datetime
) -> pa.Table:
    """盖 ADR-0002 五列（`source` / `source_version` / `ingested_at` / `run_id` / `batch_id`）。

    `ingested_at` 由调用方传入而不是这里读时钟：同一个 batch 的所有行必须同一个时刻，
    且测试要能固定它。
    """
    n = table.num_rows
    for name, array in (
        ("source", pa.array([bp.SOURCE] * n, pa.string())),
        ("source_version", pa.array([bp.SOURCE_VERSION] * n, pa.string())),
        ("ingested_at", pa.array([ingested_at] * n, pa.timestamp("us", tz="UTC"))),
        ("run_id", pa.array([run_id] * n, pa.string())),
        ("batch_id", pa.array([batch_id] * n, pa.string())),
    ):
        table = table.append_column(pa.field(name, array.type, nullable=False), array)
    return table


def _write_raw(root: Path, batch_id: str, files: Sequence[FetchedFile]) -> tuple[Path, ...]:
    """把上游原始字节按 batch 落到 `data/raw/<source>/<batch_id>/`（不可变副本）。

    走 `parquet_io.publish_bytes`：同一路径已存在即拒绝，raw 副本同样只 insert。
    """
    from quantime_core import parquet_io

    out_dir = root / raw_batch_dir(bp.SOURCE, batch_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for f in files:
        target = out_dir / f.filename
        try:
            parquet_io.publish_bytes(target, f.payload, staging=batches.publish_staging(root))
        except parquet_io.AlreadyPublishedError as exc:
            raise IngestError(f"raw 副本已存在，拒绝二次写入: {target}") from exc
        written.append(target)
    return tuple(written)


def ingest_one(
    root: str | os.PathLike[str],
    spec: IngestSpec,
    fetch: Fetcher,
    *,
    run_id: str,
    now: dt.datetime | None = None,
    kind: str = "ingest",
    rerun_of: str | None = None,
    verify_checksum: bool = True,
) -> IngestResult:
    """完整摄取一个 spec 并提交为**一个新 batch**。

    同参数重跑请传 `kind='rerun'` + `rerun_of=<原 batch_id>`：产出的是新 `batch_id`
    的新目录，原 batch 的每个字节保持不变（ADR-0002）。
    """
    root = Path(root)
    fetched, missing = fetch_files(spec, fetch, verify_checksum=verify_checksum)
    if not fetched:
        raise IngestError(
            f"{spec.describe()}：区间内上游无任何归档文件（缺 {len(missing)} 个），不写空 batch"
        )
    table = normalize(spec, fetched)
    if table.num_rows == 0:
        raise IngestError(f"{spec.describe()}：归一化并裁到请求区间后 0 行，不写空 batch")

    batch_id = new_batch_id()
    # 唯一性登记必须在 **raw 副本落盘之前**：raw 目录按 batch_id 分，`commit_batch` 内部
    # 的登记来得太晚——它失败时 `data/raw/<batch_id>/` 已经有字节了。登记在这里取得，
    # `commit_batch` 再登记同一个 id 是幂等的（同一进程、同一把锁）。
    claim = batches.claim_batch_id(root, batch_id)
    ingested_at = (now or dt.datetime.now(dt.UTC)).replace(microsecond=0)
    stamped = stamp_provenance(table, run_id=run_id, batch_id=batch_id, ingested_at=ingested_at)
    raw_paths = _write_raw(root, batch_id, fetched)

    time_col = bp.TIME_COLUMN[str(spec.datatype)]
    times = table.column(time_col).to_pylist()
    committed = batches.commit_batch(
        root,
        stamped,
        market=MARKET,
        asset_class=spec.asset_class,
        datatype=spec.datatype,
        freq=spec.freq,
        scope=spec.scope,
        source=bp.SOURCE,
        source_version=bp.SOURCE_VERSION,
        run_id=run_id,
        batch_id=batch_id,
        kind=kind,
        rerun_of=rerun_of,
        raw_files=raw_paths,
        range_start=min(times),
        range_end=max(times),
        claim=claim,
    )
    return IngestResult(
        committed=committed,
        spec=spec,
        files=tuple(f.filename for f in fetched),
        missing=missing,
    )


def expected_step(spec: IngestSpec) -> dt.timedelta | None:
    """该 spec 的期望时间步长；`None` = 不做等距检查（funding 间隔由上游逐行给出）。"""
    dtype = spec.datatype
    if dtype is DataType.KLINE:
        return bp.FREQ_STEP[str(spec.freq)]
    if dtype is DataType.OPEN_INTEREST:
        return bp.METRICS_INTERVAL
    return None


def audit_result(root: str | os.PathLike[str], result: IngestResult) -> audit.AuditResult:
    """对刚提交的 batch 做缺口/重复核查——**只读那一个 batch 的分片**。

    整档缺失（`result.missing`）一并传进去：核查读的是落盘的表，表里看不出请求区间的
    某一整个月压根没取到，所以覆盖状态必须由摄取侧告诉它（verify-a R1 P2-4）。
    """
    spec = result.spec
    time_col = bp.TIME_COLUMN[str(spec.datatype)]
    start, end = requested_window(spec)
    note = f"requested={start.date().isoformat()}..{spec.end.isoformat()}"
    if result.missing:
        note += f" missing_upstream_files={len(result.missing)}"
    return audit.audit_batch_file(
        Path(root) / result.committed.parts[0].path,
        scope=spec.scope,
        datatype=str(spec.datatype),
        freq=str(spec.freq),
        audited_batch_id=result.committed.batch_id,
        time_column=time_col,
        step=expected_step(spec),
        key_columns=("symbol", time_col),
        missing_upstream=result.missing,
        note=note,
    )


def commit_audit_report(
    root: str | os.PathLike[str],
    results: Sequence[audit.AuditResult],
    *,
    run_id: str,
    scope: str,
    datatype: DataType | str,
    freq: Freq | str,
    asset_class: AssetClass | str,
    now: dt.datetime | None = None,
) -> batches.CommittedBatch:
    """把核查报告经**同一条发布路径**提交为一个 batch（报告也可重放）。

    报告 batch 不碰被核查的数据：它写在自己的 `audit__<scope>` 目录下，
    `kind='ingest'`（它是一次新的、只 insert 的写入）。
    """
    root = Path(root)
    batch_id = new_batch_id()
    ingested_at = (now or dt.datetime.now(dt.UTC)).replace(microsecond=0)
    table = stamp_provenance(
        audit.report_table(results), run_id=run_id, batch_id=batch_id, ingested_at=ingested_at
    )
    return batches.commit_batch(
        root,
        table,
        market=MARKET,
        asset_class=asset_class,
        datatype=datatype,
        freq=freq,
        scope=f"{audit.AUDIT_SCOPE_PREFIX}{scope}",
        source=bp.SOURCE,
        source_version=bp.SOURCE_VERSION,
        run_id=run_id,
        batch_id=batch_id,
    )
