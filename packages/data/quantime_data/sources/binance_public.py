"""Binance 公开归档数据源（ADR-0003 §9.5「第一版数据源用 Vision 归档 + 无 key 镜像」）。

**无 key、无签名、只读**。本模块只做三件事：拼 URL、解 zip/CSV、归一化成 Arrow 表。
它自己**不出网**——字节由调用方经 `transport.PublicTransport` 取来传入，
因此归一化逻辑在测试里完全离线可跑。

覆盖的三类数据（卡范围）：

| datatype | 上游前缀 | 周期 | 说明 |
|---|---|---|---|
| `kline` | `data/{spot,futures/um}/monthly/klines/<SYM>/<freq>/` | `1h`/`4h`/`1d` | 12 列 |
| `funding` | `data/futures/um/monthly/fundingRate/<SYM>/` | `event` | 3 列，8h 一条 |
| `open_interest` | `data/futures/um/daily/metrics/<SYM>/` | `5m` | metrics 8 列，取 OI 两列 |

**OI 的窗口**：REST `/futures/data/openInterestHist` 官方只留最近 1 个月，
但 Vision 的 `metrics` 日归档没有这个限制——按日文件可取更早的历史。本模块走 Vision，
因此 OI 不受 30 天限制；实际取到哪天以上游文件存在与否为准（缺档由缺口报告如实记账）。

上游归档**可被替换**（Vision README Updates），所以重放只依赖本地 `raw/` 副本与
`ingestion_batch.content_sha256`，永不把上游 URL 当快照（ADR-0003 §4.6）。
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import zipfile
from collections.abc import Iterator

import pyarrow as pa
from quantime_core.allowlist import BINANCE_VISION_ARCHIVE, BINANCE_VISION_SPOT_MIRROR
from quantime_core.paths import AssetClass, DataType, Freq

#: 本源使用的 host —— 从 allowlist **引用**而非复制字面量（`core/allowlist.py` 是唯一出处，
#: 静态守卫据此 grep）。Binance 主 host 不在此列：美国节点 451，ADR-0003 §9.5 明确不使用。
HOSTS: tuple[str, ...] = (BINANCE_VISION_ARCHIVE.host, BINANCE_VISION_SPOT_MIRROR.host)

#: 归档基址（host 同样来自 allowlist 条目）。
ARCHIVE_BASE = f"https://{BINANCE_VISION_ARCHIVE.host}"

#: `source` 列的取值（同时是 `data/raw/<source>/` 与 `source=` 分区的分量）。
SOURCE = "binance_vision"

#: `source_version`：上游没有版本号，用「归档布局版本」固定字面量标注本适配器的解析口径。
SOURCE_VERSION = "vision-archive-v1"

#: 本源支持的 K 线周期（卡范围）。Vision 文件名口径，`1mo` 而非 `1M`。
SUPPORTED_KLINE_FREQS: frozenset[str] = frozenset({"1h", "4h", "1d"})

#: metrics（OI）归档的采样间隔——用于缺口检测的期望步长。
METRICS_INTERVAL = dt.timedelta(minutes=5)

#: fundingRate 归档的标称间隔（`funding_interval_hours` 列给出每行实际值）。
FUNDING_INTERVAL = dt.timedelta(hours=8)


class SourceFormatError(ValueError):
    """上游 CSV 的列数/表头与本适配器的解析口径不符——宁可失败也不猜。"""


def _um_or_spot(asset_class: AssetClass | str) -> str:
    ac = AssetClass(asset_class)
    if ac is AssetClass.SPOT:
        return "spot"
    if ac is AssetClass.PERP:
        return "futures/um"
    raise ValueError(f"本源只覆盖 spot 与 USDT 永续（perp），得到 {ac}")


def kline_url(asset_class: AssetClass | str, symbol: str, freq: Freq | str, month: str) -> str:
    """月度 K 线 zip 的 URL。`month` 形如 `2026-08`。"""
    freq = Freq(freq)
    if str(freq) not in SUPPORTED_KLINE_FREQS:
        raise ValueError(f"本卡范围只含 {sorted(SUPPORTED_KLINE_FREQS)}，得到 {freq}")
    market = _um_or_spot(asset_class)
    return (
        f"{ARCHIVE_BASE}/data/{market}/monthly/klines/{symbol}/{freq}/{symbol}-{freq}-{month}.zip"
    )


def funding_url(symbol: str, month: str) -> str:
    """月度 fundingRate zip 的 URL（只有 USD-M 永续有）。"""
    return (
        f"{ARCHIVE_BASE}/data/futures/um/monthly/fundingRate/{symbol}/"
        f"{symbol}-fundingRate-{month}.zip"
    )


def metrics_url(symbol: str, day: dt.date) -> str:
    """日度 metrics zip 的 URL（含 OI；只有 USD-M 永续有）。"""
    return (
        f"{ARCHIVE_BASE}/data/futures/um/daily/metrics/{symbol}/"
        f"{symbol}-metrics-{day.isoformat()}.zip"
    )


def checksum_url(zip_url: str) -> str:
    """每个 zip 旁的 `.CHECKSUM`（sha256）。"""
    return zip_url + ".CHECKSUM"


def parse_checksum(payload: bytes) -> str:
    """`.CHECKSUM` 正文形如 `<sha256>  <filename>`，取前一段。"""
    text = payload.decode("utf-8").strip()
    if not text:
        raise SourceFormatError("空的 .CHECKSUM")
    digest = text.split()[0].lower()
    if len(digest) != 64 or not all(c in "0123456789abcdef" for c in digest):
        raise SourceFormatError(f".CHECKSUM 不是 sha256 十六进制: {digest!r}")
    return digest


def _csv_rows(payload: bytes) -> Iterator[list[str]]:
    """解出 zip 内唯一 CSV 的行。Vision 的 zip 每个只含一个同名 CSV。"""
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = [n for n in zf.namelist() if n.endswith(".csv")]
        if len(names) != 1:
            raise SourceFormatError(f"zip 内 CSV 数量应为 1，得到 {names}")
        with zf.open(names[0]) as fh:
            yield from csv.reader(io.TextIOWrapper(fh, encoding="utf-8"))


def _ms_to_utc(value: str) -> dt.datetime:
    """毫秒 epoch → UTC datetime（微秒精度，与 Parquet `timestamp('us')` 对齐）。

    Vision 近期文件的部分时间戳是**微秒**量级（如 fundingRate 的 `calc_time`
    在某些月份是 16 位）。按位数判别，避免把 2026 年的行解析成 57000 年。
    """
    raw = int(value)
    if raw >= 10**15:  # 微秒
        return dt.datetime.fromtimestamp(raw / 1_000_000, tz=dt.UTC)
    return dt.datetime.fromtimestamp(raw / 1000, tz=dt.UTC)


#: 归一化 K 线 schema（12 列 CSV → 显式类型；`ignore` 列丢弃）。
KLINE_SCHEMA = pa.schema(
    [
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("open_time", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("close_time", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("open", pa.float64(), nullable=False),
        pa.field("high", pa.float64(), nullable=False),
        pa.field("low", pa.float64(), nullable=False),
        pa.field("close", pa.float64(), nullable=False),
        pa.field("volume", pa.float64(), nullable=False),
        pa.field("quote_volume", pa.float64(), nullable=False),
        pa.field("trade_count", pa.int64(), nullable=False),
        pa.field("taker_buy_volume", pa.float64(), nullable=False),
        pa.field("taker_buy_quote_volume", pa.float64(), nullable=False),
    ]
)

FUNDING_SCHEMA = pa.schema(
    [
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("calc_time", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("funding_interval_hours", pa.int64(), nullable=False),
        pa.field("last_funding_rate", pa.float64(), nullable=False),
    ]
)

OPEN_INTEREST_SCHEMA = pa.schema(
    [
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("create_time", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("sum_open_interest", pa.float64(), nullable=False),
        pa.field("sum_open_interest_value", pa.float64(), nullable=False),
    ]
)

#: 各 CSV 的表头（有表头的文件用它校验，无表头的老文件按列数校验）。
_KLINE_HEADER = (
    "open_time,open,high,low,close,volume,close_time,"
    "quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore"
)
_FUNDING_HEADER = "calc_time,funding_interval_hours,last_funding_rate"
_METRICS_HEADER = (
    "create_time,symbol,sum_open_interest,sum_open_interest_value,"
    "count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,"
    "count_long_short_ratio,sum_taker_long_short_vol_ratio"
)


def _strip_header(rows: list[list[str]], expected_header: str, n_cols: int) -> list[list[str]]:
    """丢掉表头行（若有）并校验列数。

    Vision 的老文件无表头、新文件有表头，两种都要吃下；列数不符一律失败——
    上游改了布局时，安静地错位解析比失败危险得多。
    """
    if not rows:
        return []
    header = ",".join(c.strip() for c in rows[0])
    body = rows[1:] if header == expected_header else rows
    bad = [i for i, r in enumerate(body) if len(r) != n_cols]
    if bad:
        raise SourceFormatError(
            f"CSV 列数应为 {n_cols}，第 {bad[:3]} 行不符（上游布局可能已变，拒绝猜测）"
        )
    return body


def normalize_klines(payload: bytes, *, symbol: str) -> pa.Table:
    """K 线 zip → 归一化表（按 `open_time` 升序，去掉 `ignore` 列）。"""
    body = _strip_header(list(_csv_rows(payload)), _KLINE_HEADER, 12)
    rows = sorted(body, key=lambda r: int(r[0]))
    return pa.Table.from_pydict(
        {
            "symbol": [symbol] * len(rows),
            "open_time": [_ms_to_utc(r[0]) for r in rows],
            "close_time": [_ms_to_utc(r[6]) for r in rows],
            "open": [float(r[1]) for r in rows],
            "high": [float(r[2]) for r in rows],
            "low": [float(r[3]) for r in rows],
            "close": [float(r[4]) for r in rows],
            "volume": [float(r[5]) for r in rows],
            "quote_volume": [float(r[7]) for r in rows],
            "trade_count": [int(r[8]) for r in rows],
            "taker_buy_volume": [float(r[9]) for r in rows],
            "taker_buy_quote_volume": [float(r[10]) for r in rows],
        },
        schema=KLINE_SCHEMA,
    )


def normalize_funding(payload: bytes, *, symbol: str) -> pa.Table:
    """fundingRate zip → 归一化表（按 `calc_time` 升序）。"""
    body = _strip_header(list(_csv_rows(payload)), _FUNDING_HEADER, 3)
    rows = sorted(body, key=lambda r: int(r[0]))
    return pa.Table.from_pydict(
        {
            "symbol": [symbol] * len(rows),
            "calc_time": [_ms_to_utc(r[0]) for r in rows],
            "funding_interval_hours": [int(r[1]) for r in rows],
            "last_funding_rate": [float(r[2]) for r in rows],
        },
        schema=FUNDING_SCHEMA,
    )


def normalize_open_interest(payload: bytes, *, symbol: str) -> pa.Table:
    """metrics zip → OI 表（只取 OI 两列；`create_time` 是 `YYYY-MM-DD HH:MM:SS` UTC）。

    上游 metrics 文件**不保证按时间有序**（实测 2026-09-15 的 BTCUSDT 文件即乱序），
    因此这里显式排序——否则确定性 writer 产出的字节会随上游行序变化。
    """
    body = _strip_header(list(_csv_rows(payload)), _METRICS_HEADER, 8)
    parsed = [
        (
            dt.datetime.fromisoformat(r[0]).replace(tzinfo=dt.UTC),
            r[1],
            float(r[2]),
            float(r[3]),
        )
        for r in body
    ]
    parsed.sort(key=lambda t: t[0])
    return pa.Table.from_pydict(
        {
            "symbol": [symbol] * len(parsed),
            "create_time": [p[0] for p in parsed],
            "sum_open_interest": [p[2] for p in parsed],
            "sum_open_interest_value": [p[3] for p in parsed],
        },
        schema=OPEN_INTEREST_SCHEMA,
    )


#: `datatype → (时间列, 期望步长)`，缺口检测用。`None` 步长表示不做等距检查。
TIME_COLUMN: dict[str, str] = {
    str(DataType.KLINE): "open_time",
    str(DataType.FUNDING): "calc_time",
    str(DataType.OPEN_INTEREST): "create_time",
}

#: K 线周期 → 期望步长。
FREQ_STEP: dict[str, dt.timedelta] = {
    "1h": dt.timedelta(hours=1),
    "4h": dt.timedelta(hours=4),
    "1d": dt.timedelta(days=1),
}
