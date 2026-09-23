"""systemd unit 文件的静态守卫（QNT-45 第 5 项）。

unit 文件不参与 pytest 的 import，也不被 ruff 检查——它是这个仓库里唯一一类「会以 root
之外的身份、在无人看管的时刻、按我们写下的字面量去访问网络」的产物。所以它的边界只能
由静态守卫来钉：

* 不得出现主网 / 交易所下单 host 字面量（crypto-boundaries ②、ADR-0001 D1.8）；
* 不得出现任何凭据字面量或明文凭据注入（AGENTS.md §3）；
* `systemd-analyze verify` 必须通过（无 root，对文件运行）；
* 部署约束（R8）：常驻检出 `/home/workspace/quantime` 只读、数据根是唯一可写处；每次运行前
  `git pull --ff-only`，失败不摄取且由 `ExecStopPost` 记 `pull_failed`。

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


#: 常驻检出与数据根（owner 2026-09-23 05:37 裁决）。
CHECKOUT = "/home/workspace/quantime"
DATA_ROOT = "/home/workspace/quantime/data"

#: `Environment=` 只许这几个键，且值固定——它们都不是凭据。其余任何键（尤其任何形似
#: `*_KEY` / `*_TOKEN` 的）一律拒绝：凭据只经 op 注入子进程，不进 unit。
ALLOWED_ENVIRONMENT: dict[str, str] = {
    "QUANTIME_DATA_ROOT": DATA_ROOT,
    "PYTHONDONTWRITEBYTECODE": "1",
    "UV_CACHE_DIR": "/tmp/uv-cache",
}
SERVICES = ("quantime-ingest@.service", "quantime-ingest-report.service")


def directives(name: str, key: str) -> list[str]:
    """某个指令的全部取值（整行注释已去掉；续行不展开——需要的调用方自己拼）。"""
    prefix = f"{key}="
    return [ln[len(prefix) :] for ln in uncommented_lines(unit_text(name)) if ln.startswith(prefix)]


def command_block(name: str, key: str) -> str:
    """把 `Key=... <反斜杠>` 续行拼回一条完整命令：与 systemd 一样去掉行尾反斜杠、以空格相接。"""
    lines = uncommented_lines(unit_text(name))
    out: list[str] = []
    grabbing = False
    for ln in lines:
        if ln.startswith(f"{key}="):
            grabbing = True
            ln = ln[len(key) + 1 :]
        elif not grabbing:
            continue
        cont = ln.rstrip().endswith("\\")
        out.append(ln.rstrip().removesuffix("\\"))
        if not cont:
            break
    return " ".join(out)


def unit_text(name: str) -> str:
    return (UNIT_DIR / name).read_text(encoding="utf-8")


def uncommented_lines(text: str) -> list[str]:
    """去掉整行注释。unit 文件的注释以 `#` 或 `;` 开头，且只能整行。"""
    return [ln for ln in text.splitlines() if not ln.lstrip().startswith(("#", ";"))]


def _looks_like_a_secret_blob(line: str) -> bool:
    if re.search(r"https?://", line):
        return False
    # 先去掉 `Key=`：否则 `WorkingDirectory=/home/…` 会因 `=` 与 `/` 都在 base64 字符集里
    # 被拼成一个长 token。绝对路径按段量——手抄的 key 塞进路径里，那一段照样 ≥ 40。
    value = re.sub(r"^\s*[A-Za-z]+=", "", line)
    for tok in re.split(r"[^A-Za-z0-9+/=]+", value):
        parts = tok.split("/") if tok.startswith("/") else [tok]
        if any(len(part) >= 40 for part in parts):
            return True
    return False


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

    env_file = [ln for ln in lines if ln.strip().startswith("EnvironmentFile=")]
    assert env_file == [], f"{name} 用 EnvironmentFile 传值（凭据须经 op 注入）:\n" + "\n".join(
        env_file
    )
    for ln in lines:
        if not ln.strip().startswith("Environment="):
            continue
        key, _, value = ln.strip().removeprefix("Environment=").partition("=")
        assert ALLOWED_ENVIRONMENT.get(key) == value, (
            f"{name} 的 Environment= 不在白名单（凭据须经 op 注入，不进 unit）: {ln}"
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


def test_the_ingest_service_resumes_from_the_watermark_not_from_yesterday():
    """QNT-45 R3：unit 不传 `--start`——起点只来自水位线，停机多天后一次补跑取回全部缺口。

    `Persistent=true` 只重放一次错过的触发；若 `--start` 钉在「昨天」，那一次只取昨天。
    """
    live = "\n".join(uncommented_lines(unit_text("quantime-ingest@.service")))
    assert "--start" not in live, "ingest unit 又传了 --start（关机期间的日子会永久缺失）"
    assert "--end" in live and "--since-last" in live


def test_the_report_service_reads_json_fields_via_report_summary():
    """QNT-45 R4：汇总按 JSON 字段读（`report-summary`），不 grep 报告文本。"""
    live = "\n".join(uncommented_lines(unit_text("quantime-ingest-report.service")))
    assert "report-summary" in live, "报告汇总没走 report-summary"
    assert "grep" not in live, "报告汇总又在 grep JSON（会读到某条序列的 coverage）"
    assert "--offline" in live and "--extra ingest" not in live, "汇总不该解析依赖或装网络库"


def test_the_report_service_neither_writes_nor_goes_online():
    """报告汇总只读本地文件：不给写权限、不给网络。"""
    text = unit_text("quantime-ingest-report.service")
    assert "PrivateNetwork=true" in text, "报告汇总不需要网络，应当断网运行"
    assert "ReadWritePaths=" not in "\n".join(uncommented_lines(text)), "报告汇总不该有任何写权限"


# ---- R8：部署约束 ----


def test_both_services_run_in_the_resident_checkout_with_one_data_root():
    """数据根统一（R8）：两个 service 都经 `QUANTIME_DATA_ROOT` 指到同一处，不再各写 `--root`。"""
    for name in SERVICES:
        assert directives(name, "WorkingDirectory") == [CHECKOUT], name
        assert f"QUANTIME_DATA_ROOT={DATA_ROOT}" in directives(name, "Environment"), name
        live = "\n".join(uncommented_lines(unit_text(name)))
        assert "--root" not in live, f"{name} 又在命令行里写 --root（与环境变量两处真相）"
        assert "%h/quantime" not in live, f"{name} 还指着旧路径 ~/quantime"


def test_the_ingest_service_pulls_fast_forward_only_before_running():
    """每次运行前 `git -C <检出> pull --ff-only`；它是唯一一条出沙箱（`+`）的命令。"""
    name = "quantime-ingest@.service"
    assert directives(name, "ExecStartPre") == [f"+/usr/bin/git -C {CHECKOUT} pull --ff-only"]
    for key in ("ExecStart", "ExecStopPost"):
        (value,) = directives(name, key)
        assert not value.startswith(("+", "!", "-", "@", ":")), f"{key} 不许带特权/忽略前缀"
    assert directives(name, "OnFailure") == [], "pull_failed 由 ExecStopPost 记，不另挂 unit"
    # ExecStart 只用装好的环境：不 sync（不写检出里的 .venv）、不出网解析依赖。
    assert "--no-sync" in command_block(name, "ExecStart")
    assert "--offline" in command_block(name, "ExecStart")


def test_the_ingest_service_guards_disk_space_explicitly():
    assert "--min-free-gb 5" in command_block("quantime-ingest@.service", "ExecStart")


def test_the_resident_checkout_is_read_only_and_only_the_data_root_is_writable():
    """常驻检出只读，data/ 是唯一例外（owner 裁决）：ReadWritePaths 恰好只有数据根。"""
    name = "quantime-ingest@.service"
    assert directives(name, "ReadWritePaths") == [DATA_ROOT]
    assert directives(name, "ProtectHome") == ["read-only"]
    assert directives(name, "ProtectSystem") == ["strict"]
    assert directives(name, "ReadOnlyPaths") == [CHECKOUT]
    for key in ("BindPaths", "PrivateUsers", "DynamicUser"):
        assert directives(name, key) == [], f"{name} 出现 {key}=（会改变上面的只读判定）"


def _systemd_to_sh(block: str) -> str:
    """把 unit 里的 `sh -c '...'` 取出来，按 systemd 的规则替换 `$$` 与 `%i`。"""
    script = block.split("sh -c '", 1)[1].rsplit("'", 1)[0]
    return script.replace("$$", "$").replace("%i", "binance_vision")


@pytest.mark.parametrize(
    ("env", "records"),
    [
        ({"SERVICE_RESULT": "exit-code"}, True),  # ExecStartPre（git pull）失败：主进程没跑
        ({"SERVICE_RESULT": "timeout"}, True),  # pull 卡住超时
        ({"SERVICE_RESULT": "exit-code", "EXIT_CODE": "exited", "EXIT_STATUS": "1"}, False),
        ({"SERVICE_RESULT": "success", "EXIT_CODE": "exited", "EXIT_STATUS": "0"}, False),
    ],
)
def test_exec_stop_post_records_pull_failed_only_when_the_main_process_never_ran(
    tmp_path, env, records
):
    """真跑一遍 ExecStopPost 的脚本（`uv` 换成记录参数的桩）。

    systemd 只在主进程跑过时设 `$EXIT_CODE`；ExecStartPre 失败时 ExecStart 不启动，
    结果非 success 且无 `$EXIT_CODE` → 记 `pull_failed`。摄取自己失败时 daily 已记过，不重复。
    """
    stub = tmp_path / "uv"
    calls = tmp_path / "calls"
    stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {calls}\n', encoding="utf-8")
    stub.chmod(0o755)
    script = _systemd_to_sh(command_block("quantime-ingest@.service", "ExecStopPost"))
    proc = subprocess.run(
        ["/bin/sh", "-c", script],
        env={"PATH": f"{tmp_path}:/usr/bin:/bin", **env},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    if not records:
        assert not calls.exists(), "摄取本身的失败 / 成功被误记成 pull_failed"
        return
    argv = calls.read_text(encoding="utf-8").splitlines()
    assert argv[:5] == ["run", "--no-sync", "--offline", "--package", "quantime-data"]
    joined = " ".join(argv)
    assert "record-abort --reason pull_failed" in joined
    assert "--source binance_vision" in joined
    assert env["SERVICE_RESULT"] in joined


def test_package_code_never_names_the_resident_checkout():
    """代码不写死常驻检出路径：写到哪只由 `--root` / `QUANTIME_DATA_ROOT` 决定（R8）。"""
    hits = [
        str(p.relative_to(REPO))
        for p in (REPO / "packages").rglob("*.py")
        if "/tests/" not in str(p) and "/home/workspace" in p.read_text(encoding="utf-8")
    ]
    assert hits == [], f"包代码写死了常驻检出路径: {hits}"


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
def test_systemd_analyze_verify_passes_on_the_binance_vision_instances(tmp_path):
    """模板实例化之后（`%i` = binance_vision）同样通过。"""
    for suffix in ("service", "timer"):
        src = UNIT_DIR / f"quantime-ingest@.{suffix}"
        (tmp_path / f"quantime-ingest@binance_vision.{suffix}").write_text(
            src.read_text(encoding="utf-8"), encoding="utf-8"
        )
    proc = subprocess.run(
        [
            "systemd-analyze", "verify", "--user",
            "./quantime-ingest@binance_vision.service", "./quantime-ingest@binance_vision.timer",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )  # fmt: skip
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


def test_install_md_documents_the_r8_deployment_choices():
    """R8：数据根、pull_failed 的记录方式、磁盘守卫、需 root 的步骤单列。"""
    text = (UNIT_DIR / "INSTALL.md").read_text(encoding="utf-8")
    for needle in (
        f"QUANTIME_DATA_ROOT={DATA_ROOT}",
        f"--root {DATA_ROOT}",
        "git -C /home/workspace/quantime pull --ff-only",
        "ExecStopPost",
        "pull_failed",
        "disk_low",
        "--min-free-gb",
        "owner 回来执行",
        "pending_since",
    ):
        assert needle in text, f"INSTALL.md 缺少 {needle!r}"
    assert "~/quantime" not in text, "INSTALL.md 还指着旧路径 ~/quantime"


def test_install_md_does_not_ask_for_a_hand_made_funding_watermark():
    """R7：首跑 pending 由 `pending_since` 接住，不许靠手工回填 / 预热去「建立水位线」。"""
    text = (UNIT_DIR / "INSTALL.md").read_text(encoding="utf-8")
    for forbidden in ("预热", "建立水位线", "自然取回"):
        assert forbidden not in text, f"INSTALL.md 出现 {forbidden!r}"


def test_install_md_documents_no_plaintext_credentials():
    text = (UNIT_DIR / "INSTALL.md").read_text(encoding="utf-8")
    assert "quant-dev" in text, "INSTALL.md 未说明业务凭据来自 vault quant-dev"
    assert re.search(SECRET_PATTERN, text) is None, "INSTALL.md 里出现了明文凭据形状"
