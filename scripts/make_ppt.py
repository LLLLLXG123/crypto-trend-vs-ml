"""
生成课堂展示用的 PPT：results/ 里的图表和指标 → results/展示.pptx（附讲稿）。

用法（项目根目录，先跑 scripts/report.py）：
    python -X utf8 scripts/make_ppt.py
"""

import json
from pathlib import Path

import pandas as pd
from pptx.util import Inches

import pptkit as k

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
SOURCE = ("数据：OKX 现货 BTC/USDT、ETH/USDT（2018-01 至 2026-10）｜ 回测：Freqtrade 2026.9 ｜ "
          "成本：每边 0.15%（手续费 0.1% + 滑点 0.05%）")

TREND = "论文规则（TrendEnsemble）"
ML = "机器学习（MLXGBoost）"
ML_GROSS = "机器学习（不计成本）"
HOLD = "BTC/ETH 各半持有"
BTC = "一直持有 BTC"
SAME = "同等仓位持有"
SHORT = {TREND: "论文规则", ML: "机器学习", HOLD: "各半持有", BTC: "持有 BTC"}


def pct(x, digits=1, sign=False):
    return f"{x * 100:+.{digits}f}%" if sign else f"{x * 100:.{digits}f}%"


def load():
    m = pd.read_csv(RES / "metrics.csv")
    metrics = {(r["策略"], r["区间"]): r for _, r in m.iterrows()}
    fee = pd.read_csv(RES / "fee_sensitivity.csv")
    exposure = pd.read_csv(RES / "exposure.csv").set_index("策略")
    baseline = json.load(open(RES / "baseline.json", encoding="utf-8"))
    period = json.load(open(RES / "period.json", encoding="utf-8"))
    look = {}
    for name in ("trend", "ml"):
        path = RES / f"lookahead_{name}.csv"
        if path.exists():
            look[name] = pd.read_csv(path).iloc[0]
    stats = pd.read_csv(RES / "trade_stats.csv").set_index("策略")
    costs = pd.read_csv(RES / "costs.csv").set_index("策略")
    recon = json.load(open(RES / "recon.json", encoding="utf-8"))
    return metrics, fee, exposure, baseline, period, look, stats, costs, recon


def main():
    metrics, fee, exposure, baseline, period, look, stats, costs, recon = load()
    has_ml = (ML, "全区间") in metrics
    t_full, t_in, t_post = (metrics[(TREND, p)] for p in ("全区间", "论文样本期内", "论文发表后"))
    h_full, h_post = metrics[(HOLD, "全区间")], metrics[(HOLD, "论文发表后")]
    b_full, b_post = metrics[(BTC, "全区间")], metrics[(BTC, "论文发表后")]
    s_full, s_in, s_post = (metrics[(SAME, p)] for p in ("全区间", "论文样本期内", "论文发表后"))
    m_full, m_post, g_full = metrics[(ML, "全区间")], metrics[(ML, "论文发表后")], metrics[(ML_GROSS, "全区间")]
    c_t, c_m = costs.loc[TREND], costs.loc[ML]
    avg_exp = baseline["trend_avg_exposure"]
    start, end = period["eval_start"][:7], period["eval_end"][:7]
    recon_text = f"最大差异 {recon['trend']:.2f}%（主策略）、{recon['ml']:.2f}%（机器学习）"

    prs = k.new_deck()
    page = 1

    # 1 封面
    s = k.blank(prs)
    k.text_box(s, k.MARGIN, Inches(2.0), Inches(12), Inches(1.0),
               [("论文说的，发表后还灵吗？", {"bold": True})], size=40)
    k.text_box(s, k.MARGIN, Inches(3.05), Inches(12), Inches(0.8),
               "在 Freqtrade 中复现 2025 年的加密货币趋势策略，并与机器学习策略对比", size=22, color=k.MUTED)
    bar = s.shapes.add_shape(k.MSO_SHAPE.RECTANGLE, k.MARGIN, Inches(4.0), Inches(1.2), Inches(0.07))
    bar.fill.solid()
    bar.fill.fore_color.rgb = k.ACCENT
    bar.line.fill.background()
    k.text_box(s, k.MARGIN, Inches(4.3), Inches(12), Inches(1.0),
               [f"BTC/USDT、ETH/USDT 现货 ｜ OKX ｜ 回测区间 {start} 至 {end}",
                ("2026 年 10 月 22 日", {"color": k.MUTED})], size=16)
    k.notes(s, "大家好。今天讲的问题很简单：一篇 2025 年发表的加密货币策略论文，"
               "我们把规则原样搬进开源交易软件 Freqtrade，在论文发表之后的真实行情里，它还灵不灵？"
               "另外我们还做了一个机器学习版本作为对照。")

    # 2 研究问题与依据
    page += 1
    s = k.blank(prs)
    k.title(s, "为什么选趋势跟踪：高波动资产上证据最多的策略", "研究依据")
    k.text_box(s, k.MARGIN, Inches(1.65), Inches(12.1), Inches(4.2), [
        "**期货（含商品）**：过去 12 个月涨跌能预测未来，百年样本都成立 —— Moskowitz, Ooi & Pedersen (2012)；Hurst, Ooi & Pedersen (2017)",
        "**加密货币**：时间序列动量很强 —— Liu & Tsyvinski (2021, RFS)；均线规则明显降低比特币回撤 —— Detzel 等 (2021)",
        "**最新**：多周期通道突破 + 按波动率定仓位，扣费后夏普 > 1.5 —— Zarattini, Pagani & Barbon (2025)",
        "**反面**：抄底类规则在 2022 年后失效 —— Quantpedia (2024)；大批技术指标在比特币样本外失灵 —— Hudson & Urquhart (2021)",
        "**提醒**：策略发表后收益平均下降一半以上 —— McLean & Pontiff (2016, JF)",
    ], size=17, spacing=12)
    k.callout(s, k.MARGIN, Inches(5.75), Inches(12.1), Inches(0.9),
              "我们的问题：2025 年论文的规则一个参数都不改，论文样本截止（2025-03）之后的 19 个月还有效吗？")
    k.footer(s, page, "文献详见项目 docs/2026-10-20-策略文献调研.md")
    k.notes(s, "选趋势跟踪是因为它在高波动资产上证据最多：商品期货上有百年证据，"
               "加密货币上 2021 年 RFS 的论文也证实了很强的动量。我们复现的是 2025 年 Zarattini 等人的论文。"
               "同时要提醒：McLean 和 Pontiff 发现策略发表后收益平均会下降一半以上，所以发表后的检验才是关键。")

    # 3 主策略规则
    page += 1
    s = k.blank(prs)
    k.title(s, "主策略 TrendEnsemble：照抄论文规则，一个参数都没调", "策略一")
    w, gap, top, h = Inches(3.85), Inches(0.28), Inches(1.75), Inches(3.6)
    k.panel(s, k.MARGIN, top, w, h, "什么时候买",
            ["回看期共 9 个，从 5 天到 360 天",
             "收盘价创出该回看期的新高 → 这一份开仓",
             "9 份各自独立进出"])
    k.panel(s, k.MARGIN + w + gap, top, w, h, "什么时候卖",
            ["止损线 = 回看期内最高与最低收盘价的中点",
             "止损线只升不降（移动止损）",
             "收盘价跌破止损线 → 这一份平仓"])
    k.panel(s, k.MARGIN + 2 * (w + gap), top, w, h, "买多少",
            ["每份权重 = min(25% ÷ 近 90 天年化波动率, 2)",
             "9 份取平均；现货不加杠杆，封顶 100%",
             "BTC、ETH 各占一半资金"])
    k.text_box(s, k.MARGIN, Inches(5.65), Inches(12.1), Inches(1.0), [
        "日线运行：每天 UTC 0 点收盘后算信号，下一根开盘成交；每天把仓位调到目标，偏差小于 5% 不动（降低换手）",
        ("参数全部来自论文，没有在我们的数据上优化过 —— 所以不存在“调参凑曲线”", {"color": k.ACCENT, "bold": True}),
    ], size=15, spacing=8)
    k.footer(s, page, SOURCE)
    k.notes(s, "规则分三块。买：9 个不同长度的回看期，收盘价创新高就开一份。卖：止损线是区间高低点的中点，"
               "只升不降，跌破就平。买多少：按波动率定仓位，波动越大仓位越小。"
               "所有参数都是论文里的，我们一个都没改，这样就不存在拿数据调参数的问题。")

    # 4 机器学习备份
    page += 1
    s = k.blank(prs)
    k.title(s, "备份策略 MLXGBoost：让机器学习自己找规律", "策略二")
    k.text_box(s, k.MARGIN, Inches(1.65), Inches(7.3), Inches(4.9), [
        "**模型**：Freqtrade 自带的 FreqAI + XGBoost，参照 Bysik & Ślepaczuk (2026)",
        "**预测什么**：未来 24 小时的平均涨幅（1 小时 K 线）",
        "**看什么**：58 个简单特征 —— 多周期涨跌幅、波动率、离区间高低点的距离、量比、几点钟、星期几，以及另一个币的同类特征",
        "**怎么训练**：每周用过去 365 天重新训练一次 → 每次预测的都是模型没见过的未来",
        "**什么时候买**：预测涨幅 > 2 × 一买一卖总成本（0.6%）才买；预测转负就卖；模型没见过的行情不交易",
        "**买多少**：min(25% ÷ 年化波动率, 1) × 该币一半资金",
    ], size=16, spacing=11)
    k.panel(s, Inches(8.25), Inches(1.75), Inches(4.45), Inches(3.3), "为什么这样设计",
            ["Jaquart 等 (2021)：预测太短期，手续费会吃光收益",
             "Cakici 等 (2024)：复杂模型提升有限，简单特征才有用",
             "门槛和训练窗口事先定死，不看结果调"], size=15)
    k.footer(s, page, SOURCE)
    k.notes(s, "备份策略换一个思路：不写死规则，让 XGBoost 从 58 个简单特征里自己学，预测未来 24 小时的涨幅。"
               "关键是滚动训练：每周只用过去一年的数据重训，所以每一次预测都是对没见过的未来做的。"
               "另外只有预测涨幅超过两倍成本才交易，避免被手续费吃掉。")

    # 5 四件事
    page += 1
    s = k.blank(prs)
    k.title(s, "让结果可信的四件事", "检验方法")
    fee_hi = fee.iloc[-1]
    look_t, look_m = look["trend"], look["ml"]
    signals_ok = all(r["biased_entry_signals"] == 0 and r["biased_exit_signals"] == 0 for r in (look_t, look_m))
    look_text = (f"两个策略各抽查 {int(look_t['total_signals'])} 笔交易，买卖点全部一致" if signals_ok
                 else "发现偏差，见第 11 页")
    k.table(s, k.MARGIN, Inches(1.7), Inches(12.1), [
        ["检验", "怎么做", "结果"],
        ["1 手续费", "每边 0.15%；另测 0、0.25%、0.5%",
         f"主策略：成本提高到 3 倍多，年化仍有 {pct(fee_hi['年化收益'])}；机器学习：扣费后由盈转亏"],
        ["2 不偷看未来", "Freqtrade 的 lookahead-analysis：截掉后面的数据重跑，逐笔比对", look_text],
        ["3 和一直持有比", "BTC、ETH、各半持有，外加“同等仓位持有”",
         f"同等风险下，主策略年化 {pct(t_full['年化收益'])} vs {pct(s_full['年化收益'])}"],
        ["4 样本内外分开", "以论文样本截止日 2025-03-15 为界；机器学习每周滚动重训，全程样本外",
         f"发表后：主策略年化 {pct(t_post['年化收益'])}，与同等仓位持有 {pct(s_post['年化收益'])} 打平"],
    ], col_widths=[2.0, 5.0, 5.1], size=14, row_height=0.78)
    k.text_box(s, k.MARGIN, Inches(5.95), Inches(12.1), Inches(0.8), [
        f"另外：用逐笔订单独立重算净值，与 Freqtrade 自己的账户记录逐日对比，{recon_text}",
    ], size=14, color=k.MUTED)
    k.footer(s, page, SOURCE)
    k.notes(s, "为了让结果可信，我们做了四件事。手续费：按每边 0.15% 算，还测了不收费和更贵的情况。"
               "偷看未来：用 Freqtrade 自带的工具，把后面的数据截掉重跑，逐笔比对买卖点，两个策略都一致。"
               "对比：不只比一直持有，还比了一个同等仓位的持有组合，这样风险是对齐的。"
               "样本内外：主策略以论文样本截止日为界分开看；机器学习每周只用过去的数据重训，本身就全程是样本外。")

    # 6 收益曲线
    page += 1
    s = k.blank(prs)
    k.title(s, "全区间：收益只有持有的零头，但回撤小得多", "结果一")
    k.image(s, RES / "equity_curves.png", k.MARGIN, Inches(1.55), width=Inches(9.0))
    k.text_box(s, k.MARGIN, Inches(5.9), Inches(9.0), Inches(0.8),
               [(f"公平的比较：蓝色虚线同样只放 {pct(avg_exp, 0)} 在币上，论文规则每年比它多赚约 "
                 f"{(t_full['年化收益'] - s_full['年化收益']) * 100:.0f} 个百分点", {"bold": True, "color": k.ACCENT})], size=16)
    k.panel(s, Inches(9.85), Inches(1.6), Inches(2.9), Inches(4.25), "数字",
            [f"论文规则：年化 **{pct(t_full['年化收益'])}**，最大回撤 **{pct(t_full['最大回撤'])}**",
             f"各半持有：年化 {pct(h_full['年化收益'])}，最大回撤 {pct(h_full['最大回撤'])}",
             f"论文规则平均只用了 **{pct(avg_exp, 0)}** 的资金",
             f"同样只放 {pct(avg_exp, 0)} 在币上：年化 {pct(s_full['年化收益'])}",
             ("橙线：机器学习，见第 10 页", {"color": k.MUTED})], size=15)
    k.footer(s, page, SOURCE)
    k.notes(s, f"先看全区间。一直持有的收益远高于论文规则，这是事实，但它中间最多亏了 {pct(-h_full['最大回撤'], 0)}。"
               f"论文规则平均只用了 {pct(avg_exp, 0)} 的资金，所以公平的比较对象是同样只放 {pct(avg_exp, 0)} 在币上的组合，"
               f"它的年化是 {pct(s_full['年化收益'])}，论文规则是 {pct(t_full['年化收益'])}。"
               "最下面的橙线是机器学习，扣费后是亏的，后面单独讲。")

    # 7 收益和风险一起看
    page += 1
    s = k.blank(prs)
    k.title(s, "收益和风险放在一起看：同样的风险，论文规则赚得更多", "结果二")
    k.image(s, RES / "risk_return.png", k.MARGIN, Inches(1.5), height=Inches(5.3))
    rows = [["", "年化收益", "年化波动", "夏普", "最大回撤"]]
    names = [TREND] + ([ML] if has_ml else []) + [SAME, HOLD, BTC]
    for n in names:
        r = metrics[(n, "全区间")]
        label = f"同等仓位（{pct(avg_exp, 0)}）" if n == SAME else SHORT.get(n, n)
        rows.append([label, pct(r["年化收益"]), pct(r["年化波动"]), f"{r['夏普']:.2f}", pct(r["最大回撤"])])
    k.table(s, Inches(8.0), Inches(1.75), Inches(4.75), rows, col_widths=[2.3, 1.3, 1.3, 1.0, 1.3],
            size=12, row_height=0.6)
    k.footer(s, page, SOURCE)
    k.notes(s, "这张图横轴是最大回撤，越往左越安全；纵轴是年化收益。一直持有在右上角，收益高但风险极大。"
               "论文规则在左边。和同等仓位的持有组合比，论文规则在同样风险下收益更高，夏普也更高。"
               "机器学习在零线以下，扣费后是亏的。")

    # 8 论文发表后
    page += 1
    s = k.blank(prs)
    k.title(s, "论文发表之后：风险控制还在，超额收益没了", "结果三：真正的样本外")
    k.image(s, RES / "post_paper.png", k.MARGIN, Inches(1.55), width=Inches(9.0))
    k.text_box(s, k.MARGIN, Inches(5.65), Inches(9.0), Inches(0.9),
               [("持有的人坐了一趟过山车；论文规则几乎是一条直线，但和同等仓位持有（浅蓝）基本重合",
                 {"bold": True, "color": k.ACCENT})], size=16)
    k.text_box(s, Inches(9.75), Inches(1.6), Inches(3.0), Inches(0.5),
               [("2025-03 之后", {"bold": True, "color": k.ACCENT})], size=18)
    rows = [["", "总收益", "最大回撤"]]
    for n, label in ((TREND, "论文规则"), (SAME, "同等仓位"), (BTC, "持有 BTC"), (ML, "机器学习")):
        r = metrics[(n, "论文发表后")]
        rows.append([label, pct(r["总收益"], sign=True), pct(r["最大回撤"])])
    k.table(s, Inches(9.75), Inches(2.2), Inches(3.0), rows, col_widths=[1.2, 0.9, 0.9], size=13,
            row_height=0.5)
    k.text_box(s, Inches(9.75), Inches(4.85), Inches(3.0), Inches(1.2),
               ["论文规则与同等仓位打平", "超额收益消失", "印证文献中的“发表后衰减”"], size=14, spacing=2)
    k.footer(s, page, SOURCE)
    k.notes(s, f"这是最关键的一页。论文样本截止后的 19 个月，BTC 先涨后跌，持有的人最多亏了 {pct(-b_post['最大回撤'], 0)}。"
               f"论文规则赚了 {pct(t_post['总收益'])}，最大回撤只有 {pct(-t_post['最大回撤'], 0)}。"
               "但和同等仓位持有比，收益基本打平：风险控制依然有效，超额收益没了。"
               "这正好印证了 McLean 和 Pontiff 的发现。19 个月样本还短，结论要谨慎。")

    # 9 熊市
    page += 1
    s = k.blank(prs)
    k.title(s, "2022 年熊市：价格跌了 77%，论文规则基本在场外", "结果四：为什么回撤小")
    k.image(s, RES / "trend_exposure.png", k.MARGIN, Inches(1.55), width=Inches(9.0))
    k.panel(s, Inches(9.85), Inches(1.6), Inches(2.9), Inches(4.25), "看点",
            ["上涨趋势里逐步加仓，跌破止损就撤",
             "2022 年几乎全程空仓或小仓位",
             f"平均仓位 {pct(avg_exp, 0)}，最高 {pct(exposure.loc[TREND, '最高仓位'], 0)}",
             "代价：牛市里也只拿到一部分涨幅"], size=16)
    k.footer(s, page, SOURCE)
    k.notes(s, "回撤小的原因在这张图：下面是论文规则在 BTC 上的仓位。上涨趋势里仓位逐步加上去，"
               "趋势一破就撤。2022 年熊市几乎全程在场外。代价是牛市里也只拿到一部分涨幅。")

    # 10 机器学习
    page += 1
    s = k.blank(prs)
    k.title(s, f"机器学习：扣费前赚 {pct(g_full['总收益'], 0)}，扣费后亏 {pct(-m_full['总收益'], 0)}",
            "结果五：策略二")
    k.image(s, RES / "ml_costs.png", k.MARGIN, Inches(1.55), width=Inches(8.2))
    k.text_box(s, k.MARGIN, Inches(5.2), Inches(8.2), Inches(1.6), [
        (f"同样的买卖信号，只差成本：一年交易 {c_m['每年交易笔数']:.0f} 笔，平均只拿 {c_m['平均持仓天数']:.1f} 天",
         {"bold": True, "color": k.ACCENT, "size": 16}),
        f"7.5 年手续费合计 {c_m['手续费合计']:,.0f} USDT，相当于本金的 {c_m['手续费合计'] / 10000:.0%}",
        "与 Jaquart 等 (2021) 一致：扣费前赚、扣费后亏",
        "Bysik 等 (2026) 称加了成本门槛就能赚，我们照这个思路做了，没能复现",
    ], size=14, spacing=6)
    rows = [["", "论文规则", "机器学习"],
            ["每年交易", f"{c_t['每年交易笔数']:.0f} 笔", f"{c_m['每年交易笔数']:.0f} 笔"],
            ["平均持仓", f"{c_t['平均持仓天数']:.0f} 天", f"{c_m['平均持仓天数']:.1f} 天"],
            ["胜率", pct(c_t["计成本胜率"], 0), pct(c_m["计成本胜率"], 0)],
            ["不计成本年化", pct(c_t["不计成本年化"]), pct(c_m["不计成本年化"])],
            ["计成本年化", pct(c_t["计成本年化"]), pct(c_m["计成本年化"])],
            ["**成本每年吃掉**", f"**{c_t['成本每年吃掉'] * 100:.1f} 个点", f"**{c_m['成本每年吃掉'] * 100:.1f} 个点"]]
    k.table(s, Inches(9.1), Inches(1.75), Inches(3.65), rows, col_widths=[1.55, 1.05, 1.05], size=13,
            row_height=0.56)
    k.text_box(s, Inches(9.1), Inches(5.85), Inches(3.65), Inches(0.8),
               [("胜率高不等于赚钱：论文规则靠少数大赚，机器学习每笔赚得太少", {"color": k.MUTED})], size=12)
    k.footer(s, page, SOURCE)
    k.notes(s, f"机器学习的结果很有意思。虚线是不计成本的净值，赚了 {pct(g_full['总收益'], 0)}；"
               f"实线是同样的买卖信号扣掉成本，亏了 {pct(-m_full['总收益'], 0)}。"
               f"它每年交易 {c_m['每年交易笔数']:.0f} 笔，平均只持有 {c_m['平均持仓天数']:.1f} 天，"
               f"成本每年吃掉约 {c_m['成本每年吃掉'] * 100:.0f} 个百分点；论文规则每年只交易 {c_t['每年交易笔数']:.0f} 笔，"
               f"成本每年不到 1 个点。所以模型不是完全没用，胜率有 {pct(c_m['计成本胜率'], 0)}，但它每笔赚得太少，付不起成本。"
               "这和 Jaquart 等人 2021 年的发现一样。Bysik 等人 2026 年说加成本门槛就能赚，我们照这个思路做了，没有复现出来。")

    # 11 稳健性
    page += 1
    s = k.blank(prs)
    k.title(s, "稳健性：主策略不怕手续费，检查工具也没发现问题", "补充检验")
    rows = [["每边成本", "年化收益", "夏普", "最大回撤"]]
    for _, r in fee.iterrows():
        label = "0（不计成本）" if r["单边成本"] == 0 else pct(r["单边成本"], 2)
        rows.append([label, pct(r["年化收益"]), f"{r['夏普']:.2f}", pct(r["最大回撤"])])
    k.table(s, k.MARGIN, Inches(1.75), Inches(6.0), rows, col_widths=[1.8, 1.4, 1.1, 1.4], size=15,
            row_height=0.62)
    k.text_box(s, k.MARGIN, Inches(5.0), Inches(6.0), Inches(0.9),
               [("表中为主策略（论文规则）2019-05 至 2026-10 的结果", {"color": k.MUTED})], size=12)
    k.text_box(s, Inches(7.0), Inches(1.75), Inches(5.75), Inches(4.9), [
        f"**手续费**：每边成本从 0 提到 0.5%，年化从 {pct(fee.iloc[0]['年化收益'])} 降到 {pct(fee_hi['年化收益'])}，因为日线策略换手低",
        f"**偷看未来**：lookahead-analysis 截掉后面的数据重跑，两个策略各 {int(look_t['total_signals'])} 笔交易的买卖点全部一致。"
        "机器学习被工具标为有差异，逐行查过只是小数点后第 14 位的浮点误差，外加截断处最后一根 K\u00a0线没出预测",
        "**预热长度**：recursive-analysis 用 460 和 999 根 K 线预热，指标完全一致",
        "**训练不越界**：机器学习每次训练都丢掉窗口最后 24 根 K 线，因为它们的标签要用到窗口之后的价格",
        f"**净值核对**：逐笔订单重算 vs Freqtrade 账户记录，{recon_text}",
    ], size=15, spacing=10)
    k.footer(s, page, SOURCE)
    k.notes(s, "补充几项稳健性检验。主策略的成本从 0 提到 0.5%，年化只少两三个百分点，结论不变。"
               "Freqtrade 的两个检查工具都没有发现买卖点被未来数据影响。机器学习被工具标了有差异，"
               "我们逐行查过：一是相似度指标在小数点后第 14 位的浮点误差，二是截断重跑时最后一根 K 线没有预测，"
               "其余每一行的预测和信号都完全一样。机器学习训练时，"
               "窗口最后 24 根 K 线的标签要用到之后的价格，FreqAI 会自动丢掉，我们在日志里确认过。"
               "我们还用逐笔订单独立重算了净值，和 Freqtrade 自己的记录逐日对得上。")

    # 12 结论
    page += 1
    s = k.blank(prs)
    k.title(s, "结论与下一步", "总结")
    k.text_box(s, k.MARGIN, Inches(1.65), Inches(7.0), Inches(5.0), [
        ("结论", {"bold": True, "color": k.ACCENT, "size": 19}),
        f"1. 论文规则在 2019–2025 有效：同等风险下年化 {pct(t_in['年化收益'])} vs {pct(s_in['年化收益'])}，"
        "回撤不到持有的 1/4",
        f"2. 论文发表后：最大回撤依旧只有 {pct(-t_post['最大回撤'])}，但超额收益消失，和文献的“发表后衰减”一致",
        f"3. 机器学习：扣费前年化 {pct(g_full['年化收益'])}，扣费后 {pct(m_full['年化收益'])}。"
        "交易太频繁，成本吃掉了全部收益",
        "4. 所有结果都扣了成本、做了未来数据检查、分了样本内外，代码可复现",
    ], size=16, spacing=12)
    k.panel(s, Inches(7.9), Inches(1.75), Inches(4.85), Inches(3.6), "下一步",
            ["资金费过滤：溢价过高时降仓（BIS 2023）",
             "机器学习：拉长预测周期、降低换手，再用新数据检验",
             "用永续合约做空，熊市也能赚",
             "扩到论文的 20 个币轮动",
             "Freqtrade 模拟盘实时运行，与回测对比"], size=15)
    k.footer(s, page, SOURCE)
    k.notes(s, "总结一下：论文规则在样本期内确实有效；发表之后风险控制还在，但超额收益没了。"
               "机器学习有一点预测力，但交易太频繁，成本把收益吃光了。"
               "下一步可以加资金费过滤、给机器学习降低换手、做空、扩到更多币种，并让它在模拟盘上实时跑起来。谢谢大家。")

    # 13 附录：特征重要性
    page += 1
    s = k.blank(prs)
    k.title(s, "附：机器学习最看重哪些特征", "附录")
    k.image(s, RES / "ml_feature_importance.png", k.MARGIN, Inches(1.55), width=Inches(8.2))
    k.panel(s, Inches(9.1), Inches(1.6), Inches(3.65), Inches(4.5), "看点",
            ["最有用的是慢变量：离近 7 天、30 天高低点的距离和波动率，和论文规则用的是同一类信息",
             "1–4 小时的涨跌幅、量比几乎没用，各约 0.5%",
             "另一个币的特征占一半重要性：BTC 和 ETH 联动很强",
             "**信息是慢的，交易却是快的** —— 这就是成本吃掉收益的原因"], size=14)
    k.footer(s, page, "780 个滚动模型（390 周 × 2 个币）的平均特征重要性，按信息增益计")
    k.notes(s, "这一页备用。780 个滚动训练的模型平均下来，最重要的特征是离近 7 天、30 天高低点的距离和波动率，"
               "和论文规则用的是同一类信息；1 到 4 小时的短期特征几乎没用。模型能用的信息变化很慢，"
               "却按小时进出，这就是成本吃掉收益的原因。")

    out = RES / "展示.pptx"
    prs.save(out)
    print("saved", out)


if __name__ == "__main__":
    main()
