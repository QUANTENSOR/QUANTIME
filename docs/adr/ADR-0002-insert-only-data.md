---
id: ADR-0002
title: 数据层：append-only、每行带 source/ingested_at、确定性重放
status: PROPOSED
date: 2026-09-16
deciders: WitnessJ (pending)
depends_on: []
research: docs/research/market-data-sources.md（QNT-2 评论 §2）
amended: 2026-09-17（QNT-4 §0 D2.7 ingestion_batch）
---

# ADR-0002 数据层：只 insert 不 update、可解释、可重放、带 source（PROPOSED）

> 正文取自 QNT-2 调研评论（2026-09-17T00:34Z）§4 草案与 QNT-4 最终交付（2026-09-17T05:10Z）§0 修订，原文照录，未重写。verify-c 两轮对可重放定义的 REJECT 意见见文末"未决项"，只记录不裁决。

## Context

多数据源（付费主源 + 免费 fallback）、供应商会回补/修订历史（split 调整、busted trades）、许可条款可能要求删除某一源的数据（ThetaData §8(e)）。研究结论必须能回答"这个数字来自哪个源、哪次拉取、当时看到的是什么"。

## Decision

- D2.1 所有市场数据表与账本表 **append-only**：无 `UPDATE`、无 `DELETE`（许可驱动的删除除外，见 D2.5）；修订用新行 + 更大的 `ingested_at` 表达。DB 角色层面收回应用账号的 UPDATE/DELETE 权限。
- D2.2 每行必带：`source`（枚举：`thetadata` / `alpaca` / `yfinance` / `stooq` / `databento` / …）、`source_version`（供应商 API/feed 版本）、`ingested_at`、`run_id`（拉取任务 id）。同一 `(natural key, source)` 允许多版本；"当前视图"由 `latest per source` 视图给出，视图逻辑在 repo 内且有测试。
- D2.3 冲突仲裁不改数据：多源同键不一致时，写入 `source_conflict` 表并按显式 `source_priority` 配置选值；配置版本化，回测记录其 hash。
- D2.4 可重放：每个回测/研究 run 记录 `data_snapshot`（涉及表的 `max(ingested_at)` 截止点 + 配置 hash + 代码 commit）；重放时只读 `ingested_at <= 截止点` 的行，结果必须逐字节一致。
- D2.5 许可驱动的删除是**按 `source` 整体 drop 分区/文件**，不是逐行 UPDATE/DELETE；执行前须 owner 确认并记入 ADR 修订。
- D2.6 原始供应商响应（raw payload）以 Parquet/JSONL 按 `source/quote_date` 分文件落盘（`data/raw/`，gitignore），DB 中只存归一化行 + raw 文件的 hash 引用。
- D2.7（QNT-4 新增，承接 verify-c 对 D2.4 的 REJECT）每次摄取写 `ingestion_batch(batch_id 单调, source, source_version, content_sha256, row_count, manifest_path)`，replay 以 `batch_id ≤ N` 为界而非时间戳；Parquet 文件不可变，manifest 记 hash。

## Evidence

ThetaData §8(e)（30 天 expunge，含衍生作品）；Massive §8（终止即删）；Databento 无 redistribution 限制但合同原文未见；yfinance 2025-04 断供事件说明 fallback 源不稳定；全 universe 5 年 EOD 链在 Postgres ≈135–195 GB（§2.4）。

> QNT-4 §0 修订：ThetaData 条款号引用有误且 §2.1 禁 archive/download，已降级为"在线查询 + 本地缓存不超授权范围"；全宇宙基数由 500 改为 5,333 标的，Postgres 估算相应放大至 1.4–2.1 TB，研究宇宙仍取 100 标的。上述 Evidence 段保留 QNT-2 原文，以修订表为准。

## Reasoning

不可变数据 + 显式来源是可解释性的最低成本形态；供应商修订用新版本行表达才能重放"当时看到的世界"；按源整体删除让许可合规不破坏 append-only 原则。

## Consequences

+ 任意历史结论可复现；− 存储放大（同键多版本）、查询要经视图；需新增：DB 权限迁移、`latest per source` 视图测试、`data_snapshot` 表、`ingestion_batch` 表。

> 编者说明：QNT-2 草案 Consequences 仅列 `data_snapshot` 表；`ingestion_batch` 表为承接 QNT-4 D2.7 时在 Consequences 补入，Decision 正文 D2.7 仍为 QNT-4 原文。

## Revisit trigger

单表超 50 GB 或 latest 视图 p95 > 5 s（考虑分区/TimescaleDB，沿用 euexia ADR-0001 的"直接跳 Timescale"结论）；新增第三个及以上重叠源。

## 未决项（verify-c REJECT，原文摘录，待 owner / planner 裁决）

- 2026-09-17T00:38Z：仅记录各表 `max(ingested_at)` 不是稳定快照：以后插入一条相同或回填的时间戳即可改变旧 run；`source/quote_date` 的 Parquet 路径也未定义不可覆盖的对象名和精确文件清单。→ D2.7 承接。
- 2026-09-17T05:11Z：`batch_id` 单调分配不等于按序提交：批次 1 未完成、批次 2 先完成时保存 `N=2`；之后批次 1 完成，同一 `batch_id <= 2` 的结果就从 B 变为 B+A。必须固定 run 的确切已提交 batch/file 集合及 hash，或明确无未完成低序号批次的封闭提交水位；补入晚到/乱序提交、源文件变异后旧 run 重放不变的验收。**此项涉及可重放硬边界，D2.7 尚未闭合。**
