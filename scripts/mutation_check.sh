#!/usr/bin/env bash
# 变异验证（AGENTS.md §5）：逐条把一个断言点改坏，确认对应测试由绿变红，然后还原。
# 每次变异前后 `rm -rf __pycache__`，最后 fresh 重跑全量。
#
# 用法： bash scripts/mutation_check.sh
# 退出码 0 = 每一条变异都成功把对应测试打红，且还原后全量绿。

set -uo pipefail
cd "$(dirname "$0")/.."

PASS=0
FAIL=0

clean() { find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null; }

# mutate <标签> <文件> <python 替换表达式> <pytest 选择器>
mutate() {
  local label="$1" file="$2" expr="$3" target="$4"
  cp "$file" "$file.mutbak"
  python3 - "$file" "$expr" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1]); old, new = sys.argv[2].split("=>>", 1)
s = p.read_text()
assert old in s, f"变异锚点未找到: {old!r} in {p}"
p.write_text(s.replace(old, new, 1))
PY
  clean
  if uv run pytest "$target" -q >/dev/null 2>&1; then
    echo "  FAIL  $label —— 变异后测试仍绿（断言无效）"
    FAIL=$((FAIL+1))
  else
    echo "  ok    $label —— 变异后由绿变红"
    PASS=$((PASS+1))
  fi
  mv "$file.mutbak" "$file"
  clean
}

CORE=packages/core/quantime_core
DATA=packages/data/quantime_data

echo "== 变异验证 =="

mutate "覆盖已有文件 → 拒绝" "$DATA/batches.py" \
  'if batch_dir.exists() and any(batch_dir.iterdir()):=>>if False:' \
  packages/data/tests/test_batches.py::test_overwriting_existing_file_in_same_batch_dir_is_rejected

mutate "单源不变量（行 source ≠ 路径 source=）" "$DATA/batches.py" \
  'if distinct_sources != {source}:=>>if False:' \
  packages/data/tests/test_batches.py::test_row_source_mismatching_path_source_is_rejected

mutate "缺 ADR-0002 五列 → 报错" "$DATA/batches.py" \
  'if missing:=>>if False:' \
  packages/data/tests/test_batches.py::test_missing_any_adr_0002_column_is_rejected

mutate "R1/R4 缺文件" "$DATA/replay.py" \
  'if missing:=>>if False:' \
  packages/data/tests/test_replay.py::test_r4_deleting_a_file_is_rejected

mutate "R4 多出未登记文件" "$DATA/replay.py" \
  'if extra:=>>if False:' \
  packages/data/tests/test_replay.py::test_r4_extra_unregistered_part_inside_listed_batch_dir_is_rejected

mutate "R4 sha 不符" "$DATA/replay.py" \
  'if got.sha256 != want.sha256:=>>if False:' \
  packages/data/tests/test_replay.py::test_r4_flipping_one_byte_is_rejected

mutate "R3 清单外 batch 被误扫描" "$DATA/replay.py" \
  'directory = root / record.batch_dir=>>directory = (root / record.batch_dir).parent' \
  packages/data/tests/test_replay.py::test_r3_late_batch_outside_manifest_does_not_break_replay

mutate "R2 结果 sha 比较" "$DATA/replay.py" \
  'if manifest.result_sha256 and actual_sha != manifest.result_sha256:=>>if False:' \
  packages/data/tests/test_replay.py::test_r2_result_sha_mismatch_is_rejected

mutate "R2 确定性 writer（压缩级别漂移）" "$CORE/parquet_io.py" \
  'COMPRESSION_LEVEL = 3=>>import os; COMPRESSION_LEVEL = 3 if os.environ.get("Q") else 5' \
  packages/core/tests/test_parquet_io.py

mutate "R5 ingestion_batch 不进清单" "$DATA/replay.py" \
  'records["ingestion_batch"] = _ingestion_batch_records(root)=>>records["ingestion_batch"] = ()' \
  packages/data/tests/test_replay.py::test_r5_mutating_ingestion_batch_file_is_rejected

mutate "allowlist: 交易断言放行只读 host" "$CORE/allowlist.py" \
  'if entry.public_readonly:=>>if False:' \
  packages/core/tests/test_allowlist.py::test_assert_trading_host_rejects_public_readonly_entry

# 第一处 `entry = _BY_HOST.get(host)` 在 assert_public_readonly_host 内（lookup 用的是 return）。
mutate "allowlist: 只读断言放行未登记 host" "$CORE/allowlist.py" \
  'entry = _BY_HOST.get(host)=>>entry = _BY_HOST.get(host) or ALLOWLIST[0]' \
  packages/core/tests/test_allowlist.py::test_assert_public_readonly_host_rejects_host_outside_allowlist

mutate "视图只 join 已提交 batch" "$DATA/views.py" \
  'SEMI JOIN (SELECT batch_id FROM committed_batch_rows(batch_files)) c=>>LEFT JOIN (SELECT batch_id AS _c FROM committed_batch_rows(batch_files)) c' \
  packages/data/tests/test_views.py::test_committed_rows_only_include_registered_batches

mutate "bench 生成器可复现（seed 漂移）" fixtures/bench/bench_gen.py \
  'rng = np.random.default_rng(seed)=>>rng = np.random.default_rng(seed + 1)' \
  tests/test_bench_fixtures.py::test_expected_json_matches_full_bench_params_and_sha

mutate "checks 事后复核单源不变量" "$DATA/checks.py" \
  'if distinct != {expected_source}:=>>if False:' \
  packages/data/tests/test_checks.py::test_check_detects_source_mismatch_written_out_of_band

echo
echo "== fresh 重跑（还原后全量）=="
clean
if uv run pytest -q 2>&1 | tail -3; then
  echo "fresh 重跑：绿"
else
  echo "fresh 重跑：红 —— 还原不完整"
  FAIL=$((FAIL+1))
fi

echo
echo "变异点 由绿变红: $PASS  未能打红: $FAIL"
[ "$FAIL" -eq 0 ]
