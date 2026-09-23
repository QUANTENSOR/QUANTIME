"""缺口补采（QNT-45 第 3 项）——**源无关**：从核查报告读缺档，按新 batch 补回。

输入是 `--backfill-from-report <path>` 指的那份 JSON 报告（`report.py` 生成的那一份，
schema v3）。报告里每条序列都带足够的字段重建 `IngestSpec`（含请求日 `as_of`），以及
**结构化的缺档清单** `missing_archives`（url / filename / covers_start / covers_end）。
两类序列都产出任务（QNT-45 R5）：

* `status=ok` 且有整档缺失 → 每个缺档一个 `kind='rerun'`、`rerun_of=<原 batch_id>` 的任务；
* `status=failed`（当天一行都没进湖，没有原 batch）→ 每个缺档一个 `kind='ingest'` 的任务，
  batch 清单 JSON 记 `from_report=<报告路径>`。不造空 batch 去凑一个 `rerun_of`。

补采做三件事：

1. 缺档的日期区间直接取自报告（`covers_start..covers_end`），并与 adapter 按同一请求日
   重列的归档**核对**——口径不一致就拒绝盲补；
2. 过滤掉 `upstream_missing.yaml` 里已被人工核实为「上游确实没有」的文件——它们不再重试；
3. 剩下的经 `ingest_one` 补回。

**补采写的是新 batch，不是覆盖。** 被补的那个 batch 的每个字节保持不变，两者由
`rerun_of` 连起来（ADR-0002 D2.1）。写成覆盖会把「当时取到的是什么」这个事实抹掉，
重放随即失效——那是这一项最容易出错、也最要命的地方（QNT-45 变异点 c）。
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from quantime_core.paths import AssetClass, DataType, Freq

from . import ingest as ingest_mod
from .adapter import SourceAdapter, get_adapter
from .report import load_report
from .spec import Fetcher, IngestError, IngestSpec
from .upstream_missing import UpstreamMissing, load_upstream_missing

#: 补有原 batch 可接的缺口时的 batch kind——必带 `rerun_of`。
BACKFILL_KIND = "rerun"
#: 原序列当天整条失败、没有 batch 可接时的 kind——带 `from_report`，不带 `rerun_of`。
FIRST_FILL_KIND = "ingest"


@dataclass(frozen=True, slots=True)
class BackfillTask:
    """一个待补的归档：补哪个文件、补哪段区间、接在哪个 batch 之后（或出自哪份报告）。"""

    spec: IngestSpec
    filename: str
    source: str
    rerun_of: str | None
    kind: str = BACKFILL_KIND
    from_report: str | None = None

    def __post_init__(self) -> None:
        if self.kind == BACKFILL_KIND and not self.rerun_of:
            raise IngestError(f"kind='rerun' 的补采必须带 rerun_of（{self.filename}）")
        if self.kind == FIRST_FILL_KIND and (self.rerun_of or not self.from_report):
            raise IngestError(
                f"无原 batch 的补采必须是 kind='ingest' + from_report（{self.filename}）"
            )

    def describe(self) -> str:
        link = f"rerun_of={self.rerun_of}" if self.rerun_of else f"from_report={self.from_report}"
        return f"{self.filename} → {self.spec.describe()}（kind={self.kind}，{link}）"


@dataclass(frozen=True, slots=True)
class SkippedTask:
    """已知上游确实缺失、因而**不再重试**的归档。"""

    filename: str
    source: str
    reason: str


@dataclass(frozen=True, slots=True)
class BackfillPlan:
    tasks: tuple[BackfillTask, ...]
    skipped: tuple[SkippedTask, ...]

    def describe(self) -> str:
        return f"待补 {len(self.tasks)} 个归档，已知上游缺失跳过 {len(self.skipped)} 个"


def spec_from_series(entry: dict) -> IngestSpec:
    """从报告条目重建 `IngestSpec`。字段不全就报错——补采不猜区间。"""
    try:
        return IngestSpec(
            datatype=DataType(entry["datatype"]),
            asset_class=AssetClass(entry["asset_class"]),
            symbol=entry["scope"],
            freq=Freq(entry["freq"]),
            start=dt.date.fromisoformat(entry["range_start"]),
            end=dt.date.fromisoformat(entry["range_end"]),
            as_of=dt.date.fromisoformat(entry["as_of"]) if entry.get("as_of") else None,
        )
    except (KeyError, ValueError) as exc:
        raise IngestError(f"报告条目无法重建 spec: {exc}") from exc


def plan_backfill(
    report_path: str | os.PathLike[str],
    *,
    adapter: SourceAdapter | None = None,
    whitelist: UpstreamMissing | None = None,
) -> BackfillPlan:
    """读报告，列出要补的归档。纯读：不出网、不落盘。

    每个缺档单独成一个 task 而不是把整条序列重取一遍：报告说缺的是那一个月，重取整个
    区间会把已经取好的月份也重下一遍，还会写出一个区间与缺口无关的 batch。
    失败序列的缺档 = 它区间内全部已发布归档（一行都没进湖）；成功序列的缺档 = 那几个 404。
    """
    adapter = adapter if adapter is not None else get_adapter()
    whitelist = whitelist if whitelist is not None else load_upstream_missing()
    data = load_report(report_path)
    report_ref = Path(report_path).as_posix()

    tasks: list[BackfillTask] = []
    skipped: list[SkippedTask] = []
    for entry in data.get("series", []):
        archives = entry.get("missing_archives") or []
        if not archives:
            continue
        source = entry["source"]
        if source != adapter.name:
            raise IngestError(
                f"报告条目的 source={source!r} 与 adapter {adapter.name!r} 不符——"
                "补采请按源分别运行，不要跨源混补"
            )
        spec = spec_from_series(entry)
        by_name = {a.filename: a for a in adapter.list_archives(spec)}
        rerun_of = entry.get("batch_id")
        for recorded in archives:
            name = recorded["filename"]
            if whitelist.is_known_missing(source, name):
                skipped.append(
                    SkippedTask(
                        filename=name,
                        source=source,
                        reason=whitelist.reason_for(source, name) or "上游确实缺失（白名单）",
                    )
                )
                continue
            archive = by_name.get(name)
            if archive is None or (
                archive.covers_start.isoformat(),
                archive.covers_end.isoformat(),
            ) != (recorded["covers_start"], recorded["covers_end"]):
                raise IngestError(
                    f"报告里的缺档 {name!r} 与 adapter 按同一请求日列出的归档对不上"
                    f"（{spec.describe()}）——报告与 adapter 口径不一致，拒绝盲补"
                )
            # 补的区间 = 缺档覆盖区间 ∩ 原请求区间（月档可能超出一个增量窗口的两端）。
            window = spec.with_window(
                max(archive.covers_start, spec.start), min(archive.covers_end, spec.end)
            )
            tasks.append(
                BackfillTask(
                    spec=window,
                    filename=name,
                    source=source,
                    rerun_of=rerun_of,
                    kind=BACKFILL_KIND,
                )
                if rerun_of
                else BackfillTask(
                    spec=window,
                    filename=name,
                    source=source,
                    rerun_of=None,
                    kind=FIRST_FILL_KIND,
                    from_report=report_ref,
                )
            )
    return BackfillPlan(tasks=tuple(tasks), skipped=tuple(skipped))


def run_backfill(
    root: str | os.PathLike[str],
    plan: BackfillPlan,
    fetch: Fetcher,
    *,
    run_id: str,
    now: dt.datetime | None = None,
    verify_checksum: bool = True,
    adapter: SourceAdapter | None = None,
    retry: object | None = None,
) -> tuple[list[ingest_mod.IngestResult], list[str]]:
    """执行补采计划。回传 `(成功的结果, 失败说明)`。

    每个 task 都是一次**新 batch**——`kind='rerun'` 的 `rerun_of` 指向报告里那个有缺口的
    batch；`kind='ingest'` 的清单记 `from_report`。任何一步都不碰已发布的文件。
    """
    root = Path(root)
    adapter = adapter if adapter is not None else get_adapter()
    results: list[ingest_mod.IngestResult] = []
    failures: list[str] = []
    for task in plan.tasks:
        try:
            results.append(
                ingest_mod.ingest_one(
                    root,
                    task.spec,
                    fetch,
                    run_id=run_id,
                    now=now,
                    kind=task.kind,
                    rerun_of=task.rerun_of,
                    verify_checksum=verify_checksum,
                    adapter=adapter,
                    retry=retry,
                    from_report=task.from_report,
                )
            )
        except IngestError as exc:
            failures.append(f"{task.describe()}: {exc}")
    return results, failures


def backfilled_filenames(results: Sequence[ingest_mod.IngestResult]) -> tuple[str, ...]:
    """补采实际取回的归档文件名（升序），供复核报告前后差异。"""
    return tuple(sorted({name for r in results for name in r.files}))
