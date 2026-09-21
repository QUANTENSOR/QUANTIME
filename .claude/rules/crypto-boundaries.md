---
paths:
  - "packages/core/**"
  - "packages/execution/**"
  - "packages/data/**"
  - "packages/backtest/**"
  - "packages/risk/**"
---

# 加密边界（QNT-4 增补，② 收窄；① ② 路径迁移 QNT-39）

代码目录尚未建立；下列 `paths:` 只引用 QNT-4 骨架，不预建空目录。CI grep 拦截的实现不在本文件（后续卡）。

① 任何新增 host/URL 必须先进 `packages/core/quantime_core/allowlist.py`（`HostEntry(host, public_readonly: bool, exchange, doc_url, demo_marker)`，字段名沿用 `public_readonly=true/false`，见 ADR-0003 §3.3）并附官方文档链接。该文件由 QNT-27 随骨架创建；在其落地前，本条按位置约定生效，不得另建第二份 allowlist。

① *[superseded 2026-09-21 by QNT-39]* 任何新增 host/URL 必须先进 `execution/allowlist.py` 并附官方文档链接

② **下单 / 账户 / 资金类代码**（`execution/`、broker 适配层、任何持凭据调用的模块）禁止出现主网 host 字面量（`api.binance.com` / `api.bybit.com` / `www.okx.com` 无 demo 头等），CI grep 拦截范围限定到这些路径；**行情摄取的公共只读端点例外**，例外须走 ① 的 allowlist（即 `packages/core/quantime_core/allowlist.py`）并在 allowlist 条目标 `public_readonly=true`。依据 ADR-0001 D1.8。

② *[superseded 2026-09-21 by QNT-39]* **下单 / 账户 / 资金类代码**（`execution/`、broker 适配层、任何持凭据调用的模块）禁止出现主网 host 字面量（`api.binance.com` / `api.bybit.com` / `www.okx.com` 无 demo 头等），CI grep 拦截范围限定到这些路径；**行情摄取的公共只读端点例外**，例外须走 ① 的 allowlist 并在 allowlist 条目标 `public_readonly=true`。依据 ADR-0001 D1.8。

> superseded 说明：①② 的新旧两版**语义一致**（单一 allowlist、必附官方文档链接、公共只读例外须标 `public_readonly=true`、CI grep 范围不变），差异仅为 allowlist 文件的物理位置由 `execution/` 迁至 `packages/core/`，使 `data` 层不再 import `execution`（ADR-0003 §3 分层 / import-linter 单向依赖）。新版生效日 2026-09-21；标 superseded 的原文保留仅作历史对照，**不再作为判定依据**。本次迁移不削弱 ADR-0001 D1.7 / D1.8。

③ perp 回测须附黄金用例

④ 每次摄取必须写 `ingestion_batch` 并在 PR 描述贴 hash

⑤ 涉及美国合规表述一律标注来源与"未验证"

来源：QNT-4 评论 AGENTS.md 增补 ①–⑤；② 按 owner 2026-09-19 裁决收窄；①② allowlist 路径按 ADR-0003 §3.3 / §9.10 第 10 条与 owner 2026-09-21 裁决（5A）迁至 `packages/core`（QNT-39）
