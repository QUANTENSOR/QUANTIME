# fixtures/bench — 基准输入（ADR-0003 §5.1）

`synthetic: true`。本目录**只有生成脚本与常量**入库，生成物（Parquet / zip）不入库。

- `bench_gen.py` — 合成日 K 生成器，不接网络。
  - `uv run python fixtures/bench/bench_gen.py --print-sha` 打印 `payload_sha256`。
  - `uv run python fixtures/bench/bench_gen.py --check-expected` 与 `EXPECTED.json` 比对。
  - `uv run python fixtures/bench/bench_gen.py --mode vision-zip --out <dir>` 生成摄取基准 zip。
- `EXPECTED.json` — `payload_sha256` 常量（§5.1 (a)，纯业务列、不含 provenance 列），由测试断言。
- `factors.yaml` — 固定 20 因子定义（§5.1 原文），QNT-29 按此实现。

QNT-27 只保证生成器可复现（两次生成 `payload_sha256` 相等），**不跑性能阈值**（§5.2 归 QNT-28/29/30/31）。
