"""运行记录（QNT-45 第 2 项的「运行记录」段）——**只追加**的 run 级账本。

`ingestion_batch` 记的是「写进了什么」；`run_log` 记的是「跑过一次，结果如何」。两者不能
互相替代：空增量的那一天**没有任何 batch**，若不另记一笔，事后无法区分「跑了但没有新
数据」与「根本没跑」——而这正是 timer 是否正常工作的判据。

只追加的实现方式：每次运行写自己的 `data/runs/<run_id>/run_log.json`，经
`parquet_io.publish_text` 发布（同路径已存在即拒绝）。没有任何一处会改写已有记录。
`/data/` 不入库，所以这里只有 schema 与生成器带测试（卡第 4 项同款口径）。

运行记录还承载两类**可重放的运维事实**（都只追加）：

* `pending_since`（QNT-45 R7）：`--since-last` 下某条从未提交过数据的序列，本次整段都在
  等上游发布、什么都没写——它的请求起点记在这里，之后的 `--since-last` 从
  `min(水位线次日, 未消化的 pending 起点)` 起取（`incremental.next_window`）。
* `abort_reason`（QNT-45 R8）：本次运行在摄取之前就被拦下的原因——`pull_failed`（unit 的
  `ExecStartPre` 拉代码失败，由 `ExecStopPost` 调 `record-abort` 记账）或 `disk_low`
  （磁盘守卫拒绝开新 batch）。
"""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from quantime_core import parquet_io
from quantime_core.paths import run_dir

from .batches import publish_staging

#: 运行记录文件名（在 `data/runs/<run_id>/` 下，与 replay 的 `manifest.json` 并列）。
RUN_LOG_FILENAME = "run_log.json"

#: schema 版本——读侧据此判断能不能解析。字段只增不删，删字段要升版本。
RUN_LOG_SCHEMA_VERSION = 1

#: 运行被拦下的原因（`abort_reason`）。
ABORT_PULL_FAILED = "pull_failed"
ABORT_DISK_LOW = "disk_low"
ABORT_REASONS: tuple[str, ...] = (ABORT_PULL_FAILED, ABORT_DISK_LOW)

#: pending 起点的键——与 `incremental.CoverageKey` 同构。
PendingKey = tuple[str, str, str, str, str]

#: 运行结局。`ok` = 无失败；`partial` = 有成功也有失败；`failed` = 全部失败。
OUTCOME_OK = "ok"
OUTCOME_PARTIAL = "partial"
OUTCOME_FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SeriesOutcome:
    """一条序列在本次运行里的结果（成功与否都记）。"""

    spec: str
    source: str
    action: str  # ingest / rerun / skipped_empty_increment / pending_upstream / failed
    batch_id: str | None = None
    rows: int = 0
    retries: int = 0
    missing_upstream: int = 0
    elapsed_seconds: float = 0.0
    error: str | None = None
    #: 本序列一共发起了几次归档拉取尝试（含重试）；失败序列据此看出「试了几次才放弃」。
    attempts: int = 0
    #: 失败的异常类（`RetryExhaustedError(TransportIOError)` 这种形状带上根因）。
    error_class: str | None = None
    #: 按发布节奏上游尚未发布、留给下一次 `--since-last` 的天数（不是缺失）。
    pending_upstream_days: int = 0


@dataclass(frozen=True, slots=True)
class PendingSince:
    """一条从未提交过数据的序列在本次运行里整段待发布：它的请求起点（R7）。"""

    source: str
    asset_class: str
    datatype: str
    freq: str
    scope: str
    since: dt.date

    @property
    def key(self) -> PendingKey:
        return (self.source, self.asset_class, self.datatype, self.freq, self.scope)

    def to_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "asset_class": self.asset_class,
            "datatype": self.datatype,
            "freq": self.freq,
            "scope": self.scope,
            "since": self.since.isoformat(),
        }


@dataclass(slots=True)
class RunLog:
    """一次运行的完整记账。`finish()` 之后即不可再变（只发布一次）。"""

    run_id: str
    source: str
    mode: str
    started_at: dt.datetime
    finished_at: dt.datetime | None = None
    series: list[SeriesOutcome] = field(default_factory=list)
    #: 运维需要知道的说明（例如「有水位线，`--start` 被忽略」）——只追加，随记录发布。
    notes: list[str] = field(default_factory=list)
    #: R7：本次整段待发布、且尚无水位线的序列的请求起点。
    pending_since: list[PendingSince] = field(default_factory=list)
    #: R8：运行在摄取前被拦下的原因（`ABORT_REASONS` 之一）；`None` = 正常跑完。
    abort_reason: str | None = None

    def record(self, outcome: SeriesOutcome) -> None:
        self.series.append(outcome)

    @property
    def ok_count(self) -> int:
        return sum(1 for s in self.series if s.error is None)

    @property
    def failed_count(self) -> int:
        return sum(1 for s in self.series if s.error is not None)

    @property
    def skipped_count(self) -> int:
        return sum(1 for s in self.series if s.action == "skipped_empty_increment")

    @property
    def total_rows(self) -> int:
        return sum(s.rows for s in self.series)

    @property
    def total_retries(self) -> int:
        return sum(s.retries for s in self.series)

    @property
    def outcome(self) -> str:
        if self.abort_reason is not None:
            return OUTCOME_FAILED
        if self.failed_count == 0:
            return OUTCOME_OK
        return OUTCOME_FAILED if self.ok_count == 0 else OUTCOME_PARTIAL

    @property
    def exit_code(self) -> int:
        """非零退出 = 本次运行有失败。timer 与运维脚本只看这个数。

        注意「有成功也有失败」同样非零：部分失败若退 0，systemd 会把一次半成功的运行
        记成 `SUCCESS`，缺的那半永远不会有人去看。
        """
        return 0 if self.failed_count == 0 and self.abort_reason is None else 1

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": RUN_LOG_SCHEMA_VERSION,
            "run_id": self.run_id,
            "source": self.source,
            "mode": self.mode,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "outcome": self.outcome,
            "exit_code": self.exit_code,
            "totals": {
                "series": len(self.series),
                "ok": self.ok_count,
                "failed": self.failed_count,
                "skipped_empty_increment": self.skipped_count,
                "rows": self.total_rows,
                "retries": self.total_retries,
            },
            "series": [asdict(s) for s in self.series],
            "notes": list(self.notes),
            "pending_since": [p.to_dict() for p in self.pending_since],
            "abort_reason": self.abort_reason,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def run_log_path(root: str | os.PathLike[str], run_id: str) -> Path:
    return Path(root) / run_dir(run_id) / RUN_LOG_FILENAME


def publish_run_log(
    root: str | os.PathLike[str], log: RunLog, *, now: dt.datetime | None = None
) -> str:
    """把运行记录发布到 `data/runs/<run_id>/run_log.json`；回传 sha256。

    走与湖内数据同一条发布路径（staging → fsync → `os.link`），因此同一个 `run_id`
    的记录只能写一次：重复发布抛 `AlreadyPublishedError`，而不是把上一次的结论换掉。
    """
    root = Path(root)
    log.finished_at = (now or dt.datetime.now(dt.UTC)).replace(microsecond=0)
    target = run_log_path(root, log.run_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    return parquet_io.publish_text(target, log.to_json(), staging=publish_staging(root))


def read_run_log(root: str | os.PathLike[str], run_id: str) -> dict[str, object]:
    """只读：解析一次运行的记录。"""
    return json.loads(run_log_path(root, run_id).read_text(encoding="utf-8"))


def read_pending_since(root: str | os.PathLike[str]) -> dict[PendingKey, tuple[dt.date, ...]]:
    """只读：全部运行记录里的 pending 起点，按序列归并（升序、去重）。

    是否已消化不在这里判断——那要对照水位线（`incremental.next_window`）。两份只增记录
    放在一起读就能推出来，不需要回头给旧记录打「已消化」标记。
    """
    runs = Path(root) / "data" / "runs"
    if not runs.is_dir():
        return {}
    out: dict[PendingKey, set[dt.date]] = {}
    for run in sorted(runs.iterdir()):
        path = run / RUN_LOG_FILENAME
        if not path.is_file():
            continue
        for entry in json.loads(path.read_text(encoding="utf-8")).get("pending_since", []):
            key = (
                entry["source"],
                entry["asset_class"],
                entry["datatype"],
                entry["freq"],
                entry["scope"],
            )
            out.setdefault(key, set()).add(dt.date.fromisoformat(entry["since"]))
    return {k: tuple(sorted(v)) for k, v in out.items()}
