"""
回测结果整理：按日逐笔重建市值净值，算分段指标，出图表。

用法（项目根目录）：
    python -X utf8 scripts/report.py

读取 user_data/backtest_results/named/ 下按名字保存的回测结果（见 scripts/run_backtests.sh），
输出到 results/：metrics.csv（分段指标）、costs.csv（成本吃掉多少）、fee_sensitivity.csv、各 PNG 图。
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
    "同等仓位持有": "#7fa7d0",
    "调参版（TrendTuned）": "#2f7d4f",
    "同等仓位持有（调参版）": "#93c4a6",
}
TUNED = "调参版（TrendTuned）"
TUNED_SAME = "同等仓位持有（调参版）"

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def shown(name: str) -> str:
    """图上显示的名字，和 PPT 的叫法一致。"""
    return name.replace("论文规则", "趋势追踪")


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


def fees_paid(stats: dict) -> tuple[float, float]:
    """逐笔订单累计的成交额和手续费（USDT）。"""
    volume = fees = 0.0
    for trade in stats["trades"]:
        for order in trade["orders"]:
            value = float(order["amount"]) * float(order["safe_price"])
            volume += value
            fees += value * (trade["fee_open"] if order["ft_order_side"] == "buy" else trade["fee_close"])
    return volume, fees


def wallet_check(name: str, equity: pd.Series) -> float:
    """逐笔重建的净值 vs Freqtrade 自己记录的每日账户市值，返回最大相对差异（%）。
    Freqtrade 的账户记录按当天开盘（= 前一天收盘）估值，所以把重建值往后错一天对齐。"""
    import io

    with zipfile.ZipFile(NAMED / f"{name}.zip") as zf:
        member = next(n for n in zf.namelist() if n.endswith("_wallet.feather"))
        wallet = pd.read_feather(io.BytesIO(zf.read(member))).groupby("date")["total_quote"].sum()
    shifted = equity.copy()
    shifted.index = shifted.index + pd.Timedelta(days=1)
    both = pd.concat([shifted, wallet], axis=1, keys=["rebuilt", "wallet"], sort=True).dropna()
    return float((both["rebuilt"] / both["wallet"] - 1).abs().max() * 100)


def buy_and_hold(closes: pd.DataFrame, start: pd.Timestamp, weights: dict) -> pd.Series:
    px = closes.loc[start:]
    units = {p: INITIAL * w * (1 - FEE) / px[p].iloc[0] for p, w in weights.items()}
    return sum(px[p] * u for p, u in units.items())


def constant_mix(closes: pd.DataFrame, start: pd.Timestamp, exposure: float) -> pd.Series:
    """BTC/ETH 各半、总仓位固定为 exposure、其余现金；每天调回目标权重，调仓部分扣成本。"""
    px = closes.loc[start:]
    rets = px.pct_change().fillna(0.0)
    target = np.array([exposure / 2, exposure / 2])
    equity = INITIAL * (1 - FEE * exposure)
    values = []
    for _, r in rets.iterrows():
        risky = equity * target * (1 + r.to_numpy())
        cash = equity * (1 - exposure)
        equity_before = cash + risky.sum()
        turnover = np.abs(equity_before * target - risky).sum()
        equity = equity_before - turnover * FEE
        values.append(equity)
    return pd.Series(values, index=px.index)


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


def mark_paper_end(ax, end: pd.Timestamp, y: float = 0.98):
    ax.axvline(PAPER_END, color="#c00000", linestyle="--", linewidth=1)
    ax.axvspan(PAPER_END, end, color="#c00000", alpha=0.04)
    ax.text(PAPER_END, y, " 论文样本截止 →\n 之后都是样本外", transform=ax.get_xaxis_transform(),
            va="top" if y > 0.5 else "bottom", fontsize=9, color="#c00000")


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

    recon = {"trend": wallet_check("trend_fee0.0015", trend_eq)}
    if ml_path.exists():
        recon["ml"] = wallet_check("ml_fee0.0015", ml_eq)
    json.dump(recon, open(OUT / "recon.json", "w", encoding="utf-8"))

    # 共同评估区间：两个策略都开始有效之后
    start = max(_first_active(eq) for eq in curves.values())
    end = closes.index[-1]
    curves = {k: v.loc[start:end] / v.loc[start] * INITIAL for k, v in curves.items()}
    curves["一直持有 BTC"] = buy_and_hold(closes, start, {"BTC/USDT": 1.0})
    curves["一直持有 ETH"] = buy_and_hold(closes, start, {"ETH/USDT": 1.0})
    curves["BTC/ETH 各半持有"] = buy_and_hold(closes, start, {"BTC/USDT": 0.5, "ETH/USDT": 0.5})
    trend_avg_exposure = float((held["论文规则（TrendEnsemble）"].loc[start:end].sum(axis=1)
                                / trend_eq.loc[start:end]).mean())
    curves["同等仓位持有"] = constant_mix(closes, start, trend_avg_exposure)

    # 不计成本的对照：同样的信号，成本设为 0。只进指标表和成本图，不进主图
    gross, gross_stats = {}, {}
    for label, name in (("论文规则（不计成本）", "trend_fee0"), ("机器学习（不计成本）", "ml_fee0")):
        if (NAMED / f"{name}.zip").exists():
            gross_stats[label] = load_result(name)
            e, _ = equity_from_orders(gross_stats[label], closes)
            gross[label] = e.loc[start:end] / e.loc[start] * INITIAL

    # 调参版（参数只在论文样本期上调过）和它的同等仓位基准，只进指标表和自己的图
    tuned, tuned_avg_exposure = {}, None
    if (NAMED / "tuned_fee0.0015.zip").exists():
        tuned_stats = load_result("tuned_fee0.0015")
        e, h = equity_from_orders(tuned_stats, closes)
        tuned_raw, held[TUNED] = e, h
        tuned_avg_exposure = float((h.loc[start:end].sum(axis=1) / e.loc[start:end]).mean())
        tuned[TUNED] = e.loc[start:end] / e.loc[start] * INITIAL
        tuned[TUNED_SAME] = constant_mix(closes, start, tuned_avg_exposure)
        recon["tuned"] = wallet_check("tuned_fee0.0015", e)
        json.dump(recon, open(OUT / "recon.json", "w", encoding="utf-8"))

    # 分段指标
    rows = []
    for name, eq in {**curves, **gross, **tuned}.items():
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

    # 成本吃掉多少：换手、手续费合计、计不计成本的年化之差
    cost_rows = []
    years = (end - start).days / 365
    for name, stats, gross_name in (("论文规则（TrendEnsemble）", trend_stats, "论文规则（不计成本）"),) + (
            (("机器学习（MLXGBoost）", ml_stats, "机器学习（不计成本）"),) if ml_path.exists() else ()):
        if gross_name not in gross:
            continue
        volume, fees = fees_paid(stats)
        net_cagr, gross_cagr = metrics(curves[name])["年化收益"], metrics(gross[gross_name])["年化收益"]
        cost_rows.append({
            "策略": name,
            "每年交易笔数": stats["total_trades"] / years,
            "平均持仓天数": np.mean([t["trade_duration"] for t in stats["trades"]]) / 60 / 24,
            "年换手倍数": volume / years / curves[name].mean(),
            "手续费合计": fees,
            "不计成本胜率": gross_stats[gross_name]["winrate"],
            "计成本胜率": stats["winrate"],
            "不计成本年化": gross_cagr,
            "计成本年化": net_cagr,
            "成本每年吃掉": gross_cagr - net_cagr,
        })
    pd.DataFrame(cost_rows).to_csv(OUT / "costs.csv", index=False, encoding="utf-8-sig")

    # 图 1：收益曲线（对数坐标）
    fig, ax = plt.subplots(figsize=(12, 5.6), dpi=150)
    for name, eq in curves.items():
        lw = 2.4 if "（" in name else 1.3
        ls = "--" if name == "同等仓位持有" else "-"
        label = f"同等仓位持有（BTC/ETH 共 {trend_avg_exposure:.0%}，其余现金）" if name == "同等仓位持有" else shown(name)
        ax.plot(eq.index, eq.values, label=label, color=COLORS[name], linewidth=lw, linestyle=ls)
    ax.set_yscale("log")
    ax.set_ylabel("净值（初始 10,000 USDT，对数坐标）")
    style_axes(ax, "收益曲线：策略 vs 一直持有")
    mark_paper_end(ax, end, y=0.6)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.07), ncol=3, frameon=False, fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "equity_curves.png")
    plt.close(fig)

    # 图 2：回撤
    fig, ax = plt.subplots(figsize=(12, 4.2), dpi=150)
    for name in [n for n in curves if n != "一直持有 ETH"]:
        dd = drawdown(curves[name])
        lw = 2.0 if "（" in name else 1.2
        ax.plot(dd.index, dd.values * 100, label=shown(name), color=COLORS[name], linewidth=lw)
    ax.set_ylabel("回撤（%）")
    style_axes(ax, "回撤：离前高跌了多少")
    mark_paper_end(ax, end, y=0.03)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=5, frameon=False, fontsize=10)
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
    style_axes(ax1, "趋势追踪什么时候在场：BTC 价格与 BTC 仓位")
    ax2.fill_between(btc_weight.index, btc_weight.values * 100, color="#1f4e79", alpha=0.55, linewidth=0)
    ax2.set_ylabel("BTC 仓位占总资产（%）")
    ax2.set_ylim(0, 55)
    style_axes(ax2, "")
    fig.tight_layout()
    fig.savefig(OUT / "trend_exposure.png")
    plt.close(fig)

    # 图 4：论文发表后（真正的样本外），从同一起点重新归一
    fig, ax = plt.subplots(figsize=(12, 5.2), dpi=150)
    for name, eq in curves.items():
        post = eq.loc[PAPER_END:]
        post = post / post.iloc[0] * INITIAL
        lw = 2.6 if "（" in name else 1.3
        ax.plot(post.index, post.values, label=shown(name), color=COLORS[name], linewidth=lw)
    ax.axhline(INITIAL, color="#999999", linewidth=0.8)
    ax.set_ylabel("净值（2025-03-15 = 10,000 USDT）")
    style_axes(ax, "论文发表之后：同一起点重新比较")
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 4, 7, 10)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.legend(loc="upper left", frameon=False, fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "post_paper.png")
    plt.close(fig)

    # 图 5：收益 vs 回撤（全区间）
    full = table[(table["区间"] == "全区间") & table["策略"].isin(curves)].set_index("策略")
    fig, ax = plt.subplots(figsize=(8, 5.6), dpi=150)
    holds = ["一直持有 BTC", "一直持有 ETH", "BTC/ETH 各半持有"]
    for name, row in full.iterrows():
        x, y = -row["最大回撤"] * 100, row["年化收益"] * 100
        ax.scatter(x, y, s=160, color=COLORS[name], zorder=3)
        if name in holds:
            continue
        label = f"同等仓位持有（{trend_avg_exposure:.0%}）" if name == "同等仓位持有" else shown(name)
        ax.annotate(f"{label}\n夏普 {row['夏普']:.2f}", (x, y), textcoords="offset points",
                    xytext=(12, -6), fontsize=9.5, color="#222222")
    hold_rows = full.loc[holds]
    ax.annotate("一直持有 BTC / ETH / 各半\n"
                f"夏普 {hold_rows['夏普'].min():.2f}–{hold_rows['夏普'].max():.2f}",
                (-hold_rows["最大回撤"].mean() * 100, hold_rows["年化收益"].mean() * 100),
                textcoords="offset points", xytext=(-150, -34), fontsize=9.5, color="#222222")
    ax.set_xlabel("最大回撤（%，越往左越好）")
    ax.set_ylabel("年化收益（%）")
    ax.set_xlim(0, 100)
    ax.set_ylim(bottom=min(0, full["年化收益"].min() * 100 - 5))
    ax.axhline(0, color="#999999", linewidth=0.8)
    ax.grid(True, color="#e5e5e5")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.set_title(f"收益和风险放在一起看（{start:%Y-%m} 至 {end:%Y-%m}）", loc="left", fontsize=13,
                 fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUT / "risk_return.png")
    plt.close(fig)

    # 图 6：机器学习计不计成本（同样的信号，只差手续费）
    if "机器学习（MLXGBoost）" in curves and "机器学习（不计成本）" in gross:
        net, gr = curves["机器学习（MLXGBoost）"], gross["机器学习（不计成本）"]
        color = COLORS["机器学习（MLXGBoost）"]
        fig, ax = plt.subplots(figsize=(12, 5.2), dpi=150)
        ax.plot(gr.index, gr.values, color=color, linewidth=1.6, linestyle="--", label="不计成本")
        ax.plot(net.index, net.values, color=color, linewidth=2.4, label="每边成本 0.15%（手续费 + 滑点）")
        ax.fill_between(net.index, net.values, gr.values, color=color, alpha=0.10, linewidth=0)
        ax.axhline(INITIAL, color="#999999", linewidth=0.8)
        for series in (gr, net):
            ax.annotate(f"{series.iloc[-1] / INITIAL - 1:+.0%}", (series.index[-1], series.iloc[-1]),
                        textcoords="offset points", xytext=(6, -4), fontsize=12, color=color,
                        fontweight="bold")
        mid = net.index[len(net) * 2 // 3]
        ax.text(mid, (net.loc[mid] + gr.loc[mid]) / 2, "被手续费吃掉的部分", ha="center", va="center",
                fontsize=11, color=color)
        ax.set_xlim(right=end + pd.Timedelta(days=150))
        ax.set_ylabel("净值（初始 10,000 USDT）")
        style_axes(ax, "机器学习：同样的买卖信号，计不计成本")
        ax.legend(loc="upper left", frameon=False, fontsize=10)
        fig.tight_layout()
        fig.savefig(OUT / "ml_costs.png")
        plt.close(fig)

    # 平均仓位（持仓市值 / 总资产），用没归一的原始净值
    raw_equity = {"论文规则（TrendEnsemble）": trend_eq}
    if ml_path.exists():
        raw_equity["机器学习（MLXGBoost）"] = ml_eq
    if tuned:
        raw_equity[TUNED] = tuned_raw
    exposure_rows = []
    for name, h in held.items():
        eq = raw_equity[name].loc[start:end]
        w = h.loc[start:end].sum(axis=1) / eq
        exposure_rows.append({"策略": name, "平均仓位": w.mean(), "最高仓位": w.max(),
                              "有持仓的天数占比": (w > 0.001).mean()})
    pd.DataFrame(exposure_rows).to_csv(OUT / "exposure.csv", index=False, encoding="utf-8-sig")
    json.dump({"trend_avg_exposure": trend_avg_exposure, "tuned_avg_exposure": tuned_avg_exposure},
              open(OUT / "baseline.json", "w"))
    if tuned:
        plot_tuned(curves["论文规则（TrendEnsemble）"], tuned, start, end, tuned_avg_exposure)

    # 手续费敏感度
    fee_rows = []
    for fee in ("0", "0.0015", "0.0025", "0.005"):
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

    plot_feature_importance()

    json.dump({"eval_start": str(start.date()), "eval_end": str(end.date())},
              open(OUT / "period.json", "w", encoding="utf-8"))
    pd.set_option("display.width", 200)
    print(table.to_string(index=False))
    print(fee_table.to_string(index=False))


FEATURE_NAMES = {
    "ret": "涨跌幅", "vol": "波动率", "dist_high": "离最高价", "dist_low": "离最低价",
    "volume_ratio": "量比", "ret_1h": "1 小时涨跌幅", "dist_high_720h": "720 小时离最高价",
    "dist_low_720h": "720 小时离最低价", "hour_of_day": "几点钟（UTC）", "day_of_week": "星期几",
}


def pretty_feature(raw: str, own_coin: str) -> str:
    """'%-ret-period_168_BTC/USDT_1h' → '本币 168 小时涨跌幅'。"""
    body = raw.lstrip("%-")
    parts = body.split("_")
    coin = next((p.split("/")[0] for p in parts if "/" in p), None)
    who = "" if coin is None else ("本币 " if coin == own_coin else "另一币 ")
    if "-period" in body:
        base = body.split("-period")[0]
        period = body.split("-period_")[1].split("_")[0]
        return f"{who}{period} 小时{FEATURE_NAMES[base]}"
    base = body.split("_" + coin)[0] if coin else body
    base = base.removesuffix("_gen")  # FreqAI 给 expand_basic 的特征加的后缀
    return f"{who}{FEATURE_NAMES.get(base, base)}"


def feature_importance(models_dir: Path) -> pd.Series:
    """所有滚动训练出的 XGBoost 模型的平均特征重要性（gain，按本币/另一币归并）。"""
    import joblib

    totals = {}
    count = 0
    for model_file in sorted(models_dir.glob("sub-train-*/*_model.joblib")):
        own = model_file.parent.name.split("-")[2].split("_")[0]
        model = joblib.load(model_file)
        names = model.get_booster().feature_names
        for name, value in zip(names, model.feature_importances_):
            key = pretty_feature(name, own)
            totals[key] = totals.get(key, 0.0) + float(value)
        count += 1
    return (pd.Series(totals) / count).sort_values(ascending=False), count


def plot_feature_importance():
    models_dir = ROOT / "user_data" / "models" / "xgb-v1"
    if not models_dir.exists():
        return
    imp, count = feature_importance(models_dir)
    imp.to_csv(OUT / "ml_feature_importance.csv", encoding="utf-8-sig", header=["平均重要性"])
    top = imp.head(12)[::-1]
    fig, ax = plt.subplots(figsize=(10, 5.6), dpi=150)
    ax.barh(top.index, top.values * 100, color="#c55a11")
    ax.set_xlabel("平均重要性（%，按信息增益）")
    ax.set_title(f"机器学习最看重的 12 个特征（{count} 个滚动模型的平均）", loc="left",
                 fontsize=13, fontweight="bold")
    ax.grid(True, axis="x", color="#e5e5e5")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "ml_feature_importance.png")
    plt.close(fig)


def label_ends(fig, ax, ends, min_gap_pt=14):
    """在每条线的终点标总收益；终点太近时把标签上下错开，免得叠在一起。"""
    fig.canvas.draw()
    to_px = ax.transData.transform
    min_gap_px = min_gap_pt * fig.dpi / 72
    ends = sorted(ends, key=lambda e: e[1])
    placed = []
    for x, y, color in ends:
        py = to_px((mdates.date2num(x), y))[1]
        target = max(py, placed[-1] + min_gap_px) if placed else py
        placed.append(target)
        ax.annotate(f"{y / INITIAL - 1:+.0%}", (x, y), textcoords="offset points",
                    xytext=(5, (target - py) * 72 / fig.dpi - 4), fontsize=11, color=color, fontweight="bold")


def plot_tuned(paper: pd.Series, tuned: dict, start: pd.Timestamp, end: pd.Timestamp, exposure: float):
    """调参版 vs 趋势追踪：左边样本内（调参用的数据），右边样本外（从同一起点重新归一）。"""
    lines = {TUNED: tuned[TUNED], "论文规则（TrendEnsemble）": paper, TUNED_SAME: tuned[TUNED_SAME]}
    labels = {TUNED: "调参版", "论文规则（TrendEnsemble）": "趋势追踪",
              TUNED_SAME: f"同等仓位持有（{exposure:.0%}，和调参版一样）"}
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2), dpi=150, gridspec_kw={"width_ratios": [3, 2]})
    spans = (("样本内：调参用的就是这段数据", start, PAPER_END - pd.Timedelta(days=1)),
             ("样本外：调参时没见过的行情", PAPER_END, end))
    for ax, (title, a, b) in zip(axes, spans):
        ends = []
        for name, eq in lines.items():
            part = eq.loc[a:b]
            part = part / part.iloc[0] * INITIAL
            lw = 2.6 if name == TUNED else 1.6
            ls = "--" if name == TUNED_SAME else "-"
            ax.plot(part.index, part.values, color=COLORS[name], linewidth=lw, linestyle=ls, label=labels[name])
            ends.append((part.index[-1], part.iloc[-1], COLORS[name]))
        ax.axhline(INITIAL, color="#999999", linewidth=0.8)
        style_axes(ax, title)
        ax.set_xlim(right=b + (b - a) * 0.11)
        label_ends(fig, ax, ends)
    axes[1].xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 7)))
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    axes[0].set_ylabel("净值（每段起点 = 10,000 USDT）")
    axes[0].legend(loc="upper left", frameon=False, fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "tuned.png")
    plt.close(fig)


def _first_active(equity: pd.Series) -> pd.Timestamp:
    """净值第一次偏离初始资金的那天，视为策略开始有效。"""
    moved = equity[(equity - INITIAL).abs() > 1e-6]
    return moved.index[0] - pd.Timedelta(days=1) if len(moved) else equity.index[0]


if __name__ == "__main__":
    main()
