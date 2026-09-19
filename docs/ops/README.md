# docs/ops — 运维记录

只放可追溯的运维与对照记录；决策进 `docs/adr/`，调研进 `docs/research/`。本目录文件全部 append-only（同 ADR-0002 精神：重跑不覆盖历史行，以 `source` 列区分）。

模型花费不进本仓库、不进自动化：由 owner 在 Bifrost UI / YC 额度页人工查看。

| 文件 | 用途 | 来源 | 产出卡 |
|---|---|---|---|
| `model-ab-<date>.md` | 五卡对照结论：同一批任务卡分别由 Grok 4.6 / Opus 5 等实现后的四项对比摘要——verify 发现数 / 到 APPROVE 轮次 / 单卡花费 / 墙钟。用来划定 `AGENTS.md §4` 中 Grok "其余"类的适用边界。 | 试验在 euexia 仓库做，quantime **只引用结论**（链接 + 一句话摘要），不复制原始数据、不改判定。 | QNT-13（等 euexia 侧文档落地后启动） |

`model-ab-<date>.md` 目前未落地；本 README 先定义格式与来源，避免后续卡各写一套。
