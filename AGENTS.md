# quantime — working rules for coding agents

## 1. 产品与权威

quantime 是美股 + 美股期权 + 加密合约、日线为主的量化研究系统；**第一阶段只做 research / 回测，不交易**。**quantime 是产品；可重放的研究结论（数据快照 + 代码 commit + 报告）是它的产物。** 设计权威：`docs/adr/`（ADR，状态 PROPOSED 的条目是草案，不是许可）；调研事实：`docs/research/`；任务真相源是 Multica issue，代码真相源是 GitHub PR，聊天不算数。

## 2. Map

`docs/research/`（调研，带 provenance 头）· `docs/adr/`（设计决策，唯一权威）· `docs/ops/`（花费与运维记录，见 `docs/ops/README.md`）。代码目录尚未建立；落地时按 QNT-4 骨架提案（`packages/{core,data,backtest,research,execution,risk,monitor}`、`systemd/`）在对应任务卡里建，**不预建空目录**。市场数据是许可受限资产：`data/` 永不入库，`fixtures/` 只放合成数据（`synthetic: true` 头）。

## 3. 硬边界

- **ADR-0001 凭据边界**：任何 agent 永不接触实盘券商 / 交易所主网凭据；开发、回测、paper 全程 paper / testnet / demo 凭据；实盘下单路径只允许"生成意图 → 输出给人"，由 owner 在 agent 不可达的环境人工确认执行；Robinhood 仅 owner 手动终端。
- **ADR-0002 数据层**：市场数据与账本表只 insert 不 update / delete；每行带 `source` / `source_version` / `ingested_at` / `run_id`；每次摄取写 `ingestion_batch`；任何结论必须可解释、可按批次重放。
- **凭据来源**：Bifrost key 共用 1Password vault `health-dev`；交易所、数据源等其余凭据只来自 vault `quant-dev`。一律 `op read` / `op run` 注入子进程，读取时 `.strip()`；禁止手抄、打印、写文件、入库。仓库只跟踪 `*.tpl`（含 `op://` 引用），所有真实 `.env*` 保持 ignored，每次 commit 前看 stage。
- **常驻只读检出**：`/home/workspace/quantime` 是 owner 的常驻检出，只读——不在其中改文件、不切分支。所有改动在 `multica repo checkout` 的专用分支或独立 worktree 里做。
- **`main` PR-only**：不直推 main；不绕过、不削弱任何 check / review / ruleset。
- **不按名字 pkill**；需要停进程按端口取 PID。改主机（systemd unit、目录属主、全局配置）的操作先在任务卡评论里逐项列出（路径 + 改前/改后，值打码），owner 确认后再动手。

## 4. 模型路由（长期版）

全部模型调用经 Bifrost 网关：Anthropic 走 `/anthropic` 前缀，其余走 `/v1`；base URL 与 key 由 `op` 注入，不写进仓库。模型 id 按 runtime 写法：Claude Code 用 `claude-fable-5-1` / `claude-opus-5`；Pi 用 `bifrost/xai/grok-4.6`；Codex 用 `foundry/gpt-6-astra`。`bifrost/` 前缀只对 pi 有效。

| 角色 | 模型 / 运行时 | 职责与边界 |
|---|---|---|
| planner | Claude Fable 5.1 / Claude Code | 规划、拆卡、集成、写 ADR；建卡时判定难度，需要时给卡打 `hard` 标签 |
| implementer · `hard` | Claude Fable 5.1 / Claude Code | 仅 planner 打了 `hard` 标签的卡 |
| implementer · 关键路径 | Claude Opus 5 / Claude Code | 数据库迁移 · 算法与评分 · 认证与安全边界 · 外部接入与凭据 · systemd 与基础设施 |
| implementer · 其余 | Grok 4.6 / pi | UI、文档、测试补强、脚本、demo |
| verify | GPT-6 Astra / Codex | 一律跨家族审查；同族审自家产物不算数 |

规则：
- 升级到 Fable 由 planner 建卡时判定，implementer **不自选**模型，也不自行改卡标签。
- 关键路径 PR 的 verify 须复现测试 + 变异验证；非关键路径审 diff 即可。
- Grok 适用边界以 euexia 五卡对照结论为准：`docs/ops/model-ab-<date>.md`（链接占位，由 QNT-13 填入；在此之前"其余"类边界按上表执行）。

## 5. Done means

测试通过 → 分支 commit → PR。完成、验证过的改动永不只存在于工作区。首跑即绿必做变异验证（变异前后 `rm -rf __pycache__`），再 fresh 重跑；绿灯不可转述——verifier 自己重跑。每张卡收工在 Multica issue 评论里贴四段式汇报：**改动文件树 / 测试计数 / 偏离项 / 发现的文档矛盾**；文档矛盾只报不修，由 planner 决定改法。附件易损，产出一律用文字贴在评论里。

## 6. Loaded on demand

`.claude/rules/crypto-boundaries.md`（加密边界；`paths:` 指向 `packages/execution/**`、`packages/data/**`、`packages/backtest/**`、`packages/risk/**`）。Claude Code 自动加载；Codex / pi 编辑这些路径时读取。其余 `.claude/rules/<topic>.md` 与 `.claude/skills/<skill>/SKILL.md` 需要时随对应任务卡加入。
