"""合成 Tushare Pro 响应生成器（QNT-48 阶段 1）——`synthetic: true`。

这些 fixture **不是录制**：阶段 1 无 token，一行真实响应都没有见过。字段名、类型与
信封结构逐条按公开文档手写，数值是确定性伪造的（固定种子的纯算术，无 `random`）。

    uv run --package quantime-data python fixtures/tushare_pro/synth_gen.py          # 重新生成
    uv run --package quantime-data python fixtures/tushare_pro/synth_gen.py --check  # 核对未漂移

文档来源（访问日期 2026-09-23）
------------------------------
- HTTP 协议 / 信封：https://tushare.pro/document/1?doc_id=130
- `daily` 日线：      https://tushare.pro/document/2?doc_id=27
- `adj_factor`：      https://tushare.pro/document/2?doc_id=28
- `daily_basic`：     https://tushare.pro/document/2?doc_id=32
- `trade_cal`：       https://tushare.pro/document/2?doc_id=26
- `stock_basic`：     https://tushare.pro/document/2?doc_id=25

阶段 2 会用**脱敏**的真实录制替换/补充这些文件（去掉 token、账户信息、请求/响应头），
届时 `MANIFEST.json` 的 `synthetic` 翻为 false 并登记 provenance。
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

#: 文档访问日期——fixture 的"版本"锚点。
DOC_ACCESSED = "2026-09-23"

DOC_URLS = {
    "protocol": "https://tushare.pro/document/1?doc_id=130",
    "daily": "https://tushare.pro/document/2?doc_id=27",
    "adj_factor": "https://tushare.pro/document/2?doc_id=28",
    "daily_basic": "https://tushare.pro/document/2?doc_id=32",
    "trade_cal": "https://tushare.pro/document/2?doc_id=26",
    "stock_basic": "https://tushare.pro/document/2?doc_id=25",
}

#: 合成的标的与区间。两只票、十个自然日——够覆盖排序、缺口、多标的，又小到能肉眼核对。
TS_CODES = ("000001.SZ", "600000.SH")
START = dt.date(2026, 9, 1)
DAYS = 10

#: A 股涨跌停 ±10%，合成价的日变动刻意压在 ±2% 以内，免得 fixture 自身看起来像异常数据。
_BASE_PRICE = {"000001.SZ": 12.00, "600000.SH": 8.50}


def _round2(x: float) -> float:
    return round(x + 1e-12, 2)


def _is_weekday(day: dt.date) -> bool:
    """合成日历：周一–周五为交易日。真实 A 股还有法定节假日，阶段 2 的录制会带上。"""
    return day.weekday() < 5


def _trading_days() -> list[dt.date]:
    return [
        START + dt.timedelta(days=i)
        for i in range(DAYS)
        if _is_weekday(START + dt.timedelta(days=i))
    ]


def _ymd(day: dt.date) -> str:
    return day.strftime("%Y%m%d")


def _price_series(ts_code: str) -> dict[dt.date, tuple[float, float, float, float, float]]:
    """确定性 OHLC + 前收：第 i 天收盘 = 基价 × (1 + 0.004·((i%5) − 2))。"""
    base = _BASE_PRICE[ts_code]
    out: dict[dt.date, tuple[float, float, float, float, float]] = {}
    prev = base
    for i, day in enumerate(_trading_days()):
        close = _round2(base * (1 + 0.004 * ((i % 5) - 2)))
        open_ = _round2((prev + close) / 2)
        high = _round2(max(open_, close) * 1.006)
        low = _round2(min(open_, close) * 0.994)
        out[day] = (open_, high, low, close, prev)
        prev = close
    return out


def envelope(
    fields: list[str], items: list[list], *, code: int = 0, msg: str | None = None
) -> dict:
    """文档 doc_id=130 的信封：`{"code":0,"msg":null,"data":{"fields":[],"items":[]}}`。"""
    return {"code": code, "msg": msg, "data": {"fields": fields, "items": items}}


def build_daily() -> dict:
    fields = [
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "change",
        "pct_chg",
        "vol",
        "amount",
    ]
    items: list[list] = []
    for ts_code in TS_CODES:
        series = _price_series(ts_code)
        for i, (day, (o, h, low_, c, prev)) in enumerate(series.items()):
            change = _round2(c - prev)
            vol = float(1_200_00 + i * 1_000)  # 手
            items.append(
                [
                    ts_code,
                    _ymd(day),
                    o,
                    h,
                    low_,
                    c,
                    prev,
                    change,
                    round(change / prev * 100, 4),
                    vol,
                    _round2(vol * c * 100 / 1000),  # 千元
                ]
            )
    # 上游实测按 trade_date **倒序**返回；fixture 照此摆放，好让归一化的排序真的被测到。
    items.reverse()
    return envelope(fields, items)


def build_adj_factor() -> dict:
    fields = ["ts_code", "trade_date", "adj_factor"]
    items: list[list] = []
    for ts_code in TS_CODES:
        for i, day in enumerate(_trading_days()):
            # 第 5 个交易日除权一次，因子跳一档——复权逻辑的下游测试需要这个台阶。
            items.append([ts_code, _ymd(day), round(1.0 if i < 5 else 1.0526, 4)])
    items.reverse()
    return envelope(fields, items)


def build_daily_basic() -> dict:
    fields = [
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
    ]
    items: list[list] = []
    for ts_code in TS_CODES:
        series = _price_series(ts_code)
        total_share = 194_056.0 if ts_code == "000001.SZ" else 293_520.0  # 万股
        for i, (day, (_o, _h, _l, c, _p)) in enumerate(series.items()):
            float_share = round(total_share * 0.98, 2)
            items.append(
                [
                    ts_code,
                    _ymd(day),
                    c,
                    round(0.35 + i * 0.01, 4),
                    round(0.36 + i * 0.01, 4),
                    round(0.9 + i * 0.02, 2),
                    round(5.4 + i * 0.05, 4),
                    round(5.2 + i * 0.05, 4),
                    round(0.55 + i * 0.002, 4),
                    round(1.8 + i * 0.01, 4),
                    round(2.4 + i * 0.01, 4),
                    total_share,
                    float_share,
                    round(total_share * 0.62, 2),
                    round(total_share * c, 2),
                    round(float_share * c, 2),
                ]
            )
    items.reverse()
    return envelope(fields, items)


def build_trade_cal() -> dict:
    """含休市日——`is_open=0` 的行是日历的一半价值，过滤掉就没法判断"该有数据却没有"。"""
    fields = ["exchange", "cal_date", "is_open", "pretrade_date"]
    items: list[list] = []
    for exchange in ("SSE", "SZSE"):
        prev_open: dt.date | None = None
        for i in range(DAYS):
            day = START + dt.timedelta(days=i)
            is_open = 1 if _is_weekday(day) else 0
            items.append(
                [
                    exchange,
                    _ymd(day),
                    str(is_open),
                    _ymd(prev_open) if prev_open else None,
                ]
            )
            if is_open:
                prev_open = day
    return envelope(fields, items)


def build_stock_basic() -> dict:
    fields = [
        "ts_code",
        "symbol",
        "name",
        "area",
        "industry",
        "market",
        "exchange",
        "curr_type",
        "list_status",
        "list_date",
        "delist_date",
    ]
    items = [
        [
            "000001.SZ",
            "000001",
            "平安银行",
            "深圳",
            "银行",
            "主板",
            "SZSE",
            "CNY",
            "L",
            "19910403",
            None,
        ],
        [
            "600000.SH",
            "600000",
            "浦发银行",
            "上海",
            "银行",
            "主板",
            "SSE",
            "CNY",
            "L",
            "19991110",
            None,
        ],
    ]
    return envelope(fields, items)


#: 文件名 → (构造函数, 对应文档键)。
BUILDERS = {
    "daily.json": (build_daily, "daily"),
    "adj_factor.json": (build_adj_factor, "adj_factor"),
    "daily_basic.json": (build_daily_basic, "daily_basic"),
    "trade_cal.json": (build_trade_cal, "trade_cal"),
    "stock_basic.json": (build_stock_basic, "stock_basic"),
}


def _render(payload: dict) -> bytes:
    """确定性序列化：同一份数据永远产出同样的字节，`--check` 才有意义。"""
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _manifest(rendered: dict[str, bytes]) -> bytes:
    entries = [
        {
            "api_name": name.removesuffix(".json"),
            "doc_url": DOC_URLS[BUILDERS[name][1]],
            "file": name,
            "sha256": hashlib.sha256(blob).hexdigest(),
            "size": len(blob),
        }
        for name, blob in sorted(rendered.items())
    ]
    payload = {
        "doc_accessed": DOC_ACCESSED,
        "files": entries,
        "generator": "fixtures/tushare_pro/synth_gen.py",
        "note": (
            "按公开文档手写的合成响应，非录制；不含 token、账户信息、请求/响应头。"
            "阶段 2 用脱敏真实录制替换/补充后，synthetic 翻为 false。"
        ),
        "protocol_doc_url": DOC_URLS["protocol"],
        "synthetic": True,
    }
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成/核对 Tushare Pro 合成 fixture")
    parser.add_argument("--check", action="store_true", help="只核对，不写盘；有漂移则 exit 1")
    args = parser.parse_args(argv)

    rendered = {name: _render(build()) for name, (build, _doc) in BUILDERS.items()}
    rendered["MANIFEST.json"] = _manifest({k: v for k, v in rendered.items()})

    drift = []
    for name, blob in sorted(rendered.items()):
        path = HERE / name
        if args.check:
            if not path.exists() or path.read_bytes() != blob:
                drift.append(name)
        else:
            path.write_bytes(blob)
    if args.check and drift:
        print(f"fixture 与生成器不一致: {drift}", file=sys.stderr)
        return 1
    print("OK" if args.check else f"wrote {len(rendered)} file(s) to {HERE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
