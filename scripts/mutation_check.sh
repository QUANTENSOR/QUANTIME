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

# ---- QNT-27 返修 R1：verify-a 五项，每项一个变异点 ----

# P1-1：唯一性锁改成「先写再检查」——锁本身失效，同 batch_id 第二次提交会落盘。
mutate "P1-1 batch_id 全局唯一性登记（独占创建）" "$DATA/batches.py" \
  'os.O_CREAT | os.O_EXCL | os.O_WRONLY=>>os.O_CREAT | os.O_WRONLY' \
  packages/data/tests/test_batches.py::test_same_batch_id_second_commit_leaves_every_file_byte_identical

# P1-1b：发布回到 os.replace（静默盖写）——不可覆盖语义消失。
mutate "P1-1b 最终文件不存在才发布（os.link → os.replace）" "$CORE/parquet_io.py" \
  'os.link(tmp, target)=>>os.replace(tmp, target)' \
  packages/data/tests/test_batches.py::test_final_part_publish_refuses_an_existing_file_even_if_earlier_checks_pass

# P1-2：provenance 校验退回校验**投影前**的表——columns 投影重新可以绕过五列。
mutate "P1-2 provenance 校验最终落盘 schema" "$DATA/batches.py" \
  '_assert_provenance(final_table, source=source, batch_id=batch_id)=>>_assert_provenance(table, source=source, batch_id=batch_id)' \
  packages/data/tests/test_batches.py::test_columns_projection_dropping_provenance_is_rejected_before_any_write

# P1-3：清单取证退回「扫目录」——建清单前植入的文件会被就地合法化。
mutate "P1-3 清单只认提交时固定的 batch_manifest" "$DATA/replay.py" \
  'files=_registered_files(root, batch.batch_id, batch.batch_dir),=>>files=tuple(_scan_dir(root, Path(root) / batch.batch_dir)),' \
  packages/data/tests/test_replay.py::test_build_manifest_rejects_file_planted_before_the_run

# P1-4：run 清单回到 write_text（静默覆盖）——二次 write_manifest 可换掉重放输入与基准 hash。
mutate "P1-4 run 清单不可覆盖" "$DATA/replay.py" \
  'parquet_io.publish_text(path, payload, staging=publish_staging(root))=>>path.write_text(payload, encoding="utf-8")' \
  packages/data/tests/test_replay.py::test_write_manifest_twice_is_rejected_and_bytes_are_unchanged

# P1-4b：结果文件回到可覆盖写。
mutate "P1-4b 重放结果文件不可覆盖" "$DATA/replay.py" \
  'sha = parquet_io.publish_table(table, target, columns, staging=publish_staging(root))=>>sha = parquet_io.write_table(table, target, columns)' \
  packages/data/tests/test_replay.py::test_write_result_twice_is_rejected_and_bytes_are_unchanged

# ---- QNT-27 返修 R2：verify-a 第二轮 P1「独占创建 ≠ 原子发布」 ----

# R2-1：退回「最终路径 O_EXCL 创建后再写 payload」——创建与写入之间该路径以 size=0 可见，
# 并发读侧会把在途文件登记进 manifest（verify-a 的原始复现）。
mutate "R2-1 原子发布（不在最终路径上先创建后写）" "$CORE/parquet_io.py" \
  'tmp = _write_tmp(Path(staging), payload)
    try:
        _link_exclusive(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)=>>fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)' \
  packages/data/tests/test_concurrent_publish.py::test_in_flight_batch_is_invisible_to_readers_until_publish_lands

# R2-2：tmp 改写进最终路径旁边（湖/meta 的 batch 目录内）——虽然 link 时已完整，
# 但在途 tmp 落在枚举范围内，会被目录扫描当成「多出未登记文件」。
mutate "R2-2 tmp 必须在最终枚举范围之外" "$CORE/parquet_io.py" \
  'tmp = _write_tmp(Path(staging), payload)=>>tmp = _write_tmp(target.parent, payload)' \
  packages/data/tests/test_concurrent_publish.py::test_publish_writes_its_tmp_outside_every_enumerated_directory

# R2-3：跳过 fsync/close 直接 link——tmp 未确保完整就发布。
mutate "R2-3 tmp 写完 fsync + close 之后才发布" "$CORE/parquet_io.py" \
  'os.fsync(fd)
        finally:
            os.close(fd)=>>pass
        finally:
            pass' \
  packages/data/tests/test_concurrent_publish.py::test_interrupted_write_leaves_no_final_file_and_no_visible_residue

# R2-4：data 层把 staging 指回最终目录——core 的两段式还在，但中转站选错了位置，
# 在途 tmp 重新落进读侧枚举范围。这与 R2-2 是两个独立的接缝（原语 vs. 调用方选址）。
mutate "R2-4 staging 目录必须在枚举范围之外" "$DATA/batches.py" \
  'return root / staging_dir()=>>return root / "data" / "meta" / "ingestion_batch"' \
  packages/data/tests/test_concurrent_publish.py::test_publish_writes_its_tmp_outside_every_enumerated_directory

# P2：CI 注释过滤退回失效写法——ci.yml 的静态守卫步骤重新变红。
mutate "P2 CI 注释过滤（前缀感知）" .github/workflows/ci.yml \
  "grep -vP '^[^:]+:\\d+:\\s*#'=>>grep -v '^\\s*#'" \
  tests/test_static_guards.py::test_ci_static_guard_step_passes_as_shipped

# P2b：退回 `! grep ... | grep .` 串联——`set -e` 不作用于被 `!` 取反的命令，
# 只有最后一条的退出码算数，前面几条命中也照样绿（QNT-28 变异验证暴露的真因）。
mutate "P2b CI 每条检查都能单独打红" .github/workflows/ci.yml \
  'exit "$fail"=>>exit 0' \
  tests/test_static_guards.py::test_ci_static_guard_fails_on_the_first_check_not_only_the_last

# ---- QNT-28：公开只读摄取（planner 派单要求的三条 + 同层接缝）----

# Q28-1：去掉限流退避——429 不再睡，直接下一次重打。被 ban 的路径重新打开。
mutate "Q28-1 限流退避（429/418 必须退避）" "$DATA/transport.py" \
  'self._nap(self._backoff_seconds(attempt, response.retry_after))=>>pass' \
  packages/data/tests/test_transport.py::test_429_is_retried_with_exponential_backoff_then_succeeds

# Q28-1b：退避用尽后静默返回空正文，而不是抛错——摄取会写出一个空/残缺 batch。
mutate "Q28-1b 退避用尽必须抛错（不得静默返空）" "$DATA/transport.py" \
  'raise RateLimitedError(
            f"退避重试 {len(self._backoff)} 次后仍为 HTTP {last_status}（最后一次）: {url}"
        )=>>return b""' \
  packages/data/tests/test_transport.py::test_exhausting_retries_raises_and_never_returns_empty_bytes

# Q28-2：去掉 allowlist 校验——未登记 host 可以从公共只读出口发出请求。
mutate "Q28-2 出口 allowlist 校验（host 闸）" "$DATA/transport.py" \
  'assert_public_readonly_url(url)=>>pass' \
  packages/data/tests/test_transport.py::test_unlisted_host_is_rejected_before_any_request

# Q28-2b：路径白名单退化成放行一切——交易/账户端点可以从摄取出口发出。
mutate "Q28-2b 出口路径白名单（交易端点不可达）" "$DATA/transport.py" \
  'if path in PUBLIC_READONLY_REST_PATHS:=>>if True:' \
  packages/data/tests/test_transport.py::test_trading_and_account_paths_are_rejected

# Q28-3：唯一性登记在摄取链路上的表现——同 batch_id 二次提交不再被锁挡住。
#（batches.py 的 P1-1 变异从写侧钉这一点；这条从摄取侧钉，两条互不替代。）
mutate "Q28-3 唯一性登记（摄取侧）" "$DATA/batches.py" \
  'fd = os.open(claim_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)=>>fd = os.open(claim_path, os.O_CREAT | os.O_WRONLY, 0o644)' \
  packages/data/tests/test_ingest.py::test_two_ingests_colliding_on_one_batch_id_are_stopped_by_the_lock

# ---- R1 返修：verify-a 复现的四条反例，各自钉一个变异点 ----

# R1-1a：所有权校验退回「Path 值相等」——正是被 REJECT 的那一版实现。
#   凭 `root / batch_claim_path(bid)` 构造的路径重新变成有效令牌，锁形同虚设。
mutate "R1-1a claim 必须是独占取得的凭证（退回 Path 比较）" "$DATA/batches.py" \
  'if not isinstance(claim, BatchClaim):=>>if False:' \
  packages/data/tests/test_batches.py::test_a_forged_path_is_not_a_claim_even_when_the_lock_does_not_exist

# R1-1b：类型校验还在，但不再核对锁文件里登记的 digest——自造一个 BatchClaim 就能重入。
mutate "R1-1b claim 必须与盘上那把锁对得上" "$DATA/batches.py" \
  'if on_disk != claim.digest():=>>if False:' \
  packages/data/tests/test_batches.py::test_a_fabricated_claim_object_with_a_guessed_nonce_is_rejected

# R1-1c：锁文件落 nonce 本身而不是它的 sha256——任何读得到文件的人都能拼出有效凭证。
mutate "R1-1c 锁文件只落 digest，不落 nonce" "$DATA/batches.py" \
  'digest = hashlib.sha256(nonce.encode("ascii")).hexdigest()=>>digest = nonce' \
  packages/data/tests/test_batches.py::test_a_lock_file_records_only_the_digest_never_the_nonce

# R1-2a：REST 白名单退回前缀匹配——`/api/v3/klinesX` 一类后缀延伸重新被放行。
mutate "R1-2a REST 端点精确匹配（退回 startswith）" "$DATA/transport.py" \
  'if path in PUBLIC_READONLY_REST_PATHS:=>>if any(path.startswith(p) for p in PUBLIC_READONLY_REST_PATHS):' \
  packages/data/tests/test_transport.py::test_rest_whitelist_is_exact_match_not_prefix

# R1-2b：不再拒绝点段——`/data/spot/monthly/../../api/v3/account` 过闸（归档前缀放行它），
#   httpx 折叠后发出的是账户路径。REST 那批有精确匹配兜底，钉不动这一层。
mutate "R1-2b 点段/空段一律拒绝" "$DATA/transport.py" \
  'if seg in ("", ".", ".."):=>>if False:' \
  packages/data/tests/test_transport.py::test_normalization_bypasses_are_rejected_before_any_request

# R1-2c：不再拒绝百分号编码——`%2e%2e` 原样发出，由服务端去折。
mutate "R1-2c 百分号编码一律拒绝" "$DATA/transport.py" \
  'for ch in _FORBIDDEN_PATH_CHARS:=>>for ch in ():' \
  packages/data/tests/test_transport.py::test_normalization_bypasses_are_rejected_before_any_request

# R1-3：不按请求区间裁剪——`start=end=2026-08-15` 重新提交整月 31 行。
mutate "R1-3 按请求区间裁剪落盘的行" "$DATA/spec.py" \
  'keep = [i for i, t in enumerate(times) if start <= t < end]=>>keep = list(range(len(times)))' \
  packages/data/tests/test_ingest.py::test_only_rows_inside_the_requested_window_are_committed

# R1-3b：窗口右端点算错一天——末日整根日线被裁掉（半开窗口的经典 off-by-one）。
mutate "R1-3b 窗口右端点含 end 当天" "$DATA/spec.py" \
  'end = dt.datetime.combine(spec.end + dt.timedelta(days=1), dt.time.min, tzinfo=dt.UTC)=>>end = dt.datetime.combine(spec.end, dt.time.min, tzinfo=dt.UTC)' \
  packages/data/tests/test_ingest.py::test_clip_to_window_is_a_pure_half_open_utc_window

# R1-4a：整档缺失不再影响 clean——少一整个月的数据重新被判为干净。
mutate "R1-4a 覆盖不全不得判 clean" "$DATA/audit.py" \
  'return not self.gaps and not self.duplicates and self.coverage == COVERAGE_COMPLETE=>>return not self.gaps and not self.duplicates' \
  packages/data/tests/test_ingest.py::test_a_partially_covered_range_is_not_clean

# R1-4b：摄取侧不再把缺档传给核查——核查读表，表里看不出整月没取到。
mutate "R1-4b 缺档必须传进核查" "$DATA/ingest.py" \
  'missing_upstream=result.missing,=>>missing_upstream=(),' \
  packages/data/tests/test_ingest.py::test_a_partially_covered_range_is_not_clean

# R1-4c：报告表丢掉覆盖状态——报告本身答不了「这段数据全不全」。
mutate "R1-4c 报告带 coverage 与缺档清单" "$DATA/audit.py" \
  '"coverage": r.coverage,=>>"coverage": COVERAGE_COMPLETE,' \
  packages/data/tests/test_ingest.py::test_the_report_carries_coverage_and_the_missing_file_names

# R1-5：record.py 的用法行退回不可用形式（根目录无 ingest extra）。
mutate "R1-5 record.py 用法命令可用" fixtures/binance_public/record.py \
  'uv run --package quantime-data --extra ingest python=>>uv run --extra ingest python' \
  tests/test_static_guards.py::test_record_script_documents_a_runnable_command

# Q28-4：跳过 .CHECKSUM 核对——被篡改/截断的上游字节会被当成好数据入湖。
mutate "Q28-4 上游 .CHECKSUM 核对" "$DATA/sources/binance_public.py" \
  'if verify_checksum:=>>if False:' \
  packages/data/tests/test_ingest.py::test_checksum_mismatch_refuses_to_write_anything

# Q28-5：OI 归档上游行序不定，不显式排序 → 确定性 writer 的字节随上游漂移，R2 重放失效。
mutate "Q28-5 open_interest 显式排序" "$DATA/sources/binance_public.py" \
  'parsed.sort(key=lambda t: t[0])=>>pass' \
  packages/data/tests/test_binance_public.py::test_open_interest_is_sorted_even_though_upstream_is_not

# Q28-6：核查只报不改——报告写回被核查数据的 scope，读侧会把报告当行情读。
mutate "Q28-6 核查报告写独立 scope" "$DATA/ingest.py" \
  'scope=f"{audit.AUDIT_SCOPE_PREFIX}{scope}"=>>scope=scope' \
  packages/data/tests/test_ingest.py::test_audit_report_lands_in_a_separate_scope_from_the_data

# Q28-7：缺口检测失效——上游缺档留下的空洞不会出现在报告里。
mutate "Q28-7 缺口检测" "$DATA/audit.py" \
  'if delta > step:=>>if False:' \
  packages/data/tests/test_audit.py

# Q28-8：CI 静态守卫的新范围（出网点收敛）被删——第二个 import httpx 的模块不再被拦。
mutate "Q28-8 CI 出网点收敛守卫" .github/workflows/ci.yml \
  "'quantime_data/cli\\.py'=>>'quantime_data/'" \
  tests/test_static_guards.py::test_ci_static_guard_egress_scope_is_not_weakened

echo
# ---- QNT-45 卡描述的四个变异点 ----
mutate "Q45-a 重试之间必须退避" "$DATA/retry.py" \
  '            sleep(wait)=>>            pass' \
  packages/data/tests/test_retry.py::test_every_retry_is_preceded_by_an_exponential_wait

mutate "Q45-b 增量只取水位线之后（改成全量重取）" "$DATA/incremental.py" \
  'return spec.with_window(max(start, spec.start), spec.end)=>>return spec' \
  packages/data/tests/test_incremental.py::test_the_next_window_starts_the_day_after_the_watermark

mutate "Q45-c 补采写新 rerun batch（改成覆盖式 ingest）" "$DATA/daily.py" \
  'kind=backfill_mod.BACKFILL_KIND,
            rerun_of=task.rerun_of,=>>kind="ingest",
            rerun_of=None,' \
  packages/data/tests/test_daily.py::test_backfill_writes_a_new_rerun_batch_and_never_touches_the_original

mutate "Q45-d unit 文件注入主网 host 字面量" "systemd/user/quantime-ingest@.service" \
  '[Service]=>>[Service]
Environment=QUANTIME_UPSTREAM=https://api.binance.com' \
  tests/test_systemd_units.py::test_no_mainnet_or_trading_host_literals_in_unit_files

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
