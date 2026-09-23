"""QNT-32 因子文献库：字段校验 + 按 market/family/reproducible 过滤。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "factor_library.py"


def _load_mod():
    spec = importlib.util.spec_from_file_location("factor_library", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["factor_library"] = mod
    spec.loader.exec_module(mod)
    return mod


fl = _load_mod()


@pytest.fixture(scope="module")
def records():
    return fl.load_all()


def test_library_meets_batch_counts(records):
    assert len(records) >= 30
    crypto = [r for r in records if "crypto" in r["markets"]]
    us = [r for r in records if "us_equity" in r["markets"]]
    assert len(crypto) >= 12
    assert len(us) >= 12
    crypto_yes = [r for r in crypto if r["reproducible"] == "yes"]
    assert len(crypto_yes) >= 6
    us_yes = [r for r in us if r["reproducible"] == "yes"]
    assert us_yes, "美股线至少应有若干 yes（日线 OHLCV+市值，待付费源）"
    for r in us_yes:
        assert "待付费源" in r["reproducible_reason"]


def test_every_yaml_validates_and_id_matches_filename(records):
    paths = fl.list_yaml_paths()
    assert paths, "papers/ 下应有 YAML"
    stems = {p.stem for p in paths}
    ids = {r["id"] for r in records}
    assert stems == ids


def test_reject_downgrades_are_partial_with_substitution_formula(records):
    """verify-b REJECT 点名的 5 条必须降为 partial，且写出原文用/我们只有/替换为。"""
    by_id = {r["id"]: r for r in records}
    named = (
        "arxiv-2310.11771",
        "arxiv-2506.08573",
        "arxiv-2108.11921",
        "arxiv-2409.00416",
        "arxiv-2607.01377",
        "arxiv-2202.09845",
        "arxiv-1906.03430",
    )
    for rid in named:
        rec = by_id[rid]
        assert rec["reproducible"] == "partial", rid
        for needle in ("原文用", "我们只有", "替换为"):
            assert needle in rec["reproducible_reason"], rid


def test_yes_reasons_do_not_describe_a_proxy(records):
    for r in records:
        if r["reproducible"] != "yes":
            continue
        assert "替换为" not in r["reproducible_reason"], r["id"]


def test_filter_by_market_family_reproducible(records):
    crypto = fl.filter_records(records, market="crypto")
    assert crypto and all("crypto" in r["markets"] for r in crypto)
    mom = fl.filter_records(records, family="momentum")
    assert mom and all(r["family"] == "momentum" for r in mom)
    yes = fl.filter_records(records, reproducible="yes")
    assert yes and all(r["reproducible"] == "yes" for r in yes)
    combo = fl.filter_records(records, market="crypto", family="momentum", reproducible="yes")
    for r in combo:
        assert "crypto" in r["markets"]
        assert r["family"] == "momentum"
        assert r["reproducible"] == "yes"


def test_filter_rejects_unknown_market(records):
    with pytest.raises(fl.RecordError, match="未知 market"):
        fl.filter_records(records, market="a_share")


def test_validate_rejects_missing_required_field():
    rec = _valid_stub()
    del rec["title"]
    with pytest.raises(fl.RecordError, match="缺少字段"):
        fl.validate_record(rec, filename="stub.yaml")


def test_validate_rejects_pdf_url():
    rec = _valid_stub()
    rec["url"] = "https://arxiv.org/pdf/2212.06888.pdf"
    with pytest.raises(fl.RecordError, match="PDF"):
        fl.validate_record(rec, filename="stub.yaml")


def test_validate_rejects_arxiv_without_qfin():
    rec = _valid_stub()
    rec["categories"] = ["cs.LG"]
    with pytest.raises(fl.RecordError, match="q-fin"):
        fl.validate_record(rec, filename="stub.yaml")


def test_validate_rejects_us_yes_without_paid_flag():
    rec = _valid_stub()
    rec["markets"] = ["us_equity"]
    rec["reproducible"] = "yes"
    rec["reproducible_reason"] = "只需日线 OHLCV 与市值即可构造该因子。"
    with pytest.raises(fl.RecordError, match="待付费源"):
        fl.validate_record(rec, filename="stub.yaml")


def test_index_render_contains_every_id(records):
    text = fl.render_index(records)
    for r in records:
        assert f"`{r['id']}`" in text


def test_committed_index_matches_generator(records):
    committed = fl.INDEX_PATH.read_text(encoding="utf-8")
    assert committed == fl.render_index(records)


def test_no_record_is_a_dumped_abstract(records):
    """因子定义是转写：禁止把摘要原文整段贴进 definition。"""
    for r in records:
        assert len(r["factor_definition"]) <= fl.MAX_DEFINITION_CHARS
        assert "We establish that" not in r["factor_definition"]
        assert "Abstract:" not in r["factor_definition"]


def test_cli_validate_and_filter_exit_zero(records):
    assert fl.main(["validate"]) == 0
    assert fl.main(["filter", "--market", "crypto", "--reproducible", "yes"]) == 0


def test_load_record_rejects_non_mapping(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("- just a list\n", encoding="utf-8")
    with pytest.raises(fl.RecordError, match="mapping"):
        fl.load_record(p)


def test_yaml_roundtrip_keeps_required_keys(records):
    sample = records[0]
    dumped = yaml.safe_dump(sample, sort_keys=False, allow_unicode=True)
    loaded = yaml.safe_load(dumped)
    fl.validate_record(loaded, filename="roundtrip.yaml")


def _valid_stub() -> dict:
    return {
        "id": "arxiv-2212.06888",
        "source_kind": "arxiv",
        "arxiv_id": "2212.06888",
        "categories": ["q-fin.PR"],
        "title": "Fundamentals of Perpetual Futures",
        "authors": ["Songrun He"],
        "year": 2022,
        "url": "https://arxiv.org/abs/2212.06888",
        "accessed": "2026-09-23",
        "factor_name": "funding carry",
        "factor_definition": "资金费与基差把永续价钉向现货；多头在费率为正时支付空头。",
        "family": "carry",
        "frequency": "daily",
        "required_fields": [{"name": "funding_rate", "frequency": "daily"}],
        "original_findings": {
            "sample_market": "crypto perpetuals",
            "sample_period": "abstract, not restated",
            "stats": "偏离大于传统外汇，且跨币种共动、随时间缩小。",
        },
        "reproducible": "yes",
        "reproducible_reason": "Vision 归档含 USDT 永续 funding 与 OHLCV，可构造资金费 carry。",
        "markets": ["crypto"],
    }
