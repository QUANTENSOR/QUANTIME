---
id: ADR-0001
title: 凭据边界：agent 全程 paper 凭据，实盘下单必经人工确认，Robinhood 仅 owner 手动终端
status: PROPOSED
date: 2026-09-16
deciders: WitnessJ (pending)
related: [REQ-SAFE-001（待编号）]
research: docs/research/brokers-paper-trading.md（QNT-2 评论 §1）
amended: 2026-09-17（QNT-4 §3 加密条款 D1.6–D1.10）
---

# ADR-0001 凭据边界：agent 永不持有实盘凭据（PROPOSED）

> 正文取自 QNT-2 调研评论（2026-09-17T00:34Z）§4 草案与 QNT-4 最终交付（2026-09-17T05:10Z）§3 增补，原文照录，未重写。verify-c 对两条评论的 REJECT 意见见文末"未决项"，只记录不裁决。

## Context

quantime 第一阶段只做 research/回测，第二阶段 paper 交易。agent 是编码与运行主体，误操作、提示注入或凭据泄露都可能导致实钱下单。owner 现有券商 Robinhood 无 paper 环境、无 REST API，其 Agentic Trading（MCP）是实钱专用账户。

## Decision

- D1.1 任何 agent（实现、审查、研究）运行环境中**不得存在**实盘券商凭据：不在 1Password vault `quant-dev`、不在 `.env`、不在环境变量、不在代码/fixtures/日志。
- D1.2 开发、回测、paper 全程只用 paper/sandbox 凭据；配置项 `BROKER_BASE_URL` 白名单只含 paper 域名（如 `paper-api.alpaca.markets`），代码在启动时断言 URL 命中白名单，否则拒绝启动。
- D1.3 实盘下单路径（若未来存在）必须经**人工确认**：由 owner 在 agent 不可达的环境执行；仓库内只允许存在"生成订单意图 → 输出给人"的代码，不允许直接调用 live 下单端点。
- D1.4 Robinhood 仅作 owner 手动执行终端；agent 不接入其 MCP server、不读取其账户数据。
- D1.5 凭据只经 `op` 注入子进程（`op run` / `op read`），读取时 `.strip()`；禁止打印、复制到文件、写入提交。

### 加密条款（QNT-4 增补，2026-09-17）

- D1.6 加密凭据只能是：交易所 demo/testnet API key（Binance demo、Bybit testnet/demo、OKX demo key、Deribit test、Kraken demo）或**专用测试网钱包私钥**（Hyperliquid/dYdX，该地址主网永不存资金）；主网 key/主钱包私钥不进入 vault quant-dev。
- D1.7 启动强制 allowlist：REST/WS host ∈ {`demo-fapi.binance.com`, `demo-fstream.binance.com`, `api-testnet.bybit.com`, `stream-testnet.bybit.com`, `api-demo.bybit.com`, `stream-demo.bybit.com`, `test.deribit.com`, `api.hyperliquid-testnet.xyz`, `indexer.v4testnet.dydx.exchange`, `demo-futures.kraken.com`}；OKX 因同域名必须校验请求头 `x-simulated-trading: 1` 且 key 标签含 `demo`，缺一 fail-closed；Bitget 同理校验 `paptrading: 1`。
- D1.8 只读优先：数据摄取一律用无 key 公共端点或 Read-only key（Binance 无 IP 的 HMAC key 本就只读）；交易 key 永不申请 withdraw/transfer（OKX Trade 含划转 → 只在子账户上发 key）。
- D1.9 美国居民合规：实盘候选仅 CFTC 监管场所（Coinbase Advanced/CDE、Kraken Derivatives US、CME via IBKR）；离岸所与链上永续限 testnet 研究，ADR 中显式记录各所 ToS 排除条款（条款号多为未验证，需 owner 复核）。
- D1.10 vault 新条目：`binance-demo-api`、`bybit-testnet-api`、`okx-demo-api`、`deribit-test-api`、`hyperliquid-testnet-wallet`（仅 owner 决定纳入的所）。

## Evidence (time-bound)

Alpaca paper key 与 live 分离、Paper Only 账户无需 live 账户（docs 2026-09-16）；Robinhood Agentic Trading 为实钱子账户、无沙盒（newsroom 2026-05-27）；Tastytrade sandbox 无行情，官方建议生产凭据拉行情——**这正是 D1.1 要禁止的模式**。

## Reasoning (durable)

安全边界要靠"凭据不存在"而非"代码不调用"；白名单 + 启动断言让误配置在最早一刻失败；人工确认是唯一不受提示注入影响的闸门。

## Consequences

+ 任何 agent 产物即使被完整泄露也无法触及实钱；− 第二阶段 paper 与真实成交质量有差距（需在报告中标注 paper 模型局限）；需新增：`BROKER_BASE_URL` 白名单测试、verify 审查清单加"凭据/URL 扫描"。

> 编者说明：QNT-2 草案此处写 `verify-c`；迁入时改为跨家族角色名 `verify`（QNT-9 后 verify-c 已归档）。未改决策正文。

## Revisit trigger

owner 决定进入实盘；Alpaca 变更 paper/live 隔离模型；出现 owner 认可的、带独立沙盒的 Robinhood API。

## Alternatives considered

live key + `dry_run` 标志（REJECT：一个 flag 之差）；IBKR paper（REJECT 作为默认：需入金 live 账户、Gateway 常驻 + 2FA）；Robinhood MCP 子账户限额（REJECT：仍是实钱，且违反 D1.4）。

## 未决项（verify-c 2026-09-17T05:11Z REJECT，原文摘录，待 owner / planner 裁决）

- D1.8 写"永不申请 transfer"，同时承认 OKX Trade 包含划转；子账户隔离不会消除该权限，应明确停用还是待 owner 批准的受限例外。
- Bybit demo 公共行情来自主网，而 AGENTS 提案禁止加密代码出现主网 host 且对所有 URL 使用 execution allowlist；这与公共只读历史摄取冲突。需分开公共只读数据与签名交易通道，并分别规定 REST、私有 WS、公共 WS 的 host/模拟环境校验；不能用一次启动头校验代替所有交易请求的 fail-closed 约束。
- D1.9 的美国合规声明越过证据范围（Kraken US API 未验证却称 Coinbase "唯一"；testnet 不自动豁免 ToS）。应将政策选择"本项目仅考虑 CFTC 路径"与法律事实分开。
