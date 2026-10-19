"""
回测结果整理：按日逐笔重建市值净值，算分段指标，出图表。

用法（项目根目录）：
    python -X utf8 scripts/report.py

读取 user_data/backtest_results/named/ 下按名字保存的回测结果（见 scripts/run_backtests.sh），
输出到 results/：metrics.csv、fee_sensitivity.csv、各 PNG 图。
"""

import json
import zipfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "user_data" / "data" / "okx"
NAMED = ROOT / "user_data" / "backtest_results" / "named"
OUT = ROOT / "results"

INITIAL = 10_000.0
FEE = 0.0015
PAPER_END = pd.Timestamp("2025-03-15", tz="UTC")  # 论文样本截止（2025 年 3 月中旬）
PAIRS = ["BTC/USDT", "ETH/USDT"]

COLORS = {
    "论文规则（TrendEnsemble）": "#1f4e79",
    "机器学习（MLXGBoost）": "#c55a11",
    "一直持有 BTC": "#7f7f7f",
    "一直持有 ETH": "#a5a5a5",
    "BTC/ETH 各半持有": "#404040",
}

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def load_closes() -> pd.DataFrame:
    closes = {}
    for pair in PAIRS:
        df = pd.read_feather(DATA / f"{pair.replace('/', '_')}-1d.feather")
        closes[pair] = df.set_index("date")["close"]
    return pd.DataFrame(closes).sort_index()


def load_result(name: str) -> dict:
    """读取 Freqtrade 导出的 zip，返回其中第一个策略的统计字典。"""
    path = NAMED / f"{name}.zip"
    with zipfile.ZipFile(path) as zf:
        member = next(
            n for n in zf.namelist()
            if n.endswith(".json") and "_config" not in n and "_market_change" not in n
        )
        data = json.loads(zf.read(member))
    strategy = next(iter(data["strategy"].values()))
    return strategy


def equity_from_orders(stats: dict, closes: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    """逐笔订单重建每日收盘时的市值净值和持仓数量。

    日线 K 线以开盘时间标记；订单在某根 K 线开盘时成交，所以第 d 天收盘净值
    = 截至第 d+1 天 0 点之前成交的所有订单之后的现金 + 持仓 × 第 d 天收盘价。
    """
    events = []
    for trade in stats["trades"]:
        fee_open = trade.get("fee_open", FEE)
        fee_close = trade.get("fee_close", FEE)
        for order in trade["orders"]:
            ts = pd.Timestamp(order["order_filled_timestamp"], unit="ms", tz="UTC")
            amount = float(order["amount"])
            price = float(order["safe_price"])
            is_buy = order["ft_order_side"] == "buy"
            events.append((ts, trade["pair"], amount if is_buy else -amount, price,
                           fee_open if is_buy else fee_close))
    events.sort(key=lambda e: e[0])

    days = closes.index
    cash = INITIAL
    holdings = {pair: 0.0 for pair in PAIRS}
    equity = pd.Series(index=days, dtype=float)
    held = pd.DataFrame(0.0, index=days, columns=PAIRS)
    i = 0
    for day in days:
        day_end = day + pd.Timedelta(days=1)
        while i < len(events) and events[i][0] < day_end:
            _, pair, qty, price, fee = events[i]
            value = abs(qty) * price
            cash += -value * (1 + fee) if qty > 0 else value * (1 - fee)
            holdings[pair] += qty
            i += 1
        equity[day] = cash + sum(holdings[p] * closes.at[day, p] for p in PAIRS)
        for p in PAIRS:
            held.at[day, p] = holdings[p] * closes.at[day, p]
    return equity, held


def buy_and_hold(closes: pd.DataFrame, start: pd.Timestamp, weights: dict) -> pd.Series:
    px = closes.loc[start:]
    units = {p: INITIAL * w * (1 - FEE) / px[p].iloc[0] for p, w in weights.items()}
    return sum(px[p] * u for p, u in units.items())


def metrics(equity: pd.Series, start=None, end=None) -> dict:
    e = equity.loc[start:end].dropna()
    r = e.pct_change().dropna()
    years = (e.index[-1] - e.index[0]).days / 365
    total = e.iloc[-1] / e.iloc[0] - 1
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 else np.nan
    vol = r.std() * np.sqrt(365)
    sharpe = r.mean() / r.std() * np.sqrt(365) if r.std() > 0 else np.nan
    mdd = (e / e.cummax() - 1).min()
    return {
        "起": e.index[0].date(), "止": e.index[-1].date(),
        "总收益": total, "年化收益": cagr, "年化波动": vol,
        "夏普": sharpe, "最大回撤": mdd,
        "卡玛": cagr / abs(mdd) if mdd < 0 else np.nan,
    }


def drawdown(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1


def style_axes(ax, title: str):
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", color="#222222")
    ax.grid(True, color="#e5e5e5", linewidth=0.8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


def mark_paper_end(ax):
    ax.axvline(PAPER_END, color="#c00000", linestyle="--", linewidth=1)
    ax.axvspan(PAPER_END, ax.get_xlim()[1], color="#c00000", alpha=0.04)
    ax.text(PAPER_END, 0.98, " 论文样本截止 →\n 之后都是样本外", transform=ax.get_xaxis_transform(),
            va="top", fontsize=9, color="#c00000")


def main():
    OUT.mkdir(exist_ok=True)
    closes = load_closes()

    trend_stats = load_result("trend_fee0.0015")
    trend_eq, trend_held = equity_from_orders(trend_stats, closes)
    curves = {"论文规则（TrendEnsemble）": trend_eq}
    held = {"论文规则（TrendEnsemble）": trend_held}

    ml_path = NAMED / "ml_fee0.0015.zip"
    if ml_path.exists():
        ml_stats = load_result("ml_fee0.0015")
        ml_eq, ml_held = equity_from_orders(ml_stats, closes)
        curves["机器学习（MLXGBoost）"] = ml_eq
        held["机器学习（MLXGBoost）"] = ml_held

    # 共同评估区间：两个策略都开始有效之后
    start = max(_first_active(eq) for eq in curves.values())
    end = closes.index[-1]
    curves = {k: v.loc[start:end] / v.loc[start] * INITIAL for k, v in curves.items()}
    curves["一直持有 BTC"] = buy_and_hold(closes, start, {"BTC/USDT": 1.0})
    curves["一直持有 ETH"] = buy_and_hold(closes, start, {"ETH/USDT": 1.0})
    curves["BTC/ETH 各半持有"] = buy_and_hold(closes, start, {"BTC/USDT": 0.5, "ETH/USDT": 0.5})

    # 分段指标
    rows = []
    for name, eq in curves.items():
        for label, a, b in (("全区间", None, None),
                            ("论文样本期内", None, PAPER_END - pd.Timedelta(days=1)),
                            ("论文发表后", PAPER_END, None)):
            m = metrics(eq, a, b)
            rows.append({"策略": name, "区间": label, **m})
    table = pd.DataFrame(rows)
    table.to_csv(OUT / "metrics.csv", index=False, encoding="utf-8-sig")

    # 交易统计（Freqtrade 原始口径）
    stats_rows = []
    for name, stats in (("论文规则（TrendEnsemble）", trend_stats),) + (
            (("机器学习（MLXGBoost）", ml_stats),) if ml_path.exists() else ()):
        stats_rows.append({
            "策略": name,
            "交易笔数": stats.get("total_trades"),
            "胜率": stats.get("winrate"),
            "Freqtrade 总收益": stats.get("profit_total"),
            "期末资金": stats.get("final_balance"),
            "平均持仓时长": stats.get("holding_avg"),
        })
    pd.DataFrame(stats_rows).to_csv(OUT / "trade_stats.csv", index=False, encoding="utf-8-sig")

    # 图 1：收益曲线（对数坐标）
    fig, ax = plt.subplots(figsize=(12, 5.6), dpi=150)
    for name, eq in curves.items():
        lw = 2.4 if "（" in name else 1.3
        ax.plot(eq.index, eq.values, label=name, color=COLORS[name], linewidth=lw)
    ax.set_yscale("log")
    ax.set_ylabel("净值（初始 10,000 USDT，对数坐标）")
    style_axes(ax, "收益曲线：策略 vs 一直持有")
    mark_paper_end(ax)
    ax.legend(loc="upper left", frameon=False, fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "equity_curves.png")
    plt.close(fig)

    # 图 2：回撤
    fig, ax = plt.subplots(figsize=(12, 4.2), dpi=150)
    for name in [n for n in curves if n != "一直持有 ETH"]:
        dd = drawdown(curves[name])
        lw = 2.0 if "（" in name else 1.2
        ax.plot(dd.index, dd.values * 100, label=name, color=COLORS[name], linewidth=lw)
    ax.set_ylabel("回撤（%）")
    style_axes(ax, "回撤：离前高跌了多少")
    mark_paper_end(ax)
    ax.legend(loc="lower left", frameon=False, fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "drawdowns.png")
    plt.close(fig)

    # 图 3：主策略的仓位（BTC 价格 + 实际仓位占总资产比例）
    eq = trend_eq.loc[start:end]
    btc_weight = (held["论文规则（TrendEnsemble）"].loc[start:end, "BTC/USDT"] / eq).clip(lower=0)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 5.6), dpi=150, sharex=True,
                                   gridspec_kw={"height_ratios": [3, 2]})
    ax1.plot(closes.loc[start:end].index, closes.loc[start:end, "BTC/USDT"], color="#404040", linewidth=1.3)
    ax1.set_yscale("log")
    ax1.set_ylabel("BTC 价格（USDT）")
    style_axes(ax1, "主策略什么时候在场：BTC 价格与 BTC 仓位")
    ax2.fill_between(btc_weight.index, btc_weight.values * 100, color="#1f4e79", alpha=0.55, linewidth=0)
    ax2.set_ylabel("BTC 仓位占总资产（%）")
    ax2.set_ylim(0, 55)
    style_axes(ax2, "")
    fig.tight_layout()
    fig.savefig(OUT / "trend_exposure.png")
    plt.close(fig)

    # 手续费敏感度
    fee_rows = []
    for fee in ("0.0015", "0.0025", "0.005"):
        path = NAMED / f"trend_fee{fee}.zip"
        if not path.exists():
            continue
        e, _ = equity_from_orders(load_result(f"trend_fee{fee}"), closes)
        e = e.loc[start:end]
        m = metrics(e)
        fee_rows.append({"单边成本": float(fee), "年化收益": m["年化收益"], "夏普": m["夏普"],
                         "最大回撤": m["最大回撤"]})
    fee_table = pd.DataFrame(fee_rows)
    fee_table.to_csv(OUT / "fee_sensitivity.csv", index=False, encoding="utf-8-sig")

    json.dump({"eval_start": str(start.date()), "eval_end": str(end.date())},
              open(OUT / "period.json", "w", encoding="utf-8"))
    pd.set_option("display.width", 200)
    print(table.to_string(index=False))
    print(fee_table.to_string(index=False))


def _first_active(equity: pd.Series) -> pd.Timestamp:
    """净值第一次偏离初始资金的那天，视为策略开始有效。"""
    moved = equity[(equity - INITIAL).abs() > 1e-6]
    return moved.index[0] - pd.Timedelta(days=1) if len(moved) else equity.index[0]


if __name__ == "__main__":
    main()
