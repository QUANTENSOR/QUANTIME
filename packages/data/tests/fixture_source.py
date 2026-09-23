"""离线回放的 fetch 与共用 spec —— 摄取相关测试的**唯一**一份录制表。

QNT-28 把这些放在 `test_ingest.py` 里；QNT-45 的通用层测试要用同一份录制，于是提到这里。
两处各写一份回放表的话，改了一处另一处就悄悄失去覆盖。

这里**不出网**：`FixtureFetcher` 只认 `RECORDED` 里的 URL，其余一律 `FileNotFoundError`
——即上游 404 / 整档缺失，与真实 `PublicTransport` 的语义一致。
"""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

from quantime_core.paths import AssetClass, DataType, Freq
from quantime_data.sources import binance_public as bp
from quantime_data.spec import IngestSpec

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "binance_public"

#: 上游 URL → 录制文件名。摄取时 `fetch` 按这张表回放，永不出网。
RECORDED: dict[str, str] = {
    bp.kline_url("spot", "BTCUSDT", "1d", "2026-08"): "spot-BTCUSDT-1d-2026-08.zip",
    bp.kline_url("perp", "BTCUSDT", "4h", "2026-08"): "um-BTCUSDT-4h-2026-08.zip",
    bp.funding_url("BTCUSDT", "2026-08"): "um-BTCUSDT-fundingRate-2026-08.zip",
    bp.metrics_url("BTCUSDT", dt.date(2026, 9, 15)): "um-BTCUSDT-metrics-2026-09-15.zip",
}

NOW = dt.datetime(2026, 9, 21, 12, 0, tzinfo=dt.UTC)


def snapshot(root: Path) -> dict[str, str]:
    """湖里每个文件的相对路径 → sha256，用于断言「一个字节都没动」。"""
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((root / "data").rglob("*"))
        if p.is_file()
    }


class FixtureFetcher:
    """离线 fetch：录制里有就回放，没有就当上游 404（缺档）。

    `fail_urls` 把「前 N 次失败、之后成功」这件事做成可注入的剧本——重试测试因此既不
    等待也不出网：`{url: [RateLimitedError(...), RateLimitedError(...)]}` 表示前两次抛，
    第三次起正常回放。
    """

    def __init__(self, *, fail_urls: dict[str, list[BaseException]] | None = None) -> None:
        self.urls: list[str] = []
        self.fail_urls = fail_urls or {}

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        pending = self.fail_urls.get(url)
        if pending:
            raise pending.pop(0)
        if url.endswith(".CHECKSUM"):
            name = RECORDED.get(url.removesuffix(".CHECKSUM"))
            if name is None:
                raise FileNotFoundError(url)
            return (FIXTURES / (name + ".CHECKSUM")).read_bytes()
        name = RECORDED.get(url)
        if name is None:
            raise FileNotFoundError(url)
        return (FIXTURES / name).read_bytes()


def spot_1d(start: dt.date, end: dt.date) -> IngestSpec:
    """录制覆盖的现货日线序列（BTCUSDT，2026-08 整月在案）。"""
    return IngestSpec(
        datatype=DataType.KLINE,
        asset_class=AssetClass.SPOT,
        symbol="BTCUSDT",
        freq=Freq.D1,
        start=start,
        end=end,
    )


SPOT_KLINE_SPEC = spot_1d(dt.date(2026, 8, 1), dt.date(2026, 8, 31))
FUNDING_SPEC = IngestSpec(
    datatype=DataType.FUNDING,
    asset_class=AssetClass.PERP,
    symbol="BTCUSDT",
    freq=Freq.EVENT,
    start=dt.date(2026, 8, 1),
    end=dt.date(2026, 8, 31),
)
OI_SPEC = IngestSpec(
    datatype=DataType.OPEN_INTEREST,
    asset_class=AssetClass.PERP,
    symbol="BTCUSDT",
    freq=Freq.M5,
    start=dt.date(2026, 9, 15),
    end=dt.date(2026, 9, 15),
)
