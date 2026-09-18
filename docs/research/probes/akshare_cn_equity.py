"""Probe: AKShare — A股 股票 / ETF / 可转债 日线历史 + 最新行情.

Upstream for these functions is 东方财富 (push2his). No token needed.
Run: python akshare_cn_equity.py
"""
from __future__ import annotations

import akshare as ak

from _common import df_summary, main_guard, run_check, years_ago

START = years_ago(4)


def stock_hist():
    df = ak.stock_zh_a_hist(symbol="600519", period="daily", start_date=START,
                            end_date="20500101", adjust="qfq")
    return df_summary(df, "日期")


def stock_latest():
    # 全市场实时快照（东财），取贵州茅台一行
    df = ak.stock_zh_a_spot_em()
    row = df[df["代码"] == "600519"]
    out = df_summary(row)
    out["note"] = f"spot rows total={len(df)}; 600519 最新价={row['最新价'].iloc[0] if len(row) else None}"
    return out


def etf_hist():
    df = ak.fund_etf_hist_em(symbol="510300", period="daily", start_date=START,
                             end_date="20500101", adjust="qfq")
    return df_summary(df, "日期")


def etf_latest():
    df = ak.fund_etf_spot_em()
    row = df[df["代码"] == "510300"]
    out = df_summary(row)
    out["note"] = f"etf spot rows total={len(df)}"
    return out


def cb_hist():
    # 可转债日线（新浪源）；113050 南银转债 2021-06 上市
    df = ak.bond_zh_hs_cov_daily(symbol="sh113050")
    return df_summary(df, "date")


def cb_latest():
    df = ak.bond_zh_hs_cov_spot()
    out = df_summary(df)
    out["note"] = "可转债实时全表（新浪）"
    return out


def stock_hist_sina():
    # 新浪源日线（含复权因子列可选）
    df = ak.stock_zh_a_daily(symbol="sh600519", start_date=START, end_date="20500101", adjust="qfq")
    return df_summary(df, "date")


def stock_hist_tx():
    df = ak.stock_zh_a_hist_tx(symbol="sh600519", start_date=START, end_date="20500101", adjust="qfq")
    return df_summary(df, "date")


def etf_hist_sina():
    df = ak.fund_etf_hist_sina(symbol="sh510300")
    return df_summary(df, "date")


def stock_latest_sina():
    df = ak.stock_zh_a_spot()  # 新浪全市场快照（分页拉取，较慢）
    row = df[df["代码"] == "sh600519"]
    out = df_summary(row)
    out["note"] = f"sina spot rows total={len(df)}"
    return out


def main():
    # --- 东方财富源（本美国节点 push2his 断连，见 eastmoney_cn_equity.py） ---
    run_check("akshare", "cn_equity_stock", "daily_history", stock_hist, upstream="eastmoney")
    run_check("akshare", "cn_equity_stock", "latest_quote", stock_latest, upstream="eastmoney")
    run_check("akshare", "cn_equity_etf", "daily_history", etf_hist, upstream="eastmoney")
    run_check("akshare", "cn_equity_etf", "latest_quote", etf_latest, upstream="eastmoney")
    # --- 新浪 / 腾讯源 ---
    run_check("akshare", "cn_equity_stock", "daily_history_sina", stock_hist_sina, upstream="sina")
    run_check("akshare", "cn_equity_stock", "daily_history_tx", stock_hist_tx, upstream="tencent")
    run_check("akshare", "cn_equity_etf", "daily_history_sina", etf_hist_sina, upstream="sina")
    run_check("akshare", "cn_convertible_bond", "daily_history", cb_hist, upstream="sina")
    run_check("akshare", "cn_convertible_bond", "latest_quote", cb_latest, upstream="sina")


if __name__ == "__main__":
    main_guard(main)
