"""`run_id` / `batch_id` 生成与校验（ADR-0003 §3.2 `core/ids.py`）。

`batch_id` 用 ULID：字典序单调（ADR-0002 D2.7「batch_id 单调」），且天然可作目录名。
单调只保证「分配顺序」，不保证「提交顺序」——提交语义由 `ingestion_batch` 行的存在与否
决定（ADR-0003 §4.3「未出现在 ingestion_batch 的文件视为不存在」）。
"""

from __future__ import annotations

import re

from ulid import ULID

_ULID_RE = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")


class InvalidIdError(ValueError):
    """id 不是合法 ULID。"""


def new_batch_id() -> str:
    """分配一个新的 `batch_id`（ULID，26 字符 Crockford base32）。"""
    return str(ULID())


def new_run_id() -> str:
    """分配一个新的 `run_id`（ULID）。"""
    return str(ULID())


def is_valid_id(value: str) -> bool:
    """`value` 是否为合法 ULID 字面量。"""
    return bool(_ULID_RE.match(value))


def assert_valid_id(value: str, *, field: str = "id") -> str:
    """校验并回传 `value`；非法时抛 `InvalidIdError`。"""
    if not is_valid_id(value):
        raise InvalidIdError(f"{field} 不是合法 ULID: {value!r}")
    return value
