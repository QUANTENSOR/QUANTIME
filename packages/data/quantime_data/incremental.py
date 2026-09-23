"""增量摄取（QNT-45 第 1 项）——**源无关**的水位线推算。

「上次取到哪了」的答案只有一个出处：已提交的 `ingestion_batch` 行。不读目录、不读状态
文件、不信任何一份 CLI 之外的记账——湖里已提交的区间就是事实，其余都是它的影子。
键是 `(source, symbol, datatype, freq)`，与 ADR-0003 §4.1 的 lake 路径分量一一对应。

推算只有三个结果：

* 从未取过、也没有未消化的 pending 起点 → 请求区间原样（首次全量；`--start` 只在这时生效）；
* 有水位线 → **水位线次日**起到请求区间末（只取新的那一段）。起点**不再**被 `--start`
  截住：水位线落在 `--start` 之前（机器停了几天、timer 的 `Persistent=true` 只补跑一次）
  时，截住就等于把停机那几天永久跳过（QNT-45 R3）。`--start` 被忽略这件事会写进运行记录；
* 有**未消化的 pending 起点**（运行记录里的 `pending_since`，见下）→ 起点取
  `min(水位线次日, pending 起点)`（QNT-45 R7）；
* 水位线已覆盖请求区间 → `None`，即空增量。空增量**不写 batch**（ADR-0002 不写空批次），
  但仍写一条运行记录（`runlog`），否则「今天跑过且没有新数据」与「今天根本没跑」
  在事后无法区分。

**pending 起点**（R7）：一条序列在 `--since-last` 下这次什么都没提交（整段待发布，或整条
失败），它的请求起点就写进本次运行记录的 `pending_since`。没有它，空湖首跑时 funding
整段 pending、不写 batch、没有水位线——下一天的窗口跟着「昨日」前移，前一天的待发布
日期再也不会被请求。pending 起点**只追加、不改写**：它在水位线越过它（真实 batch 已
提交到那天或更后）时视为已消化，这是读侧从两份只增记录推出来的，不需要回头标记。
禁止用空 batch 伪造水位线（ADR-0002 不写空批次）。

本模块不出网、不落盘，只读 `ingestion_batch` 与运行记录。
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .audit import AUDIT_SCOPE_PREFIX
from .batches import read_ingestion_batch
from .runlog import read_pending_since
from .spec import IngestSpec

#: 增量键——与 lake 路径分量同构。`asset_class` 也在键里：同一个 symbol 的现货与永续
#: 是两条独立序列，共用一个水位线会让其中一条永远取不到数据。
CoverageKey = tuple[str, str, str, str, str]


def coverage_key(
    source: str, asset_class: str, datatype: str, freq: str, scope: str
) -> CoverageKey:
    return (source, str(asset_class), str(datatype), str(freq), scope)


def spec_key(spec: IngestSpec, source: str) -> CoverageKey:
    return coverage_key(source, spec.asset_class, spec.datatype, spec.freq, spec.scope)


@dataclass(frozen=True, slots=True)
class Coverage:
    """一条序列已提交的区间端点与批次数。`end` 是**已提交数据的最后一个时间戳**。"""

    key: CoverageKey
    start: dt.datetime
    end: dt.datetime
    batches: int


def committed_coverage(root: str | os.PathLike[str]) -> dict[CoverageKey, Coverage]:
    """扫描已提交的 `ingestion_batch`，按增量键归并出每条序列的已覆盖区间。

    排除两类行：`kind='license_drop'`（那是「数据被删除」的记账，不代表有数据），
    以及 `audit__` 前缀的核查报告 scope（报告不是行情，把它算进水位线会让真正的
    行情序列永远显示"已经取到今天"）。
    """
    table = read_ingestion_batch(root)
    if table.num_rows == 0:
        return {}
    cols = {name: table.column(name).to_pylist() for name in table.column_names}
    out: dict[CoverageKey, Coverage] = {}
    for i in range(table.num_rows):
        if cols["kind"][i] == "license_drop":
            continue
        scope = cols["scope"][i]
        if scope.startswith(AUDIT_SCOPE_PREFIX):
            continue
        start, end = cols["range_start"][i], cols["range_end"][i]
        if start is None or end is None:
            continue
        key = coverage_key(
            cols["source"][i],
            cols["asset_class"][i],
            cols["datatype"][i],
            cols["freq"][i],
            scope,
        )
        prev = out.get(key)
        if prev is None:
            out[key] = Coverage(key=key, start=start, end=end, batches=1)
        else:
            out[key] = Coverage(
                key=key,
                start=min(prev.start, start),
                end=max(prev.end, end),
                batches=prev.batches + 1,
            )
    return out


def watermark(root: str | os.PathLike[str], spec: IngestSpec, source: str) -> dt.datetime | None:
    """这条序列已提交数据的最后一个时间戳；从未取过则 `None`。"""
    cov = committed_coverage(root).get(spec_key(spec, source))
    return cov.end if cov is not None else None


def next_window(
    spec: IngestSpec, mark: dt.datetime | None, pending_since: Sequence[dt.date] = ()
) -> IngestSpec | None:
    """把请求区间改成「水位线之后」的那一段；已无新区间则 `None`。

    有水位线时起点**只**看水位线（`--start` 不参与）：恢复窗口从水位线延伸到 `--end`，
    停机多久就补多久，不会被一个「昨天」式的 `--start` 截成一天（QNT-45 R3）。

    起点取**水位线当日的次日**：日线级别摄取只跑已收盘的完整日（CLI 的 `--end` 默认为
    UTC 昨日），所以水位线当天一定是取全了的，次日起才是新的。若改成「从头再取一遍」，
    每天都会把全部历史重下一遍——既是对上游的滥用，也让「今天新增了多少行」这个报告
    数字永远等于全量（QNT-45 变异点 b）。

    `pending_since` 是运行记录里这条序列的全部 pending 起点（R7）。落在水位线当日或之前的
    已消化；其余最早的一个参与起点：`min(水位线次日, 未消化的 pending 起点)`。
    """
    mark_day = mark.astimezone(dt.UTC).date() if mark is not None else None
    starts = [d for d in pending_since if mark_day is None or d > mark_day]
    if mark_day is not None:
        starts.append(mark_day + dt.timedelta(days=1))
    if not starts:
        return spec
    start = min(starts)
    if start > spec.end:
        return None
    return spec.with_window(start, spec.end)


def plan_incremental(
    root: str | os.PathLike[str],
    spec: IngestSpec,
    source: str,
    pending_index: Mapping[CoverageKey, Sequence[dt.date]] | None = None,
) -> IngestSpec | None:
    """`--since-last` 的完整推算：读水位线与 pending 起点 → 收窄区间。`None` = 空增量。

    `pending_index` 是 `runlog.read_pending_since(root)` 的结果；一次运行读一遍传进来，
    不必每条序列都把全部运行记录重扫一遍。不传则现读。
    """
    if pending_index is None:
        pending_index = read_pending_since(root)
    pending = pending_index.get(spec_key(spec, source), ())
    return next_window(spec, watermark(root, spec, source), pending)


def describe_increment(spec: IngestSpec, narrowed: IngestSpec | None) -> str:
    """一行人类可读的推算说明——直接进运行日志与报告，便于运维复核。"""
    if narrowed is None:
        return f"{spec.describe()} → 空增量（水位线已覆盖请求区间）"
    if narrowed is spec:
        return f"{spec.describe()} → 首次全量（无水位线、无 pending 起点）"
    text = f"{spec.describe()} → 增量 {narrowed.start.isoformat()}..{narrowed.end.isoformat()}"
    note = start_ignored_note(spec, narrowed)
    return f"{text}（{note}）" if note else text


def start_ignored_note(spec: IngestSpec, narrowed: IngestSpec | None) -> str | None:
    """有水位线时 `--start` 不生效；两者不一致就留一句话，进运行记录（R3）。"""
    if narrowed is None or narrowed is spec or narrowed.start == spec.start:
        return None
    return (
        f"--start {spec.start.isoformat()} 被忽略：已有水位线或未消化的 pending 起点，"
        f"从 {narrowed.start.isoformat()} 续取"
    )
