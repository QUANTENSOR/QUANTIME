"""标的清单（`universe.yaml`）加载测试。

清单是**版本控制的固定表**，不按实时成交量动态选——动态清单会让「同参数重跑」
拿到不同的标的集合，破坏 ADR-0002 可重放。这里钉住的是这个性质，不只是解析。
"""

from __future__ import annotations

import pytest
from quantime_core.paths import AssetClass, Freq
from quantime_data import universe as uni


def write(tmp_path, text: str):
    p = tmp_path / "universe.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_shipped_universe_has_ten_symbols_per_leg_and_the_three_planned_freqs():
    u = uni.load_universe()
    assert u.version == 1
    assert {leg.asset_class for leg in u.legs} == {AssetClass.SPOT, AssetClass.PERP}
    for leg in u.legs:
        assert len(leg.symbols) == 10, f"{leg.asset_class} 腿不是 10 个标的"
        assert leg.freqs == (Freq.H1, Freq.H4, Freq.D1)
        assert all(s.endswith("USDT") for s in leg.symbols)


def test_shipped_universe_is_a_fixed_list_not_a_query():
    """反证：清单文件里不得出现「按成交量取前 N」这类动态选取指令。"""
    text = uni.DEFAULT_UNIVERSE_PATH.read_text(encoding="utf-8")
    for banned in ("top_n", "top-n", "volume", "sort_by", "limit:"):
        assert banned not in text, f"清单出现动态选取字段 {banned!r}"


def test_leg_lookup_by_name_and_enum():
    u = uni.load_universe()
    assert u.leg("spot").asset_class is AssetClass.SPOT
    assert u.leg(AssetClass.PERP).asset_class is AssetClass.PERP


def test_missing_leg_raises():
    u = uni.load_universe()
    with pytest.raises(uni.UniverseError, match="无"):
        u.leg(AssetClass.OPTION)


def test_symbols_are_deduped_but_keep_file_order(tmp_path):
    p = write(
        tmp_path,
        "version: 1\nspot:\n  freqs: [1d]\n  symbols: [BTCUSDT, ETHUSDT, BTCUSDT]\n",
    )
    leg = uni.load_universe(p).leg("spot")
    assert leg.symbols == ("BTCUSDT", "ETHUSDT")


def test_empty_symbol_list_is_rejected(tmp_path):
    """空腿必须报错：安静地摄取 0 个标的是最糟的失败方式。"""
    p = write(tmp_path, "version: 1\nspot:\n  freqs: [1d]\n  symbols: []\n")
    with pytest.raises(uni.UniverseError, match="无 symbol"):
        uni.load_universe(p)


def test_empty_freq_list_is_rejected(tmp_path):
    p = write(tmp_path, "version: 1\nspot:\n  freqs: []\n  symbols: [BTCUSDT]\n")
    with pytest.raises(uni.UniverseError, match="无 freq"):
        uni.load_universe(p)


def test_universe_without_any_leg_is_rejected(tmp_path):
    p = write(tmp_path, "version: 1\n")
    with pytest.raises(uni.UniverseError, match="无任何腿"):
        uni.load_universe(p)


def test_missing_version_is_rejected(tmp_path):
    p = write(tmp_path, "spot:\n  freqs: [1d]\n  symbols: [BTCUSDT]\n")
    with pytest.raises(uni.UniverseError, match="version"):
        uni.load_universe(p)


def test_non_mapping_root_is_rejected(tmp_path):
    p = write(tmp_path, "- BTCUSDT\n")
    with pytest.raises(uni.UniverseError, match="根节点"):
        uni.load_universe(p)


def test_unknown_freq_is_rejected(tmp_path):
    p = write(tmp_path, "version: 1\nspot:\n  freqs: [3s]\n  symbols: [BTCUSDT]\n")
    with pytest.raises(ValueError):
        uni.load_universe(p)
