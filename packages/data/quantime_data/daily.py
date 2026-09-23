"""每日运行编排（QNT-45 通用层）——增量 / 重试 / 补采 / 核查 / 报告缝在一起。

`cli.py` 只负责解析参数与组装真实网络；**运行的逻辑全在这里**，因此它可以用注入的
`fetch` 在离线 fixture 上整条跑通。换数据源不改这个文件：它只跟 `adapter.SourceAdapter`
说话。

一次运行（`run_daily`）的形状：

    对每条序列：
      推算增量区间（`--since-last`）—— 空增量则记一笔 skip，不写 batch
      → 带退避重试地摄取（`retry.RetryContext`）
      → 核查刚提交的 batch（缺口 / 重复 / 覆盖）
      → 记进运行记录与报告
    最后：发布 `data/reports/<date>/<run_id>.{json,md}` 与 `data/runs/<run_id>/run_log.json`

退出码来自运行记录：有任何失败即非零（`runlog.RunLog.exit_code`）。
"""

from __future__ import annotations

import datetime as dt
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import backfill as backfill_mod
from . import ingest as ingest_mod
from .adapter import SourceAdapter, get_adapter
from .incremental import describe_increment, plan_incremental
from .report import DailyReport, publish_report, series_from_audit
from .retry import RetryContext, RetryExhaustedError, RetryPolicy
from .runlog import RunLog, SeriesOutcome, publish_run_log
from .spec import Fetcher, IngestError, IngestSpec

#: 运行模式——写进报告与运行记录，事后能分辨这一份是日常增量还是一次补采。
MODE_FULL = "full"
MODE_INCREMENTAL = "incremental"
MODE_BACKFILL = "backfill"


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
) -> tuple[ingest_mod.IngestResult | None, SeriesOutcome, str | None]:
    """摄取一条序列并记账。回传 `(结果, 运行记录条目, 失败说明)`。"""
    before = retry.retries
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
        ),
        None,
    )


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
) -> RunOutput:
    """跑一轮摄取 + 核查 + 报告。**不出网**：字节全经注入的 `fetch`。

    `since_last=True` 时每条序列的区间先按已提交的 `ingestion_batch` 收窄；收窄成空的序列
    不写 batch（ADR-0002 不写空批次），但**照样在运行记录里留一行** `skipped_empty_increment`
    ——否则「今天没有新数据」与「今天 timer 没跑」事后分不开。
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

    for spec in specs:
        target = plan_incremental(root, spec, adapter.name) if since_last else spec
        if since_last:
            out.increments.append(describe_increment(spec, target))
        if target is None:
            log.record(
                SeriesOutcome(
                    spec=spec.describe(),
                    source=adapter.name,
                    action="skipped_empty_increment",
                )
            )
            continue
        result, outcome, failure = _ingest_series(
            root,
            target,
            fetch,
            run_id=run_id,
            adapter=adapter,
            retry=retry,
            now=stamp,
            kind="ingest",
            rerun_of=None,
            verify_checksum=verify_checksum,
            monotonic=monotonic,
        )
        log.record(outcome)
        if failure is not None:
            report.failures.append(failure)
            continue
        assert result is not None
        out.results.append(result)
        audited = ingest_mod.audit_result(root, result, adapter)
        out.audits.append(audited)
        report.add(
            series_from_audit(
                audited,
                source=adapter.name,
                asset_class=str(target.asset_class),
                range_start=target.start,
                range_end=target.end,
                spec_text=target.describe(),
                retries=outcome.retries,
                elapsed_seconds=outcome.elapsed_seconds,
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
) -> RunOutput:
    """按一份核查报告补采缺口，并产出**补采后的**新报告。

    补采写的是 `kind='rerun'` 的新 batch，被补的 batch 原样不动。补完重新核查，新报告里
    这些序列应当是 `coverage=complete`（除非缺的那几档本来就在上游缺失白名单里）。
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
        result, outcome, failure = _ingest_series(
            root,
            task.spec,
            fetch,
            run_id=run_id,
            adapter=adapter,
            retry=retry,
            now=stamp,
            kind=backfill_mod.BACKFILL_KIND,
            rerun_of=task.rerun_of,
            verify_checksum=verify_checksum,
            monotonic=monotonic,
        )
        log.record(outcome)
        if failure is not None:
            report.failures.append(failure)
            continue
        assert result is not None
        out.results.append(result)
        audited = ingest_mod.audit_result(root, result, adapter)
        out.audits.append(audited)
        report.add(
            series_from_audit(
                audited,
                source=adapter.name,
                asset_class=str(task.spec.asset_class),
                range_start=task.spec.start,
                range_end=task.spec.end,
                spec_text=task.spec.describe(),
                retries=outcome.retries,
                elapsed_seconds=outcome.elapsed_seconds,
            )
        )

    report.elapsed_seconds = monotonic() - run_started
    out.retry_log = retry.log_lines()
    if write_report:
        out.report_paths = publish_report(root, report)
    publish_run_log(root, log, now=stamp)
    return out
