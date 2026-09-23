"""摄取编排（ADR-0003 §3.2 `data/ingest.py`）——把「取字节」与「写批次」缝起来。

一次摄取 = 一个 `(datatype, asset_class, symbol, freq, 区间)` 的**一个 batch**：

    adapter.list_archives → adapter.fetch_archive（经 PublicTransport，唯一出网点）
      → 落 raw 副本（`data/raw/<source>/<batch_id>/`，不可变）
      → adapter.normalize → 盖 ADR-0002 provenance 五列
      → `batches.commit_batch`（唯一性登记 → `_staging` → sha → 原子发布 → insert 行）

本模块**没有任何改写路径**：重跑同参数走 `kind='rerun'` + `rerun_of`，
写的是一个全新 `batch_id` 的新目录，历史字节一个不动（ADR-0002 D2.1）。

QNT-45 起，三个「认识数据源」的动作（列归档 / 拉取 / 归一化）全部经
`adapter.SourceAdapter` 注入，本模块因此**不 import 任何具体数据源**：Binance Vision 只是
默认 adapter，Massive（QNT-47）与 Tushare（QNT-48）接进来时这里一行都不用改。

`fetch` 同样是注入的（`Fetcher = url -> bytes`），所以集成测可以拿录制的 fixture 跑完整条
链路，测试与 CI 全程离线。真正的网络只在 `cli.py` 里组装。
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
from quantime_core.ids import new_batch_id
from quantime_core.paths import AssetClass, DataType, Freq, Market, raw_batch_dir

from . import audit, batches
from .adapter import Archive, SourceAdapter, get_adapter
from .spec import (
    FetchedFile,
    Fetcher,
    IngestError,
    IngestSpec,
    clip_to_window,
    days_between,
    months_between,
    requested_window,
)

__all__ = [
    "MARKET",
    "Archive",
    "FetchedFile",
    "Fetcher",
    "IngestError",
    "IngestResult",
    "IngestSpec",
    "audit_result",
    "clip_to_window",
    "commit_audit_report",
    "days_between",
    "expected_step",
    "fetch_files",
    "ingest_one",
    "months_between",
    "normalize",
    "plan_urls",
    "requested_window",
    "stamp_provenance",
]

#: 默认 adapter 的市场——历史签名（`MARKET`）保留，实际写路径时取 `adapter.market`。
MARKET = Market.CRYPTO


@dataclass(frozen=True, slots=True)
class IngestResult:
    committed: batches.CommittedBatch
    spec: IngestSpec
    files: tuple[str, ...]
    missing: tuple[str, ...]
    source: str = ""
    time_column: str = ""
    step: dt.timedelta | None = None


def plan_urls(spec: IngestSpec, adapter: SourceAdapter | None = None) -> list[tuple[str, str]]:
    """列出本次摄取要取的 `(url, 本地文件名)`——纯函数，便于单测与 dry-run。"""
    adapter = adapter if adapter is not None else get_adapter()
    return [(a.url, a.filename) for a in adapter.list_archives(spec)]


def fetch_files(
    spec: IngestSpec,
    fetch: Fetcher,
    *,
    verify_checksum: bool = True,
    adapter: SourceAdapter | None = None,
    retry: object | None = None,
) -> tuple[tuple[FetchedFile, ...], tuple[str, ...]]:
    """取回本次摄取的全部文件。上游 404（该区间无归档）**不是错误**，计入 `missing`。

    完整性校验的方式各源不同（Vision 是旁路 `.CHECKSUM`，别的源可能是行数或 ETag），
    所以校验在 `adapter.fetch_archive` 里；这里只负责「缺档记账、其余上抛」。

    `retry` 传 `retry.RetryContext` 时，每个归档的拉取都被退避重试包起来
    （限流 / 5xx / 连接错误重试，404 与校验失败不重试）。
    """
    adapter = adapter if adapter is not None else get_adapter()
    got: list[FetchedFile] = []
    missing: list[str] = []
    for archive in adapter.list_archives(spec):

        def _once(archive: Archive = archive) -> FetchedFile:
            return adapter.fetch_archive(archive, fetch, verify_checksum=verify_checksum)

        try:
            got.append(_once() if retry is None else retry.run(_once, label=archive.filename))
        except FileNotFoundError:
            missing.append(archive.filename)
    return tuple(got), tuple(missing)


def normalize(
    spec: IngestSpec, files: Sequence[FetchedFile], adapter: SourceAdapter | None = None
) -> pa.Table:
    """把取回的文件归一化、**裁到请求区间**并拼成一张表（按时间列升序，行序确定）。"""
    adapter = adapter if adapter is not None else get_adapter()
    return adapter.normalize(spec, files).table


def stamp_provenance(
    table: pa.Table,
    *,
    run_id: str,
    batch_id: str,
    ingested_at: dt.datetime,
    source: str | None = None,
    source_version: str | None = None,
) -> pa.Table:
    """盖 ADR-0002 五列（`source` / `source_version` / `ingested_at` / `run_id` / `batch_id`）。

    `ingested_at` 由调用方传入而不是这里读时钟：同一个 batch 的所有行必须同一个时刻，
    且测试要能固定它。`source` / `source_version` 不传则取默认 adapter 的取值。
    """
    if source is None or source_version is None:
        default = get_adapter()
        source = source if source is not None else default.name
        source_version = source_version if source_version is not None else default.version
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
    root: Path, source: str, batch_id: str, files: Sequence[FetchedFile]
) -> tuple[Path, ...]:
    """把上游原始字节按 batch 落到 `data/raw/<source>/<batch_id>/`（不可变副本）。

    走 `parquet_io.publish_bytes`：同一路径已存在即拒绝，raw 副本同样只 insert。
    """
    from quantime_core import parquet_io

    out_dir = root / raw_batch_dir(source, batch_id)
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
    adapter: SourceAdapter | None = None,
    retry: object | None = None,
) -> IngestResult:
    """完整摄取一个 spec 并提交为**一个新 batch**。

    同参数重跑请传 `kind='rerun'` + `rerun_of=<原 batch_id>`：产出的是新 `batch_id`
    的新目录，原 batch 的每个字节保持不变（ADR-0002）。补采（QNT-45 第 3 项）走的正是
    这条路径——它写的是新 batch，绝不动被补的那一个。
    """
    root = Path(root)
    adapter = adapter if adapter is not None else get_adapter()
    fetched, missing = fetch_files(
        spec, fetch, verify_checksum=verify_checksum, adapter=adapter, retry=retry
    )
    if not fetched:
        raise IngestError(
            f"{spec.describe()}：区间内上游无任何归档文件（缺 {len(missing)} 个），不写空 batch"
        )
    normalized = adapter.normalize(spec, fetched)
    table = normalized.table
    if table.num_rows == 0:
        raise IngestError(f"{spec.describe()}：归一化并裁到请求区间后 0 行，不写空 batch")

    batch_id = new_batch_id()
    # 唯一性登记必须在 **raw 副本落盘之前**：raw 目录按 batch_id 分，`commit_batch` 内部
    # 的登记来得太晚——它失败时 `data/raw/<batch_id>/` 已经有字节了。登记在这里取得，
    # `commit_batch` 再登记同一个 id 是幂等的（同一进程、同一把锁）。
    claim = batches.claim_batch_id(root, batch_id)
    ingested_at = (now or dt.datetime.now(dt.UTC)).replace(microsecond=0)
    stamped = stamp_provenance(
        table,
        run_id=run_id,
        batch_id=batch_id,
        ingested_at=ingested_at,
        source=adapter.name,
        source_version=adapter.version,
    )
    raw_paths = _write_raw(root, adapter.name, batch_id, fetched)

    times = table.column(normalized.time_column).to_pylist()
    committed = batches.commit_batch(
        root,
        stamped,
        market=adapter.market,
        asset_class=spec.asset_class,
        datatype=spec.datatype,
        freq=spec.freq,
        scope=spec.scope,
        source=adapter.name,
        source_version=adapter.version,
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
        source=adapter.name,
        time_column=normalized.time_column,
        step=normalized.step,
    )


def expected_step(spec: IngestSpec, adapter: SourceAdapter | None = None) -> dt.timedelta | None:
    """该 spec 的期望时间步长；`None` = 不做等距检查（如 funding，间隔由上游逐行给出）。"""
    adapter = adapter if adapter is not None else get_adapter()
    return adapter.normalize(spec, ()).step


def time_column(spec: IngestSpec, adapter: SourceAdapter | None = None) -> str:
    """该 spec 的时间列名——核查与裁剪都按它。"""
    adapter = adapter if adapter is not None else get_adapter()
    return adapter.normalize(spec, ()).time_column


def audit_result(
    root: str | os.PathLike[str], result: IngestResult, adapter: SourceAdapter | None = None
) -> audit.AuditResult:
    """对刚提交的 batch 做缺口/重复核查——**只读那一个 batch 的分片**。

    整档缺失（`result.missing`）一并传进去：核查读的是落盘的表，表里看不出请求区间的
    某一整个月压根没取到，所以覆盖状态必须由摄取侧告诉它（verify-a R1 P2-4）。
    """
    spec = result.spec
    time_col = result.time_column or time_column(spec, adapter)
    step = result.step if result.time_column else expected_step(spec, adapter)
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
        step=step,
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
    adapter: SourceAdapter | None = None,
) -> batches.CommittedBatch:
    """把核查报告经**同一条发布路径**提交为一个 batch（报告也可重放）。

    报告 batch 不碰被核查的数据：它写在自己的 `audit__<scope>` 目录下，
    `kind='ingest'`（它是一次新的、只 insert 的写入）。
    """
    root = Path(root)
    adapter = adapter if adapter is not None else get_adapter()
    batch_id = new_batch_id()
    ingested_at = (now or dt.datetime.now(dt.UTC)).replace(microsecond=0)
    table = stamp_provenance(
        audit.report_table(results),
        run_id=run_id,
        batch_id=batch_id,
        ingested_at=ingested_at,
        source=adapter.name,
        source_version=adapter.version,
    )
    return batches.commit_batch(
        root,
        table,
        market=adapter.market,
        asset_class=asset_class,
        datatype=datatype,
        freq=freq,
        scope=f"{audit.AUDIT_SCOPE_PREFIX}{scope}",
        source=adapter.name,
        source_version=adapter.version,
        run_id=run_id,
        batch_id=batch_id,
    )
