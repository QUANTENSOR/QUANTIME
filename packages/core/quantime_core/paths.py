"""Parquet 湖目录规范（ADR-0003 §4.1，承接 ADR-0002 D2.6/D2.7）。

枚举取值与目录形态原文照 ADR-0003 §4.1：

    data/
      raw/<source>/<batch_id>/...
      lake/<market>/<asset_class>/<datatype>/<freq>/<symbol_or_universe>/
           source=<source>/batch=<batch_id>/part-0000.parquet
      meta/<table>/source=<source>/batch=<batch_id>/part-0000.parquet
      meta/ingestion_batch/batch=<batch_id>/part-0000.parquet
      runs/<run_id>/{manifest.json, results/*.parquet}

周期命名统一用 Vision 文件名口径 `1mo`，不用 REST 的 `1M`（§4.1）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from .ids import assert_valid_id


class Market(StrEnum):
    CRYPTO = "crypto"
    US = "us"
    CN = "cn"
    HK = "hk"


class AssetClass(StrEnum):
    SPOT = "spot"
    PERP = "perp"
    DELIVERY = "delivery"
    EQUITY = "equity"
    ETF = "etf"
    OPTION = "option"
    FUTURE = "future"
    FUND = "fund"


class DataType(StrEnum):
    KLINE = "kline"
    TRADE = "trade"
    AGG_TRADE = "agg_trade"
    FUNDING = "funding"
    OPEN_INTEREST = "open_interest"
    MARK_PRICE = "mark_price"
    BOOK_DEPTH = "book_depth"
    NAV = "nav"
    DIVIDEND = "dividend"
    CORP_ACTION = "corp_action"


class Freq(StrEnum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1w"
    MO1 = "1mo"
    TICK = "tick"
    EVENT = "event"


class MetaTable(StrEnum):
    """`data/meta/` 下的表（§4.1）。`INGESTION_BATCH` 是唯一无 `source=` 分区的表。"""

    TRADING_CALENDAR = "trading_calendar"
    INSTRUMENT_META = "instrument_meta"
    ADJUST_FACTOR = "adjust_factor"
    SOURCE_CONFLICT = "source_conflict"
    INGESTION_BATCH = "ingestion_batch"


#: ADR-0002 D2.2 + ADR-0003 §4.1「每个 Parquet 行必带」的 provenance 列。
PROVENANCE_COLUMNS: tuple[str, ...] = (
    "source",
    "source_version",
    "ingested_at",
    "run_id",
    "batch_id",
)

#: `ingestion_batch.kind` 取值（ADR-0003 §4.3）。
BATCH_KINDS: frozenset[str] = frozenset({"ingest", "rerun", "license_drop"})

_SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
_SCOPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class PathSpecError(ValueError):
    """路径分量不合规范。"""


def assert_source(source: str) -> str:
    """`source` 必须是小写 snake 标识符（它是目录分量，不能含 `/` 或 `=`）。"""
    if not _SOURCE_RE.match(source):
        raise PathSpecError(f"source 不合规范（小写 snake）: {source!r}")
    return source


def assert_scope(scope: str) -> str:
    """`symbol_or_universe` 分量校验。"""
    if not _SCOPE_RE.match(scope):
        raise PathSpecError(f"symbol_or_universe 不合规范: {scope!r}")
    return scope


def assert_batch_kind(kind: str) -> str:
    if kind not in BATCH_KINDS:
        raise PathSpecError(f"kind 必须 ∈ {sorted(BATCH_KINDS)}，得到 {kind!r}")
    return kind


@dataclass(frozen=True, slots=True)
class LakePath:
    """`data/lake/` 下一个 batch 目录的完整坐标（§4.1）。"""

    market: Market
    asset_class: AssetClass
    datatype: DataType
    freq: Freq
    scope: str
    source: str
    batch_id: str

    def __post_init__(self) -> None:
        assert_scope(self.scope)
        assert_source(self.source)
        assert_valid_id(self.batch_id, field="batch_id")

    @property
    def dataset_dir(self) -> PurePosixPath:
        """不含 `source=`/`batch=` 的数据集目录。"""
        return PurePosixPath(
            "data",
            "lake",
            str(self.market),
            str(self.asset_class),
            str(self.datatype),
            str(self.freq),
            self.scope,
        )

    @property
    def batch_dir(self) -> PurePosixPath:
        """本 batch 的目录——R1/R3/R4 的校验单位（§4.2「校验单位是 …batch 目录」）。"""
        return self.dataset_dir / f"source={self.source}" / f"batch={self.batch_id}"

    def part(self, index: int = 0) -> PurePosixPath:
        return self.batch_dir / f"part-{index:04d}.parquet"


def lake_batch_dir(
    market: Market | str,
    asset_class: AssetClass | str,
    datatype: DataType | str,
    freq: Freq | str,
    scope: str,
    source: str,
    batch_id: str,
) -> PurePosixPath:
    """构造 `data/lake/.../source=<s>/batch=<b>` 目录路径（分量经枚举校验）。"""
    return LakePath(
        market=Market(market),
        asset_class=AssetClass(asset_class),
        datatype=DataType(datatype),
        freq=Freq(freq),
        scope=scope,
        source=source,
        batch_id=batch_id,
    ).batch_dir


def parse_lake_batch_dir(path: str | PurePosixPath) -> LakePath:
    """解析 `lake_batch_dir` 产出的路径；不合规范抛 `PathSpecError`。

    接受绝对路径或相对路径，只要其尾部与 `data/lake/...` 形态匹配。
    """
    parts = PurePosixPath(path).parts
    try:
        idx = len(parts) - 1 - list(reversed(parts)).index("lake")
    except ValueError:
        raise PathSpecError(f"路径不含 lake 分量: {path!r}") from None
    if idx == 0 or parts[idx - 1] != "data":
        raise PathSpecError(f"lake 之前必须是 data 分量: {path!r}") from None
    tail = parts[idx + 1 :]
    if len(tail) != 7:
        raise PathSpecError(f"lake 路径应有 7 个分量，得到 {len(tail)}: {path!r}")
    market, asset_class, datatype, freq, scope, source_part, batch_part = tail
    if not source_part.startswith("source=") or not batch_part.startswith("batch="):
        raise PathSpecError(f"缺少 source=/batch= 分区分量: {path!r}")
    try:
        return LakePath(
            market=Market(market),
            asset_class=AssetClass(asset_class),
            datatype=DataType(datatype),
            freq=Freq(freq),
            scope=scope,
            source=source_part.removeprefix("source="),
            batch_id=batch_part.removeprefix("batch="),
        )
    except ValueError as exc:
        raise PathSpecError(f"路径分量取值非法: {path!r} ({exc})") from exc


def source_of_batch_dir(path: str | PurePosixPath) -> str:
    """取一个 batch 目录的 `source=` 分量——单源不变量断言的右值（§4.1）。"""
    for part in reversed(PurePosixPath(path).parts):
        if part.startswith("source="):
            return part.removeprefix("source=")
    raise PathSpecError(f"路径不含 source= 分量: {path!r}")


def meta_batch_dir(
    table: MetaTable | str, batch_id: str, source: str | None = None
) -> PurePosixPath:
    """`data/meta/<table>/...` 目录。

    `ingestion_batch` 是唯一无 `source=` 分区的表（§4.1：「它本身是 source→文件清单」），
    传 `source` 视为错误；其余 meta 表必须带 `source`。
    """
    table = MetaTable(table)
    assert_valid_id(batch_id, field="batch_id")
    base = PurePosixPath("data", "meta", str(table))
    if table is MetaTable.INGESTION_BATCH:
        if source is not None:
            raise PathSpecError("ingestion_batch 无 source= 分区（§4.1）")
        return base / f"batch={batch_id}"
    if source is None:
        raise PathSpecError(f"meta 表 {table} 必须带 source= 分区")
    return base / f"source={assert_source(source)}" / f"batch={batch_id}"


def raw_batch_dir(source: str, batch_id: str) -> PurePosixPath:
    """`data/raw/<source>/<batch_id>/`——天然单源（§4.1）。"""
    return PurePosixPath(
        "data", "raw", assert_source(source), assert_valid_id(batch_id, field="batch_id")
    )


def staging_dir() -> PurePosixPath:
    """`data/_staging/`：临时名所在，位于最终目录之外（§4.3）。"""
    return PurePosixPath("data", "_staging")


def run_dir(run_id: str) -> PurePosixPath:
    return PurePosixPath("data", "runs", assert_valid_id(run_id, field="run_id"))


def run_manifest_path(run_id: str) -> PurePosixPath:
    return run_dir(run_id) / "manifest.json"


def run_results_dir(run_id: str) -> PurePosixPath:
    return run_dir(run_id) / "results"
