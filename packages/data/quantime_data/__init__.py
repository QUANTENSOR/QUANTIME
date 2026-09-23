"""quantime 数据中心（ADR-0003 §3.1「数据中心」行）。

只允许依赖 `quantime_core`，不得 import 任何上层包（import-linter 守卫）。
"""

__all__ = ["audit", "batches", "checks", "ingest", "replay", "transport", "universe", "views"]
