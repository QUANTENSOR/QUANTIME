"""缺口 / 重复核查（QNT-28）——**只产出报告，不改数据**。

本模块对已提交的 batch **读一遍**，报告两件事：

- **缺口**：相邻时间戳之差 > 期望步长（K 线 `1h`/`4h`/`1d`、OI metrics 5m）。
  funding 不做等距检查——`funding_interval_hours` 由上游逐行给出，标称 8h 但历史上变过。
- **重复**：同一自然键（`(symbol, <时间列>)`）在同一 batch 内出现多次。

与 `checks.py` 的分工：`checks.py` 复核**不变量**（违反即抛错），本模块统计**数据质量**
（缺口是上游事实，不是错误，所以如实记账而非报错）。

报告本身是一张 Arrow 表，经 `batches.commit_batch` 走同一条发布路径落进湖里
（`datatype` 沿用被核查数据的 datatype，`scope` 标 `audit__<scope>`），
因此报告也有 `ingestion_batch` 行、也可重放。**不写回、不修正任何被核查的数据**。
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
from quantime_core import parquet_io

#: 报告表 schema。一行 = 一个发现（`kind ∈ {gap, duplicate}`）或一行汇总（`kind='summary'`）。
AUDIT_SCHEMA = pa.schema(
    [
        pa.field("kind", pa.string(), nullable=False),
        pa.field("scope", pa.string(), nullable=False),
        pa.field("datatype", pa.string(), nullable=False),
        pa.field("freq", pa.string(), nullable=False),
        pa.field("audited_batch_id", pa.string(), nullable=False),
        pa.field("gap_start", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("gap_end", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("missing_steps", pa.int64(), nullable=True),
        pa.field("duplicate_key", pa.string(), nullable=True),
        pa.field("occurrences", pa.int64(), nullable=True),
        pa.field("rows_audited", pa.int64(), nullable=False),
        pa.field("note", pa.string(), nullable=True),
    ]
)

#: 报告在湖里的 scope 前缀——与被核查的数据 scope 区分开，避免读侧混读。
AUDIT_SCOPE_PREFIX = "audit__"


@dataclass(frozen=True, slots=True)
class Gap:
    start: dt.datetime
    end: dt.datetime
    missing_steps: int


@dataclass(frozen=True, slots=True)
class Duplicate:
    key: str
    occurrences: int


@dataclass(frozen=True, slots=True)
class AuditResult:
    """一个 batch 的核查结论。`note` 记录窗口/覆盖等如实说明。"""

    scope: str
    datatype: str
    freq: str
    audited_batch_id: str
    rows_audited: int
    gaps: tuple[Gap, ...]
    duplicates: tuple[Duplicate, ...]
    note: str = ""

    @property
    def clean(self) -> bool:
        return not self.gaps and not self.duplicates


def find_gaps(timestamps: Sequence[dt.datetime], step: dt.timedelta) -> tuple[Gap, ...]:
    """相邻时间戳之差 > `step` 即一个缺口。输入须已排序；重复值不算缺口。

    `missing_steps` = 该空洞里缺掉的完整步数。差值不是 `step` 整数倍时向下取整，
    并且只要 > 0 就记账——宁可报一个形状怪的缺口，也不静默吞掉。
    """
    if step <= dt.timedelta(0):
        raise ValueError("step 必须为正")
    gaps: list[Gap] = []
    for prev, cur in zip(timestamps, timestamps[1:], strict=False):
        delta = cur - prev
        if delta > step:
            missing = int(delta / step) - 1
            gaps.append(Gap(start=prev, end=cur, missing_steps=max(missing, 1)))
    return tuple(gaps)


def find_duplicates(keys: Sequence[str]) -> tuple[Duplicate, ...]:
    """同一自然键出现多次即一条重复记录（按键排序，结果确定）。"""
    counts: dict[str, int] = {}
    for k in keys:
        counts[k] = counts.get(k, 0) + 1
    return tuple(Duplicate(key=k, occurrences=n) for k, n in sorted(counts.items()) if n > 1)


def audit_table(
    table: pa.Table,
    *,
    scope: str,
    datatype: str,
    freq: str,
    audited_batch_id: str,
    time_column: str,
    step: dt.timedelta | None,
    key_columns: tuple[str, ...],
    note: str = "",
) -> AuditResult:
    """核查一张已落盘的表。`step=None` 表示不做等距检查（如 funding）。"""
    for column in (time_column, *key_columns):
        if column not in table.column_names:
            raise KeyError(f"表缺少核查所需的列 {column!r}")
    times: list[dt.datetime] = table.column(time_column).to_pylist()
    order = sorted(range(len(times)), key=lambda i: times[i])
    sorted_times = [times[i] for i in order]

    columns = [table.column(c).to_pylist() for c in key_columns]
    keys = ["|".join(str(col[i]) for col in columns) for i in order]

    return AuditResult(
        scope=scope,
        datatype=datatype,
        freq=freq,
        audited_batch_id=audited_batch_id,
        rows_audited=table.num_rows,
        gaps=find_gaps(sorted_times, step) if step is not None else (),
        duplicates=find_duplicates(keys),
        note=note,
    )


def audit_batch_file(
    path: str | os.PathLike[str],
    *,
    scope: str,
    datatype: str,
    freq: str,
    audited_batch_id: str,
    time_column: str,
    step: dt.timedelta | None,
    key_columns: tuple[str, ...],
    note: str = "",
) -> AuditResult:
    """读一个已提交的 Parquet 分片并核查它。**只读**。"""
    return audit_table(
        parquet_io.read_table(Path(path)),
        scope=scope,
        datatype=datatype,
        freq=freq,
        audited_batch_id=audited_batch_id,
        time_column=time_column,
        step=step,
        key_columns=key_columns,
        note=note,
    )


def report_table(results: Sequence[AuditResult]) -> pa.Table:
    """把若干 `AuditResult` 拼成报告表（每个 result 至少一行 `summary`）。

    行序固定为「按 result 顺序，summary → gaps → duplicates」，
    使同样的输入产出逐字节相同的 Parquet（ADR-0003 §4.2 R2）。
    """
    rows: list[dict[str, object]] = []
    for r in results:
        common = {
            "scope": r.scope,
            "datatype": r.datatype,
            "freq": r.freq,
            "audited_batch_id": r.audited_batch_id,
            "rows_audited": r.rows_audited,
        }
        rows.append(
            {
                **common,
                "kind": "summary",
                "gap_start": None,
                "gap_end": None,
                "missing_steps": len(r.gaps),
                "duplicate_key": None,
                "occurrences": len(r.duplicates),
                "note": r.note or None,
            }
        )
        for g in r.gaps:
            rows.append(
                {
                    **common,
                    "kind": "gap",
                    "gap_start": g.start,
                    "gap_end": g.end,
                    "missing_steps": g.missing_steps,
                    "duplicate_key": None,
                    "occurrences": None,
                    "note": None,
                }
            )
        for d in r.duplicates:
            rows.append(
                {
                    **common,
                    "kind": "duplicate",
                    "gap_start": None,
                    "gap_end": None,
                    "missing_steps": None,
                    "duplicate_key": d.key,
                    "occurrences": d.occurrences,
                    "note": None,
                }
            )
    return pa.Table.from_pylist(rows, schema=AUDIT_SCHEMA)
