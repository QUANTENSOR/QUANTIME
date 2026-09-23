"""摄取请求的**源无关**描述（QNT-45）。

`IngestSpec` 原本长在 `ingest.py` 里，和 Binance 的 URL 拼装挤在一起。QNT-47（Massive
美股+期权）/ QNT-48（Tushare Pro A 股）要复用同一套增量 / 重试 / 补采 / 核查，所以
「要取哪个序列的哪段区间」必须先独立成一个不认识任何数据源的类型——它是通用层与
adapter 之间传递的唯一请求对象。

本模块**不出网、不落盘、不 import 任何 adapter**：只有纯数据与纯函数。
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import pyarrow as pa
from quantime_core.paths import AssetClass, DataType, Freq

#: 公开源的取字节函数：`url -> bytes`。实现由调用方注入（离线测试传 fixture reader）；
#: 上游没有该文件时抛 `FileNotFoundError`（= 整档缺失，不是错误）。通用层把 fetch 当
#: 不透明句柄透传给 `adapter.fetch_archive`——需凭据的源可以注入别的形状（见 `adapter`）。
Fetcher = Callable[[str], bytes]


class IngestError(RuntimeError):
    """摄取失败（上游缺档、校验不过、区间非法、adapter 不支持该 spec）。"""


@dataclass(frozen=True, slots=True)
class IngestSpec:
    """一次摄取的完整参数——它同时是「同参数重跑」的判定依据。

    字段全部是 `core/paths.py` 的枚举或纯值：spec 里不出现 URL、host、文件名，
    那些是 adapter 的事。`symbol` 对非单标的序列（如整个 universe 的汇总）就是 scope 名。
    """

    datatype: DataType
    asset_class: AssetClass
    symbol: str
    freq: Freq
    start: dt.date
    end: dt.date
    #: 请求日（UTC 日期）——adapter 据此判断「截至今天上游已经发布了哪些归档」
    #: （`list_archives` 只列已发布的；未发布的日子由通用层记成 `pending_upstream`）。
    #: `None` = 历史请求，视全部归档已发布。它描述的是**何时**请求而不是请求**什么**，
    #: 所以不参与相等比较：同一序列同一区间，今天问与明天问是同一个 spec。
    as_of: dt.date | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise IngestError(f"区间非法: {self.start} > {self.end}")

    @property
    def scope(self) -> str:
        return self.symbol

    def describe(self) -> str:
        return (
            f"{self.datatype}/{self.asset_class}/{self.symbol}/{self.freq}"
            f"/{self.start.isoformat()}..{self.end.isoformat()}"
        )

    def with_window(self, start: dt.date, end: dt.date) -> IngestSpec:
        """同一序列、换一段区间——增量推算与补采都靠它，不用手抄六个字段。"""
        return IngestSpec(
            datatype=self.datatype,
            asset_class=self.asset_class,
            symbol=self.symbol,
            freq=self.freq,
            start=start,
            end=end,
            as_of=self.as_of,
        )

    def requested_on(self, as_of: dt.date | None) -> IngestSpec:
        """同一序列同一区间，换一个请求日。"""
        return IngestSpec(
            datatype=self.datatype,
            asset_class=self.asset_class,
            symbol=self.symbol,
            freq=self.freq,
            start=self.start,
            end=self.end,
            as_of=as_of,
        )


@dataclass(frozen=True, slots=True)
class FetchedFile:
    """一个已取回并校验过的上游文件。`filename` 是 adapter 给的稳定标识。"""

    url: str
    filename: str
    payload: bytes


def months_between(start: dt.date, end: dt.date) -> list[str]:
    """`[start, end]` 覆盖到的月份标签（`YYYY-MM`），升序。按月归档的 adapter 用。"""
    out: list[str] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def month_bounds(label: str) -> tuple[dt.date, dt.date]:
    """`YYYY-MM` → 该月的首尾日期（含）。按月归档的 `Archive.covers_*` 用。"""
    year, month = (int(p) for p in label.split("-"))
    first = dt.date(year, month, 1)
    nxt = dt.date(year + 1, 1, 1) if month == 12 else dt.date(year, month + 1, 1)
    return first, nxt - dt.timedelta(days=1)


def first_monday(year: int, month: int) -> dt.date:
    """该月第一个周一。Binance Vision 的月归档在「次月第一个周一」发布（调研 §4.5）。"""
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(7 - first.weekday()) % 7)


def days_between(start: dt.date, end: dt.date) -> Iterator[dt.date]:
    day = start
    while day <= end:
        yield day
        day += dt.timedelta(days=1)


def requested_window(spec: IngestSpec) -> tuple[dt.datetime, dt.datetime]:
    """请求区间的 UTC 半开窗口 `[start 00:00, end+1d 00:00)`。

    `IngestSpec` 的 `start`/`end` 是**含**两端的日期，而上游归档的最小粒度往往是整月或
    整日——取回来的行几乎总是比请求的区间宽。窗口在这里算一次，裁剪与覆盖判定都用它，
    两处不会各算各的。
    """
    start = dt.datetime.combine(spec.start, dt.time.min, tzinfo=dt.UTC)
    end = dt.datetime.combine(spec.end + dt.timedelta(days=1), dt.time.min, tzinfo=dt.UTC)
    return start, end


def clip_to_window(table: pa.Table, time_column: str, spec: IngestSpec) -> pa.Table:
    """只保留落在请求区间内的行（`start <= t < end+1d`，UTC）。

    不裁剪的话，`start=end=2026-08-15` 会提交整个八月 31 行——写进湖的区间与
    `ingestion_batch.range_start/range_end` 声明的区间不符，重放时读到的也不是请求的那段
    （verify-a R1 P2-3）。裁剪发生在盖 provenance **之前**，所以被丢掉的行从未进过 batch。
    """
    if table.num_rows == 0:
        return table
    start, end = requested_window(spec)
    times = table.column(time_column).to_pylist()
    keep = [i for i, t in enumerate(times) if start <= t < end]
    if len(keep) == table.num_rows:
        return table
    return table.take(pa.array(keep, pa.int64()))
