"""磁盘守卫（QNT-45 R8/R9）——**全部写入口共用的唯一一处**。

数据根所在文件系统剩余不足阈值就不开新 batch。它只在 `ingest.ingest_one` 的开头被调用
（取任何字节、登记任何 batch_id 之前），`daily` / `backfill` / `ingest` / `ingest --rerun-of`
四条路径都经过那里，入口自己不再各带一份判断：入口只负责把 `DiskLowError` 记成
`abort_reason=disk_low`。
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path

from .runlog import ABORT_DISK_LOW

#: 默认阈值：剩余不足 5 GB 就不开新 batch（owner 裁决 2026-09-23）。`None` = 关闭守卫。
DEFAULT_MIN_FREE_BYTES = 5 * 1024**3


class ThresholdError(ValueError):
    """阈值配置错误（负数 / NaN / ±inf / 非数字）：进程拒绝启动，而不是当成「关闭守卫」。"""


def parse_min_free_gb(text: str) -> int | None:
    """阈值解析（R10）——`--min-free-gb` 与 `$QUANTIME_MIN_FREE_GB` 共用的**唯一实现**。

    有限非负数才合法：`0` → `None`（关闭守卫）；正数 → 阈值字节数。
    负数、NaN、±inf、非数字 → `ThresholdError`。此前 `value > 0 else None` 会把这些
    全部静默当成「关闭」，一个写错的配置就能让守卫失效。
    """
    try:
        value = float(text.strip())
    except ValueError:
        raise ThresholdError(f"不是数字: {text!r}（要有限非负数，GB；0 关闭守卫）") from None
    if not math.isfinite(value) or value < 0:
        raise ThresholdError(f"非法阈值: {text!r}（要有限非负数，GB；0 关闭守卫）")
    return int(value * 1024**3) if value > 0 else None


class DiskLowError(Exception):
    """剩余空间不足，拒绝开始新 batch。

    故意**不是** `IngestError` / `OSError` 的子类：前者会被入口当成普通的单序列失败吞掉，
    后者会被退避重试当成瞬时网络故障重试。
    """

    def __init__(self, free: int, threshold: int) -> None:
        self.free = free
        self.threshold = threshold
        self.detail = (
            f"数据根所在文件系统剩余 {free / 1024**3:.2f} GB"
            f" < 阈值 {threshold / 1024**3:.2f} GB，拒绝开始新 batch"
        )
        super().__init__(f"{ABORT_DISK_LOW}: {self.detail}")


def free_bytes(root: Path) -> int:
    """数据根所在文件系统的剩余字节。`data/` 可能是指向别的盘的软链接，所以量它而不是量 root。"""
    target = root / "data"
    return shutil.disk_usage(target if target.exists() else root).free


def check_disk(root: Path, min_free_bytes: int | None) -> None:
    """够用或守卫关闭（`None`）→ 什么都不做；不足 → `DiskLowError`。"""
    if min_free_bytes is None:
        return
    free = free_bytes(root)
    if free < min_free_bytes:
        raise DiskLowError(free, min_free_bytes)
