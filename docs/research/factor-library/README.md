# 可复现因子文献库（QNT-32）

owner 2026-09-23：市场两条线并行（crypto + us_equity/us_option），来源范围 B
（arXiv q-fin / NBER / SSRN 摘要 / JF·JFE·RFS·JFQA 公开摘要页）。

- 一篇一个 YAML：`papers/<id>.yaml`
- 本目录 `index.md` 由 `scripts/factor_library.py index --write` 生成，不要手改
- 查询：`uv run python scripts/factor_library.py filter --market crypto --family momentum --reproducible yes`
- **不下载 PDF、不存全文、不登录**；每篇只记摘要页 URL + 访问日期
- 因子定义是公式/文字转写，不是摘要粘贴
- 加密线 `reproducible: yes` 对照 QNT-28 Vision 归档（OHLCV 多周期 / funding / OI）
- 美股线 `reproducible: yes` 以「只需日线 OHLCV + 市值」为准，并在理由里标注「待付费源」

本节点 SSRN 摘要页 HTTP 403、Wiley/Elsevier/OUP 期刊摘要页 403，故首批未收录 SSRN / 期刊行（来源允许，但不可核就不写）。
