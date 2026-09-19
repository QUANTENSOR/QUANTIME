# docs/ops — 花费与运维记录

只放"钱花在哪、模型分工效果如何"的可追溯记录；决策进 `docs/adr/`，调研进 `docs/research/`。本目录文件全部 append-only（同 ADR-0002 精神：重跑不覆盖历史行，以 `source` 列区分）。

| 文件 | 用途 | 来源 | 产出卡 |
|---|---|---|---|
| `spend.md` | 每日模型花费汇总，按 provider（Anthropic / Foundry / xAI，由模型 id 前缀 `anthropic/` `foundry/` `xai/` 推）分列。表头 `date \| provider \| requests \| input_tok \| output_tok \| cache_tok \| cost_usd \| source`。 | Bifrost **管理 API**（`127.0.0.1:8080`，admin auth，非 `/v1` 公共口）：`GET /api/logs/rankings` / `/api/logs` 聚合；由 systemd timer 驱动 `ops/spend/bifrost_spend.py` 每日追加一行/provider；重跑同日以 `source=rerun` 新增行。admin 凭据经 `op read` 注入，unit 内不含明文。 | QNT-12（当前 blocked：容器内 `:8080` 不可达、admin item 名待 owner 补） |
| `model-ab-<date>.md` | 五卡对照结论：同一批任务卡分别由 Grok 4.6 / Opus 5 等实现后的四项对比摘要——verify 发现数 / 到 APPROVE 轮次 / 单卡花费 / 墙钟。用来划定 `AGENTS.md §4` 中 Grok "其余"类的适用边界。 | 试验在 euexia 仓库做，quantime **只引用结论**（链接 + 一句话摘要），不复制原始数据、不改判定。 | QNT-13（等 euexia 侧文档落地后启动） |

两份文件目前均未落地；本 README 先定义格式与来源，避免后续卡各写一套。
