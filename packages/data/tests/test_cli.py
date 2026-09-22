"""摄取 CLI 测试——**全程离线**。

`plan` 是 dry-run，本来就不出网；`ingest` 的出网点只有 `_http_opener`，
测试里从不调用它（这一点由 `test_ingest_never_builds_the_http_opener_when_fetch_is_injected`
之外的静态守卫 `tests/test_static_guards.py` 兜底）。
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
from quantime_core.paths import AssetClass, DataType, Freq
from quantime_data import cli
from quantime_data.universe import Leg, Universe

START = dt.date(2026, 8, 1)
END = dt.date(2026, 8, 31)

UNIVERSE = Universe(
    version=1,
    legs=(
        Leg(AssetClass.SPOT, ("BTCUSDT", "ETHUSDT"), (Freq.H1, Freq.D1)),
        Leg(AssetClass.PERP, ("BTCUSDT",), (Freq.H1,)),
    ),
)


def specs(**kw):
    kw.setdefault("datatypes", ["kline", "funding", "open_interest"])
    kw.setdefault("start", START)
    kw.setdefault("end", END)
    kw.setdefault("symbols", [])
    return cli._specs_for(UNIVERSE, **kw)


def test_http_client_is_imported_inside_the_opener_not_at_module_level():
    """`httpx` 只在 `_http_opener` 函数体内 import：导入本模块不碰网络库。

    查的是 AST 而不是字符串——注释里提到 httpx 不该让这条红，顶层 import 必须红。
    """
    import ast

    tree = ast.parse(pathlib.Path(cli.__file__).read_text(encoding="utf-8"))
    top_level = [n for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)]
    names = {a.name.split(".")[0] for n in top_level if isinstance(n, ast.Import) for a in n.names}
    names |= {(n.module or "").split(".")[0] for n in top_level if isinstance(n, ast.ImportFrom)}
    assert not names & {"httpx", "requests", "urllib", "socket", "websockets"}, (
        f"网络库出现在模块顶层 import: {sorted(names)}"
    )

    opener = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_http_opener"
    )
    inner = {a.name for n in ast.walk(opener) if isinstance(n, ast.Import) for a in n.names}
    assert "httpx" in inner, "_http_opener 不再是唯一的网络出口"


def test_kline_expands_over_every_freq_of_its_leg():
    out = [s for s in specs(datatypes=["kline"]) if s.asset_class is AssetClass.SPOT]
    assert [(s.symbol, str(s.freq)) for s in out] == [
        ("BTCUSDT", "1h"),
        ("BTCUSDT", "1d"),
        ("ETHUSDT", "1h"),
        ("ETHUSDT", "1d"),
    ]


def test_funding_and_open_interest_skip_the_spot_leg():
    out = specs(datatypes=["funding", "open_interest"])
    assert {s.asset_class for s in out} == {AssetClass.PERP}
    assert {(s.datatype, str(s.freq)) for s in out} == {
        (DataType.FUNDING, "event"),
        (DataType.OPEN_INTEREST, "5m"),
    }


def test_symbol_filter_narrows_every_leg():
    out = specs(symbols=["ETHUSDT"])
    assert {s.symbol for s in out} == {"ETHUSDT"}
    assert {s.asset_class for s in out} == {AssetClass.SPOT}, "ETHUSDT 不在永续腿里"


def test_expansion_order_is_deterministic():
    assert [s.describe() for s in specs()] == [s.describe() for s in specs()]


def test_plan_prints_urls_and_makes_no_network_call(tmp_path, capsys, monkeypatch):
    def boom():  # pragma: no cover - 被调用即失败
        raise AssertionError("plan 不得建立网络出口")

    monkeypatch.setattr(cli, "_http_opener", boom)
    universe = tmp_path / "u.yaml"
    universe.write_text(
        "version: 1\nspot:\n  freqs: [1d]\n  symbols: [BTCUSDT]\n", encoding="utf-8"
    )
    rc = cli.main(
        [
            "--universe",
            str(universe),
            "plan",
            "--start",
            "2026-08-01",
            "--end",
            "2026-08-31",
            "--datatype",
            "kline",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2026-08.zip"
    ]


def test_plan_urls_all_point_at_an_allowlisted_public_readonly_host(tmp_path, capsys):
    from quantime_core.allowlist import assert_public_readonly_host
    from quantime_data.transport import assert_public_readonly_path, split_public_url

    universe = tmp_path / "u.yaml"
    universe.write_text(
        "version: 1\nspot:\n  freqs: [1h, 1d]\n  symbols: [BTCUSDT]\n"
        "perp:\n  freqs: [4h]\n  symbols: [BTCUSDT]\n",
        encoding="utf-8",
    )
    cli.main(["--universe", str(universe), "plan", "--start", "2026-08-01", "--end", "2026-08-31"])
    urls = capsys.readouterr().out.splitlines()
    assert urls
    for url in urls:
        host, path = split_public_url(url)
        assert assert_public_readonly_host(host).public_readonly
        assert_public_readonly_path(path)


def test_unknown_datatype_is_rejected_by_the_parser():
    with pytest.raises(SystemExit):
        cli.main(["plan", "--start", "2026-08-01", "--end", "2026-08-31", "--datatype", "trade"])


def test_missing_subcommand_is_rejected():
    with pytest.raises(SystemExit):
        cli.main([])
