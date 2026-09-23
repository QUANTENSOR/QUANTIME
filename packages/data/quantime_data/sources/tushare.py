"""Tushare Pro 数据源（QNT-48 阶段 1）——A 股日线 + 复权因子 + 每日指标 + 日历 + 股票列表。

**需 token、只读**。形状对齐 `sources/binance_public.py`：本模块只做三件事——
拼请求、校验信封、归一化成 Arrow 表。它自己**不出网**（`data` 由调用方经
`transport.CredentialedTransport` 取来传入），也**不接触 token**（token 由出口持有），
因此归一化逻辑在测试里完全离线可跑，且本文件里不存在任何能打印秘钥的路径。

> QNT-45 的源接口契约尚未合并，本模块先按 `binance_public` 的形状写；契约到位后
> 只需把 `plan_requests` / `normalize_*` 挂进去。**待对齐**。

与 Binance 归档的三点结构性差异
--------------------------------
1. **端点在 body 里**：Tushare 只有一个 URL（POST `https://api.tushare.pro/`），
   `api_name` 决定取什么（https://tushare.pro/document/1?doc_id=130）。所以「端点白名单」
   开在 `transport.TUSHARE_READONLY_API_NAMES` 上，而不是路径上。
2. **列顺序不保证**：响应是 `{"fields": [...], "items": [[...]]}`，`fields` 是运行时给的。
   本模块一律**按名取列**，绝不按下标——上游哪天调换列序，按下标解析会安静地把
   `open` 读成 `high`，那种错误在回测里可能几个月都发现不了。
3. **截断无信号**：单次最多 6000 行（文档 doc_id=27），超出部分**直接少给**，不报错、
   不分页游标。所以本模块按区间切片请求，并在行数触顶时**失败**而不是接受
   （`MAX_ROWS_PER_REQUEST`）。

许可要点（不做文献式核查，owner 2026-09-23 裁决）
-------------------------------------------------
- 数据按积分档开放，机构价为个人价 10 倍；购买后不支持退款。
  条款/积分页：https://tushare.pro/document/1?doc_id=290（访问日期 2026-09-23）
- 该页**未**给出明确的转售/再分发条款。本项目用途为**内部研究**，数据本地落库、
  不对外分发；`data/` 永不入库（AGENTS.md §2）。若后续要超出内部研究用途，
  须先由 owner 与上游确认条款——这属未决事项，不由本卡决定。
- 账号与积分由 owner 持有（卡：不购买、不注册）。
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

import pyarrow as pa
from quantime_core.allowlist import TUSHARE_PRO_API
from quantime_core.paths import AssetClass, DataType, Freq, Market

#: 本源使用的 host —— 从 allowlist **引用**而非复制字面量（`core/allowlist.py` 是唯一出处，
#: 静态守卫据此 grep）。它是 `credentialed_readonly=True` 条目，不是交易 host。
HOSTS: tuple[str, ...] = (TUSHARE_PRO_API.host,)

#: 唯一的请求 URL（端点靠 body 的 `api_name` 区分）。
API_URL = f"https://{TUSHARE_PRO_API.host}/"

#: `source` 列的取值（同时是 `data/raw/<source>/` 与 `source=` 分区的分量）。
SOURCE = "tushare_pro"

#: `source_version`：上游没有版本号，用「HTTP 协议 + 字段口径版本」固定字面量标注本适配器。
SOURCE_VERSION = "tushare-pro-http-v1"

#: 本源覆盖的市场/资产类别（A 股股票）。
MARKET = Market.CN
ASSET_CLASS = AssetClass.EQUITY

#: 日线——本卡只做日线级别（卡标题）。
FREQ = Freq.D1

#: 单次请求最多 6000 行（https://tushare.pro/document/2?doc_id=27）。
#: 上游截断**无任何信号**，所以触顶即判失败，见 `assert_not_truncated`。
MAX_ROWS_PER_REQUEST = 6000

#: 每个请求覆盖的最大自然日跨度。A 股约 243 个交易日/年（≈0.67 自然日占比），
#: 3650 天 ≈ 2430 行，离 6000 有两倍余量；`trade_cal` 按自然日计 3650 行，同样安全。
MAX_DAYS_PER_REQUEST = 3650

#: 交易所代码（`trade_cal` 的 `exchange` 参数）。本卡只取沪深两市。
EXCHANGES: tuple[str, ...] = ("SSE", "SZSE")


class SourceFormatError(ValueError):
    """上游信封/字段与本适配器的解析口径不符——宁可失败也不猜。"""


# ---- 请求计划（纯函数，可 dry-run）----


@dataclass(frozen=True, slots=True)
class TushareRequest:
    """一次 Tushare 调用的完整参数。`api_name` 必经出口的枚举白名单。"""

    api_name: str
    params: dict[str, str]
    fields: tuple[str, ...]

    def describe(self) -> str:
        """给 dry-run 打印用。**只含 api_name 与参数**——请求体（含 token）从不出现在这里。"""
        rendered = ",".join(f"{k}={v}" for k, v in sorted(self.params.items()))
        return f"{self.api_name}({rendered})"


@dataclass(frozen=True, slots=True)
class Endpoint:
    """一个只读端点的静态描述：`api_name` + 取哪些字段 + 归一化后的 schema。"""

    api_name: str
    fields: tuple[str, ...]
    schema: pa.Schema
    #: 归一化后用于排序/去重的自然键（列名），保证同区间重放逐字节一致。
    sort_key: tuple[str, ...]
    #: 该端点是否按 `[start_date, end_date]` 区间切片（`stock_basic` 是全量快照）。
    ranged: bool = True
    #: 固定参数（如 `trade_cal` 的 `is_open` 不设——两种日期都要，休市日是日历的一部分）。
    fixed_params: dict[str, str] = field(default_factory=dict)


def _ymd(day: dt.date) -> str:
    """Tushare 的日期参数一律 `YYYYMMDD`。"""
    return day.strftime("%Y%m%d")


def date_chunks(start: dt.date, end: dt.date) -> Iterator[tuple[dt.date, dt.date]]:
    """把 `[start, end]` 切成 ≤ `MAX_DAYS_PER_REQUEST` 天的闭区间，升序、不重叠、无缝隙。"""
    if end < start:
        raise SourceFormatError(f"区间非法: {start} > {end}")
    cursor = start
    step = dt.timedelta(days=MAX_DAYS_PER_REQUEST - 1)
    while cursor <= end:
        stop = min(cursor + step, end)
        yield cursor, stop
        cursor = stop + dt.timedelta(days=1)


# ---- 归一化 schema ----

#: 日线 OHLCV。金额单位保持上游口径（`vol` 手、`amount` 千元），换算留给研究层——
#: 摄取层做单位换算会让「落盘的数」与「上游的数」对不上，重放时无从核对。
DAILY_SCHEMA = pa.schema(
    [
        pa.field("ts_code", pa.string(), nullable=False),
        pa.field("trade_date", pa.date32(), nullable=False),
        pa.field("open", pa.float64(), nullable=True),
        pa.field("high", pa.float64(), nullable=True),
        pa.field("low", pa.float64(), nullable=True),
        pa.field("close", pa.float64(), nullable=True),
        pa.field("pre_close", pa.float64(), nullable=True),
        pa.field("change", pa.float64(), nullable=True),
        pa.field("pct_chg", pa.float64(), nullable=True),
        pa.field("vol", pa.float64(), nullable=True),
        pa.field("amount", pa.float64(), nullable=True),
    ]
)

ADJ_FACTOR_SCHEMA = pa.schema(
    [
        pa.field("ts_code", pa.string(), nullable=False),
        pa.field("trade_date", pa.date32(), nullable=False),
        pa.field("adj_factor", pa.float64(), nullable=True),
    ]
)

#: 每日指标最小集（卡：市值/换手/PE 等）。只取研究会用到的列，不把 19 列全拉下来——
#: 字段越多，上游任何一列改口径都会打断摄取。
DAILY_BASIC_FIELDS: tuple[str, ...] = (
    "ts_code",
    "trade_date",
    "close",
    "turnover_rate",
    "turnover_rate_f",
    "volume_ratio",
    "pe",
    "pe_ttm",
    "pb",
    "ps_ttm",
    "dv_ttm",
    "total_share",
    "float_share",
    "free_share",
    "total_mv",
    "circ_mv",
)

DAILY_BASIC_SCHEMA = pa.schema(
    [
        pa.field("ts_code", pa.string(), nullable=False),
        pa.field("trade_date", pa.date32(), nullable=False),
    ]
    + [pa.field(name, pa.float64(), nullable=True) for name in DAILY_BASIC_FIELDS[2:]]
)

TRADE_CAL_SCHEMA = pa.schema(
    [
        pa.field("exchange", pa.string(), nullable=False),
        pa.field("cal_date", pa.date32(), nullable=False),
        pa.field("is_open", pa.int64(), nullable=False),
        pa.field("pretrade_date", pa.date32(), nullable=True),
    ]
)

STOCK_BASIC_SCHEMA = pa.schema(
    [
        pa.field("ts_code", pa.string(), nullable=False),
        pa.field("symbol", pa.string(), nullable=True),
        pa.field("name", pa.string(), nullable=True),
        pa.field("area", pa.string(), nullable=True),
        pa.field("industry", pa.string(), nullable=True),
        pa.field("market", pa.string(), nullable=True),
        pa.field("exchange", pa.string(), nullable=True),
        pa.field("curr_type", pa.string(), nullable=True),
        pa.field("list_status", pa.string(), nullable=True),
        pa.field("list_date", pa.date32(), nullable=True),
        pa.field("delist_date", pa.date32(), nullable=True),
    ]
)

#: 五个只读端点。`api_name` 与 `transport.TUSHARE_READONLY_API_NAMES` 必须逐个对上
#: （有专门的测试钉住两边不漂移）。
ENDPOINTS: dict[str, Endpoint] = {
    "daily": Endpoint(
        api_name="daily",
        fields=tuple(f.name for f in DAILY_SCHEMA),
        schema=DAILY_SCHEMA,
        sort_key=("ts_code", "trade_date"),
    ),
    "adj_factor": Endpoint(
        api_name="adj_factor",
        fields=tuple(f.name for f in ADJ_FACTOR_SCHEMA),
        schema=ADJ_FACTOR_SCHEMA,
        sort_key=("ts_code", "trade_date"),
    ),
    "daily_basic": Endpoint(
        api_name="daily_basic",
        fields=DAILY_BASIC_FIELDS,
        schema=DAILY_BASIC_SCHEMA,
        sort_key=("ts_code", "trade_date"),
    ),
    "trade_cal": Endpoint(
        api_name="trade_cal",
        fields=tuple(f.name for f in TRADE_CAL_SCHEMA),
        schema=TRADE_CAL_SCHEMA,
        sort_key=("exchange", "cal_date"),
    ),
    "stock_basic": Endpoint(
        api_name="stock_basic",
        fields=tuple(f.name for f in STOCK_BASIC_SCHEMA),
        schema=STOCK_BASIC_SCHEMA,
        sort_key=("ts_code",),
        ranged=False,
        fixed_params={"list_status": "L"},
    ),
}

#: `datatype` → 端点名。`kline` 走 `daily`；其余三个落 `data/meta/` 表，
#: `daily_basic` 是新增的 lake datatype（**偏离项**：ADR-0003 §4.1 的 datatype 枚举
#: 没有它，需 planner 决定是否修 ADR——本卡只报不改文档）。
DATATYPE_TO_ENDPOINT: dict[str, str] = {
    str(DataType.KLINE): "daily",
    "adj_factor": "adj_factor",
    "daily_basic": "daily_basic",
    "trade_cal": "trade_cal",
    "stock_basic": "stock_basic",
}


def plan_requests(
    endpoint_name: str,
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
    ts_code: str | None = None,
    exchange: str | None = None,
) -> list[TushareRequest]:
    """列出一次摄取要发的请求——纯函数，便于单测与 dry-run。

    区间型端点按 `MAX_DAYS_PER_REQUEST` 切片；`stock_basic` 是全量快照，只发一次。
    """
    ep = ENDPOINTS.get(endpoint_name)
    if ep is None:
        raise SourceFormatError(f"未知端点 {endpoint_name!r}（本卡范围: {sorted(ENDPOINTS)}）")
    if not ep.ranged:
        return [TushareRequest(ep.api_name, dict(ep.fixed_params), ep.fields)]
    if start is None or end is None:
        raise SourceFormatError(f"{endpoint_name} 是区间型端点，必须给 start/end")

    base: dict[str, str] = dict(ep.fixed_params)
    if ts_code is not None:
        base["ts_code"] = ts_code
    if exchange is not None:
        base["exchange"] = exchange
    if endpoint_name == "trade_cal":
        if exchange is None:
            raise SourceFormatError("trade_cal 必须指定 exchange（本卡: SSE / SZSE）")
    elif ts_code is None:
        raise SourceFormatError(f"{endpoint_name} 必须指定 ts_code（按标的增量）")

    return [
        TushareRequest(
            ep.api_name,
            {**base, "start_date": _ymd(lo), "end_date": _ymd(hi)},
            ep.fields,
        )
        for lo, hi in date_chunks(start, end)
    ]


# ---- 信封校验与归一化 ----


def assert_not_truncated(api_name: str, n_rows: int) -> None:
    """行数触顶即失败。

    上游超过 6000 行时**直接少给**，没有分页游标、没有 `has_more` 标志。把触顶当成
    「正好这么多」会安静地丢数据——缺失的行在缺口报告里也不一定看得出来（整段尾巴没了，
    看起来就像那段时间没交易）。所以宁可让摄取红掉，由调用方缩小区间重来。
    """
    if n_rows >= MAX_ROWS_PER_REQUEST:
        raise SourceFormatError(
            f"{api_name}: 返回 {n_rows} 行，已达单次上限 {MAX_ROWS_PER_REQUEST}，"
            "结果可能被截断且上游无截断信号——请缩小区间重取"
        )


def _column_index(
    api_name: str, got_fields: Sequence[str], wanted: Sequence[str]
) -> dict[str, int]:
    """按**名字**建列索引。缺列即失败；多出来的列忽略（上游加列不该打断摄取）。"""
    index = {name: i for i, name in enumerate(got_fields)}
    missing = [w for w in wanted if w not in index]
    if missing:
        raise SourceFormatError(f"{api_name}: 响应缺少字段 {missing}（得到 {list(got_fields)}）")
    return index


def _to_date(value: object) -> dt.date | None:
    """`YYYYMMDD` 字符串 → `date`。空值（上游用 `None` 或空串）保持 `None`。"""
    if value is None or value == "":
        return None
    text = str(value).strip()
    if len(text) != 8 or not text.isdigit():
        raise SourceFormatError(f"日期不是 YYYYMMDD: {text!r}")
    return dt.date(int(text[:4]), int(text[4:6]), int(text[6:8]))


def _to_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _to_int(value: object) -> int:
    if value is None or value == "":
        raise SourceFormatError("必填整型字段为空")
    return int(value)


def _to_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


#: 每个字段名 → 转换函数。按名字查，因此与列序无关。
_CONVERTERS = {
    pa.date32(): _to_date,
    pa.float64(): _to_float,
    pa.int64(): _to_int,
    pa.string(): _to_str,
}


def normalize(endpoint_name: str, data: dict[str, list]) -> pa.Table:
    """`{"fields": [...], "items": [[...]]}` → 归一化表（按 `sort_key` 升序）。

    排序是确定性重放的前提：上游不保证行序（`daily` 实测按 `trade_date` 倒序返回），
    不排序的话同一区间两次摄取会得到不同的 `content_sha256`。
    """
    ep = ENDPOINTS.get(endpoint_name)
    if ep is None:
        raise SourceFormatError(f"未知端点 {endpoint_name!r}")
    got_fields = data.get("fields")
    items = data.get("items")
    if not isinstance(got_fields, list) or not isinstance(items, list):
        raise SourceFormatError(f"{ep.api_name}: data 缺少 fields/items 列表")

    wanted = [f.name for f in ep.schema]
    index = _column_index(ep.api_name, got_fields, wanted)
    assert_not_truncated(ep.api_name, len(items))

    width = len(got_fields)
    bad = [i for i, row in enumerate(items) if len(row) != width]
    if bad:
        raise SourceFormatError(
            f"{ep.api_name}: 第 {bad[:3]} 行列数与 fields 不符（{width} 列），拒绝错位解析"
        )

    columns: dict[str, list] = {}
    for f in ep.schema:
        convert = _CONVERTERS[f.type]
        col = index[f.name]
        try:
            values = [convert(row[col]) for row in items]
        except (TypeError, ValueError) as exc:
            raise SourceFormatError(f"{ep.api_name}.{f.name}: {exc}") from None
        if not f.nullable and any(v is None for v in values):
            raise SourceFormatError(f"{ep.api_name}.{f.name} 不可为空，但响应里有空值")
        columns[f.name] = values

    table = pa.Table.from_pydict(columns, schema=ep.schema)
    if table.num_rows:
        table = table.sort_by([(k, "ascending") for k in ep.sort_key])
    return table


#: `endpoint → 时间列`，缺口检测用（复用 QNT-45 通用层的接口形状；**待对齐**）。
TIME_COLUMN: dict[str, str] = {
    "daily": "trade_date",
    "adj_factor": "trade_date",
    "daily_basic": "trade_date",
    "trade_cal": "cal_date",
}
