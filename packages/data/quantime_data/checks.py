"""摄取后核查（ADR-0003 §4.1「`checks.py` 抽样复核」）。

写入侧断言在 `batches.py`（拒绝非法写入）；本模块是**事后**复核，对已落盘的 batch
目录重新核对单源不变量与 provenance 列，供摄取任务收尾与运维排查调用。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from quantime_core import parquet_io
from quantime_core.paths import PROVENANCE_COLUMNS, source_of_batch_dir


class CheckError(RuntimeError):
    """复核发现落盘数据违反不变量。"""


@dataclass(frozen=True, slots=True)
class CheckReport:
    batch_dir: str
    files_checked: int
    rows_checked: int


def check_batch_dir(root: str | os.PathLike[str], batch_dir: str | os.PathLike[str]) -> CheckReport:
    """复核一个 batch 目录：每个 Parquet 的 `source` 列必须等于路径 `source=` 分量，
    且 ADR-0002 五列齐备。"""
    root = Path(root)
    rel = Path(batch_dir)
    directory = rel if rel.is_absolute() else root / rel
    if not directory.is_dir():
        raise CheckError(f"batch 目录不存在: {directory}")
    expected_source = source_of_batch_dir(directory.as_posix())

    files = sorted(p for p in directory.rglob("*.parquet"))
    if not files:
        raise CheckError(f"batch 目录内无 Parquet 文件: {directory}")
    rows = 0
    for f in files:
        table = parquet_io.read_table(f)
        missing = [c for c in PROVENANCE_COLUMNS if c not in table.column_names]
        if missing:
            raise CheckError(f"{f} 缺少 ADR-0002 provenance 列: {missing}")
        distinct = set(table.column("source").to_pylist())
        if distinct != {expected_source}:
            raise CheckError(
                f"{f} 违反单源不变量：行 source={sorted(distinct)}，路径 source={expected_source!r}"
            )
        rows += table.num_rows
    return CheckReport(
        batch_dir=directory.relative_to(root).as_posix()
        if not rel.is_absolute()
        else str(directory),
        files_checked=len(files),
        rows_checked=rows,
    )
