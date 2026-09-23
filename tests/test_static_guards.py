"""静态守卫（QNT-27 验收「静态」段 + crypto-boundaries ②）。

这些断言在 CI 之外也可被同一条 `grep` 复核，测试只是把它们钉住并给出定位。
统一排除 `tests/` 目录：测试要故意构造被拒绝的输入，不是写入路径。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PACKAGES = REPO / "packages"

#: 验收要求的写入路径 grep 模式（原文照录）。
MUTATION_PATTERN = r"UPDATE|DELETE|overwrite|mode=.w."

#: 逐处注明「为何不是覆盖」的豁免：`相对路径` → 理由。当前为空——写入路径 0 处命中。
MUTATION_EXEMPTIONS: dict[str, str] = {}


def _grep(pattern: str, root: Path, *, include: str = "*.py") -> list[str]:
    proc = subprocess.run(
        ["grep", "-rEn", f"--include={include}", pattern, str(root)],
        capture_output=True,
        text=True,
    )
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def _relpath(hit: str) -> str:
    return hit.split(":", 1)[0].replace(str(PACKAGES) + "/", "")


def _non_test_hits(hits: list[str]) -> list[str]:
    return [h for h in hits if "/tests/" not in h]


def test_no_update_delete_overwrite_in_write_paths():
    """验收：`grep -rE "UPDATE|DELETE|overwrite|mode=.w." packages/` 在写入路径为 0 处。"""
    hits = _non_test_hits(_grep(MUTATION_PATTERN, PACKAGES))
    unexplained = [h for h in hits if _relpath(h) not in MUTATION_EXEMPTIONS]
    assert unexplained == [], (
        "写入路径出现改写语义，需消除或在 MUTATION_EXEMPTIONS 逐处注明:\n" + "\n".join(unexplained)
    )


def test_no_sql_mutation_verbs_in_duckdb_layer():
    """视图层只 CREATE OR REPLACE VIEW/MACRO，不得出现 INSERT/UPDATE/DELETE 业务行的 SQL。"""
    hits = _non_test_hits(
        _grep(r"\b(INSERT INTO|UPDATE |DELETE FROM|CREATE TABLE)\b", PACKAGES / "data")
    )
    assert hits == [], "DuckDB 层出现持久化业务表的 SQL（§4.2 只作查询/视图层）:\n" + "\n".join(
        hits
    )


def test_no_mainnet_host_literals_in_packages():
    """crypto-boundaries ②：下单/账户/资金类代码禁止主网 host 字面量。

    本卡尚无 `execution`/`risk` 包，范围收紧为整个 `packages/` 非测试代码。
    """
    mainnet = r"api\.binance\.com|fapi\.binance\.com|api\.bybit\.com|www\.okx\.com|api\.bitget\.com"
    hits = [h for h in _non_test_hits(_grep(mainnet, PACKAGES)) if not _is_comment(h)]
    assert hits == [], "packages/ 出现主网 host 字面量:\n" + "\n".join(hits)


def _is_comment(hit: str) -> bool:
    """`path:lineno:text` 中 text 是纯注释行。"""
    text = hit.split(":", 2)[2] if hit.count(":") >= 2 else ""
    return text.lstrip().startswith("#")


#: allowlist 里登记过的 API host 字面量（ERE）。凡是能当出网目标用的 host，
#: 都只许出现在 `core/allowlist.py` 一处。
#:
#: 刻意只匹配 `api.` / `files.` 开头的那几个，而不是整个 `massive\.com`：`https://massive.com/docs/…`
#: 与 `https://massive.com/legal/…` 是**文档与条款链接**，不是出网目标，适配器的文档头必须
#: 能引用它们（crypto-boundaries ① 反而要求附官方文档链接）。
ALLOWLISTED_HOST_PATTERN = r"binance\.vision|api\.massive\.com|api\.polygon\.io|files\.massive\.com"


def test_allowlist_is_the_only_file_with_allowlisted_host_literals():
    """§3.3：`core/allowlist.py` 是唯一允许出现 allowlist host 字面量的文件。

    其余模块引用具名条目（`MASSIVE_REST.host`）而不是复制字符串——否则会长出第二份
    绕过 allowlist 的 host 表，本守卫的 grep 也随之失效。
    """
    files = {_relpath(h) for h in _non_test_hits(_grep(ALLOWLISTED_HOST_PATTERN, PACKAGES))}
    assert files <= {"core/quantime_core/allowlist.py"}, f"host 字面量泄漏到: {sorted(files)}"


def test_the_allowlist_really_holds_those_literals():
    """反证：上一条不是空集通过——allowlist.py 里每个 host 家族都确实有字面量。"""
    hits = _grep(ALLOWLISTED_HOST_PATTERN, PACKAGES / "core" / "quantime_core" / "allowlist.py")
    assert hits, "allowlist.py 里没有 host 字面量 —— 泄漏测试成了空集通过"
    for family in ("binance.vision", "api.massive.com", "api.polygon.io", "files.massive.com"):
        assert any(family in h for h in hits), f"allowlist 里缺 {family}"


#: key 形态的字面量（ERE）。值须 ≥21 字符且含小写字母——`FOO_KEY = "MASSIVE_API_KEY"`
#: 这种全大写的环境变量名因此不会被误报，而真 key（Massive 的是 32 位混合大小写字母数字）
#: 会被抓住。ruff format 把 Python 字符串统一成双引号，所以只匹配双引号即可。
KEY_LITERAL_PATTERN = (
    r"([Aa][Pp][Ii][_-]?[Kk][Ee][Yy]|[Ss][Ee][Cc][Rr][Ee][Tt]|[Tt][Oo][Kk][Ee][Nn]"
    r"|[Cc][Rr][Ee][Dd][Ee][Nn][Tt][Ii][Aa][Ll])[A-Za-z0-9_]*[[:space:]]*[=:][[:space:]]*"
    r'"[A-Za-z0-9_+/.=-]{10,}[a-z][A-Za-z0-9_+/.=-]{10,}"'
)


def test_no_key_shaped_literals_in_packages():
    """AGENTS.md §3：禁止手抄秘钥。key 只经 `op` 注入，仓库里不得有 key 形态的字面量。"""
    hits = [h for h in _non_test_hits(_grep(KEY_LITERAL_PATTERN, PACKAGES)) if not _is_comment(h)]
    assert hits == [], "出现疑似硬编码的凭据字面量:\n" + "\n".join(hits)


def test_the_key_literal_guard_is_not_vacuous(tmp_path):
    """反证：把一条真 key 形态的行写进临时文件，同一条 grep 必须命中。"""
    probe = tmp_path / "probe.py"
    probe.write_text('API_KEY = "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY"\n', encoding="utf-8")
    assert _grep(KEY_LITERAL_PATTERN, tmp_path), "key 形态守卫抓不到真 key —— 它是空集通过"
    # 环境变量名不该被误报（否则守卫会被「先加豁免」削弱）。
    probe.write_text('API_KEY_ENV = "MASSIVE_API_KEY"\n', encoding="utf-8")
    assert _grep(KEY_LITERAL_PATTERN, tmp_path) == [], "全大写环境变量名被误报"


#: 真正的 1Password 引用（`op://<vault>/…`）。行文提到协议名不算；写成字符类使本文件不自我命中。
OP_REFERENCE_PATTERN = r"op:/[/][A-Za-z0-9_-]+/"


def test_op_references_live_only_in_templates_and_docs():
    """AGENTS.md §3：仓库只跟踪 `*.tpl`（含 `op://` 引用）；代码里不得出现 `op://` 字面量。

    代码里写 `op://…` 等于把凭据位置硬编码进出网路径；`op run --env-file=<tpl>` 才是
    唯一注入口。`docs/` 允许出现是因为它在**记述**该引用，不会被执行。
    """
    tracked = subprocess.run(
        ["git", "grep", "-lnE", OP_REFERENCE_PATTERN], cwd=REPO, capture_output=True, text=True
    ).stdout.splitlines()
    offenders = [
        t
        for t in tracked
        if not t.endswith(".tpl")
        and not t.startswith("docs/")
        and t not in {".gitignore", "AGENTS.md"}
    ]
    assert offenders == [], f"`op://` 字面量出现在模板与文档之外: {offenders}"


def test_the_massive_template_is_tracked_and_holds_only_a_reference():
    """模板必须在库里（否则 `op run --env-file=` 无从谈起），且只含引用不含值。"""
    tpl = REPO / "docs" / "ops" / "massive.env.tpl"
    tracked = subprocess.run(
        ["git", "ls-files", "docs/ops/massive.env.tpl"], cwd=REPO, capture_output=True, text=True
    ).stdout.strip()
    assert tracked, "massive.env.tpl 未被跟踪"
    text = tpl.read_text(encoding="utf-8")
    from quantime_data.sources.massive import CREDENTIAL_POINTER

    reference = CREDENTIAL_POINTER.replace("op:", "op:/" + "/", 1)
    assert f'MASSIVE_API_KEY="{reference}"' in text
    # 模板里不得出现任何 key 形态的值（只许有 op:// 引用）。
    assert _grep(KEY_LITERAL_PATTERN, tpl, include="*.tpl") == [], "模板里出现疑似真值"


def test_core_imports_no_network_clients():
    """§3.3：整个 core 不得 import 任何网络客户端（import-linter 同规则的 grep 侧复核）。"""
    pattern = r"^\s*(import|from)\s+(httpx|websockets|requests|urllib|socket|http\.client)\b"
    hits = _non_test_hits(_grep(pattern, PACKAGES / "core"))
    assert hits == [], "core 引入网络客户端:\n" + "\n".join(hits)


def test_gitignore_covers_data_duckdb_and_real_env_files():
    text = (REPO / ".gitignore").read_text(encoding="utf-8")
    for needle in ["/data/", "*.duckdb", ".env*", "!*.tpl"]:
        assert needle in text, f".gitignore 缺少 {needle}"


def test_no_data_or_duckdb_or_real_env_files_are_tracked():
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert [t for t in tracked if t.startswith("data/")] == []
    # `/data/` 是根锚定的：packages/data/ 必须仍被跟踪，否则数据包整个漏掉。
    assert any(t.startswith("packages/data/quantime_data/") for t in tracked)
    assert [t for t in tracked if t.endswith(".duckdb")] == []
    envs = [t for t in tracked if re.search(r"(^|/)\.env", t) and not t.endswith(".tpl")]
    assert envs == []


def test_only_declared_packages_exist():
    """AGENTS.md §2 / 卡范围：只建 core 与 data，其他包目录不预建。"""
    assert sorted(p.name for p in PACKAGES.iterdir() if p.is_dir()) == ["core", "data"]


def test_fixtures_are_synthetic_only_and_generated_artifacts_not_committed():
    """AGENTS.md §2：`fixtures/` 只放合成数据；§5.1：生成物不入库。"""
    bench = REPO / "fixtures" / "bench"
    assert "synthetic: true" in (bench / "factors.yaml").read_text(encoding="utf-8")
    assert "synthetic: true" in (bench / "bench_gen.py").read_text(encoding="utf-8")
    generated = [p.name for p in bench.iterdir() if p.suffix in {".parquet", ".zip", ".csv"}]
    assert generated == [], f"生成物不入库，发现: {generated}"


#: AGENTS.md §2「fixtures/ 只放合成数据」的**唯一**豁免目录 → 理由（PR 描述偏离项 #3）。
#: 离线重放外部接入必须用真实响应的录制，否则测的是我们自己编的格式。
NON_SYNTHETIC_FIXTURE_DIRS = {
    "binance_public": "QNT-28：Binance 公开归档的真实响应录制，供离线集成测试重放",
    "massive_recorded": (
        "QNT-47 阶段 2：Massive 真实响应脱敏录制（REST 正文去 request_id；"
        "day_aggs 仅取前 100 行），MANIFEST 标 synthetic: false"
    ),
}


#: 合成 fixture 目录 → 用途。合成性不是靠出现在这个集合里成立的，而是靠目录内的
#: `synthetic: true` 声明——下一条测试逐目录核对那个声明确实存在。
SYNTHETIC_FIXTURE_DIRS = {
    "bench": "QNT-40：确定性基准输入，由 bench_gen.py 生成",
    "massive": "QNT-47：按公开文档**手写**的合成响应（MANIFEST.json 标 synthetic: true）",
}


def test_every_synthetic_fixture_dir_actually_declares_itself_synthetic():
    """出现在 SYNTHETIC_FIXTURE_DIRS 里不等于是合成的——目录里必须有那句声明。"""
    for name in SYNTHETIC_FIXTURE_DIRS:
        d = REPO / "fixtures" / name
        declared = any(
            needle in f.read_text(encoding="utf-8", errors="ignore")
            for f in d.rglob("*")
            if f.is_file() and f.suffix in {".json", ".yaml", ".yml", ".py", ".md"}
            for needle in ("synthetic: true", '"synthetic": true')
        )
        assert declared, f"fixtures/{name}/ 未声明 synthetic: true"


def test_the_massive_fixtures_declare_their_doc_provenance():
    """合成件不是录制件，没有 sha256 可核——它能被核对的是「按哪篇文档、哪天写的」。"""
    import json

    d = REPO / "fixtures" / "massive"
    manifest = json.loads((d / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True, "手写件必须显式标 synthetic: true"
    assert manifest["doc_access_date"], "缺访问日期"
    assert manifest["doc_sources"], "缺文档 URL"
    for url in manifest["doc_sources"]:
        assert url.startswith("https://"), url
    on_disk = {f.name for f in d.glob("*.json")} - {"MANIFEST.json"}
    assert {e["file"] for e in manifest["files"]} == on_disk, "MANIFEST 与目录内容不一致"
    for entry in manifest["files"]:
        assert entry["doc_url"].startswith("https://"), entry["file"]
        assert entry["endpoint"], entry["file"]
        json.loads((d / entry["file"]).read_text(encoding="utf-8"))  # 必须是合法 JSON


def test_the_massive_recordings_declare_their_provenance_and_carry_no_key():
    """Massive 录制件是**手工一次性**脱敏录下的（owner 凭据，不留录制脚本以免被当成可跑入口）。

    能核对的是：URL（https、无 apiKey）+ sha256 + 尺寸；目录内容与 MANIFEST 一一对应。
    """
    import hashlib
    import json

    d = REPO / "fixtures" / "massive_recorded"
    manifest = json.loads((d / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["synthetic"] is False, "录制件必须显式标 synthetic: false"
    assert manifest["recorded_at"], "缺录制日期"
    on_disk = {f.name for f in d.iterdir() if f.is_file()} - {"MANIFEST.json"}
    assert {e["file"] for e in manifest["files"]} == on_disk, "MANIFEST 与目录内容不一致"
    for entry in manifest["files"]:
        payload = (d / entry["file"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"], entry["file"]
        assert len(payload) == entry["size"], entry["file"]
        assert entry["url"].startswith("https://"), entry["url"]
        assert "apikey" not in entry["url"].lower(), entry["url"]
        assert entry["sanitized"], entry["file"]
        assert b"request_id" not in payload, f"{entry['file']} 未去 request_id"
        assert b"apiKey" not in payload, f"{entry['file']} 含 apiKey"


def test_only_the_declared_fixture_dir_holds_non_synthetic_data():
    """录制 fixture 是**逐目录**豁免，不是对 fixtures/ 整体放行。"""
    fixtures = REPO / "fixtures"
    dirs = {p.name for p in fixtures.iterdir() if p.is_dir() and p.name != "__pycache__"}
    undeclared = dirs - set(SYNTHETIC_FIXTURE_DIRS) - set(NON_SYNTHETIC_FIXTURE_DIRS)
    assert undeclared == set(), (
        f"新 fixture 目录未声明合成性: {sorted(undeclared)}"
        "（合成数据加 `synthetic: true` 头；录制数据须在 NON_SYNTHETIC_FIXTURE_DIRS 注明理由）"
    )


def test_recorded_fixtures_declare_their_provenance_and_record_no_headers():
    """录制件必须能被独立核对：URL + sha256 + 尺寸在案，且只录响应正文。

    请求/响应头里可能带 cookie、限流配额、节点标识——与数据无关，一律不落盘。
    """
    import hashlib
    import json

    d = REPO / "fixtures" / "binance_public"
    manifest = json.loads((d / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["synthetic"] is False, "录制件必须显式标 synthetic: false"
    assert manifest["files"], "MANIFEST 无条目"
    for entry in manifest["files"]:
        payload = (d / entry["file"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"], entry["file"]
        assert len(payload) == entry["size"], entry["file"]
        assert entry["url"].startswith("https://"), entry["url"]
    text = (d / "record.py").read_text(encoding="utf-8")
    for banned in ("headers=", "cookies", "request.headers", "response.headers"):
        assert banned not in text, f"录制脚本疑似落盘请求/响应头: {banned!r}"


def test_bench_generator_makes_no_network_calls():
    """§5.1：基准输入不走网络。"""
    pattern = r"\b(httpx|requests|urllib|socket|websockets|curl|wget)\b"
    hits = _grep(pattern, REPO / "fixtures")
    assert hits == [], "fixtures/ 出现网络调用:\n" + "\n".join(hits)


#: `.github/workflows/ci.yml` 里静态守卫步骤的名字——测试直接抽出它的 `run:` 脚本执行，
#: 而不是在测试里复制一份等价管线（复制品和 CI 会各自漂移）。
CI_WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
CI_STATIC_GUARD_STEP = "Static guards (ADR-0002 只 insert / crypto-boundaries ②)"

#: 前缀感知的注释过滤（QNT-27 P2）。`grep -rEn` 输出 `path:lineno:text`，
#: 必须连前缀一起匹配；`^\s*#` 单独用在这种输出上永不命中，是无效过滤。
COMMENT_FILTER = r"^[^:]+:\d+:\s*#"


def _ci_step_script(step_name: str) -> str:
    """从 ci.yml 抽出某个 step 的 `run: |` 脚本原文（不引第三方 YAML 解析器）。"""
    lines = CI_WORKFLOW.read_text(encoding="utf-8").splitlines()
    heads = [n for n, line in enumerate(lines) if line.strip() == f"- name: {step_name}"]
    if len(heads) != 1:
        raise AssertionError(f"ci.yml 里 step {step_name!r} 出现 {len(heads)} 次，期望 1 次")
    i = heads[0]
    assert lines[i + 1].strip() == "run: |", f"step {step_name!r} 不是 `run: |` 块"
    body_indent = len(lines[i + 2]) - len(lines[i + 2].lstrip())
    body = []
    for line in lines[i + 2 :]:
        if line.strip() and len(line) - len(line.lstrip()) < body_indent:
            break
        body.append(line[body_indent:] if line.strip() else "")
    return "\n".join(body)


def _run(script: str) -> subprocess.CompletedProcess:
    """按 CI 的 shell 跑：`-e` 不可省。

    GitHub Actions 的 `run: |` 用 `shell: /usr/bin/bash -e {0}`。没有 `-e` 时只有
    **最后一条**命令的退出码算数，守卫步骤里前面几段被改坏也照样"通过"——
    QNT-28 追加第三、四段检查时，P2 变异正是这样失去效力的。
    """
    return subprocess.run(["bash", "-e", "-c", script], cwd=REPO, capture_output=True, text=True)


def test_ci_static_guard_step_passes_as_shipped():
    r"""P2（CI run 35566457361）：直接跑 ci.yml 里那段脚本，必须退出 0。

    原失败点：`grep -rEn` 输出 `path:lineno:text`，后续 `grep -v '^\s*#'` 匹配不到行首，
    allowlist.py 的说明性注释因此把 CI 打红。范围没问题，过滤方式有问题。
    """
    script = _ci_step_script(CI_STATIC_GUARD_STEP)
    proc = _run(script)
    assert proc.returncode == 0, f"ci.yml 静态守卫步骤失败:\n{proc.stdout}\n{proc.stderr}"


def test_ci_static_guard_comment_filter_is_not_vacuous():
    """反证：该 host 字面量确实存在（在注释里），过滤不是空集通过；旧写法仍是红的。"""
    mainnet = r"api\.binance\.com|fapi\.binance\.com|api\.bybit\.com|www\.okx\.com|api\.bitget\.com"
    raw = _run(f"grep -rEn --include='*.py' '{mainnet}' packages/ | grep -v '/tests/'")
    assert raw.stdout.strip(), "没有任何命中——过滤测试成了空集通过"
    assert all(_is_comment(ln) for ln in raw.stdout.splitlines()), (
        "命中里有非注释行，应由 test_no_mainnet_host_literals_in_packages 拦下"
    )
    broken = _run(
        f"! grep -rEn --include='*.py' '{mainnet}' packages/ "
        f"| grep -v '/tests/' | grep -v '^\\s*#' | grep ."
    )
    assert broken.returncode != 0, "旧过滤写法居然通过了——这条回归测试失去意义"


def test_ci_static_guard_keeps_full_scope_and_grants_no_exemption():
    """修过滤方式的同时不得缩小 grep 范围、不得给 allowlist.py 开豁免（planner 派单约束）。"""
    script = _ci_step_script(CI_STATIC_GUARD_STEP)
    runnable = "\n".join(ln for ln in script.splitlines() if not ln.lstrip().startswith("#"))
    assert COMMENT_FILTER in runnable, "ci.yml 未使用前缀感知的注释过滤"
    assert "grep -v '^\\s*#'" not in runnable, "ci.yml 仍有失效的 `grep -v '^\\s*#'`"
    assert "packages/" in runnable and "grep -v '/tests/'" in runnable, "grep 范围被缩小"
    assert "allowlist.py" not in runnable, "给 allowlist.py 开了豁免"
    for host in ("api\\.binance\\.com", "api\\.bybit\\.com", "www\\.okx\\.com"):
        assert host in runnable, f"host 边界被放宽，缺 {host}"


def test_ci_static_guard_fails_on_the_first_check_not_only_the_last():
    r"""每条检查都必须能单独把步骤打红（QNT-28 变异验证暴露）。

    原写法是一串 `! grep ... | grep .`。`set -e` 按 POSIX **不适用于**被 `!` 取反的
    命令，所以整步的退出码只由最后一条决定——前面几条命中也照样绿。这条测试逐条注入
    一个必然命中的模式，断言每一条都能让退出码非 0。
    """
    script = _ci_step_script(CI_STATIC_GUARD_STEP)
    assert _run(script).returncode == 0, "未注入前就是红的"

    # 逐条把模式替换成必然命中的 `.`，确认每条都能单独打红。
    lines = script.splitlines()
    deny_idx = [n for n, ln in enumerate(lines) if ln.lstrip().startswith("deny ")]
    assert len(deny_idx) >= 6, f"ci.yml 只有 {len(deny_idx)} 条 deny，期望 ≥6 条"
    for i in deny_idx:
        mutated = list(lines)
        # 模式可能在同一行，也可能在续行上——两种都换掉第一个引号串。
        target = i if "'" in lines[i] else i + 1
        mutated[target] = re.sub(r"'[^']*'", "'.'", mutated[target], count=1)
        proc = _run("\n".join(mutated))
        assert proc.returncode != 0, (
            f"第 {deny_idx.index(i) + 1} 条 deny 命中了却没能把步骤打红:\n{proc.stdout}"
        )


def test_ci_static_guard_op_reference_check_can_fail_the_step():
    """`op://` 那段不是 `deny`（它扫全部被跟踪文件），所以单独钉它也能把步骤打红。"""
    script = _ci_step_script(CI_STATIC_GUARD_STEP)
    assert f"git grep -lnE '{OP_REFERENCE_PATTERN}'" in script, "ci.yml 缺少 op:// 守卫"
    assert _run(script).returncode == 0, "未注入前就是红的"
    # 把豁免列表换成一个匹配不到任何路径的模式：模板与文档里的 op:// 会随即变成命中。
    mutated = script.replace(
        "'\\.tpl$|^docs/|^\\.gitignore$|^AGENTS\\.md$'", "'^__no_such_path__$'"
    )
    assert mutated != script, "变异没有生效 —— 豁免模式的写法变了"
    proc = _run(mutated)
    assert proc.returncode != 0, f"op:// 守卫命中了却没能把步骤打红:\n{proc.stdout}"


# ---- QNT-28：公开只读摄取的出网边界 ----

#: 唯一允许 import 网络客户端的模块（相对 `packages/`）。
NETWORK_EGRESS_FILE = "data/quantime_data/cli.py"

#: 交易 / 账户 / 资金端点。公共只读摄取不该认识它们中的任何一个。
TRADING_ENDPOINT_PATTERN = (
    r"/api/v3/(order|openOrders|allOrders|account|myTrades|userDataStream)"
    r"|/fapi/v[0-9]+/(order|positionRisk|account|balance|leverage)"
    r"|/sapi/"
)


def test_network_clients_appear_only_in_the_ingest_cli():
    """出网点收敛到一处：第二个 import httpx 的模块就可能绕过 allowlist 与退避。"""
    # urllib.parse 是纯字符串解析、不出网，所以按子模块匹配而不是整个 urllib。
    pattern = (
        r"^\s*(import|from)\s+"
        r"(httpx|requests|websockets|socket|urllib\.request|http\.client|boto3|botocore|aiobotocore)\b"
    )
    files = {_relpath(h) for h in _non_test_hits(_grep(pattern, PACKAGES))}
    assert files <= {NETWORK_EGRESS_FILE}, f"网络客户端泄漏到: {sorted(files)}"


def test_the_ingest_cli_really_is_the_egress():
    """反证：上一条不是空集通过——CLI 里确实有那个 import。"""
    hits = _grep(r"import httpx", PACKAGES / "data" / "quantime_data" / "cli.py")
    assert hits, "cli.py 里没有 httpx —— 出网收敛测试成了空集通过"
    hits = _grep(r"import boto3", PACKAGES / "data" / "quantime_data" / "cli.py")
    assert hits, "cli.py 里没有 boto3 —— Flat Files 出口收敛测试成了空集通过"


def test_no_trading_or_account_endpoint_literals_in_packages():
    """crypto-boundaries ② / ADR-0001 D1.7：摄取路径不得出现下单/账户/资金端点。"""
    hits = [
        h for h in _non_test_hits(_grep(TRADING_ENDPOINT_PATTERN, PACKAGES)) if not _is_comment(h)
    ]
    assert hits == [], "出现交易/账户/资金端点字面量:\n" + "\n".join(hits)


def test_public_readonly_path_whitelist_contains_no_trading_endpoint():
    """白名单本身也要过一遍这把尺子——它是放行清单，写错就是直接放行。"""
    from quantime_data.transport import PUBLIC_READONLY_PREFIXES

    bad = [p for p in PUBLIC_READONLY_PREFIXES if re.search(TRADING_ENDPOINT_PATTERN, p)]
    assert bad == [], f"公共只读白名单里出现交易/账户端点: {bad}"


#: 交易/账户/资金的**词根**。端点命名各家不同，穷举路径挡不住新上游，所以白名单
#: 自检按词根来——白名单是放行清单，写错就是直接放行。
TRADING_WORD_ROOTS = (
    "order",
    "account",
    "position",
    "balance",
    "withdraw",
    "transfer",
    "trading",
    "wallet",
    "funding",
)


def test_keyed_readonly_whitelist_contains_no_trading_endpoint():
    """QNT-47：需 key 的白名单同样要过这把尺子——它带着凭据，写错的代价更高。"""
    from quantime_data.keyed_transport import KEYED_READONLY_ALL

    assert KEYED_READONLY_ALL, "白名单为空 —— 本条成了空集通过"
    bad = [p for p in KEYED_READONLY_ALL if re.search(TRADING_ENDPOINT_PATTERN, p)]
    assert bad == [], f"需 key 的白名单里出现交易/账户端点: {bad}"
    rooted = [p for p in KEYED_READONLY_ALL for w in TRADING_WORD_ROOTS if w in p.lower()]
    assert rooted == [], f"需 key 的白名单里出现交易类词根: {rooted}"


def test_keyed_readonly_hosts_are_not_trading_hosts():
    """带凭据的行情出口的 host 绝不能同时是合法的下单出口（ADR-0001 D1.7）。"""
    from quantime_core.allowlist import TradingBoundaryError, assert_trading_host
    from quantime_data.keyed_transport import KEYED_READONLY_PATHS

    assert KEYED_READONLY_PATHS
    for host in ("api.massive.com", "api.polygon.io"):
        with pytest.raises(TradingBoundaryError):
            assert_trading_host(host)


def test_ci_static_guard_egress_scope_is_not_weakened():
    """ci.yml 的出网点守卫必须精确到 cli.py：放宽到整个包等于不拦（QNT-28）。"""
    script = _ci_step_script(CI_STATIC_GUARD_STEP)
    runnable = "\n".join(ln for ln in script.splitlines() if not ln.lstrip().startswith("#"))
    assert "quantime_data/cli\\.py" in runnable, "出网点豁免不再精确到 cli.py"
    assert "httpx" in runnable, "ci.yml 缺少网络客户端守卫"
    assert "/sapi/" in runnable, "ci.yml 缺少交易/账户端点守卫"


def test_ci_static_guard_step_covers_everything_the_tests_assert():
    """CI 与本文件不得各自漂移：这里断言的每一段范围，ci.yml 里必须都有。"""
    script = _ci_step_script(CI_STATIC_GUARD_STEP)
    for needle in (
        "UPDATE|DELETE",
        "api\\.binance\\.com",
        "/api/v3/(order",
        "import|from",
        "api\\.massive\\.com",  # QNT-47：allowlist host 字面量归位
        "[Kk][Ee][Yy]",  # QNT-47：key 形态字面量
        "op:/[/][A-Za-z0-9_-]+/",  # QNT-47：op 引用只许在模板与文档里
    ):
        assert needle in script, f"ci.yml 静态守卫缺少 {needle!r} 这一段"


# ---- R1 第 5、6 点：文档命令可用 / 重跑术语统一 ----


def test_record_script_documents_a_runnable_command():
    """`record.py` 的用法行必须是真能跑的那条（verify-a R1 第 5 点）。

    `ingest` extra 属 `quantime-data`，根项目没有它——仓库根目录直接
    `uv run --extra ingest …` 会报 unknown extra。文档里的命令跑不起来，等于没有文档。
    """
    text = (REPO / "fixtures" / "binance_public" / "record.py").read_text(encoding="utf-8")
    usage = [ln for ln in text.splitlines() if "record.py`" in ln and "uv run" in ln]
    assert usage, "record.py 缺少用法行"
    for line in usage:
        assert "--package quantime-data" in line, f"缺少 --package，根目录跑不通: {line}"
        assert "--extra ingest" in line, line


def test_rerun_is_recorded_as_kind_not_source():
    """ADR-0003 §4.1/§4.3：`source` 是数据源单值，重跑标在 `kind='rerun'` + `rerun_of`。

    `source='rerun'` 会把「数据从哪来」和「这是第几次跑」挤进同一个字段，单源不变量
    （同一 batch 的 source 唯一）随即失去意义。这条钉住代码里没有按 source 判重跑的地方。
    """
    hits = _grep(r"source\s*[=:]\s*[\"']rerun", PACKAGES)
    assert hits == [], "出现 source='rerun'（应为 kind='rerun' + rerun_of）:\n" + "\n".join(hits)

    # 「重跑」是 kind 枚举的一个取值，不是一个 source。
    from quantime_core.paths import PathSpecError, assert_batch_kind

    assert assert_batch_kind("rerun") == "rerun"
    with pytest.raises(PathSpecError):
        assert_batch_kind("source_rerun")
