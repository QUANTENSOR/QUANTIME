"""运行记录（QNT-45 第 2 项的「运行记录」段）——**只追加**的 run 级账本。

`ingestion_batch` 记的是「写进了什么」；`run_log` 记的是「跑过一次，结果如何」。两者不能
互相替代：空增量的那一天**没有任何 batch**，若不另记一笔，事后无法区分「跑了但没有新
数据」与「根本没跑」——而这正是 timer 是否正常工作的判据。

只追加的实现方式：每次运行写自己的 `data/runs/<run_id>/run_log.json`，经
`parquet_io.publish_text` 发布（同路径已存在即拒绝）。没有任何一处会改写已有记录。
`/data/` 不入库，所以这里只有 schema 与生成器带测试（卡第 4 项同款口径）。
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
        if self.failed_count == 0:
            return OUTCOME_OK
        return OUTCOME_FAILED if self.ok_count == 0 else OUTCOME_PARTIAL

    @property
    def exit_code(self) -> int:
        """非零退出 = 本次运行有失败。timer 与运维脚本只看这个数。

        注意「有成功也有失败」同样非零：部分失败若退 0，systemd 会把一次半成功的运行
        记成 `SUCCESS`，缺的那半永远不会有人去看。
        """
        return 0 if self.failed_count == 0 else 1

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
