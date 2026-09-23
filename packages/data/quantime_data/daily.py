"""每日运行编排（QNT-45 通用层）——增量 / 重试 / 补采 / 核查 / 报告缝在一起。

`cli.py` 只负责解析参数与组装真实网络；**运行的逻辑全在这里**，因此它可以用注入的
`fetch` 在离线 fixture 上整条跑通。换数据源不改这个文件：它只跟 `adapter.SourceAdapter`
说话。

一次运行（`run_daily`）的形状：

    对每条序列：
      定请求日（`as_of` = 本次运行的 UTC 日期；adapter 据此只列已发布的归档）
      推算增量区间（`--since-last`：起点 = min(水位线次日, 未消化的 pending 起点)）
        —— 空增量则记一笔 skip
      → 整段都还没发布 → 记 `pending_upstream`，不取、不算失败
      → 磁盘守卫：数据根所在文件系统剩余 < 阈值 → 不开新 batch，记 `disk_low`（R8）
      → 带退避重试地摄取（`retry.RetryContext`）
      → 核查刚提交的 batch（缺口 / 重复 / 覆盖）
      → 记进运行记录与报告（**失败的序列同样进报告**，带结构化缺档清单，补采据此重建）
      → `--since-last` 下本次什么都没提交的序列：请求起点记进运行记录 `pending_since`，
        之后的 `--since-last` 从那里续取（R7；没有它，空湖首跑的 pending 日子会随「昨日」漂走）
    最后：发布 `data/reports/<date>/<run_id>.{json,md}` 与 `data/runs/<run_id>/run_log.json`

退出码来自运行记录：有任何失败即非零（`runlog.RunLog.exit_code`）。
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import backfill as backfill_mod
from . import ingest as ingest_mod
from .adapter import Archive, SourceAdapter, get_adapter
from .incremental import describe_increment, plan_incremental, start_ignored_note
from .report import (
    DailyReport,
    PendingWindow,
    publish_report,
    series_failed,
    series_from_audit,
    series_pending,
)
from .retry import RetryContext, RetryExhaustedError, RetryPolicy
from .runlog import (
    ABORT_DISK_LOW,
    PendingSince,
    RunLog,
    SeriesOutcome,
    publish_run_log,
    read_pending_since,
)
from .spec import Fetcher, IngestError, IngestSpec

#: 运行模式——写进报告与运行记录，事后能分辨这一份是日常增量还是一次补采。
MODE_FULL = "full"
MODE_INCREMENTAL = "incremental"
MODE_BACKFILL = "backfill"
MODE_ABORTED = "aborted"

#: 磁盘守卫默认阈值：数据根所在文件系统剩余不足 5 GB 就不开新 batch（owner 裁决 2026-09-23）。
DEFAULT_MIN_FREE_BYTES = 5 * 1024**3


@dataclass(slots=True)
class RunOutput:
    """一次运行的全部产物。CLI 据此打印与退出，测试据此断言。"""

    run_id: str
    log: RunLog
    report: DailyReport
    results: list[ingest_mod.IngestResult] = field(default_factory=list)
    audits: list = field(default_factory=list)
    report_paths: tuple[str, str] | None = None
    increments: list[str] = field(default_factory=list)
    retry_log: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return self.log.exit_code


def _now(now: dt.datetime | None) -> dt.datetime:
    return (now or dt.datetime.now(dt.UTC)).replace(microsecond=0)


def error_class(exc: BaseException) -> str:
    """失败的分类：重试用尽时把根因也带上（`RetryExhaustedError(TransportIOError)`）。"""
    name = type(exc).__name__
    cause = exc.__cause__
    return f"{name}({type(cause).__name__})" if cause is not None else name


def free_bytes(root: Path) -> int:
    """数据根所在文件系统的剩余字节。`data/` 可能是指向别的盘的软链接，所以量它而不是量 root。"""
    target = root / "data"
    return shutil.disk_usage(target if target.exists() else root).free


def disk_low_reason(root: Path, min_free_bytes: int | None) -> str | None:
    """磁盘守卫（R8）：剩余不足阈值 → 回传写进报告的原因；够用或守卫关闭 → `None`。"""
    if min_free_bytes is None:
        return None
    free = free_bytes(root)
    if free >= min_free_bytes:
        return None
    return (
        f"{ABORT_DISK_LOW}: 数据根所在文件系统剩余 {free / 1024**3:.2f} GB"
        f" < 阈值 {min_free_bytes / 1024**3:.2f} GB，拒绝开始新 batch"
    )


def pending_windows(adapter: SourceAdapter, spec: IngestSpec) -> tuple[PendingWindow, ...]:
    """adapter 声明的「按发布节奏尚未发布」日期段；没实现这个可选方法的源 = 无。"""
    fn = getattr(adapter, "pending_windows", None)
    return tuple(fn(spec)) if fn is not None else ()


def _archives_named(
    adapter: SourceAdapter, spec: IngestSpec, names: Sequence[str]
) -> tuple[Archive, ...]:
    by_name = {a.filename: a for a in adapter.list_archives(spec)}
    return tuple(by_name[n] for n in names if n in by_name)


def _ingest_series(
    root: Path,
    spec: IngestSpec,
    fetch: Fetcher,
    *,
    run_id: str,
    adapter: SourceAdapter,
    retry: RetryContext,
    now: dt.datetime,
    kind: str,
    rerun_of: str | None,
    verify_checksum: bool,
    monotonic,
    from_report: str | None = None,
) -> tuple[ingest_mod.IngestResult | None, SeriesOutcome, str | None]:
    """摄取一条序列并记账。回传 `(结果, 运行记录条目, 失败说明)`。"""
    before = retry.retries
    attempts_before = retry.recorder.attempts
    started = monotonic()
    try:
        result = ingest_mod.ingest_one(
            root,
            spec,
            fetch,
            run_id=run_id,
            now=now,
            kind=kind,
            rerun_of=rerun_of,
            verify_checksum=verify_checksum,
            adapter=adapter,
            retry=retry,
            from_report=from_report,
        )
    except (IngestError, RetryExhaustedError) as exc:
        elapsed = monotonic() - started
        message = f"{spec.describe()}: {exc}"
        return (
            None,
            SeriesOutcome(
                spec=spec.describe(),
                source=adapter.name,
                action="failed",
                retries=retry.retries - before,
                elapsed_seconds=elapsed,
                error=str(exc),
                attempts=retry.recorder.attempts - attempts_before,
                error_class=error_class(exc),
            ),
            message,
        )
    elapsed = monotonic() - started
    return (
        result,
        SeriesOutcome(
            spec=spec.describe(),
            source=adapter.name,
            action=kind,
            batch_id=result.committed.batch_id,
            rows=result.committed.row_count,
            retries=retry.retries - before,
            missing_upstream=len(result.missing),
            elapsed_seconds=elapsed,
            attempts=retry.recorder.attempts - attempts_before,
        ),
        None,
    )


def _process_series(
    root: Path,
    target: IngestSpec,
    fetch: Fetcher,
    *,
    out: RunOutput,
    run_id: str,
    adapter: SourceAdapter,
    retry: RetryContext,
    now: dt.datetime,
    kind: str,
    rerun_of: str | None,
    verify_checksum: bool,
    monotonic,
    from_report: str | None = None,
    min_free_bytes: int | None = DEFAULT_MIN_FREE_BYTES,
) -> bool:
    """一条序列：待发布判定 → 磁盘守卫 → 摄取 → 核查 → 记账。回传「是否提交了 batch」。

    成功、失败、待发布、被磁盘守卫拦下的**都进报告**。
    """
    pending = pending_windows(adapter, target)
    pending_days = sum((b - a).days + 1 for a, b in pending)
    if not adapter.list_archives(target) and pending:
        out.log.record(
            SeriesOutcome(
                spec=target.describe(),
                source=adapter.name,
                action="pending_upstream",
                pending_upstream_days=pending_days,
            )
        )
        out.report.add(series_pending(target, source=adapter.name, pending_upstream=pending))
        return False
    low = disk_low_reason(root, min_free_bytes)
    if low is not None:
        # 不开新 batch：一个字节都不取、不写。缺档照样进报告，磁盘腾出来后可按报告补采，
        # `--since-last` 也会从本次的起点续取（`pending_since`）。
        out.log.abort_reason = ABORT_DISK_LOW
        out.report.abort_reason = ABORT_DISK_LOW
        if low not in out.report.failures:
            out.report.failures.append(low)
        out.log.record(
            SeriesOutcome(
                spec=target.describe(),
                source=adapter.name,
                action="failed",
                error=low,
                error_class=ABORT_DISK_LOW,
                pending_upstream_days=pending_days,
            )
        )
        out.report.add(
            series_failed(
                target,
                source=adapter.name,
                error_class=ABORT_DISK_LOW,
                error=low,
                missing_archives=tuple(adapter.list_archives(target)),
                pending_upstream=pending,
                retries=0,
                attempts=0,
                elapsed_seconds=0.0,
            )
        )
        return False
    result, outcome, failure = _ingest_series(
        root,
        target,
        fetch,
        run_id=run_id,
        adapter=adapter,
        retry=retry,
        now=now,
        kind=kind,
        rerun_of=rerun_of,
        verify_checksum=verify_checksum,
        monotonic=monotonic,
        from_report=from_report,
    )
    if pending_days:
        outcome = replace(outcome, pending_upstream_days=pending_days)
    out.log.record(outcome)
    if failure is not None:
        out.report.failures.append(failure)
        out.report.add(
            series_failed(
                target,
                source=adapter.name,
                error_class=outcome.error_class or "",
                error=outcome.error or "",
                # 没有 batch 提交 = 区间内每个已发布的归档都没进湖，全部是待补的缺档。
                missing_archives=adapter.list_archives(target),
                pending_upstream=pending,
                retries=outcome.retries,
                attempts=outcome.attempts,
                elapsed_seconds=outcome.elapsed_seconds,
            )
        )
        return False
    assert result is not None
    out.results.append(result)
    audited = ingest_mod.audit_result(root, result, adapter)
    out.audits.append(audited)
    out.report.add(
        series_from_audit(
            audited,
            source=adapter.name,
            asset_class=str(target.asset_class),
            range_start=target.start,
            range_end=target.end,
            spec_text=target.describe(),
            retries=outcome.retries,
            elapsed_seconds=outcome.elapsed_seconds,
            attempts=outcome.attempts,
            as_of=target.as_of,
            missing_archives=_archives_named(adapter, target, result.missing),
            pending_upstream=pending,
        )
    )
    return True


def run_daily(
    root: str | os.PathLike[str],
    specs: Sequence[IngestSpec],
    fetch: Fetcher,
    *,
    run_id: str,
    adapter: SourceAdapter | None = None,
    since_last: bool = False,
    verify_checksum: bool = True,
    retry_policy: RetryPolicy | None = None,
    sleep=time.sleep,
    monotonic=time.monotonic,
    now: dt.datetime | None = None,
    write_report: bool = True,
    report_date: dt.date | None = None,
    min_free_bytes: int | None = DEFAULT_MIN_FREE_BYTES,
) -> RunOutput:
    """跑一轮摄取 + 核查 + 报告。**不出网**：字节全经注入的 `fetch`。

    `since_last=True` 时每条序列的区间按已提交的 `ingestion_batch` 推算：有水位线就从
    水位线次日起（`--start` 只是无水位线时的初始起点，被忽略时写进运行记录的 `notes`）。
    推算成空的序列不写 batch（ADR-0002 不写空批次），但**照样在运行记录里留一行**
    `skipped_empty_increment`——否则「今天没有新数据」与「今天 timer 没跑」事后分不开。

    每条 spec 的请求日（`as_of`）未指定时取本次运行的 UTC 日期：adapter 按它判断哪些归档
    已经发布（R2）。

    `since_last=True` 下本次没有提交 batch 的序列（整段待发布 / 失败 / 磁盘守卫拦下），把它
    的请求起点记进运行记录 `pending_since`（R7）：下一次从 `min(水位线次日, 该起点)` 续取，
    真实 batch 提交到那天或更后才算消化。

    `min_free_bytes` 是磁盘守卫阈值（默认 5 GB，`None` 关闭）；不足时不开新 batch、
    运行记录 `abort_reason=disk_low`、报告 coverage 为 `failed`（R8）。
    """
    root = Path(root)
    adapter = adapter if adapter is not None else get_adapter()
    stamp = _now(now)
    retry = RetryContext(policy=retry_policy or RetryPolicy(), sleep=sleep, monotonic=monotonic)
    mode = MODE_INCREMENTAL if since_last else MODE_FULL
    log = RunLog(run_id=run_id, source=adapter.name, mode=mode, started_at=stamp)
    report = DailyReport(
        run_id=run_id,
        report_date=report_date or stamp.date(),
        generated_at=stamp,
        mode=mode,
    )
    out = RunOutput(run_id=run_id, log=log, report=report)
    run_started = monotonic()
    pending_index = read_pending_since(root) if since_last else {}

    for spec in specs:
        if spec.as_of is None:
            spec = spec.requested_on(stamp.date())
        target = plan_incremental(root, spec, adapter.name, pending_index) if since_last else spec
        if since_last:
            out.increments.append(describe_increment(spec, target))
            note = start_ignored_note(spec, target)
            if note:
                log.notes.append(f"{spec.describe()}: {note}")
        if target is None:
            log.record(
                SeriesOutcome(
                    spec=spec.describe(),
                    source=adapter.name,
                    action="skipped_empty_increment",
                )
            )
            continue
        committed = _process_series(
            root,
            target,
            fetch,
            out=out,
            run_id=run_id,
            adapter=adapter,
            retry=retry,
            now=stamp,
            kind="ingest",
            rerun_of=None,
            verify_checksum=verify_checksum,
            monotonic=monotonic,
            min_free_bytes=min_free_bytes,
        )
        if since_last and not committed:
            log.pending_since.append(
                PendingSince(
                    source=adapter.name,
                    asset_class=str(target.asset_class),
                    datatype=str(target.datatype),
                    freq=str(target.freq),
                    scope=target.scope,
                    since=target.start,
                )
            )

    report.elapsed_seconds = monotonic() - run_started
    out.retry_log = retry.log_lines()
    if write_report:
        out.report_paths = publish_report(root, report)
    publish_run_log(root, log, now=stamp)
    return out


def run_backfill_from_report(
    root: str | os.PathLike[str],
    report_path: str | os.PathLike[str],
    fetch: Fetcher,
    *,
    run_id: str,
    adapter: SourceAdapter | None = None,
    verify_checksum: bool = True,
    retry_policy: RetryPolicy | None = None,
    sleep=time.sleep,
    monotonic=time.monotonic,
    now: dt.datetime | None = None,
    write_report: bool = True,
    report_date: dt.date | None = None,
    whitelist=None,
    min_free_bytes: int | None = DEFAULT_MIN_FREE_BYTES,
) -> RunOutput:
    """按一份核查报告补采缺口，并产出**补采后的**新报告。

    有原 batch 可接的缺档写 `kind='rerun'` + `rerun_of` 的新 batch；原 batch 当天整条失败
    （报告里 `batch_id=null`）的写 `kind='ingest'`，清单 JSON 记 `from_report=<报告路径>`。
    被补的 batch 原样不动。补完重新核查，新报告里这些序列应当是 `coverage=complete`
    （除非缺的那几档本来就在上游缺失白名单里）。
    """
    root = Path(root)
    adapter = adapter if adapter is not None else get_adapter()
    stamp = _now(now)
    retry = RetryContext(policy=retry_policy or RetryPolicy(), sleep=sleep, monotonic=monotonic)
    log = RunLog(run_id=run_id, source=adapter.name, mode=MODE_BACKFILL, started_at=stamp)
    report = DailyReport(
        run_id=run_id,
        report_date=report_date or stamp.date(),
        generated_at=stamp,
        mode=MODE_BACKFILL,
    )
    out = RunOutput(run_id=run_id, log=log, report=report)
    run_started = monotonic()

    plan = backfill_mod.plan_backfill(report_path, adapter=adapter, whitelist=whitelist)
    out.increments.append(plan.describe())
    for skip in plan.skipped:
        out.increments.append(f"跳过（上游确实缺失）: {skip.filename} —— {skip.reason}")

    for task in plan.tasks:
        _process_series(
            root,
            task.spec,
            fetch,
            out=out,
            run_id=run_id,
            adapter=adapter,
            retry=retry,
            now=stamp,
            kind=task.kind,
            rerun_of=task.rerun_of,
            verify_checksum=verify_checksum,
            monotonic=monotonic,
            from_report=task.from_report,
            min_free_bytes=min_free_bytes,
        )

    report.elapsed_seconds = monotonic() - run_started
    out.retry_log = retry.log_lines()
    if write_report:
        out.report_paths = publish_report(root, report)
    publish_run_log(root, log, now=stamp)
    return out


def record_abort(
    root: str | os.PathLike[str],
    reason: str,
    *,
    run_id: str,
    source: str,
    detail: str | None = None,
    now: dt.datetime | None = None,
) -> RunOutput:
    """记一笔「本次运行在摄取之前就被拦下」：运行记录 + 报告（coverage=failed）。

    systemd unit 在 `ExecStartPre` 拉代码失败时调它（`record-abort --reason pull_failed`）：
    那时主进程根本不会启动，没有这一笔，当天的运行记录与报告就是空的——事后分不清
    「拉代码失败」与「timer 没跑」。不出网、不取任何字节、不写任何 batch。
    """
    root = Path(root)
    stamp = _now(now)
    log = RunLog(
        run_id=run_id,
        source=source,
        mode=MODE_ABORTED,
        started_at=stamp,
        abort_reason=reason,
    )
    if detail:
        log.notes.append(detail)
    report = DailyReport(
        run_id=run_id,
        report_date=stamp.date(),
        generated_at=stamp,
        mode=MODE_ABORTED,
        abort_reason=reason,
    )
    report.failures.append(f"{reason}: {detail}" if detail else reason)
    out = RunOutput(run_id=run_id, log=log, report=report)
    out.report_paths = publish_report(root, report)
    publish_run_log(root, log, now=stamp)
    return out
