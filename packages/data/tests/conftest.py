from __future__ import annotations

import collections
import datetime as dt

import pyarrow as pa
import pytest
from quantime_core.ids import new_batch_id, new_run_id
from quantime_data import batches, diskguard

shutil_usage = collections.namedtuple("shutil_usage", "total used free")

KLINE_SCHEMA = pa.schema(
    [
        pa.field("symbol", pa.string()),
        pa.field("ts", pa.timestamp("us", tz="UTC")),
        pa.field("close", pa.float64()),
        pa.field("source", pa.string()),
        pa.field("source_version", pa.string()),
        pa.field("ingested_at", pa.timestamp("us", tz="UTC")),
        pa.field("run_id", pa.string()),
        pa.field("batch_id", pa.string()),
    ]
)

#: 所有数据层测试共用的 lake 坐标。
LAKE_KW = {
    "market": "crypto",
    "asset_class": "spot",
    "datatype": "kline",
    "freq": "1d",
    "scope": "BTCUSDT",
}


def build_table(
    *,
    source: str,
    batch_id: str,
    run_id: str,
    source_version: str = "v1",
    n: int = 3,
    price0: float = 100.0,
    row_sources: list[str] | None = None,
    drop_columns: tuple[str, ...] = (),
) -> pa.Table:
    """构造一张带 ADR-0002 五列的归一化表。"""
    base = dt.datetime(2021, 1, 4, tzinfo=dt.UTC)
    ingested = dt.datetime(2026, 9, 21, tzinfo=dt.UTC)
    table = pa.Table.from_pydict(
        {
            "symbol": ["BTCUSDT"] * n,
            "ts": [base + dt.timedelta(days=i) for i in range(n)],
            "close": [price0 + i for i in range(n)],
            "source": row_sources if row_sources is not None else [source] * n,
            "source_version": [source_version] * n,
            "ingested_at": [ingested] * n,
            "run_id": [run_id] * n,
            "batch_id": [batch_id] * n,
        },
        schema=KLINE_SCHEMA,
    )
    if drop_columns:
        table = table.select([c for c in table.column_names if c not in drop_columns])
    return table


@pytest.fixture
def lake_kw() -> dict[str, str]:
    return dict(LAKE_KW)


@pytest.fixture
def make_table():
    return build_table


@pytest.fixture
def root(tmp_path):
    return tmp_path


@pytest.fixture(autouse=True)
def _plenty_of_disk(monkeypatch):
    """磁盘守卫默认开（5 GB）：测试不依赖 CI 主机的真实剩余空间。

    需要「磁盘不足」的测试用 `test_run_guards.disk` 覆盖这一桩。
    """
    monkeypatch.setattr(
        diskguard.shutil,
        "disk_usage",
        lambda path: shutil_usage(total=1 << 50, used=0, free=1 << 50),
    )


@pytest.fixture
def run_id():
    return new_run_id()


@pytest.fixture
def commit(root, run_id):
    """提交一个 batch，回传 CommittedBatch。"""

    def _commit(*, source="synthetic_bench", batch_id=None, price0=100.0, **kw):
        bid = batch_id or new_batch_id()
        table = build_table(source=source, batch_id=bid, run_id=run_id, price0=price0)
        return batches.commit_batch(
            root,
            table,
            source=source,
            source_version="v1",
            run_id=run_id,
            batch_id=bid,
            **LAKE_KW,
            **kw,
        )

    return _commit
