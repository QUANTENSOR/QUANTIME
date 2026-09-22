# QUANTIME
Now is the time for quants.

## 开发（QNT-27 骨架）

需要 `uv`（Python 3.14 由 uv 自动装）。

```bash
uv sync                  # 装依赖（唯一需要网络的步骤；不下载任何行情数据）
uv run pytest            # 全量测试
uv run ruff check . && uv run ruff format --check .
uv run lint-imports      # ADR-0003 §3.2 依赖方向守卫
bash scripts/mutation_check.sh   # 变异验证（AGENTS.md §5）
```

`data/` 永不入库（许可受限）；`fixtures/` 只放合成数据与生成脚本，生成物不入库。
`data/quantime.duckdb` 只存视图与宏定义，可由 `packages/data/quantime_data/views.py` 重建。
