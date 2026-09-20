---
paths:
  - "packages/execution/**"
  - "packages/data/**"
  - "packages/backtest/**"
  - "packages/risk/**"
---

# 加密边界（QNT-4 增补，② 收窄）

代码目录尚未建立；下列 `paths:` 只引用 QNT-4 骨架，不预建空目录。CI grep 拦截的实现不在本文件（后续卡）。

① 任何新增 host/URL 必须先进 `execution/allowlist.py` 并附官方文档链接

② **下单 / 账户 / 资金类代码**（`execution/`、broker 适配层、任何持凭据调用的模块）禁止出现主网 host 字面量（`api.binance.com` / `api.bybit.com` / `www.okx.com` 无 demo 头等），CI grep 拦截范围限定到这些路径；**行情摄取的公共只读端点例外**，例外须走 ① 的 allowlist 并在 allowlist 条目标 `public_readonly=true`。依据 ADR-0001 D1.8。

③ perp 回测须附黄金用例

④ 每次摄取必须写 `ingestion_batch` 并在 PR 描述贴 hash

⑤ 涉及美国合规表述一律标注来源与"未验证"

来源：QNT-4 评论 AGENTS.md 增补 ①–⑤；② 按 owner 2026-09-19 裁决收窄
