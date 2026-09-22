#!/usr/bin/env python3
"""基准输入生成器（ADR-0003 §5.1）。

`synthetic: true` —— 本脚本只生成合成数据，不接网络、不下载任何行情
（AGENTS.md §2：`fixtures/` 只放合成数据；生成脚本入库，生成物不入库）。

合成规则原文照 §5.1：几何布朗运动日 K（`mu=0`、`sigma=0.02/√252`、`open=prev_close`、
`high/low = close·(1±|N(0,0.01)|)`、`volume ~ LogNormal(12, 1)`），`freq=1d`、
`market=crypto/asset_class=spot`，按 `CRYPTO_24_7` 日历取连续 1,260 个自然日。

两个 hash 分离（§5.1）：
  (a) `payload_sha256` —— 纯业务列 `symbol, ts, open, high, low, close, volume` 的
      确定性 Parquet 序列化 sha256，**不含** ADR-0002 provenance 列；断言等于
      `EXPECTED.json`。
  (b) `content_sha256` —— payload 经 §4.3 摄取写成 batch 后的文件 sha，含
      `ingested_at/run_id/batch_id`，每次不同，只记录不比较。

用法：
    uv run python fixtures/bench/bench_gen.py --print-sha
    uv run python fixtures/bench/bench_gen.py --mode vision-zip --out <dir>
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pyarrow as pa
from quantime_core import parquet_io

#: 纯业务列的固定列序（§5.1「固定列序与 dtype」）。
PAYLOAD_COLUMNS: tuple[str, ...] = ("symbol", "ts", "open", "high", "low", "close", "volume")

PAYLOAD_SCHEMA = pa.schema(
    [
        pa.field("symbol", pa.string(), nullable=False),
        pa.field("ts", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("open", pa.float64(), nullable=False),
        pa.field("high", pa.float64(), nullable=False),
        pa.field("low", pa.float64(), nullable=False),
        pa.field("close", pa.float64(), nullable=False),
        pa.field("volume", pa.float64(), nullable=False),
    ]
)

DEFAULT_SEED = 20260920
DEFAULT_SYMBOLS = 1000
DEFAULT_DAYS = 1260
DEFAULT_START = "2021-01-04"
INITIAL_PRICE = 100.0

EXPECTED_PATH = Path(__file__).with_name("EXPECTED.json")


def symbol_names(n: int) -> list[str]:
    """`SYN0000USDT` … 固定命名，与 seed 无关，保证列值可复现。"""
    return [f"SYN{i:04d}USDT" for i in range(n)]


def generate_payload(
    *,
    seed: int = DEFAULT_SEED,
    symbols: int = DEFAULT_SYMBOLS,
    days: int = DEFAULT_DAYS,
    start: str = DEFAULT_START,
) -> pa.Table:
    """生成纯业务列表（不含 provenance）。同参数两次调用逐字节相同。"""
    rng = np.random.default_rng(seed)
    sigma = 0.02 / np.sqrt(252.0)

    # CRYPTO_24_7：连续自然日，无休市。
    start_date = dt.date.fromisoformat(start)
    ts = np.array(
        [
            dt.datetime.combine(start_date + dt.timedelta(days=i), dt.time(), tzinfo=dt.UTC)
            for i in range(days)
        ]
    )

    # 一次性抽满全部随机量，抽取顺序固定 → 结果只由 seed 决定。
    shocks = rng.normal(loc=0.0, scale=sigma, size=(symbols, days))
    hi_noise = np.abs(rng.normal(loc=0.0, scale=0.01, size=(symbols, days)))
    lo_noise = np.abs(rng.normal(loc=0.0, scale=0.01, size=(symbols, days)))
    volume = rng.lognormal(mean=12.0, sigma=1.0, size=(symbols, days))

    # mu=0 的 GBM：close_t = close_{t-1} · exp(-σ²/2 + σ·z)
    log_steps = -0.5 * sigma**2 + shocks
    close = INITIAL_PRICE * np.exp(np.cumsum(log_steps, axis=1))

    # open = prev_close（首日 open = 初始价）
    open_ = np.empty_like(close)
    open_[:, 0] = INITIAL_PRICE
    open_[:, 1:] = close[:, :-1]

    high = close * (1.0 + hi_noise)
    low = close * (1.0 - lo_noise)
    # 保证 OHLC 自洽：high/low 必须覆盖 open 与 close。
    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))

    names = symbol_names(symbols)
    return pa.Table.from_arrays(
        [
            pa.array(np.repeat(np.array(names, dtype=object), days).tolist(), type=pa.string()),
            pa.array(np.tile(ts, symbols).tolist(), type=pa.timestamp("us", tz="UTC")),
            pa.array(open_.reshape(-1), type=pa.float64()),
            pa.array(high.reshape(-1), type=pa.float64()),
            pa.array(low.reshape(-1), type=pa.float64()),
            pa.array(close.reshape(-1), type=pa.float64()),
            pa.array(volume.reshape(-1), type=pa.float64()),
        ],
        schema=PAYLOAD_SCHEMA,
    )


def payload_sha256(table: pa.Table) -> str:
    """§5.1 (a)：纯业务列的确定性 Parquet 序列化 sha256。"""
    return parquet_io.table_sha256(table, PAYLOAD_COLUMNS)


def generate_vision_zip(
    *, seed: int = DEFAULT_SEED, pairs: int = 300, days: int = 31, start: str = DEFAULT_START
) -> bytes:
    """合成 Vision 风格 zip（§5.1 摄取基准输入；CSV 列序与 Vision 一致，不走网络）。

    Vision 日 K CSV 列序：open_time, open, high, low, close, volume, close_time,
    quote_volume, count, taker_buy_volume, taker_buy_quote_volume, ignore
    """
    table = generate_payload(seed=seed, symbols=pairs, days=days, start=start)
    cols = {name: table.column(name).to_pylist() for name in PAYLOAD_COLUMNS}
    buf = io.BytesIO()
    day_ms = 86_400_000
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for s_idx, symbol in enumerate(symbol_names(pairs)):
            rows = io.StringIO(newline="")
            writer = csv.writer(rows, lineterminator="\n")
            for d in range(days):
                i = s_idx * days + d
                open_ms = int(cols["ts"][i].timestamp() * 1000)
                writer.writerow(
                    [
                        open_ms,
                        f"{cols['open'][i]:.8f}",
                        f"{cols['high'][i]:.8f}",
                        f"{cols['low'][i]:.8f}",
                        f"{cols['close'][i]:.8f}",
                        f"{cols['volume'][i]:.8f}",
                        open_ms + day_ms - 1,
                        f"{cols['volume'][i] * cols['close'][i]:.8f}",
                        1000,
                        f"{cols['volume'][i] / 2:.8f}",
                        f"{cols['volume'][i] * cols['close'][i] / 2:.8f}",
                        0,
                    ]
                )
            info = zipfile.ZipInfo(f"{symbol}-1d-{start[:7]}.csv", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, rows.getvalue())
    return buf.getvalue()


def read_expected() -> dict:
    return json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--symbols", type=int, default=DEFAULT_SYMBOLS)
    p.add_argument("--days", type=int, default=DEFAULT_DAYS)
    p.add_argument("--start", default=DEFAULT_START)
    p.add_argument("--mode", choices=["payload", "vision-zip"], default="payload")
    p.add_argument("--out", type=Path, default=None, help="生成物输出目录（不入库）")
    p.add_argument("--print-sha", action="store_true", help="只打印 payload_sha256")
    p.add_argument(
        "--check-expected", action="store_true", help="与 EXPECTED.json 比对并以退出码表示"
    )
    args = p.parse_args(argv)

    if args.mode == "vision-zip":
        payload = generate_vision_zip(seed=args.seed, start=args.start)
        if args.out:
            args.out.mkdir(parents=True, exist_ok=True)
            target = args.out / f"synthetic-vision-{args.seed}.zip"
            target.write_bytes(payload)
            print(f"vision_zip={target} bytes={len(payload)}")
        else:
            print(f"vision_zip_bytes={len(payload)}")
        return 0

    table = generate_payload(seed=args.seed, symbols=args.symbols, days=args.days, start=args.start)
    sha = payload_sha256(table)
    if args.print_sha:
        print(sha)
    else:
        print(f"rows={table.num_rows} payload_sha256={sha}")
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        parquet_io.write_table(table, args.out / "bench_payload.parquet", PAYLOAD_COLUMNS)
    if args.check_expected:
        expected = read_expected()
        if sha != expected["payload_sha256"]:
            print(f"MISMATCH expected={expected['payload_sha256']} actual={sha}")
            return 1
        print("OK payload_sha256 matches EXPECTED.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
