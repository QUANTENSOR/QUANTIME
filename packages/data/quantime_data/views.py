"""DuckDB 视图层（ADR-0003 §4.2）。

`data/quantime.duckdb` 只存**视图定义与宏**，不存业务行——丢掉该文件不丢数据，
视图可从本模块幂等重建。读取一律用显式文件列表 `read_parquet([...])`，不用 glob，
保证清单外文件在读取层物理不可达（§4.2 R1）。
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path

import duckdb

from .batches import committed_batch_files

DB_RELPATH = "data/quantime.duckdb"

#: 幂等注册的宏。带参数的表宏——文件列表在调用点绑定，避免把 glob 或某次运行的
#: 具体路径固化进 DB 文件（§4.2「读取用显式文件列表不用 glob」）。
_DDL: tuple[str, ...] = (
    """
    CREATE OR REPLACE MACRO committed_batch_rows(batch_files) AS TABLE
        SELECT * FROM read_parquet(batch_files) WHERE kind <> 'license_drop'
    """,
    """
    CREATE OR REPLACE MACRO committed_rows(data_files, batch_files) AS TABLE
        SELECT d.* FROM read_parquet(data_files) d
        SEMI JOIN (SELECT batch_id FROM committed_batch_rows(batch_files)) c
               ON c.batch_id = d.batch_id
    """,
)

#: 注册后应存在的对象名（`register_views` 的回传与断言口径）。
REGISTERED_MACROS: tuple[str, ...] = ("committed_batch_rows", "committed_rows")


def db_path(root: str | os.PathLike[str]) -> Path:
    return Path(root) / DB_RELPATH


@contextmanager
def connect(root: str | os.PathLike[str], *, read_only: bool = False):
    """打开 `data/quantime.duckdb`（每次新建连接，无对象缓存，§5.1 测量协议）。"""
    path = db_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path), read_only=read_only)
    try:
        yield con
    finally:
        con.close()


def register_views(root: str | os.PathLike[str]) -> list[str]:
    """幂等注册视图与宏；回传已注册的对象名。重复调用结果相同。"""
    with connect(root) as con:
        for ddl in _DDL:
            con.execute(ddl)
        rows = con.execute(
            "SELECT DISTINCT function_name FROM duckdb_functions() WHERE function_name IN "
            "('committed_batch_rows', 'committed_rows')"
        ).fetchall()
    return sorted(row[0] for row in rows)


def ingestion_batch_files(root: str | os.PathLike[str]) -> list[str]:
    """`ingestion_batch` 的显式文件列表（已提交的 batch 目录逐个枚举）。"""
    return [str(p) for p in committed_batch_files(root)]


def query_committed(root: str | os.PathLike[str], data_files: Sequence[str]) -> list[tuple]:
    """只返回属于已提交 batch 的行——未登记文件的行在此被过滤掉（§4.3）。"""
    batch_files = ingestion_batch_files(root)
    if not batch_files or not data_files:
        return []
    register_views(root)
    with connect(root) as con:
        return con.execute(
            "SELECT * FROM committed_rows(?::VARCHAR[], ?::VARCHAR[]) ORDER BY batch_id",
            [list(data_files), list(batch_files)],
        ).fetchall()


def query_latest_per_source(
    root: str | os.PathLike[str],
    data_files: Sequence[str],
    keys: Sequence[str],
) -> list[tuple]:
    """按 `(natural key, source)` 取最大 `batch_id`（§4.1「当前视图」）。

    只 join 已提交 batch：`data_files` 里若含未登记 batch 的文件，其行因 join 不到
    `ingestion_batch` 而不会出现在结果中。
    """
    batch_files = ingestion_batch_files(root)
    if not batch_files or not data_files:
        return []
    for k in keys:
        if not k.isidentifier():
            raise ValueError(f"natural key 列名不合法: {k!r}")
    register_views(root)
    key_cols = ", ".join(f'"{k}"' for k in keys)
    sql = f"""
        SELECT * EXCLUDE (_rn) FROM (
            SELECT *, row_number() OVER (
                PARTITION BY {key_cols}, source ORDER BY batch_id DESC
            ) AS _rn
            FROM committed_rows(?::VARCHAR[], ?::VARCHAR[])
        ) WHERE _rn = 1
        ORDER BY {key_cols}, source
    """
    with connect(root) as con:
        return con.execute(sql, [list(data_files), list(batch_files)]).fetchall()
