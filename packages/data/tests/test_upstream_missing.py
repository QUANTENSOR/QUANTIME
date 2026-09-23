"""「上游确实缺失」白名单（QNT-45 第 3 项）——被审过的豁免，不是通配放行。"""

from __future__ import annotations

import datetime as dt

import pytest
from quantime_data.upstream_missing import (
    DEFAULT_WHITELIST_PATH,
    WhitelistError,
    load_upstream_missing,
)


def _write(tmp_path, body: str):
    p = tmp_path / "wl.yaml"
    p.write_text(body, encoding="utf-8")
    return p


GOOD = """
version: 1
entries:
  - source: binance_vision
    filename: BTCUSDT-1d-2017-07.zip
    reason: 标的 2017-08 才上线，手工 GET 返回 404
    verified_on: 2026-09-23
"""


def test_the_shipped_whitelist_loads_and_is_empty():
    """仓库里的白名单当前为空：尚无任何经人工核对的上游缺失。"""
    wl = load_upstream_missing(DEFAULT_WHITELIST_PATH)
    assert wl.version == 1
    assert wl.entries == ()


def test_an_entry_is_matched_by_exact_source_and_filename(tmp_path):
    wl = load_upstream_missing(_write(tmp_path, GOOD))
    assert wl.is_known_missing("binance_vision", "BTCUSDT-1d-2017-07.zip")
    assert not wl.is_known_missing("binance_vision", "BTCUSDT-1d-2017-08.zip")
    assert not wl.is_known_missing("massive", "BTCUSDT-1d-2017-07.zip")
    assert "404" in (wl.reason_for("binance_vision", "BTCUSDT-1d-2017-07.zip") or "")
    (entry,) = wl.entries
    assert entry.verified_on == dt.date(2026, 9, 23)


@pytest.mark.parametrize(
    "mutation",
    [
        ("filename: BTCUSDT-1d-2017-07.zip", "filename: BTCUSDT-1d-*.zip"),
        ("filename: BTCUSDT-1d-2017-07.zip", "filename: BTCUSDT-1d-2017-0?.zip"),
        ("    reason: 标的 2017-08 才上线，手工 GET 返回 404\n", "    reason: ' '\n"),
        ("    verified_on: 2026-09-23\n", ""),
        ("version: 1\n", ""),
    ],
    ids=["star", "question", "empty-reason", "no-date", "no-version"],
)
def test_malformed_whitelists_are_rejected(tmp_path, mutation):
    """放行表写错 = 直接放行，所以宁可拒绝加载。"""
    old, new = mutation
    assert old in GOOD
    with pytest.raises(WhitelistError):
        load_upstream_missing(_write(tmp_path, GOOD.replace(old, new)))


def test_duplicate_entries_are_rejected(tmp_path):
    dup = GOOD + GOOD.split("entries:\n", 1)[1]
    with pytest.raises(WhitelistError, match="重复"):
        load_upstream_missing(_write(tmp_path, dup))
