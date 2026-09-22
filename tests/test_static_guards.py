"""静态守卫（QNT-27 验收「静态」段 + crypto-boundaries ②）。

这些断言在 CI 之外也可被同一条 `grep` 复核，测试只是把它们钉住并给出定位。
统一排除 `tests/` 目录：测试要故意构造被拒绝的输入，不是写入路径。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

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


def test_allowlist_is_the_only_file_with_public_readonly_host_literals():
    """§3.3：`core/allowlist.py` 是唯一允许出现 `public_readonly=True` host 字面量的文件。"""
    files = {_relpath(h) for h in _non_test_hits(_grep(r"binance\.vision", PACKAGES))}
    assert files <= {"core/quantime_core/allowlist.py"}, f"host 字面量泄漏到: {sorted(files)}"


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
    return subprocess.run(["bash", "-c", script], cwd=REPO, capture_output=True, text=True)


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
    assert "packages/ | grep -v '/tests/'" in runnable, "grep 范围被缩小"
    assert "allowlist.py" not in runnable, "给 allowlist.py 开了豁免"
    for host in ("api\\.binance\\.com", "api\\.bybit\\.com", "www\\.okx\\.com"):
        assert host in runnable, f"host 边界被放宽，缺 {host}"
