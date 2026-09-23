#!/usr/bin/env python3
"""录制 Binance 公开归档 fixture（**手动运行**，不在 CI 里跑）。

用法：`uv run --package quantime-data --extra ingest python fixtures/binance_public/record.py`
（`ingest` extra 属 quantime-data 而非根项目——根目录直接 `--extra ingest` 找不到它。
  verify-a R1 第 5 点）

录制内容只有**响应正文字节**（zip / .CHECKSUM）。请求头、响应头、cookie、时间戳等
无关字段一律不落盘——它们与数据无关，只会让 fixture 难以复核。
每个文件旁记一条 `MANIFEST.json` 条目（url + sha256 + size + 录制日期），
使「fixture 来自哪个上游 URL、当时是什么字节」可被独立核对。

synthetic: false —— 这是**真实上游响应的录制**，不是合成数据。AGENTS.md §2 的
「fixtures/ 只放合成数据」针对的是自制基准输入（`fixtures/bench/`）；离线重放外部
接入必须用真实响应的录制，否则测的是我们自己编的格式。见 PR 描述「偏离项」。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "data"))

from quantime_data.cli import _http_opener  # noqa: E402
from quantime_data.sources import binance_public as bp  # noqa: E402
from quantime_data.transport import PublicTransport  # noqa: E402

HERE = Path(__file__).parent

#: 录制范围：刻意只取 1 个 symbol × 小区间——fixture 是为了验证解析与链路，不是数据集。
RECORDINGS: tuple[tuple[str, str], ...] = (
    (bp.kline_url("spot", "BTCUSDT", "1d", "2026-08"), "spot-BTCUSDT-1d-2026-08.zip"),
    (bp.kline_url("perp", "BTCUSDT", "4h", "2026-08"), "um-BTCUSDT-4h-2026-08.zip"),
    (bp.funding_url("BTCUSDT", "2026-08"), "um-BTCUSDT-fundingRate-2026-08.zip"),
    (
        bp.metrics_url("BTCUSDT", dt.date(2026, 9, 15)),
        "um-BTCUSDT-metrics-2026-09-15.zip",
    ),
)


def main() -> int:
    transport = PublicTransport(_http_opener())
    manifest = []
    for url, name in RECORDINGS:
        payload = transport.get(url)
        (HERE / name).write_bytes(payload)
        checksum_name = name + ".CHECKSUM"
        checksum_payload = transport.get(bp.checksum_url(url))
        (HERE / checksum_name).write_bytes(checksum_payload)
        manifest.append(
            {
                "url": url,
                "file": name,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
                "checksum_file": checksum_name,
            }
        )
        print(f"recorded {name} ({len(payload)} bytes)")
    (HERE / "MANIFEST.json").write_text(
        json.dumps(
            {
                "synthetic": False,
                "recorded_at": dt.date.today().isoformat(),
                "note": "只含响应正文字节；请求/响应头与 cookie 未录制",
                "files": manifest,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
