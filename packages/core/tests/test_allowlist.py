"""allowlist 双向断言互不放行（ADR-0003 §3.3；验收标准 allowlist 两条）。"""

from __future__ import annotations

import pytest
from quantime_core.allowlist import (
    ALLOWLIST,
    DemoMarker,
    HostEntry,
    HostNotAllowedError,
    TradingBoundaryError,
    assert_credentialed_readonly_host,
    assert_demo_headers,
    assert_public_readonly_host,
    assert_trading_host,
    lookup,
)

#: 公共只读条目（无需 key）。
PUBLIC_READONLY_HOSTS = {"data.binance.vision", "data-api.binance.vision"}
#: 需 key 的只读数据条目（QNT-47 Massive，含 Polygon 旧域名）。
KEYED_READONLY_HOSTS = {"api.massive.com", "api.polygon.io", "files.massive.com"}


def test_allowlist_holds_exactly_the_declared_hosts():
    hosts = {e.host: e for e in ALLOWLIST}
    assert hosts.keys() == PUBLIC_READONLY_HOSTS | KEYED_READONLY_HOSTS
    for entry in ALLOWLIST:
        assert entry.doc_url.startswith("https://"), entry.host
        # crypto-boundaries ①：每条都得有官方文档链接，不接受占位。
        assert len(entry.doc_url) > len("https://")


def test_binance_vision_entries_are_public_readonly():
    for host in PUBLIC_READONLY_HOSTS:
        entry = lookup(host)
        assert entry is not None
        assert entry.public_readonly is True
        assert entry.credentialed_readonly is False
        assert entry.exchange == "binance"


def test_massive_entries_are_keyed_readonly_not_public_not_trading():
    # 卡要求「Massive host `public_readonly=false`」；但 False 在本表里原本就等于
    # 「D1.7 交易 host」。所以它必须同时标 credentialed_readonly=True，自成第三类。
    for host in KEYED_READONLY_HOSTS:
        entry = lookup(host)
        assert entry is not None
        assert entry.public_readonly is False
        assert entry.credentialed_readonly is True
        assert entry.exchange == "massive"
        assert entry.demo_marker is None


def test_allowlist_holds_no_trading_host_yet():
    # 交易 host = public_readonly=False 且 credentialed_readonly=False。QNT-33 之前应为空集。
    trading = [e for e in ALLOWLIST if not e.public_readonly and not e.credentialed_readonly]
    assert trading == []


def test_three_assertions_are_mutually_exclusive():
    """一个 host 只属于一类：三个断言里恰好一个放行，另外两个必须抛错。"""
    releases = {
        "public": assert_public_readonly_host,
        "keyed": assert_credentialed_readonly_host,
        "trading": assert_trading_host,
    }
    for entry in ALLOWLIST:
        passed = set()
        for name, fn in releases.items():
            try:
                fn(entry.host)
            except HostNotAllowedError, TradingBoundaryError:
                continue
            passed.add(name)
        assert len(passed) == 1, f"{entry.host} 同时被 {sorted(passed)} 放行"


def test_assert_trading_host_rejects_keyed_readonly_entry():
    # 硬边界：行情 host 绝不能被当成下单出口。
    with pytest.raises(TradingBoundaryError, match="行情 host 不是下单出口"):
        assert_trading_host("api.massive.com")
    with pytest.raises(TradingBoundaryError, match="行情 host 不是下单出口"):
        assert_trading_host("api.polygon.io")


def test_assert_public_readonly_host_rejects_keyed_entry():
    with pytest.raises(HostNotAllowedError, match="需 key 的只读数据 host"):
        assert_public_readonly_host("api.massive.com")


def test_assert_credentialed_readonly_host_rejects_public_entry():
    with pytest.raises(HostNotAllowedError, match="不是需 key 的只读数据 host"):
        assert_credentialed_readonly_host("data.binance.vision")


def test_assert_credentialed_readonly_host_rejects_unknown_host():
    with pytest.raises(HostNotAllowedError, match="不在 allowlist"):
        assert_credentialed_readonly_host("api.polygon.io.attacker.test")


def test_keyed_readonly_and_public_readonly_cannot_both_be_set():
    with pytest.raises(ValueError, match="互斥"):
        HostEntry(
            host="both.example.test",
            public_readonly=True,
            credentialed_readonly=True,
            exchange="fake",
            doc_url="https://example.test/docs",
        )


def test_keyed_readonly_entry_cannot_carry_a_demo_marker():
    with pytest.raises(ValueError, match="demo_marker"):
        HostEntry(
            host="keyed.example.test",
            public_readonly=False,
            credentialed_readonly=True,
            exchange="fake",
            doc_url="https://example.test/docs",
            demo_marker=DemoMarker(header_name="x-simulated-trading", header_value="1"),
        )


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
