"""Massive（原 Polygon.io）美股 + 美股期权数据源（QNT-47 阶段 1，按公开文档实现）。

**需 API key、只读、无任何下单/账户端点**。本模块与 `binance_public` 同形：只做三件事
——拼 URL、解 JSON、归一化成 Arrow 表。它自己**不出网**，字节由调用方经
`data/keyed_transport.py` 取来传入，因此归一化逻辑在测试里完全离线可跑。

> **待与 QNT-45 契约对齐**：QNT-45（数据源公共层：增量 / 重试 / 回补 / 每日核查 / timer）
> 的 PR 在本卡落地时尚未开出，源接口契约无从引用。本模块因此按**现有形状**
> （`sources/binance_public.py` + `ingest.py`）写：`SOURCE` / `SOURCE_VERSION` /
> 纯 `normalize_*(payload: bytes, ...) -> pa.Table` / `TIME_COLUMN`。公共层落地后，
> 本模块只需改 URL 规划入口的签名，归一化与 schema 不动。合并顺序：QNT-45 PR → 本卡 PR。

覆盖的数据（阶段 1 卡范围）
---------------------------

| datatype | 端点（路径模板） | 归一化函数 |
|---|---|---|
| `us_equity` 日线 | `/v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}` | `normalize_equity_daily` |
| 拆股（复权事件） | `/stocks/v1/splits` | `normalize_splits` |
| 分红（复权事件） | `/stocks/v1/dividends` | `normalize_dividends` |
| `us_option` 合约参考 | `/v3/reference/options/contracts` | `normalize_option_contracts` |
| `us_option` 日线 | `/v2/aggs/ticker/{optTicker}/range/1/day/…` | `normalize_option_daily` |

**只存未复权价**：日线一律以 `adjusted=false` 请求（`ADJUSTED_QUERY`）。复权是派生量
——上游的复权口径会随新的拆股/分红事件改变昨天的数字，而 ADR-0002 的湖只 insert：
同一天的收盘价不能因为今天除权而变成另一个值。所以湖里存原始价，拆股/分红各自带
`historical_adjustment_factor` 进 `meta/adjust_factor`，复权在查询期算。

许可要点（阶段 1 只记录，不做文献式核查）
------------------------------------------

- 条款 URL：<https://massive.com/legal/individuals-terms-of-service>（个人版）、
  <https://massive.com/legal/businesses-terms-of-service>（企业版）、
  <https://massive.com/legal/website-terms-of-service>（站点）。访问日期 2026-09-23。
- 记录到的要点（**未经法务复核，采购前由 owner 确认**）：数据按订阅授权使用；
  个人版面向个人自用的内部分析，不含再分发 / 转售 / 对外提供衍生数据服务的许可；
  本地留存用于内部研究属订阅期内的使用范围。**本系统的用法**（落地到自有 Parquet 湖、
  仅供内部回测与研究、不对外提供任何数据接口）据此记为「订阅期内的内部研究使用」。
- 湖里的每个 batch 都带 `source='massive'`，因此一旦许可变更需要下线，可按
  `ingestion_batch.kind='license_drop'` 定位到全部受影响 batch（ADR-0003 §4.3）。

订阅档位（供 owner 采购；按官方文档 Plan Access / Recency / History 表，2026-09-23）
-----------------------------------------------------------------------------------

| 端点 | 档位准入 | 时效 | 历史深度 |
|---|---|---|---|
| Stocks 日线聚合 | 全部 Stocks 档 | 见下 | 见下 |
| Stocks 拆股 | 全部 Stocks 档 | 每日更新 | Basic 2 年；其余全量（回溯 1978-10-25） |
| Stocks 分红 | 全部 Stocks 档 | 每日更新 | Basic 2 年；其余全量（回溯 2000-01-15） |
| Options 合约参考 | 全部 Options 档 | 每日更新 | Basic 2 年；其余全量（回溯 2014-06-02） |
| Options 日线聚合 | 全部 Options 档 | 见下 | 见下 |

日线聚合（股票与期权同口径）按档位：

| 档位 | 时效 | 历史深度 |
|---|---|---|
| Basic | 当日收盘后（EOD） | 2 年 |
| Starter | 15 分钟延迟 | 5 年 |
| Developer | 15 分钟延迟 | 10 年 |
| Advanced / Business | 实时 | 全量（股票回溯 2003-09-10） |

**结论**：本卡只用日线 + 参考/公司行动，四类端点在**最低档**（Stocks Basic + Options
Basic）即可访问，但 Basic 只有 2 年历史与 EOD 时效。日线研究系统按 EOD 即可，
**决定采购与否的是历史深度**：要多于 2 年就必须上 Starter 及以上。分红/拆股需要全量
历史才能算长区间复权因子——这一条比行情本身更硬。

限流（官方知识库，2026-09-23）
-------------------------------

免费 / Basic 档对**未订阅的资产类**限 5 请求/分钟，超限返回 HTTP 429；已订阅的资产类
不限速。因此本源默认按 `FREE_TIER_MIN_INTERVAL`（12 秒）节流——这是最坏情况下的安全值，
拿到 key、确认档位后由调用方下调。退避/重试复用 `transport.Throttled`（共用实现，
不在本源复制第二份）。

期权全量体量估算（阶段 1 只估，不取）
--------------------------------------

按首批 20 支标的（`universe_us.yaml`）的期权链，量级如下（数量级估算，非实测）：

- 合约参考：活跃链每标的约 1e3–4e3 份合约（SPY/AAPL 这类在高位），20 支合计约 3e4；
  含已过期合约（`expired=true`，2014 年至今）则约 1e6 量级。参考数据每行约 120 B，
  Parquet zstd 后约 30 B/行 → 活跃链约 1 MB，含历史约 30 MB。
- 日线：一份合约的一生约 1e2–1e3 个交易日，但只有少数日子有成交（无成交不出 bar）。
  按 1e6 份历史合约 × 平均 30 个有效 bar ≈ 3e7 行；每行 8 个 float/int，
  Parquet zstd 后约 25 B/行 → **约 750 MB**。按单次请求覆盖一份合约的全生命周期、
  免费档 12 秒/请求计，仅拉取就需约 1e6 × 12 s ≈ 139 天——**全量回补在免费档不可行**，
  必须先确定档位（付费档不限速）再决定回补范围。阶段 1 因此只做
  「单标的 × 单到期日」的日线归一化，不做全链回补（卡范围）。

来源：<https://massive.com/docs/rest/stocks/overview>、
<https://massive.com/docs/rest/options/overview>（llms-full 全文，访问日期 2026-09-23）。
"""

from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow as pa
from quantime_core.allowlist import MASSIVE_REST, MASSIVE_REST_LEGACY

#: 本源使用的 host —— 从 allowlist **引用**而非复制字面量（`core/allowlist.py` 是唯一出处，
#: 静态守卫据此 grep）。新域名是默认值，旧域名（Polygon）只是兼容入口。
HOSTS: tuple[str, ...] = (MASSIVE_REST.host, MASSIVE_REST_LEGACY.host)

#: REST 基址（host 同样来自 allowlist 条目）。
REST_BASE = f"https://{MASSIVE_REST.host}"

#: `source` 列的取值（同时是 `data/raw/<source>/` 与 `source=` 分区的分量）。
SOURCE = "massive"

#: `source_version`：上游 REST 无全局版本号，用「本适配器的解析口径」固定字面量标注。
#: 端点各自的 `/v2`、`/v3`、`/stocks/v1` 版本段体现在 URL 里，不混进这一个字段。
SOURCE_VERSION = "massive-rest-2026-09-23"

#: 凭据来源（**不是** 1Password 引用字面量，只是一个指针串；真正的引用在
#: `docs/ops/massive.env.tpl` 里，由 `op run --env-file=...` 注入 `MASSIVE_API_KEY`）。
CREDENTIAL_POINTER = "op:quant-dev/Massive Quantime API/credential"

#: 免费 / Basic 档对未订阅资产类的限速：5 请求/分钟 → 两次请求至少隔 12 秒。
FREE_TIER_MIN_INTERVAL = 12.0

#: 付费档在**已订阅**的资产类上不限速；仍留一个下限避免把上游打满。
PAID_TIER_MIN_INTERVAL = 0.05

#: 日线一律请求未复权价（见模块头「只存未复权价」）。
ADJUSTED_QUERY = "adjusted=false"

#: 聚合端点的排序：升序，使同一区间的响应行序与湖里的行序一致（确定性 writer 的前提）。
SORT_QUERY = "sort=asc"

#: 分页上限。聚合端点 max 50000；参考/公司行动端点 `/stocks/v1/*` max 5000、
#: `/v3/reference/options/contracts` max 1000。各自取文档上限，减少请求数（免费档 12 s/次）。
AGGS_LIMIT = 50000
STOCKS_V1_LIMIT = 5000
OPTION_CONTRACTS_LIMIT = 1000

#: 上游 `status` 字段的可接受取值。`DELAYED` 是低档位的正常返回（15 分钟延迟），
#: 其余（`ERROR` / `NOT_AUTHORIZED` / `NOT_FOUND`）一律当失败——宁可失败也不写半张表。
OK_STATUSES: frozenset[str] = frozenset({"OK", "DELAYED"})

#: 股票 ticker 的形态（大写字母 + 数字 + `.`，如 `BRK.B`）。用于**拼 URL 之前**的自检：
#: 路径闸在 transport 层，但让非法 ticker 在这里就炸掉，错误信息更有用。
#:
#: 下面几条一律用 `\Z` 收尾而不是 `$`：Python 的 `$` 也匹配**结尾换行之前**，于是
#: `"AAPL\n"` 能过 `$` 锚定的校验，再被拼进 URL——一个换行足以在请求行里另起一行。
#: `\Z` 只匹配真正的串尾。
_EQUITY_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.]{0,15}\Z")

#: 期权 ticker 的 OCC 形态：`O:` + 底层(1–6) + YYMMDD + C/P + 8 位行权价（千分之一美元）。
_OPTION_TICKER_RE = re.compile(r"^O:[A-Z][A-Z0-9]{0,5}[0-9]{6}[CP][0-9]{8}\Z")

_ISO_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")


class SourceFormatError(ValueError):
    """上游 JSON 的形状/字段与本适配器的解析口径不符——宁可失败也不猜。"""


# --------------------------------------------------------------------------- 标识符


def assert_equity_ticker(ticker: str) -> str:
    if not _EQUITY_TICKER_RE.match(ticker):
        raise ValueError(f"不是合法的美股 ticker: {ticker!r}")
    return ticker


def assert_option_ticker(ticker: str) -> str:
    if not _OPTION_TICKER_RE.match(ticker):
        raise ValueError(f"不是合法的 OCC 期权 ticker（形如 O:AAPL211119C00085000）: {ticker!r}")
    return ticker


def _assert_iso_date(value: dt.date | str, *, field: str) -> str:
    text = value.isoformat() if isinstance(value, dt.date) else value
    if not _ISO_DATE_RE.match(text):
        raise ValueError(f"{field} 必须是 YYYY-MM-DD: {value!r}")
    return text


def option_scope(ticker: str) -> str:
    """OCC ticker → 湖目录的 `symbol_or_universe` 分量。

    `core/paths.py::assert_scope` 的字符集是 `[A-Za-z0-9._-]`，**不含 `:`**，
    而期权 ticker 恰恰以 `O:` 开头——直接拿 ticker 当 scope 会被路径规范拒绝。
    这里把唯一的那个 `:` 映射成 `.`（scope 允许、OCC ticker 本身永不含 `.`），
    因此映射是**双射**，`option_ticker_from_scope` 可无损还原。
    映射而不是改 `assert_scope`：路径分量的字符集是 ADR-0003 §4.1 的规范，不由本卡动。
    """
    assert_option_ticker(ticker)
    return ticker.replace(":", ".", 1)


def option_ticker_from_scope(scope: str) -> str:
    """`option_scope` 的逆映射。"""
    ticker = scope.replace(".", ":", 1)
    return assert_option_ticker(ticker)


# --------------------------------------------------------------------------- URL


def equity_daily_bars_url(ticker: str, start: dt.date | str, end: dt.date | str) -> str:
    """单只股票的日线聚合（未复权、升序）。`start`/`end` 含两端。"""
    assert_equity_ticker(ticker)
    frm = _assert_iso_date(start, field="start")
    to = _assert_iso_date(end, field="end")
    return (
        f"{REST_BASE}/v2/aggs/ticker/{ticker}/range/1/day/{frm}/{to}"
        f"?{ADJUSTED_QUERY}&{SORT_QUERY}&limit={AGGS_LIMIT}"
    )


def option_daily_bars_url(ticker: str, start: dt.date | str, end: dt.date | str) -> str:
    """单份期权合约的日线聚合（未复权、升序）。"""
    assert_option_ticker(ticker)
    frm = _assert_iso_date(start, field="start")
    to = _assert_iso_date(end, field="end")
    return (
        f"{REST_BASE}/v2/aggs/ticker/{ticker}/range/1/day/{frm}/{to}"
        f"?{ADJUSTED_QUERY}&{SORT_QUERY}&limit={AGGS_LIMIT}"
    )


def splits_url(ticker: str, *, start: dt.date | str | None = None) -> str:
    """拆股事件。`start` 给出后按 `execution_date.gte` 增量取。"""
    assert_equity_ticker(ticker)
    query = [f"ticker={ticker}", "sort=execution_date.asc", f"limit={STOCKS_V1_LIMIT}"]
    if start is not None:
        query.append(f"execution_date.gte={_assert_iso_date(start, field='start')}")
    return f"{REST_BASE}/stocks/v1/splits?{'&'.join(query)}"


def dividends_url(ticker: str, *, start: dt.date | str | None = None) -> str:
    """分红事件。`start` 给出后按 `ex_dividend_date.gte` 增量取。"""
    assert_equity_ticker(ticker)
    query = [f"ticker={ticker}", "sort=ex_dividend_date.asc", f"limit={STOCKS_V1_LIMIT}"]
    if start is not None:
        query.append(f"ex_dividend_date.gte={_assert_iso_date(start, field='start')}")
    return f"{REST_BASE}/stocks/v1/dividends?{'&'.join(query)}"


def option_contracts_url(
    underlying: str,
    *,
    expiration_date: dt.date | str | None = None,
    as_of: dt.date | str | None = None,
    expired: bool = False,
) -> str:
    """某标的的期权合约参考数据。

    阶段 1 只取「单标的 × 单到期日」的活跃链（卡范围）；`expired=True` 是全量回补的入口，
    体量见模块头的估算——免费档下不可行，必须先定档位。
    """
    assert_equity_ticker(underlying)
    query = [
        f"underlying_ticker={underlying}",
        f"expired={'true' if expired else 'false'}",
        "sort=ticker.asc",
        f"limit={OPTION_CONTRACTS_LIMIT}",
    ]
    if expiration_date is not None:
        exp = _assert_iso_date(expiration_date, field="expiration_date")
        query.append(f"expiration_date={exp}")
    if as_of is not None:
        query.append(f"as_of={_assert_iso_date(as_of, field='as_of')}")
    return f"{REST_BASE}/v3/reference/options/contracts?{'&'.join(query)}"


def year_chunks(start: dt.date, end: dt.date) -> list[tuple[dt.date, dt.date]]:
    """把 `[start, end]` 切成按自然年对齐的闭区间列表（增量/回补的区间计算）。

    聚合端点单次最多 50000 根基础 bar，日线一年约 252 根——一次请求装得下几十年。
    仍按年切，是为了让**回补的最小可重试单位**足够小：免费档 12 秒一个请求，
    一次失败重来的代价应该是一年而不是二十年。切分只依赖入参，不依赖时钟，因此可重放。
    """
    if end < start:
        raise ValueError(f"区间非法: {start} > {end}")
    out: list[tuple[dt.date, dt.date]] = []
    year = start.year
    while year <= end.year:
        lo = max(start, dt.date(year, 1, 1))
        hi = min(end, dt.date(year, 12, 31))
        out.append((lo, hi))
        year += 1
    return out


def next_page_url(payload: bytes) -> str | None:
    """上游给的下一页 URL（`next_url`），没有则 `None`。

    返回的字符串**必须**再过一遍出口的两道闸：它由服务端提供，而闸的意义就在于
    「我们只发出自己白名单里的请求」。上游文档里 `next_url` 的路径与请求路径并不总是
    一致（见 PR 描述的文档矛盾一节），所以白名单外的 `next_url` 会被 fail-closed 挡下
    ——这是设计如此，不是缺陷。
    """
    doc = _load(payload)
    url = doc.get("next_url")
    if url is None:
        return None
    if not isinstance(url, str) or not url:
        raise SourceFormatError(f"next_url 不是非空字符串: {url!r}")
    return url


# --------------------------------------------------------------------------- 解析


def _load(payload: bytes) -> dict[str, Any]:
    try:
        doc = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceFormatError(f"响应不是 UTF-8 JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise SourceFormatError(f"响应根节点应为对象，得到 {type(doc).__name__}")
    return doc


def _results(payload: bytes) -> list[dict[str, Any]]:
    """取 `results` 并先验 `status`。`results` 缺失（0 命中）视为空列表。"""
    doc = _load(payload)
    status = doc.get("status")
    if status is not None and status not in OK_STATUSES:
        raise SourceFormatError(f"上游 status={status!r}（可接受 {sorted(OK_STATUSES)}）")
    rows = doc.get("results")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise SourceFormatError(f"results 应为数组，得到 {type(rows).__name__}")
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise SourceFormatError(f"results[{i}] 应为对象，得到 {type(row).__name__}")
    return rows


def _need(row: dict[str, Any], key: str, kind: type | tuple[type, ...], where: str) -> Any:
    if key not in row:
        raise SourceFormatError(f"{where} 缺字段 {key!r}（上游布局可能已变，拒绝猜测）")
    value = row[key]
    if not isinstance(value, kind) or isinstance(value, bool) and kind is not bool:
        raise SourceFormatError(f"{where} 的 {key!r} 类型不符: {value!r}")
    return value


def _opt_float(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    return None if value is None else float(value)


def _opt_int(row: dict[str, Any], key: str) -> int | None:
    value = row.get(key)
    return None if value is None else int(value)


def _opt_str(row: dict[str, Any], key: str) -> str | None:
    value = row.get(key)
    return None if value is None else str(value)


def _opt_date(row: dict[str, Any], key: str) -> dt.date | None:
    value = row.get(key)
    if value is None:
        return None
    return dt.date.fromisoformat(str(value))


def _ms_to_utc(value: int) -> dt.datetime:
    """毫秒 epoch → UTC datetime（微秒精度，与 Parquet `timestamp('us')` 对齐）。"""
    return dt.datetime.fromtimestamp(int(value) / 1000, tz=dt.UTC)


def _canonical_json(value: Any) -> str | None:
    """把嵌套结构压成确定性 JSON 文本（键排序、无空格）。

    `additional_underlyings` 是数组套对象。把它摊平成列会让 schema 随数据变形；
    存成 JSON 文本则 schema 固定，且键排序保证同一输入产出同一字节
    （确定性 writer 的前提，ADR-0003 §4.2）。
    """
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# --------------------------------------------------------------------------- schema

#: 美股日线（未复权）。`vwap` / `trade_count` 可空：文档把它们列为响应字段，
#: 但极低流动性的 bar 上游曾省略——缺就记 null，不用 0 冒充（0 是一个真实的值）。
EQUITY_DAILY_SCHEMA = pa.schema(
    [
        pa.field("ticker", pa.string(), nullable=False),
        pa.field("window_start", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("open", pa.float64(), nullable=False),
        pa.field("high", pa.float64(), nullable=False),
        pa.field("low", pa.float64(), nullable=False),
        pa.field("close", pa.float64(), nullable=False),
        pa.field("volume", pa.float64(), nullable=False),
        pa.field("vwap", pa.float64(), nullable=True),
        pa.field("trade_count", pa.int64(), nullable=True),
        pa.field("otc", pa.bool_(), nullable=False),
    ]
)

#: 期权日线：与股票同形，去掉 `otc`（期权无场外标记）。
OPTION_DAILY_SCHEMA = pa.schema(
    [
        pa.field("ticker", pa.string(), nullable=False),
        pa.field("underlying_ticker", pa.string(), nullable=False),
        pa.field("window_start", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("open", pa.float64(), nullable=False),
        pa.field("high", pa.float64(), nullable=False),
        pa.field("low", pa.float64(), nullable=False),
        pa.field("close", pa.float64(), nullable=False),
        pa.field("volume", pa.float64(), nullable=False),
        pa.field("vwap", pa.float64(), nullable=True),
        pa.field("trade_count", pa.int64(), nullable=True),
    ]
)

SPLIT_SCHEMA = pa.schema(
    [
        pa.field("ticker", pa.string(), nullable=False),
        pa.field("execution_date", pa.date32(), nullable=False),
        pa.field("split_from", pa.float64(), nullable=False),
        pa.field("split_to", pa.float64(), nullable=False),
        pa.field("historical_adjustment_factor", pa.float64(), nullable=True),
        pa.field("adjustment_type", pa.string(), nullable=True),
        pa.field("event_id", pa.string(), nullable=False),
    ]
)

DIVIDEND_SCHEMA = pa.schema(
    [
        pa.field("ticker", pa.string(), nullable=False),
        pa.field("ex_dividend_date", pa.date32(), nullable=False),
        pa.field("cash_amount", pa.float64(), nullable=False),
        pa.field("currency", pa.string(), nullable=True),
        pa.field("declaration_date", pa.date32(), nullable=True),
        pa.field("record_date", pa.date32(), nullable=True),
        pa.field("pay_date", pa.date32(), nullable=True),
        pa.field("frequency", pa.int64(), nullable=True),
        pa.field("distribution_type", pa.string(), nullable=True),
        pa.field("split_adjusted_cash_amount", pa.float64(), nullable=True),
        pa.field("historical_adjustment_factor", pa.float64(), nullable=True),
        pa.field("event_id", pa.string(), nullable=False),
    ]
)

OPTION_CONTRACT_SCHEMA = pa.schema(
    [
        pa.field("ticker", pa.string(), nullable=False),
        pa.field("underlying_ticker", pa.string(), nullable=False),
        pa.field("contract_type", pa.string(), nullable=False),
        pa.field("expiration_date", pa.date32(), nullable=False),
        pa.field("strike_price", pa.float64(), nullable=False),
        pa.field("exercise_style", pa.string(), nullable=True),
        pa.field("shares_per_contract", pa.float64(), nullable=True),
        pa.field("primary_exchange", pa.string(), nullable=True),
        pa.field("cfi", pa.string(), nullable=True),
        pa.field("correction", pa.int64(), nullable=True),
        pa.field("additional_underlyings", pa.string(), nullable=True),
    ]
)


# --------------------------------------------------------------------------- 归一化


def _bars(rows: list[dict[str, Any]], where: str) -> list[dict[str, Any]]:
    """聚合行的共用校验 + 按 `t` 升序。

    显式排序：上游 `sort=asc` 是请求参数，不是保证。行序变了，确定性 writer 产出的
    字节就变了（ADR-0003 §4.2），所以排序在本地做一次。
    """
    for row in rows:
        for key in ("t", "o", "h", "l", "c", "v"):
            _need(row, key, (int, float), where)
    return sorted(rows, key=lambda r: int(r["t"]))


def normalize_equity_daily(payload: bytes, *, ticker: str) -> pa.Table:
    """股票日线聚合响应 → 归一化表（按 `window_start` 升序）。"""
    assert_equity_ticker(ticker)
    rows = _bars(_results(payload), f"{ticker} 日线")
    return pa.Table.from_pydict(
        {
            "ticker": [ticker] * len(rows),
            "window_start": [_ms_to_utc(r["t"]) for r in rows],
            "open": [float(r["o"]) for r in rows],
            "high": [float(r["h"]) for r in rows],
            "low": [float(r["l"]) for r in rows],
            "close": [float(r["c"]) for r in rows],
            "volume": [float(r["v"]) for r in rows],
            "vwap": [_opt_float(r, "vw") for r in rows],
            "trade_count": [_opt_int(r, "n") for r in rows],
            # 文档：`otc` 为 false 时字段被省略。缺失即 false，不是未知。
            "otc": [bool(r.get("otc", False)) for r in rows],
        },
        schema=EQUITY_DAILY_SCHEMA,
    )


def normalize_option_daily(payload: bytes, *, ticker: str) -> pa.Table:
    """单份期权合约的日线聚合 → 归一化表。

    `underlying_ticker` 从 OCC ticker 里切出来（`O:<UND><YYMMDD><C|P><strike>`）：
    聚合响应本身不带底层，而按底层分区是回测里最常用的切法。
    """
    assert_option_ticker(ticker)
    underlying = _underlying_of(ticker)
    rows = _bars(_results(payload), f"{ticker} 日线")
    return pa.Table.from_pydict(
        {
            "ticker": [ticker] * len(rows),
            "underlying_ticker": [underlying] * len(rows),
            "window_start": [_ms_to_utc(r["t"]) for r in rows],
            "open": [float(r["o"]) for r in rows],
            "high": [float(r["h"]) for r in rows],
            "low": [float(r["l"]) for r in rows],
            "close": [float(r["c"]) for r in rows],
            "volume": [float(r["v"]) for r in rows],
            "vwap": [_opt_float(r, "vw") for r in rows],
            "trade_count": [_opt_int(r, "n") for r in rows],
        },
        schema=OPTION_DAILY_SCHEMA,
    )


def _underlying_of(option_ticker: str) -> str:
    """OCC ticker 的底层部分：去掉 `O:` 前缀与末尾的 `YYMMDD C/P 八位行权价`（15 字符）。"""
    assert_option_ticker(option_ticker)
    return option_ticker[2:-15]


def normalize_splits(payload: bytes, *, ticker: str) -> pa.Table:
    """拆股事件 → 归一化表（按 `execution_date` 升序，其次 `event_id` 定序）。"""
    assert_equity_ticker(ticker)
    rows = _results(payload)
    where = f"{ticker} 拆股"
    parsed = []
    for row in rows:
        got = _need(row, "ticker", str, where)
        if got != ticker:
            raise SourceFormatError(f"{where}: 响应含他股 {got!r}，拒绝混入")
        parsed.append(
            (
                dt.date.fromisoformat(_need(row, "execution_date", str, where)),
                float(_need(row, "split_from", (int, float), where)),
                float(_need(row, "split_to", (int, float), where)),
                _opt_float(row, "historical_adjustment_factor"),
                _opt_str(row, "adjustment_type"),
                _need(row, "id", str, where),
            )
        )
    parsed.sort(key=lambda t: (t[0], t[5]))
    return pa.Table.from_pydict(
        {
            "ticker": [ticker] * len(parsed),
            "execution_date": [p[0] for p in parsed],
            "split_from": [p[1] for p in parsed],
            "split_to": [p[2] for p in parsed],
            "historical_adjustment_factor": [p[3] for p in parsed],
            "adjustment_type": [p[4] for p in parsed],
            "event_id": [p[5] for p in parsed],
        },
        schema=SPLIT_SCHEMA,
    )


def normalize_dividends(payload: bytes, *, ticker: str) -> pa.Table:
    """分红事件 → 归一化表（按 `ex_dividend_date` 升序，其次 `event_id` 定序）。"""
    assert_equity_ticker(ticker)
    where = f"{ticker} 分红"
    parsed = []
    for row in _results(payload):
        got = _need(row, "ticker", str, where)
        if got != ticker:
            raise SourceFormatError(f"{where}: 响应含他股 {got!r}，拒绝混入")
        parsed.append(
            {
                "ex_dividend_date": dt.date.fromisoformat(
                    _need(row, "ex_dividend_date", str, where)
                ),
                "cash_amount": float(_need(row, "cash_amount", (int, float), where)),
                "currency": _opt_str(row, "currency"),
                "declaration_date": _opt_date(row, "declaration_date"),
                "record_date": _opt_date(row, "record_date"),
                "pay_date": _opt_date(row, "pay_date"),
                "frequency": _opt_int(row, "frequency"),
                "distribution_type": _opt_str(row, "distribution_type"),
                "split_adjusted_cash_amount": _opt_float(row, "split_adjusted_cash_amount"),
                "historical_adjustment_factor": _opt_float(row, "historical_adjustment_factor"),
                "event_id": _need(row, "id", str, where),
            }
        )
    parsed.sort(key=lambda r: (r["ex_dividend_date"], r["event_id"]))
    columns: dict[str, list[Any]] = {"ticker": [ticker] * len(parsed)}
    for field in DIVIDEND_SCHEMA.names:
        if field != "ticker":
            columns[field] = [r[field] for r in parsed]
    return pa.Table.from_pydict(columns, schema=DIVIDEND_SCHEMA)


def normalize_option_contracts(payload: bytes, *, underlying: str) -> pa.Table:
    """期权合约参考数据 → 归一化表（按 `ticker` 升序）。"""
    assert_equity_ticker(underlying)
    where = f"{underlying} 期权合约"
    parsed = []
    for row in _results(payload):
        got = _need(row, "underlying_ticker", str, where)
        if got != underlying:
            raise SourceFormatError(f"{where}: 响应含他股的合约（underlying={got!r}），拒绝混入")
        parsed.append(
            {
                "ticker": _need(row, "ticker", str, where),
                "underlying_ticker": got,
                "contract_type": _need(row, "contract_type", str, where),
                "expiration_date": dt.date.fromisoformat(_need(row, "expiration_date", str, where)),
                "strike_price": float(_need(row, "strike_price", (int, float), where)),
                "exercise_style": _opt_str(row, "exercise_style"),
                "shares_per_contract": _opt_float(row, "shares_per_contract"),
                "primary_exchange": _opt_str(row, "primary_exchange"),
                "cfi": _opt_str(row, "cfi"),
                "correction": _opt_int(row, "correction"),
                "additional_underlyings": _canonical_json(row.get("additional_underlyings")),
            }
        )
    parsed.sort(key=lambda r: r["ticker"])
    columns: dict[str, list[Any]] = {
        name: [r[name] for r in parsed] for name in OPTION_CONTRACT_SCHEMA.names
    }
    return pa.Table.from_pydict(columns, schema=OPTION_CONTRACT_SCHEMA)


# --------------------------------------------------------------------------- 核查参数

#: `datatype → 时间列`（缺口/重复核查用；与 `binance_public.TIME_COLUMN` 同角色）。
TIME_COLUMN: dict[str, str] = {
    "kline": "window_start",
    "corp_action": "execution_date",
    "dividend": "ex_dividend_date",
    "instrument_meta": "expiration_date",
}

#: 期望步长：**全部为 `None`**。美股日线的相邻交易日不是等距的（周末 + 假日 + 半日市），
#: 用 1 天当步长会把每个周末都报成缺口。交易日历感知的缺口检测依赖
#: `meta/trading_calendar`（ADR-0003 §4.1），属公共层；本卡不在源里伪造一个等距假设。
#: → PR 描述「偏离项」记一条。
FREQ_STEP: dict[str, dt.timedelta | None] = {"1d": None}


# =========================================================================== 阶段 2：参考数据
#
# QNT-47 阶段 2（owner 裁决 2026-09-23，Stocks Starter）：全量 ticker（含 `active=false`）、
# 全市场拆股 / 分红、ticker 变更事件。落 `meta/instrument_meta`、`meta/adjust_factor`、
# `meta/ticker_events`，`source='massive_rest'`（与阶段 1 的 `massive` 分开：阶段 1 是按标的的
# 单源适配，阶段 2 是全市场参考数据，两者可各自按源 drop）。
#
# 端点以官方文档为准（与卡面不同处已在 PR 描述「文档矛盾」列出）：
#
# - ticker 全表 `GET /v3/reference/tickers`
#   <https://massive.com/docs/rest/stocks/tickers/all-tickers>
# - 拆股 `GET /stocks/v1/splits`
#   <https://massive.com/docs/rest/stocks/corporate-actions/splits>
# - 分红 `GET /stocks/v1/dividends`
#   <https://massive.com/docs/rest/stocks/corporate-actions/dividends>
# - ticker 事件 `GET /vX/reference/tickers/{id}/events`
#   <https://massive.com/docs/rest/stocks/corporate-actions/ticker-events>
#
# 卡面写的 `/v3/reference/splits`、`/v3/reference/dividends` 在现行文档里已标 deprecated，
# 改用 `/stocks/v1/*`。ticker 事件端点带 `vX`（实验性），文档未给分页；`{id}` 接受 ticker、
# CUSIP 或 composite FIGI——本卡**只用 composite FIGI**：ticker 会被复用（同一代码先后指向
# 不同公司），FIGI 不会，且 FIGI 的字符集（`BBG` + 9 位大写字母数字）可以在路径闸里写死。

_NEW_YORK = ZoneInfo("America/New_York")

#: 阶段 2 REST 参考数据的 source。
REST_SOURCE = "massive_rest"
REST_SOURCE_VERSION = "massive-rest-reference-2026-09-23"

#: `/v3/reference/tickers` 的分页上限（文档：max 1000）。
TICKERS_LIMIT = 1000

#: composite FIGI 形态（OpenFIGI：`BBG` + 9 位 `[0-9A-Z]`）。
_FIGI_RE = re.compile(r"^BBG[0-9A-Z]{9}\Z")


def assert_figi(figi: str) -> str:
    if not isinstance(figi, str) or _FIGI_RE.fullmatch(figi) is None:
        raise SourceFormatError(f"非法 composite FIGI: {figi!r}")
    return figi


def tickers_url(*, active: bool, market: str = "stocks") -> str:
    """ticker 全表的第一页（按 ticker 升序）。后续页走响应里的 `next_url`（必须再过闸）。"""
    if market not in ("stocks", "otc"):
        raise ValueError(f"market 只接受 stocks/otc: {market!r}")
    query = [
        f"market={market}",
        f"active={'true' if active else 'false'}",
        "order=asc",
        "sort=ticker",
        f"limit={TICKERS_LIMIT}",
    ]
    return f"{REST_BASE}/v3/reference/tickers?{'&'.join(query)}"


def all_splits_url(*, start: dt.date | str | None = None, end: dt.date | str | None = None) -> str:
    """全市场拆股（不按 ticker 过滤）。给 `start`/`end` 即按 `execution_date` 限区间。"""
    query = ["sort=execution_date.asc", f"limit={STOCKS_V1_LIMIT}"]
    if start is not None:
        query.append(f"execution_date.gte={_assert_iso_date(start, field='start')}")
    if end is not None:
        query.append(f"execution_date.lte={_assert_iso_date(end, field='end')}")
    return f"{REST_BASE}/stocks/v1/splits?{'&'.join(query)}"


def all_dividends_url(
    *, start: dt.date | str | None = None, end: dt.date | str | None = None
) -> str:
    """全市场分红。给 `start`/`end` 即按 `ex_dividend_date` 限区间。"""
    query = ["sort=ex_dividend_date.asc", f"limit={STOCKS_V1_LIMIT}"]
    if start is not None:
        query.append(f"ex_dividend_date.gte={_assert_iso_date(start, field='start')}")
    if end is not None:
        query.append(f"ex_dividend_date.lte={_assert_iso_date(end, field='end')}")
    return f"{REST_BASE}/stocks/v1/dividends?{'&'.join(query)}"


def ticker_events_url(figi: str) -> str:
    """某 composite FIGI 的 ticker 变更事件（只取 `ticker_change`）。"""
    return f"{REST_BASE}/vX/reference/tickers/{assert_figi(figi)}/events?types=ticker_change"


# --------------------------------------------------------------------------- instrument_id


def instrument_id_for(
    *, composite_figi: str | None, ticker: str, delisted: dt.date | None
) -> tuple[str, str]:
    """`(instrument_id, 规则名)`。稳定、不复用、可解释（QNT-26 §3.2）。

    - 有 composite FIGI → `us:figi:<FIGI>`（`figi`）。FIGI 由 OpenFIGI 分配且不复用。
    - 没有 FIGI 的已退市代码 → `us:ticker:<T>:delisted=<date>`（`ticker_delisted`）：
      同一代码可能先后属于不同公司，退市日把它们区分开。
    - 没有 FIGI 的在市代码 → `us:ticker:<T>:active`（`ticker_active`）。它**不是**永久 id：
      将来退市后同一实体会以 `…:delisted=<date>` 出现为新行——这是版本化表的新行，
      不是对旧行的改写（ADR-0002）。规则名随行落盘，下游据此判断能否跨批次关联。
    """
    if composite_figi:
        return f"us:figi:{assert_figi(composite_figi)}", "figi"
    if delisted is not None:
        return f"us:ticker:{ticker}:delisted={delisted.isoformat()}", "ticker_delisted"
    return f"us:ticker:{ticker}:active", "ticker_active"


def _opt_utc(row: dict[str, Any], key: str) -> dt.datetime | None:
    value = row.get(key)
    if value is None:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise SourceFormatError(f"{key} 不是 ISO 时间: {value!r}") from exc
    if parsed.tzinfo is None:
        raise SourceFormatError(f"{key} 无时区: {value!r}")
    return parsed.astimezone(dt.UTC)


#: ETF 类 `type` 取值（Massive ticker types：ETF / ETN / ETV / ETS）。其余按 equity。
_ETF_TYPES: frozenset[str] = frozenset({"ETF", "ETN", "ETV", "ETS"})

#: `meta/instrument_meta`（QNT-26 §3.2 列 + Massive 原始参考字段）。§3.2 规定的列在前，
#: 上游原样字段在后——前者是跨市场口径，后者保留以便重算与核对（不做任何推断）。
INSTRUMENT_META_SCHEMA = pa.schema(
    [
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("instrument_id_rule", pa.string(), nullable=False),
        pa.field("market", pa.string(), nullable=False),
        pa.field("asset_class", pa.string(), nullable=False),
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("symbol_kind", pa.string(), nullable=False),
        pa.field("effective_from", pa.date32(), nullable=True),
        pa.field("effective_to", pa.date32(), nullable=True),
        pa.field("multiplier", pa.float64(), nullable=False),
        pa.field("multiplier_unit", pa.string(), nullable=False),
        pa.field("tick_size", pa.float64(), nullable=True),
        pa.field("tick_rule_ref", pa.string(), nullable=True),
        pa.field("price_limit_kind", pa.string(), nullable=False),
        pa.field("price_limit_params", pa.string(), nullable=True),
        pa.field("settlement_kind", pa.string(), nullable=True),
        pa.field("exercise_style", pa.string(), nullable=True),
        pa.field("expiry_rule", pa.string(), nullable=True),
        pa.field("underlying_id", pa.string(), nullable=True),
        pa.field("calendar_id", pa.string(), nullable=True),
        # ---- Massive 原样字段 ----
        pa.field("name", pa.string(), nullable=True),
        pa.field("active", pa.bool_(), nullable=False),
        pa.field("ticker_type", pa.string(), nullable=True),
        pa.field("upstream_market", pa.string(), nullable=False),
        pa.field("locale", pa.string(), nullable=True),
        pa.field("primary_exchange", pa.string(), nullable=True),
        pa.field("currency_name", pa.string(), nullable=True),
        pa.field("cik", pa.string(), nullable=True),
        pa.field("composite_figi", pa.string(), nullable=True),
        pa.field("share_class_figi", pa.string(), nullable=True),
        pa.field("last_updated_utc", pa.timestamp("us", tz="UTC"), nullable=True),
        pa.field("delisted_utc", pa.timestamp("us", tz="UTC"), nullable=True),
    ]
)


def normalize_tickers(payload: bytes, *, active: bool) -> pa.Table:
    """ticker 全表的一页 → `instrument_meta` 行（按 ticker 升序）。

    `effective_from` 记 null：列表端点不返回上市日（`list_date` 只在单 ticker 详情端点里），
    本卡不为 5 万个代码逐个调详情——宁可空着也不拿 `last_updated_utc` 冒充。
    `effective_to` 取 `delisted_utc` 的纽约日期部分（上游以 UTC 表示当日 04:00/05:00，
    即纽约午夜）。`tick_size` / `tick_rule_ref` 留空：美股 tick 规则（Reg NMS 612，
    2025-11-03 起分档）属规则表，不是逐代码的上游字段。
    """
    where = f"tickers(active={active})"
    parsed: list[dict[str, Any]] = []
    for row in _results(payload):
        ticker = _need(row, "ticker", str, where)
        if not ticker or ticker != ticker.strip():
            raise SourceFormatError(f"{where}: ticker 为空或含空白: {ticker!r}")
        got_active = _need(row, "active", bool, where)
        if got_active is not active:
            raise SourceFormatError(f"{where}: {ticker} 的 active={got_active}，与请求不符")
        delisted_utc = _opt_utc(row, "delisted_utc")
        delisted = delisted_utc.astimezone(_NEW_YORK).date() if delisted_utc else None
        figi = _opt_str(row, "composite_figi") or None
        if figi is not None and _FIGI_RE.fullmatch(figi) is None:
            figi = None  # 上游偶有非 FIGI 值：不拿它当主键，退回 ticker 规则
        instrument_id, rule = instrument_id_for(
            composite_figi=figi, ticker=ticker, delisted=delisted
        )
        ticker_type = _opt_str(row, "type")
        parsed.append(
            {
                "instrument_id": instrument_id,
                "instrument_id_rule": rule,
                "market": "us",
                "asset_class": "etf" if ticker_type in _ETF_TYPES else "equity",
                "symbol": ticker,
                "symbol_kind": "ticker",
                "effective_from": None,
                "effective_to": delisted,
                "multiplier": 1.0,
                "multiplier_unit": "shares",
                "tick_size": None,
                "tick_rule_ref": None,
                "price_limit_kind": "luld",
                "price_limit_params": None,
                "settlement_kind": "physical",
                "exercise_style": None,
                "expiry_rule": None,
                "underlying_id": None,
                "calendar_id": None,
                "name": _opt_str(row, "name"),
                "active": got_active,
                "ticker_type": ticker_type,
                "upstream_market": _need(row, "market", str, where),
                "locale": _opt_str(row, "locale"),
                "primary_exchange": _opt_str(row, "primary_exchange"),
                "currency_name": _opt_str(row, "currency_name"),
                "cik": _opt_str(row, "cik"),
                "composite_figi": _opt_str(row, "composite_figi"),
                "share_class_figi": _opt_str(row, "share_class_figi"),
                "last_updated_utc": _opt_utc(row, "last_updated_utc"),
                "delisted_utc": delisted_utc,
            }
        )
    parsed.sort(key=lambda r: (r["symbol"], r["instrument_id"]))
    columns = {name: [r[name] for r in parsed] for name in INSTRUMENT_META_SCHEMA.names}
    return pa.Table.from_pydict(columns, schema=INSTRUMENT_META_SCHEMA)


#: `meta/adjust_factor`（QNT-26 §3.3，**只存因子不存复权价**）+ 事件原始量。
ADJUST_FACTOR_SCHEMA = pa.schema(
    [
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("instrument_id_rule", pa.string(), nullable=False),
        pa.field("ticker", pa.string(), nullable=False),
        pa.field("ex_date", pa.date32(), nullable=False),
        pa.field("adjust_kind", pa.string(), nullable=False),
        pa.field("factor_kind", pa.string(), nullable=False),
        pa.field("factor_value", pa.float64(), nullable=True),
        pa.field("cash_amount", pa.float64(), nullable=True),
        pa.field("share_ratio", pa.float64(), nullable=True),
        pa.field("direction", pa.string(), nullable=False),
        pa.field("nav_kind", pa.string(), nullable=True),
        pa.field("disclosure_date", pa.date32(), nullable=True),
        pa.field("adjustment_memo_ref", pa.string(), nullable=True),
        # ---- Massive 原样字段 ----
        pa.field("event_id", pa.string(), nullable=False),
        pa.field("upstream_adjustment_type", pa.string(), nullable=True),
        pa.field("upstream_historical_adjustment_factor", pa.float64(), nullable=True),
        pa.field("split_from", pa.float64(), nullable=True),
        pa.field("split_to", pa.float64(), nullable=True),
        pa.field("currency", pa.string(), nullable=True),
        pa.field("record_date", pa.date32(), nullable=True),
        pa.field("pay_date", pa.date32(), nullable=True),
        pa.field("frequency", pa.int64(), nullable=True),
        pa.field("distribution_type", pa.string(), nullable=True),
        pa.field("split_adjusted_cash_amount", pa.float64(), nullable=True),
    ]
)

#: ticker → instrument_id 的解析器（由调用方用同一次运行的 ticker 全表构造）。
TickerResolver = Any  # Callable[[str, dt.date], tuple[str, str]]


def _fallback_resolver(ticker: str, _on: dt.date) -> tuple[str, str]:
    return f"us:ticker:{ticker}", "ticker_unresolved"


def _adjust_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = dict.fromkeys(ADJUST_FACTOR_SCHEMA.names)
    row.update(overrides)
    return row


def normalize_all_splits(payload: bytes, *, resolve: TickerResolver = None) -> pa.Table:
    """全市场拆股一页 → `adjust_factor` 行。

    `factor_value = split_from / split_to`：对 `ex_date` 之前的价格乘以它（前复权口径，
    `direction='forward'`）。上游若给了 `historical_adjustment_factor` 原样另存一列——那是
    **累积**因子，会随后续事件变化，不能当本事件的因子（只 insert 的湖里存它会过时）。
    `adjustment_type='stock_dividend'` 记 `adjust_kind='stock_dividend'`，其余记 `split`。
    """
    resolve = resolve or _fallback_resolver
    where = "拆股"
    out = []
    for row in _results(payload):
        ticker = _need(row, "ticker", str, where)
        ex_date = dt.date.fromisoformat(_need(row, "execution_date", str, where))
        split_from = float(_need(row, "split_from", (int, float), where))
        split_to = float(_need(row, "split_to", (int, float), where))
        if split_from <= 0 or split_to <= 0:
            raise SourceFormatError(
                f"{where}: {ticker} {ex_date} 比例非正: {split_from}/{split_to}"
            )
        adj_type = _opt_str(row, "adjustment_type")
        instrument_id, rule = resolve(ticker, ex_date)
        out.append(
            _adjust_row(
                instrument_id=instrument_id,
                instrument_id_rule=rule,
                ticker=ticker,
                ex_date=ex_date,
                adjust_kind="stock_dividend" if adj_type == "stock_dividend" else "split",
                factor_kind="ratio",
                factor_value=split_from / split_to,
                share_ratio=split_to / split_from,
                direction="forward",
                event_id=_need(row, "id", str, where),
                upstream_adjustment_type=adj_type,
                upstream_historical_adjustment_factor=_opt_float(
                    row, "historical_adjustment_factor"
                ),
                split_from=split_from,
                split_to=split_to,
            )
        )
    out.sort(key=lambda r: (r["ex_date"], r["ticker"], r["event_id"]))
    return pa.Table.from_pylist(out, schema=ADJUST_FACTOR_SCHEMA)


def normalize_all_dividends(payload: bytes, *, resolve: TickerResolver = None) -> pa.Table:
    """全市场分红一页 → `adjust_factor` 行（`adjust_kind='cash_dividend'`）。

    `factor_value` 只在上游给了 `historical_adjustment_factor` 时才有值，否则 null：
    现金分红的比例因子要用除息前一日收盘价算，那是**查询期**的派生量（QNT-26 §3.3：
    只存因子与原始事件量，`cash_amount` 保留以便重算）。`disclosure_date` 记
    `declaration_date`（公告日，信息集边界）。
    """
    resolve = resolve or _fallback_resolver
    where = "分红"
    out = []
    for row in _results(payload):
        ticker = _need(row, "ticker", str, where)
        ex_date = dt.date.fromisoformat(_need(row, "ex_dividend_date", str, where))
        instrument_id, rule = resolve(ticker, ex_date)
        historical = _opt_float(row, "historical_adjustment_factor")
        out.append(
            _adjust_row(
                instrument_id=instrument_id,
                instrument_id_rule=rule,
                ticker=ticker,
                ex_date=ex_date,
                adjust_kind="cash_dividend",
                factor_kind="ratio",
                factor_value=None,
                cash_amount=float(_need(row, "cash_amount", (int, float), where)),
                direction="forward",
                disclosure_date=_opt_date(row, "declaration_date"),
                event_id=_need(row, "id", str, where),
                upstream_adjustment_type=_opt_str(row, "distribution_type"),
                upstream_historical_adjustment_factor=historical,
                currency=_opt_str(row, "currency"),
                record_date=_opt_date(row, "record_date"),
                pay_date=_opt_date(row, "pay_date"),
                frequency=_opt_int(row, "frequency"),
                distribution_type=_opt_str(row, "distribution_type"),
                split_adjusted_cash_amount=_opt_float(row, "split_adjusted_cash_amount"),
            )
        )
    out.sort(key=lambda r: (r["ex_date"], r["ticker"], r["event_id"]))
    return pa.Table.from_pylist(out, schema=ADJUST_FACTOR_SCHEMA)


#: `meta/ticker_events`（本卡新增 meta 表：只有 `ticker_change` 一类）。
TICKER_EVENTS_SCHEMA = pa.schema(
    [
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("composite_figi", pa.string(), nullable=False),
        pa.field("cik", pa.string(), nullable=True),
        pa.field("name", pa.string(), nullable=True),
        pa.field("event_date", pa.date32(), nullable=False),
        pa.field("event_type", pa.string(), nullable=False),
        pa.field("ticker", pa.string(), nullable=False),
    ]
)


def normalize_ticker_events(payload: bytes, *, figi: str) -> pa.Table:
    """一个 FIGI 的事件 → `ticker_events` 行（按日期升序）。

    `results` 是**对象**（不是数组）：`{name, composite_figi, cik, events:[…]}`。响应里的
    `composite_figi` 必须等于请求的 FIGI；只收 `type='ticker_change'`，其余类型出现即拒绝
    （我们请求时已按 `types=ticker_change` 过滤，出现别的说明上游口径变了）。
    """
    assert_figi(figi)
    doc = _load(payload)
    status = doc.get("status")
    if status is not None and status not in OK_STATUSES:
        raise SourceFormatError(f"ticker 事件 status={status!r}")
    results = doc.get("results")
    if not isinstance(results, dict):
        raise SourceFormatError(f"ticker 事件 results 应为对象，得到 {type(results).__name__}")
    where = f"{figi} ticker 事件"
    got = _opt_str(results, "composite_figi")
    if got is not None and got != figi:
        raise SourceFormatError(f"{where}: 响应 FIGI {got!r} 与请求不符")
    events = results.get("events") or []
    if not isinstance(events, list):
        raise SourceFormatError(f"{where}: events 应为数组")
    out = []
    for ev in events:
        if not isinstance(ev, dict):
            raise SourceFormatError(f"{where}: 事件应为对象")
        kind = _need(ev, "type", str, where)
        if kind != "ticker_change":
            raise SourceFormatError(f"{where}: 未请求的事件类型 {kind!r}")
        change = _need(ev, "ticker_change", dict, where)
        out.append(
            {
                "instrument_id": f"us:figi:{figi}",
                "composite_figi": figi,
                "cik": _opt_str(results, "cik"),
                "name": _opt_str(results, "name"),
                "event_date": dt.date.fromisoformat(_need(ev, "date", str, where)),
                "event_type": kind,
                "ticker": _need(change, "ticker", str, where),
            }
        )
    out.sort(key=lambda r: (r["event_date"], r["ticker"]))
    return pa.Table.from_pylist(out, schema=TICKER_EVENTS_SCHEMA)


def ticker_resolver(instrument_meta: pa.Table):
    """由 `instrument_meta` 行构造 `(ticker, on_date) -> (instrument_id, rule)`。

    同一 ticker 可能对应多行（代码复用）：取 `on_date` 当天仍在市的那一行——在市行
    （`effective_to` 为空）或 `effective_to >= on_date` 的退市行中，`effective_to` 最早者。
    无匹配 → `us:ticker:<T>`（`ticker_unresolved`），规则名落盘，下游可识别。
    """
    by_ticker: dict[str, list[tuple[dt.date | None, str]]] = {}
    for sym, to, iid in zip(
        instrument_meta.column("symbol").to_pylist(),
        instrument_meta.column("effective_to").to_pylist(),
        instrument_meta.column("instrument_id").to_pylist(),
        strict=True,
    ):
        by_ticker.setdefault(sym, []).append((to, iid))

    def resolve(ticker: str, on: dt.date) -> tuple[str, str]:
        candidates = [
            (to or dt.date.max, iid)
            for to, iid in by_ticker.get(ticker, [])
            if to is None or to >= on
        ]
        if not candidates:
            return _fallback_resolver(ticker, on)
        return min(candidates)[1], "resolved_by_ticker"

    return resolve
