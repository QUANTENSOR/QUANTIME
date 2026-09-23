"""systemd unit 文件的静态守卫（QNT-45 第 5 项）。

unit 文件不参与 pytest 的 import，也不被 ruff 检查——它是这个仓库里唯一一类「会以 root
之外的身份、在无人看管的时刻、按我们写下的字面量去访问网络」的产物。所以它的边界只能
由静态守卫来钉：

* 不得出现主网 / 交易所下单 host 字面量（crypto-boundaries ②、ADR-0001 D1.8）；
* 不得出现任何凭据字面量或明文凭据注入（AGENTS.md §3）；
* `systemd-analyze verify` 必须通过（无 root，对文件运行）。

`systemd-analyze` 不在时相关测试 skip——CI 的 ubuntu runner 有，本地容器不一定有。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
UNIT_DIR = REPO / "systemd" / "user"

#: 本卡交付的四个 unit。列出来而不是 glob：新增 unit 必须显式进这份清单，
#: 否则它会绕过下面每一条守卫（glob 会自动"包含"新文件，也就自动放行了它的内容）。
UNIT_FILES: tuple[str, ...] = (
    "quantime-ingest@.service",
    "quantime-ingest@.timer",
    "quantime-ingest-report.service",
    "quantime-ingest-report.timer",
)

#: 与 `tests/test_static_guards.py` / ci.yml 同一把尺子。
MAINNET_HOST_PATTERN = (
    r"api\.binance\.com|fapi\.binance\.com|api\.bybit\.com|www\.okx\.com|api\.bitget\.com"
)

#: 明文凭据的形状。`op://` 引用不在其列——那正是允许的注入写法（引用不是秘钥本身）。
SECRET_PATTERN = (
    r"(?i)(api[_-]?key|api[_-]?secret|secret[_-]?key|access[_-]?token|password|passphrase)"
    r"\s*=\s*\S"
)


def unit_text(name: str) -> str:
    return (UNIT_DIR / name).read_text(encoding="utf-8")


def uncommented_lines(text: str) -> list[str]:
    """去掉整行注释。unit 文件的注释以 `#` 或 `;` 开头，且只能整行。"""
    return [ln for ln in text.splitlines() if not ln.lstrip().startswith(("#", ";"))]


def _looks_like_a_secret_blob(line: str) -> bool:
    if re.search(r"https?://", line):
        return False
    return any(len(tok) >= 40 for tok in re.split(r"[^A-Za-z0-9+/=]+", line))


def test_every_declared_unit_file_exists():
    missing = [n for n in UNIT_FILES if not (UNIT_DIR / n).is_file()]
    assert missing == [], f"声明了但不存在的 unit: {missing}"


def test_no_undeclared_unit_files_slip_in():
    """新增 unit 必须显式进 UNIT_FILES，否则它绕过本文件的全部守卫。"""
    on_disk = {p.name for p in UNIT_DIR.iterdir() if p.suffix in {".service", ".timer"}}
    assert on_disk == set(UNIT_FILES), f"unit 清单与磁盘不符: {sorted(on_disk)}"


@pytest.mark.parametrize("name", UNIT_FILES)
def test_no_mainnet_or_trading_host_literals_in_unit_files(name):
    """crypto-boundaries ②：unit 里不得出现主网 / 下单 host 字面量。

    这一条是 QNT-45 变异点 (d) 钉住的东西。unit 是无人值守执行的——一个塞进
    `ExecStart` 的主网 host，谁都不会在 code review 里当成"代码"去看。
    """
    hits = [ln for ln in uncommented_lines(unit_text(name)) if re.search(MAINNET_HOST_PATTERN, ln)]
    assert hits == [], f"{name} 出现主网 host 字面量:\n" + "\n".join(hits)


@pytest.mark.parametrize("name", UNIT_FILES)
def test_unit_files_carry_no_credentials(name):
    """AGENTS.md §3：凭据不写进 unit、不写进 Environment=、不落文件。"""
    text = unit_text(name)
    lines = uncommented_lines(text)
    secrets = [ln for ln in lines if re.search(SECRET_PATTERN, ln)]
    assert secrets == [], f"{name} 疑似含明文凭据:\n" + "\n".join(secrets)

    env = [ln for ln in lines if ln.strip().startswith(("Environment=", "EnvironmentFile="))]
    assert env == [], (
        f"{name} 用 Environment/EnvironmentFile 传值（凭据须经 op 注入）:\n" + "\n".join(env)
    )

    # 40 字符以上的连续 base64/hex 样串——手抄的 key 长这样。URL 行先排除：
    # 文档链接天然很长，把它算成"疑似秘钥"会让这条守卫被当成噪声关掉。
    blobs = [ln for ln in lines if _looks_like_a_secret_blob(ln)]
    assert blobs == [], f"{name} 出现疑似秘钥字面量:\n" + "\n".join(blobs)


def test_the_credential_placeholder_stays_a_comment():
    """付费源的 op 注入写法只许是**注释占位**——本卡不启用任何凭据注入。"""
    text = unit_text("quantime-ingest@.service")
    assert "op://quant-dev/" in text, "凭据注入占位不见了（将来接付费源没有可照抄的形状）"
    live = [ln for ln in uncommented_lines(text) if "op run" in ln or "op://" in ln]
    assert live == [], "op 注入被启用了（本卡的源是公开只读，不需要凭据）:\n" + "\n".join(live)


def test_timers_are_daily_utc_persistent_and_jittered():
    """卡要求：固定每日 UTC 时刻、`Persistent=true`、适度 `RandomizedDelaySec`。"""
    for name in ("quantime-ingest@.timer", "quantime-ingest-report.timer"):
        text = unit_text(name)
        oncalendar = [ln for ln in uncommented_lines(text) if ln.startswith("OnCalendar=")]
        assert len(oncalendar) == 1, f"{name} 应恰好一条 OnCalendar"
        assert oncalendar[0].endswith("UTC"), (
            f"{name} 的 OnCalendar 未固定 UTC——跟着本地夏令时漂移会让某天跑两次: {oncalendar[0]}"
        )
        assert "Persistent=true" in text, f"{name} 缺 Persistent=true（关机错过就是永久的洞）"
        delay = re.search(r"RandomizedDelaySec=(\d+)(m|s|min)?", text)
        assert delay, f"{name} 缺 RandomizedDelaySec"
        value = int(delay.group(1))
        minutes = value if delay.group(2) in ("m", "min") else value / 60
        assert 1 <= minutes <= 60, f"{name} 的随机延迟 {minutes} 分钟不在「适度」区间"


def test_the_ingest_service_runs_the_incremental_mode():
    """timer 调的必须是 `daily --since-last`——不是每天把全部历史重下一遍。"""
    text = unit_text("quantime-ingest@.service")
    exec_lines = [ln for ln in uncommented_lines(text) if "quantime-ingest" in ln]
    joined = (
        " ".join(exec_lines)
        + " "
        + " ".join(ln for ln in uncommented_lines(text) if ln.startswith((" ", "\t")) or "--" in ln)
    )
    assert "daily" in joined and "--since-last" in joined, "unit 没走增量模式"


def test_the_report_service_neither_writes_nor_goes_online():
    """报告汇总只读本地文件：不给写权限、不给网络。"""
    text = unit_text("quantime-ingest-report.service")
    assert "PrivateNetwork=true" in text, "报告汇总不需要网络，应当断网运行"
    assert "ReadWritePaths=" not in "\n".join(uncommented_lines(text)), "报告汇总不该有任何写权限"


@pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="无 systemd-analyze")
def test_systemd_analyze_verify_passes_on_every_unit():
    """`systemd-analyze verify`（无 root，对文件运行）必须通过。

    在 unit 目录里跑并用 `./` 前缀：否则 systemd 会去系统路径找同名 unit，
    验的就不是我们交付的这几个文件了。
    """
    proc = subprocess.run(
        ["systemd-analyze", "verify", "--user", *[f"./{n}" for n in UNIT_FILES]],
        cwd=UNIT_DIR,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"systemd-analyze verify 失败:\n{proc.stdout}\n{proc.stderr}"


@pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="无 systemd-analyze")
def test_systemd_analyze_verify_is_not_vacuous(tmp_path):
    """反证：一个确实坏掉的 unit 会被 `verify` 判红——上一条不是空集通过。"""
    bad = tmp_path / "quantime-broken.service"
    bad.write_text("[Unit]\nDescription=x\n[Service]\nType=oneshot\n", encoding="utf-8")
    proc = subprocess.run(
        ["systemd-analyze", "verify", "--user", "./quantime-broken.service"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0, "systemd-analyze verify 连没有 ExecStart 的 unit 都放行"


def test_install_md_lists_the_owner_executed_commands():
    """INSTALL.md 必须逐项给出 owner 回来后要执行的命令，并声明本卡不执行它们。"""
    text = (UNIT_DIR / "INSTALL.md").read_text(encoding="utf-8")
    for needle in (
        "systemctl --user enable --now",
        "systemctl --user daemon-reload",
        "loginctl enable-linger",
        "journalctl --user -u quantime-ingest",
        "systemd-analyze verify",
        "systemctl --user disable",
    ):
        assert needle in text, f"INSTALL.md 缺少 {needle!r}"
    assert "由 owner 回来后逐项执行" in text, "INSTALL.md 未声明由 owner 执行"
    assert "不得在主机上执行" in text, "INSTALL.md 未声明本卡不在主机上执行"


def test_install_md_documents_no_plaintext_credentials():
    text = (UNIT_DIR / "INSTALL.md").read_text(encoding="utf-8")
    assert "quant-dev" in text, "INSTALL.md 未说明业务凭据来自 vault quant-dev"
    assert re.search(SECRET_PATTERN, text) is None, "INSTALL.md 里出现了明文凭据形状"
