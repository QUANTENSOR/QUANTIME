"""依赖方向守卫：import-linter 契约实际可跑且通过（ADR-0003 §3.2）。"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_import_linter_contracts_pass():
    proc = subprocess.run(
        ["lint-imports"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Contracts: 2 kept, 0 broken" in proc.stdout


def test_core_does_not_import_data():
    hits = subprocess.run(
        ["grep", "-rn", "quantime_data", str(REPO / "packages" / "core")],
        capture_output=True,
        text=True,
    ).stdout
    assert hits == "", f"core 反向依赖 data:\n{hits}"
