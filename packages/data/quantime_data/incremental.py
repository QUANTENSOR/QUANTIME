"""增量摄取（QNT-45 第 1 项）——**源无关**的水位线推算。

「上次取到哪了」的答案只有一个出处：已提交的 `ingestion_batch` 行。不读目录、不读状态
文件、不信任何一份 CLI 之外的记账——湖里已提交的区间就是事实，其余都是它的影子。
键是 `(source, symbol, datatype, freq)`，与 ADR-0003 §4.1 的 lake 路径分量一一对应。

推算只有三个结果：

* 从未取过 → 请求区间原样（首次全量；`--start` 只在这时生效）；
* 有水位线 → **水位线次日**起到请求区间末（只取新的那一段）。起点**不再**被 `--start`
  截住：水位线落在 `--start` 之前（机器停了几天、timer 的 `Persistent=true` 只补跑一次）
  时，截住就等于把停机那几天永久跳过（QNT-45 R3）。`--start` 被忽略这件事会写进运行记录；
* 水位线已覆盖请求区间 → `None`，即空增量。空增量**不写 batch**（ADR-0002 不写空批次），
  但仍写一条运行记录（`runlog`），否则「今天跑过且没有新数据」与「今天根本没跑」
  在事后无法区分。

本模块不出网、不落盘，只读 `ingestion_batch`。
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass

from .audit import AUDIT_SCOPE_PREFIX
from .batches import read_ingestion_batch
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


def next_window(spec: IngestSpec, mark: dt.datetime | None) -> IngestSpec | None:
    """把请求区间改成「水位线之后」的那一段；已无新区间则 `None`。

    有水位线时起点**只**看水位线（`--start` 不参与）：恢复窗口从水位线延伸到 `--end`，
    停机多久就补多久，不会被一个「昨天」式的 `--start` 截成一天（QNT-45 R3）。

    起点取**水位线当日的次日**：日线级别摄取只跑已收盘的完整日（CLI 的 `--end` 默认为
    UTC 昨日），所以水位线当天一定是取全了的，次日起才是新的。若改成「从头再取一遍」，
    每天都会把全部历史重下一遍——既是对上游的滥用，也让「今天新增了多少行」这个报告
    数字永远等于全量（QNT-45 变异点 b）。
    """
    if mark is None:
        return spec
    start = mark.astimezone(dt.UTC).date() + dt.timedelta(days=1)
    if start > spec.end:
        return None
    return spec.with_window(start, spec.end)


def plan_incremental(
    root: str | os.PathLike[str], spec: IngestSpec, source: str
) -> IngestSpec | None:
    """`--since-last` 的完整推算：读水位线 → 收窄区间。`None` = 空增量。"""
    return next_window(spec, watermark(root, spec, source))


def describe_increment(spec: IngestSpec, narrowed: IngestSpec | None) -> str:
    """一行人类可读的推算说明——直接进运行日志与报告，便于运维复核。"""
    if narrowed is None:
        return f"{spec.describe()} → 空增量（水位线已覆盖请求区间）"
    if narrowed is spec:
        return f"{spec.describe()} → 首次全量（无水位线）"
    text = f"{spec.describe()} → 增量 {narrowed.start.isoformat()}..{narrowed.end.isoformat()}"
    note = start_ignored_note(spec, narrowed)
    return f"{text}（{note}）" if note else text


def start_ignored_note(spec: IngestSpec, narrowed: IngestSpec | None) -> str | None:
    """有水位线时 `--start` 不生效；两者不一致就留一句话，进运行记录（R3）。"""
    if narrowed is None or narrowed is spec or narrowed.start == spec.start:
        return None
    return (
        f"--start {spec.start.isoformat()} 被忽略：已有水位线，"
        f"从水位线次日 {narrowed.start.isoformat()} 续取"
    )
