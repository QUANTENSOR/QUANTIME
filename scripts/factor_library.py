"""QNT-32 可复现因子文献库：校验 YAML、按标签过滤、生成 index.md。

一条 YAML 一篇；不下载 PDF、不存全文。运行入口：

    uv run python scripts/factor_library.py validate
    uv run python scripts/factor_library.py filter --market crypto --reproducible yes
    uv run python scripts/factor_library.py index --write
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
LIBRARY_DIR = REPO / "docs" / "research" / "factor-library"
PAPERS_DIR = LIBRARY_DIR / "papers"
INDEX_PATH = LIBRARY_DIR / "index.md"

SOURCE_KINDS = frozenset({"arxiv", "nber", "ssrn", "journal"})
MARKETS = frozenset({"crypto", "us_equity", "us_option", "multi"})
FAMILIES = frozenset(
    {
        "momentum",
        "value",
        "volatility",
        "liquidity",
        "carry",
        "size",
        "reversal",
        "attention",
        "network",
        "pairs",
        "funding",
        "oi",
        "microstructure",
        "quality",
        "beta",
        "sentiment",
        "methodology",
        "multi",
        "other",
    }
)
FREQUENCIES = frozenset({"daily", "weekly", "monthly", "intraday", "mixed"})
REPRODUCIBLE = frozenset({"yes", "partial", "no"})
JOURNAL_HOST_NEEDLES = (
    "onlinelibrary.wiley.com",  # Journal of Finance
    "sciencedirect.com",  # JFE
    "academic.oup.com",  # RFS
    "cambridge.org",  # JFQA
    "jstor.org",
)

REQUIRED_TOP = (
    "id",
    "source_kind",
    "title",
    "authors",
    "year",
    "url",
    "accessed",
    "factor_name",
    "factor_definition",
    "family",
    "frequency",
    "required_fields",
    "original_findings",
    "reproducible",
    "reproducible_reason",
    "markets",
)
REQUIRED_FINDINGS = ("sample_market", "sample_period", "stats")
MAX_DEFINITION_CHARS = 900
MAX_STATS_CHARS = 900
MAX_REASON_CHARS = 900


class RecordError(ValueError):
    """单篇记录未通过字段校验。"""


def papers_dir() -> Path:
    return PAPERS_DIR


def list_yaml_paths(directory: Path | None = None) -> list[Path]:
    root = directory or PAPERS_DIR
    return sorted(p for p in root.glob("*.yaml") if p.is_file())


def load_record(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise RecordError(f"{path.name}: YAML 根节点必须是 mapping")
    return data


def _require(record: dict[str, Any], key: str, path: str) -> Any:
    if key not in record or record[key] in (None, "", []):
        raise RecordError(f"{path}: 缺少字段 {key}")
    return record[key]


def _validate_url(kind: str, url: str, record: dict[str, Any], path: str) -> None:
    if not isinstance(url, str) or not url.startswith("https://"):
        raise RecordError(f"{path}: url 必须是 https URL")
    lowered = url.lower()
    if ".pdf" in lowered or "/pdf/" in lowered:
        raise RecordError(f"{path}: 禁止 PDF URL（只存摘要页）")
    if kind == "arxiv":
        arxiv_id = str(record.get("arxiv_id") or "")
        if "arxiv.org/abs/" not in lowered:
            raise RecordError(f"{path}: arXiv 记录的 url 必须是 abs 页")
        if arxiv_id and arxiv_id not in url:
            raise RecordError(f"{path}: url 未包含 arxiv_id={arxiv_id}")
    elif kind == "nber":
        if "nber.org/papers/" not in lowered:
            raise RecordError(f"{path}: NBER 记录的 url 必须是 papers 页")
    elif kind == "ssrn":
        if "ssrn.com" not in lowered:
            raise RecordError(f"{path}: SSRN 记录的 url 必须指向 ssrn.com")
    elif kind == "journal":
        if not any(n in lowered for n in JOURNAL_HOST_NEEDLES):
            raise RecordError(f"{path}: journal 记录的 url 不在 JF/JFE/RFS/JFQA 公开摘要域")


def validate_record(record: dict[str, Any], *, filename: str = "") -> None:
    path = filename or str(record.get("id", "<record>"))
    missing = [k for k in REQUIRED_TOP if record.get(k) in (None, "", [])]
    if missing:
        raise RecordError(f"{path}: 缺少字段 {', '.join(missing)}")

    rec_id = record["id"]
    if not isinstance(rec_id, str) or "/" in rec_id or " " in rec_id:
        raise RecordError(f"{path}: id 必须是无空格文件名友好字符串")

    kind = record["source_kind"]
    if kind not in SOURCE_KINDS:
        raise RecordError(f"{path}: source_kind 非法: {kind}")

    if kind == "arxiv":
        cats = record.get("categories") or []
        if not isinstance(cats, list) or not any(str(c).startswith("q-fin") for c in cats):
            raise RecordError(f"{path}: arXiv 记录必须带 q-fin 分类（来源范围 B）")
        if not record.get("arxiv_id"):
            raise RecordError(f"{path}: arXiv 记录缺少 arxiv_id")
    elif kind == "nber" and not record.get("nber_id"):
        raise RecordError(f"{path}: NBER 记录缺少 nber_id")
    elif kind == "ssrn" and not record.get("ssrn_id"):
        raise RecordError(f"{path}: SSRN 记录缺少 ssrn_id")
    elif kind == "journal" and not record.get("doi"):
        raise RecordError(f"{path}: journal 记录缺少 doi")

    authors = record["authors"]
    if not isinstance(authors, list) or not all(isinstance(a, str) and a.strip() for a in authors):
        raise RecordError(f"{path}: authors 必须是非空字符串列表")

    year = record["year"]
    if not isinstance(year, int) or year < 1900 or year > 2100:
        raise RecordError(f"{path}: year 必须是 1900–2100 的整数")

    try:
        dt.date.fromisoformat(str(record["accessed"]))
    except ValueError as exc:
        raise RecordError(f"{path}: accessed 必须是 YYYY-MM-DD") from exc

    _validate_url(kind, record["url"], record, path)

    definition = record["factor_definition"]
    if not isinstance(definition, str) or len(definition) < 20:
        raise RecordError(f"{path}: factor_definition 过短")
    if len(definition) > MAX_DEFINITION_CHARS:
        raise RecordError(
            f"{path}: factor_definition 超过 {MAX_DEFINITION_CHARS} 字符（疑似粘贴正文）"
        )

    family = record["family"]
    if family not in FAMILIES:
        raise RecordError(f"{path}: family 非法: {family}")
    if record["frequency"] not in FREQUENCIES:
        raise RecordError(f"{path}: frequency 非法: {record['frequency']}")

    fields = record["required_fields"]
    if not isinstance(fields, list) or not fields:
        raise RecordError(f"{path}: required_fields 必须是非空列表")
    for i, item in enumerate(fields):
        if not isinstance(item, dict) or "name" not in item or "frequency" not in item:
            raise RecordError(f"{path}: required_fields[{i}] 需要 name 与 frequency")
        if item["frequency"] not in FREQUENCIES:
            raise RecordError(f"{path}: required_fields[{i}].frequency 非法")

    findings = record["original_findings"]
    if not isinstance(findings, dict):
        raise RecordError(f"{path}: original_findings 必须是 mapping")
    miss_f = [k for k in REQUIRED_FINDINGS if not findings.get(k)]
    if miss_f:
        raise RecordError(f"{path}: original_findings 缺少 {', '.join(miss_f)}")
    stats = findings["stats"]
    if not isinstance(stats, str) or len(stats) > MAX_STATS_CHARS:
        raise RecordError(f"{path}: original_findings.stats 过长或非字符串")

    repro = record["reproducible"]
    if repro not in REPRODUCIBLE:
        raise RecordError(f"{path}: reproducible 必须是 yes/partial/no")
    reason = record["reproducible_reason"]
    if not isinstance(reason, str) or len(reason) < 20:
        raise RecordError(f"{path}: reproducible_reason 过短")
    if len(reason) > MAX_REASON_CHARS:
        raise RecordError(f"{path}: reproducible_reason 过长")

    markets = record["markets"]
    if not isinstance(markets, list) or not markets:
        raise RecordError(f"{path}: markets 必须是非空列表")
    bad = [m for m in markets if m not in MARKETS]
    if bad:
        raise RecordError(f"{path}: markets 非法: {bad}")

    # 「近似熵」是统计量名称，不能把「近似」一律当代理替换。只禁「替换为」。
    if repro == "yes" and "替换为" in reason:
        raise RecordError(f"{path}: yes 不得写「替换为」（应降为 partial）")
    if "crypto" in markets and repro == "yes":
        vision_ok = any(
            token in reason.lower()
            for token in ("ohlcv", "funding", "oi", "open interest", "vision")
        )
        if not vision_ok:
            raise RecordError(f"{path}: 加密线 reproducible=yes 须对照 Vision 字段写理由")
    if "us_equity" in markets and repro == "yes" and "待付费源" not in reason:
        raise RecordError(f"{path}: 美股线 reproducible=yes 须标注「待付费源」")
    if repro == "partial" and "替换为" in reason:
        for needle in ("原文用", "我们只有", "替换为"):
            if needle not in reason:
                raise RecordError(f"{path}: partial 替换理由须含「{needle}」")


def load_all(directory: Path | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in list_yaml_paths(directory):
        rec = load_record(path)
        validate_record(rec, filename=path.name)
        if rec["id"] != path.stem:
            raise RecordError(f"{path.name}: id={rec['id']!r} 必须等于文件名（不含扩展名）")
        records.append(rec)
    return records


def filter_records(
    records: list[dict[str, Any]],
    *,
    market: str | None = None,
    family: str | None = None,
    reproducible: str | None = None,
) -> list[dict[str, Any]]:
    out = records
    if market is not None:
        if market not in MARKETS:
            raise RecordError(f"未知 market: {market}")
        out = [r for r in out if market in r["markets"]]
    if family is not None:
        if family not in FAMILIES:
            raise RecordError(f"未知 family: {family}")
        out = [r for r in out if r["family"] == family]
    if reproducible is not None:
        if reproducible not in REPRODUCIBLE:
            raise RecordError(f"未知 reproducible: {reproducible}")
        out = [r for r in out if r["reproducible"] == reproducible]
    return out


def _md_cell(text: str) -> str:
    return str(text).replace("|", "/").replace("\n", " ").strip()


def render_index(records: list[dict[str, Any]]) -> str:
    rows = sorted(records, key=lambda r: (r["markets"][0], r["year"], r["id"]))
    lines = [
        "<!-- 由 scripts/factor_library.py index --write 生成；不要手改。 -->",
        "",
        "# 可复现因子文献库索引（QNT-32）",
        "",
        "一条 YAML 一篇，只存元数据 + 摘要页链接，不存 PDF / 全文。",
        "筛选：`uv run python scripts/factor_library.py filter` "
        "（--market / --family / --reproducible）。",
        "",
        f"共 {len(rows)} 篇。",
        "",
        "| id | 年 | 市场 | 族 | 可复现 | 标题 | 来源 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{r['id']}`",
                    str(r["year"]),
                    ",".join(r["markets"]),
                    r["family"],
                    r["reproducible"],
                    _md_cell(r["title"]),
                    f"[link]({r['url']})",
                ]
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def write_index(records: list[dict[str, Any]], dest: Path | None = None) -> Path:
    path = dest or INDEX_PATH
    path.write_text(render_index(records), encoding="utf-8")
    return path


def _print_table(records: list[dict[str, Any]]) -> None:
    print(f"{len(records)} record(s)")
    for r in records:
        print(
            f"{r['id']}\t{r['year']}\t{','.join(r['markets'])}\t"
            f"{r['family']}\t{r['reproducible']}\t{r['title']}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("validate", help="校验 papers/*.yaml")

    p_filter = sub.add_parser("filter", help="按 market / family / reproducible 过滤")
    p_filter.add_argument("--market", choices=sorted(MARKETS))
    p_filter.add_argument("--family", choices=sorted(FAMILIES))
    p_filter.add_argument("--reproducible", choices=sorted(REPRODUCIBLE))

    p_index = sub.add_parser("index", help="生成 Markdown 索引")
    p_index.add_argument("--write", action="store_true", help="写入 index.md")

    args = parser.parse_args(argv)
    try:
        records = load_all()
    except RecordError as exc:
        print(f"校验失败: {exc}", file=sys.stderr)
        return 1

    if args.cmd == "validate":
        print(f"OK: {len(records)} records")
        return 0
    if args.cmd == "filter":
        filtered = filter_records(
            records,
            market=args.market,
            family=args.family,
            reproducible=args.reproducible,
        )
        _print_table(filtered)
        return 0
    if args.cmd == "index":
        text = render_index(records)
        if args.write:
            write_index(records)
            print(f"wrote {INDEX_PATH.relative_to(REPO)}")
        else:
            sys.stdout.write(text)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
