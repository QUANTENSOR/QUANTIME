"""标的清单加载（QNT-28）——固定清单来自版本控制的 `universe.yaml`。

不按实时成交量动态选标的：动态清单会让「同参数重跑」不可复现。清单变更走 PR。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from quantime_core.paths import AssetClass, Freq

#: 随包分发的默认清单（加密）。
DEFAULT_UNIVERSE_PATH = Path(__file__).with_name("universe.yaml")

#: 美股 + 美股期权清单（QNT-47）。与加密分文件：两个市场的腿键与 freq 口径不同。
US_UNIVERSE_PATH = Path(__file__).with_name("universe_us.yaml")


class UniverseError(ValueError):
    """清单文件不合规范。"""


@dataclass(frozen=True, slots=True)
class Leg:
    """清单的一条腿：一个 asset_class 的 symbol 集合与 K 线周期集合。"""

    asset_class: AssetClass
    symbols: tuple[str, ...]
    freqs: tuple[Freq, ...]


@dataclass(frozen=True, slots=True)
class Universe:
    version: int
    legs: tuple[Leg, ...]

    def leg(self, asset_class: AssetClass | str) -> Leg:
        ac = AssetClass(asset_class)
        for leg in self.legs:
            if leg.asset_class is ac:
                return leg
        raise UniverseError(f"清单无 {ac} 腿")


#: 清单里的腿键 → `AssetClass`。`equity`/`option` 是 QNT-47 加的美股两腿；
#: `option` 腿的 `symbols` 是**底层** ticker，合约由参考端点按底层列出。
_KEY_TO_ASSET_CLASS = {
    "spot": AssetClass.SPOT,
    "perp": AssetClass.PERP,
    "equity": AssetClass.EQUITY,
    "option": AssetClass.OPTION,
}


def load_universe(path: str | os.PathLike[str] | None = None) -> Universe:
    """读清单。symbol 去重后仍保持文件顺序；空腿视为错误（安静地摄取 0 个标的最糟）。"""
    p = Path(path) if path is not None else DEFAULT_UNIVERSE_PATH
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise UniverseError(f"清单根节点应为映射: {p}")
    try:
        version = int(raw["version"])
    except (KeyError, TypeError, ValueError) as exc:
        raise UniverseError(f"清单缺少合法的 version: {p}") from exc

    legs: list[Leg] = []
    for key, asset_class in _KEY_TO_ASSET_CLASS.items():
        node = raw.get(key)
        if node is None:
            continue
        symbols = _unique(node.get("symbols") or [])
        freqs = _unique(node.get("freqs") or [])
        if not symbols:
            raise UniverseError(f"清单 {key} 腿无 symbol: {p}")
        if not freqs:
            raise UniverseError(f"清单 {key} 腿无 freq: {p}")
        legs.append(
            Leg(
                asset_class=asset_class,
                symbols=tuple(symbols),
                freqs=tuple(Freq(f) for f in freqs),
            )
        )
    if not legs:
        raise UniverseError(f"清单无任何腿: {p}")
    return Universe(version=version, legs=tuple(legs))


def _unique(values: list) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        s = str(v)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out
