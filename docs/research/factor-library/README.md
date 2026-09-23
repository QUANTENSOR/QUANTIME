# 可复现因子文献库（QNT-32）

owner 2026-09-23：市场两条线并行（crypto + us_equity/us_option），来源范围 B
（arXiv q-fin / NBER / SSRN 摘要 / JF·JFE·RFS·JFQA 公开摘要页）。

- 一篇一个 YAML：`papers/<id>.yaml`
- 本目录 `index.md` 由 `scripts/factor_library.py index --write` 生成，不要手改
- 查询：`uv run python scripts/factor_library.py filter --market crypto --family momentum --reproducible yes`
- **不下载 PDF、不存全文、不登录**；每篇只记摘要页 URL + 访问日期
- 因子定义是公式/文字转写，不是摘要粘贴
- 标注规则（verify-b REJECT 后收口，2026-09-23）：
  - `yes` = 原文所定义的因子，用 QNT-28 字段契约（OHLCV 多周期 / funding / OI）或「日线 OHLCV + 市值（待付费源）」**按原定义直接计算**，不换变量、不换构造
  - 任何代理替换（描述统计替代定价模型、市场收益替代新闻分解、符号×成交量替代真实订单流、丢掉原文特征腿等）→ `partial`，且 `reproducible_reason` 必须写明「原文用 X，我们只有 Y，替换为 Z」
  - `no` = 核心字段缺失且无合理代理
- 美股线 `yes` 的理由须含「待付费源」

本节点 SSRN 摘要页 HTTP 403、Wiley/Elsevier/OUP 期刊摘要页 403，故首批未收录 SSRN / 期刊行（来源允许，但不可核就不写）。
