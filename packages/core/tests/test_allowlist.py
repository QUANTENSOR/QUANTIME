"""allowlist 双向断言互不放行（ADR-0003 §3.3；验收标准 allowlist 两条）。"""

from __future__ import annotations

import pytest
from quantime_core.allowlist import (
    ALLOWLIST,
    DemoMarker,
    HostEntry,
    HostNotAllowedError,
    TradingBoundaryError,
    assert_demo_headers,
    assert_public_readonly_host,
    assert_trading_host,
    lookup,
)


def test_allowlist_first_version_is_binance_vision_public_readonly():
    hosts = {e.host: e for e in ALLOWLIST}
    assert hosts.keys() == {"data.binance.vision", "data-api.binance.vision"}
    for entry in ALLOWLIST:
        assert entry.public_readonly is True
        assert entry.exchange == "binance"
        assert entry.doc_url.startswith("https://")


def test_assert_trading_host_rejects_public_readonly_entry():
    # 验收：assert_trading_host("data.binance.vision") 抛错。
    with pytest.raises(TradingBoundaryError, match="public_readonly=True"):
        assert_trading_host("data.binance.vision")


def test_assert_public_readonly_host_rejects_host_outside_allowlist():
    # 验收：assert_public_readonly_host("api.binance.com") 抛错（主网 host 不在表内）。
    with pytest.raises(HostNotAllowedError, match="不在 allowlist"):
        assert_public_readonly_host("api.binance.com")


def test_assert_public_readonly_host_accepts_listed_entry():
    entry = assert_public_readonly_host("data-api.binance.vision")
    assert entry.public_readonly is True


def test_lookup_is_exact_no_suffix_matching():
    assert lookup("evil-data.binance.vision") is None
    with pytest.raises(HostNotAllowedError):
        assert_public_readonly_host("data.binance.vision.attacker.test")


def test_assert_trading_host_rejects_unknown_host_fail_closed():
    with pytest.raises(TradingBoundaryError, match="不在 allowlist"):
        assert_trading_host("api.bybit.com")


# --- demo_marker 逐请求校验（§3.3；用假 host 条目，第一阶段不创建 OKX/Bitget 适配器）---


@pytest.fixture
def fake_trading_entry(monkeypatch):
    entry = HostEntry(
        host="demo.example.test",
        public_readonly=False,
        exchange="fake",
        doc_url="https://example.test/docs",
        demo_marker=DemoMarker(
            header_name="x-simulated-trading",
            header_value="1",
            key_label_contains="demo",
        ),
    )
    import quantime_core.allowlist as mod

    monkeypatch.setitem(mod._BY_HOST, entry.host, entry)
    return entry


def test_demo_headers_pass_when_header_and_label_match(fake_trading_entry):
    got = assert_demo_headers(
        "demo.example.test", {"X-Simulated-Trading": "1"}, key_label=" quant-dev/okx-demo \n"
    )
    assert got.public_readonly is False


def test_demo_headers_missing_header_is_rejected(fake_trading_entry):
    with pytest.raises(TradingBoundaryError, match="缺少模拟盘请求头"):
        assert_demo_headers("demo.example.test", {}, key_label="okx-demo")


def test_demo_headers_wrong_header_value_is_rejected(fake_trading_entry):
    with pytest.raises(TradingBoundaryError, match="值不符"):
        assert_demo_headers("demo.example.test", {"x-simulated-trading": "0"}, key_label="okx-demo")


def test_demo_headers_wrong_key_label_is_rejected(fake_trading_entry):
    with pytest.raises(TradingBoundaryError, match="key 标签"):
        assert_demo_headers("demo.example.test", {"x-simulated-trading": "1"}, key_label="okx-live")
