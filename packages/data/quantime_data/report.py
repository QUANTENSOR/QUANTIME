"""每日核查报告（QNT-45 第 4 项）——**源无关**的报告 schema 与生成器。

每次运行产出一对同名文件到 `data/reports/<date>/<run_id>.{json,md}`：JSON 给机器（补采
`--backfill-from-report` 读的就是它），Markdown 给人（owner 早上扫一眼）。两者由**同一个
`DailyReport` 对象**渲染，所以不会出现「Markdown 说 complete、JSON 说 partial」。

报告内容按卡要求：分源覆盖率、新增行数、缺口、重复、重试次数、耗时。

**schema v2（QNT-45 R4/R5）**：失败的序列同样进 `series`（`status="failed"`，带错误分类、
尝试次数、耗时与**结构化的缺档清单**），补采因此能从报告重建任务，不必去翻运行记录。
覆盖状态的取值与聚合规则写死在这里，不留给读侧解释：

| 序列 `status` | 序列 `coverage` | 进覆盖率分母 |
|---|---|---|
| `ok`：已提交 batch | `complete` / `partial`（有整档缺失） | 是 |
| `failed`：未提交任何 batch | `failed` | 是 |
| `pending`：请求区间内上游**尚未发布**任何归档 | `pending` | **否** |

分源 / 全局覆盖：分母为空 → `partial`；任一 `failed` → **`failed`**；否则任一 `partial` →
`partial`；否则 `complete`。「有序列失败」永远不会显示成 `complete`。
`pending_upstream`（按发布节奏尚未发布的日期段）不是缺失、不是失败，也不拉低覆盖率——
它会被下一次 `--since-last` 取回。

报告文件本身不入库（`/data/` 是 gitignored），所以测试钉的是 **schema 与生成器**：
字段齐全、Markdown 与 JSON 同源、同样输入逐字节相同。写入同样走 `parquet_io.publish_*`
——报告也只 insert，昨天的报告永远不会被今天的覆盖。
"""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from quantime_core import parquet_io

from .adapter import Archive
from .audit import COVERAGE_COMPLETE, COVERAGE_PARTIAL, AuditResult
from .batches import publish_staging

#: 报告目录（`data/reports/<date>/`）。不在 `data/lake/` 里：它不是行情，读侧不该扫到它。
REPORTS_RELDIR = "data/reports"

#: JSON 报告的 schema 版本。补采读它之前先核对，版本不认识就拒绝而不是猜字段。
REPORT_SCHEMA_VERSION = 2

#: 序列状态（见模块头的表）。
STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_PENDING = "pending"

#: 覆盖状态：`complete` / `partial` 来自核查（`audit.py`），后两个只在报告层出现。
COVERAGE_FAILED = "failed"
COVERAGE_PENDING = "pending"

#: JSON 报告里每条序列必有的键——生成器与补采共用这一份，两处不会各自漂移。
SERIES_FIELDS: tuple[str, ...] = (
    "spec",
    "source",
    "asset_class",
    "datatype",
    "freq",
    "scope",
    "range_start",
    "range_end",
    "batch_id",
    "coverage",
    "rows",
    "gaps",
    "duplicates",
    "missing_upstream",
    "retries",
    "elapsed_seconds",
    "status",
    "error_class",
    "error",
    "attempts",
    "as_of",
    "missing_archives",
    "pending_upstream",
)


def archive_entry(archive: Archive) -> dict[str, str]:
    """缺档的结构化记录——补采据此重建任务，不再回头问 adapter 当初列了什么。"""
    return {
        "filename": archive.filename,
        "url": archive.url,
        "covers_start": archive.covers_start.isoformat(),
        "covers_end": archive.covers_end.isoformat(),
    }


PendingWindow = tuple[dt.date, dt.date]


@dataclass(frozen=True, slots=True)
class SeriesReport:
    """报告里的一条序列。字段够补采**无歧义地重建 spec**——少一个就得靠猜。"""

    spec: str
    source: str
    asset_class: str
    datatype: str
    freq: str
    scope: str
    range_start: str
    range_end: str
    batch_id: str | None
    coverage: str
    rows: int
    gaps: int
    duplicates: int
    missing_upstream: tuple[str, ...]
    retries: int
    elapsed_seconds: float
    status: str = STATUS_OK
    error_class: str | None = None
    error: str | None = None
    attempts: int = 0
    as_of: str | None = None
    missing_archives: tuple[dict[str, str], ...] = ()
    pending_upstream: tuple[PendingWindow, ...] = ()

    @property
    def counted(self) -> bool:
        """是否进覆盖率分母：只有「整段都还没发布」的序列不进。"""
        return self.status != STATUS_PENDING

    def to_dict(self) -> dict[str, object]:
        return {
            "spec": self.spec,
            "source": self.source,
            "asset_class": self.asset_class,
            "datatype": self.datatype,
            "freq": self.freq,
            "scope": self.scope,
            "range_start": self.range_start,
            "range_end": self.range_end,
            "batch_id": self.batch_id,
            "coverage": self.coverage,
            "rows": self.rows,
            "gaps": self.gaps,
            "duplicates": self.duplicates,
            "missing_upstream": list(self.missing_upstream),
            "retries": self.retries,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "status": self.status,
            "error_class": self.error_class,
            "error": self.error,
            "attempts": self.attempts,
            "as_of": self.as_of,
            "missing_archives": [dict(a) for a in self.missing_archives],
            "pending_upstream": [
                {"start": a.isoformat(), "end": b.isoformat()} for a, b in self.pending_upstream
            ],
        }


def _spec_fields(spec) -> dict[str, str]:
    return {
        "spec": spec.describe(),
        "asset_class": str(spec.asset_class),
        "datatype": str(spec.datatype),
        "freq": str(spec.freq),
        "scope": spec.scope,
        "range_start": spec.start.isoformat(),
        "range_end": spec.end.isoformat(),
        "as_of": spec.as_of.isoformat() if spec.as_of else None,
    }


def series_failed(
    spec,
    *,
    source: str,
    error_class: str,
    error: str,
    missing_archives: tuple[Archive, ...],
    pending_upstream: tuple[PendingWindow, ...] = (),
    retries: int = 0,
    attempts: int = 0,
    elapsed_seconds: float = 0.0,
) -> SeriesReport:
    """失败序列的报告条目：没有 batch，**区间内每个已发布归档都算缺档**（一行都没进湖）。"""
    return SeriesReport(
        **_spec_fields(spec),
        source=source,
        batch_id=None,
        coverage=COVERAGE_FAILED,
        rows=0,
        gaps=0,
        duplicates=0,
        missing_upstream=tuple(a.filename for a in missing_archives),
        retries=retries,
        elapsed_seconds=elapsed_seconds,
        status=STATUS_FAILED,
        error_class=error_class,
        error=error,
        attempts=attempts,
        missing_archives=tuple(archive_entry(a) for a in missing_archives),
        pending_upstream=pending_upstream,
    )


def series_pending(
    spec, *, source: str, pending_upstream: tuple[PendingWindow, ...]
) -> SeriesReport:
    """整段都还没发布的序列：不取、不写、不算缺失，也不进覆盖率分母。"""
    return SeriesReport(
        **_spec_fields(spec),
        source=source,
        batch_id=None,
        coverage=COVERAGE_PENDING,
        rows=0,
        gaps=0,
        duplicates=0,
        missing_upstream=(),
        retries=0,
        elapsed_seconds=0.0,
        status=STATUS_PENDING,
        pending_upstream=pending_upstream,
    )


def series_from_audit(
    result: AuditResult,
    *,
    source: str,
    asset_class: str,
    range_start: dt.date,
    range_end: dt.date,
    spec_text: str,
    retries: int = 0,
    elapsed_seconds: float = 0.0,
    attempts: int = 0,
    as_of: dt.date | None = None,
    missing_archives: tuple[Archive, ...] = (),
    pending_upstream: tuple[PendingWindow, ...] = (),
) -> SeriesReport:
    """把一个 `AuditResult` 转成报告条目——覆盖状态原样取自核查，不在这里重算。"""
    return SeriesReport(
        spec=spec_text,
        source=source,
        asset_class=str(asset_class),
        datatype=result.datatype,
        freq=result.freq,
        scope=result.scope,
        range_start=range_start.isoformat(),
        range_end=range_end.isoformat(),
        batch_id=result.audited_batch_id,
        coverage=result.coverage,
        rows=result.rows_audited,
        gaps=len(result.gaps),
        duplicates=len(result.duplicates),
        missing_upstream=result.missing_upstream,
        retries=retries,
        elapsed_seconds=elapsed_seconds,
        status=STATUS_OK,
        attempts=attempts,
        as_of=as_of.isoformat() if as_of else None,
        missing_archives=tuple(archive_entry(a) for a in missing_archives),
        pending_upstream=pending_upstream,
    )


def aggregate_coverage(entries) -> str:
    """覆盖聚合（规则见模块头）：分母空 → partial；任一 failed → failed；任一 partial → partial。"""
    counted = [s for s in entries if s.counted]
    if not counted:
        return COVERAGE_PARTIAL
    if any(s.coverage == COVERAGE_FAILED for s in counted):
        return COVERAGE_FAILED
    if all(s.coverage == COVERAGE_COMPLETE for s in counted):
        return COVERAGE_COMPLETE
    return COVERAGE_PARTIAL


@dataclass(slots=True)
class DailyReport:
    """一次运行的核查报告。JSON 与 Markdown 都从这里渲染。"""

    run_id: str
    report_date: dt.date
    generated_at: dt.datetime
    mode: str = "ingest"
    series: list[SeriesReport] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0

    def add(self, entry: SeriesReport) -> None:
        self.series.append(entry)

    @property
    def sources(self) -> tuple[str, ...]:
        return tuple(sorted({s.source for s in self.series}))

    def coverage_of(self, source: str) -> str:
        """该源的整体覆盖（聚合规则见 `aggregate_coverage`，宁严勿松）。"""
        return aggregate_coverage(s for s in self.series if s.source == source)

    @property
    def coverage(self) -> str:
        """全局覆盖——运行时验收（连续 3 天 `coverage=complete`）看的就是它。

        分母为空时判 `partial`：一次什么都没核查的运行不能算「覆盖完整」，
        否则清单配错导致 0 个标的被摄取时，报告反而天天显示绿。任一序列失败即 `failed`。
        """
        return aggregate_coverage(self.series)

    @property
    def total_rows(self) -> int:
        return sum(s.rows for s in self.series)

    @property
    def total_gaps(self) -> int:
        return sum(s.gaps for s in self.series)

    @property
    def total_duplicates(self) -> int:
        return sum(s.duplicates for s in self.series)

    @property
    def total_retries(self) -> int:
        return sum(s.retries for s in self.series)

    @property
    def total_missing(self) -> int:
        return sum(len(s.missing_upstream) for s in self.series)

    def count(self, status: str) -> int:
        return sum(1 for s in self.series if s.status == status)

    @property
    def total_pending_days(self) -> int:
        return sum((b - a).days + 1 for s in self.series for a, b in s.pending_upstream)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "run_id": self.run_id,
            "report_date": self.report_date.isoformat(),
            "generated_at": self.generated_at.isoformat(),
            "mode": self.mode,
            "coverage": self.coverage,
            "sources": [{"source": s, "coverage": self.coverage_of(s)} for s in self.sources],
            "totals": {
                "series": len(self.series),
                "rows": self.total_rows,
                "gaps": self.total_gaps,
                "duplicates": self.total_duplicates,
                "missing_upstream": self.total_missing,
                "retries": self.total_retries,
                "failures": len(self.failures),
                "failed_series": self.count(STATUS_FAILED),
                "pending_series": self.count(STATUS_PENDING),
                "pending_upstream_days": self.total_pending_days,
                "elapsed_seconds": round(self.elapsed_seconds, 3),
            },
            "series": [s.to_dict() for s in self.series],
            "failures": list(self.failures),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    def to_markdown(self) -> str:
        """人读的那一份。字段与 JSON 同源，数字一处算、两处显示。"""
        d = self.to_dict()
        totals = d["totals"]
        lines = [
            f"# quantime 每日核查报告 {self.report_date.isoformat()}",
            "",
            f"- run_id: `{self.run_id}`",
            f"- 模式: `{self.mode}`",
            f"- 生成时刻: {self.generated_at.isoformat()}",
            f"- 整体覆盖: **{self.coverage}**",
            f"- 序列数: {totals['series']}｜新增行数: {totals['rows']}"
            f"｜缺口: {totals['gaps']}｜重复: {totals['duplicates']}",
            f"- 上游整档缺失: {totals['missing_upstream']}｜重试次数: {totals['retries']}"
            f"｜失败: {totals['failures']}｜耗时: {totals['elapsed_seconds']}s",
            f"- 上游尚未发布（不计入覆盖率）: {totals['pending_upstream_days']} 天"
            f"｜整段待发布序列: {totals['pending_series']}",
            "",
            "## 分源覆盖",
            "",
            "| source | coverage |",
            "| --- | --- |",
        ]
        lines.extend(f"| {s} | {self.coverage_of(s)} |" for s in self.sources)
        lines += [
            "",
            "## 分序列",
            "",
            "| spec | status | coverage | rows | gaps | dups | missing | retries | elapsed |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for s in self.series:
            lines.append(
                f"| {s.spec} | {s.status} | {s.coverage} | {s.rows} | {s.gaps} | {s.duplicates} "
                f"| {len(s.missing_upstream)} | {s.retries} | {round(s.elapsed_seconds, 3)}s |"
            )
        if self.total_pending_days:
            lines += ["", "## 上游尚未发布", ""]
            for s in self.series:
                for a, b in s.pending_upstream:
                    lines.append(f"- `{s.spec}` → {a.isoformat()}..{b.isoformat()}")
        if self.total_missing:
            lines += ["", "## 上游整档缺失", ""]
            for s in self.series:
                for name in s.missing_upstream:
                    lines.append(f"- `{s.spec}` → `{name}`")
        if self.failures:
            lines += ["", "## 失败", ""]
            lines.extend(f"- {f}" for f in self.failures)
            for s in self.series:
                if s.status == STATUS_FAILED:
                    lines.append(
                        f"  - `{s.spec}`：{s.error_class}，尝试 {s.attempts} 次，"
                        f"重试 {s.retries} 次，耗时 {round(s.elapsed_seconds, 3)}s"
                    )
        return "\n".join(lines) + "\n"


def report_dir(root: str | os.PathLike[str], report_date: dt.date) -> Path:
    return Path(root) / REPORTS_RELDIR / report_date.isoformat()


def report_paths(root: str | os.PathLike[str], report: DailyReport) -> tuple[Path, Path]:
    """`(json, md)`——同目录、同名、不同后缀。"""
    d = report_dir(root, report.report_date)
    return d / f"{report.run_id}.json", d / f"{report.run_id}.md"


def publish_report(root: str | os.PathLike[str], report: DailyReport) -> tuple[str, str]:
    """把报告的 JSON 与 Markdown 发布到 `data/reports/<date>/`；回传两个 sha256。

    走 `parquet_io.publish_text`（staging → fsync → `os.link`）：同一个 run_id 的报告
    只能写一次。今天的报告绝不覆盖昨天的，重跑同一个 run_id 会被拒绝而不是悄悄替换。
    """
    root = Path(root)
    json_path, md_path = report_paths(root, report)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    staging = publish_staging(root)
    return (
        parquet_io.publish_text(json_path, report.to_json(), staging=staging),
        parquet_io.publish_text(md_path, report.to_markdown(), staging=staging),
    )


def load_report(path: str | os.PathLike[str]) -> dict[str, object]:
    """读一份 JSON 报告并核对 schema 版本。版本不认识就拒绝，不猜字段。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    version = data.get("schema_version")
    if version != REPORT_SCHEMA_VERSION:
        raise ValueError(
            f"报告 schema 版本 {version!r} 不是本代码认识的 {REPORT_SCHEMA_VERSION}：{path}"
        )
    for entry in data.get("series", []):
        missing = [f for f in SERIES_FIELDS if f not in entry]
        if missing:
            raise ValueError(f"报告条目缺字段 {missing}：{path}")
    return data


def summarize_reports(root: str | os.PathLike[str], report_date: dt.date) -> tuple[list[str], int]:
    """当天所有报告的汇总行（`report-summary` 子命令与汇总 unit 用）。回传 `(行, 退出码)`。

    **按 JSON 字段读**（`load_report` 核对版本后取 `coverage` / `totals`），不 grep 文本：
    schema v2 里 `"coverage"` 键在每条序列里也出现，grep 第一处匹配拿到的可能是某一条
    序列的覆盖，而不是整份报告的（QNT-45 R4）。退出码：无报告或任一份不是 `complete` → 1。
    """
    d = report_dir(root, report_date)
    files = sorted(d.glob("*.json")) if d.is_dir() else []
    if not files:
        return [f"今日无报告: {d}"], 1
    lines: list[str] = []
    worst = 0
    for path in files:
        data = load_report(path)
        totals = data["totals"]
        coverage = data["coverage"]
        lines.append(
            f"{path.name} mode={data['mode']} coverage={coverage} "
            f"series={totals['series']} failed_series={totals['failed_series']} "
            f"pending_series={totals['pending_series']} rows={totals['rows']} "
            f"missing={totals['missing_upstream']} retries={totals['retries']} "
            f"pending_upstream_days={totals['pending_upstream_days']}"
        )
        if coverage != COVERAGE_COMPLETE:
            worst = 1
    return lines, worst
