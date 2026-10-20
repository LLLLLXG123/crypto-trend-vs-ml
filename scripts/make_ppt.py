"""
生成课堂展示用的 PPT：results/ 里的图表和指标 → results/展示_v2.pptx（附讲稿）。

用法（项目根目录，先跑 scripts/report.py 和 scripts/traits.py）：
    python -X utf8 scripts/make_ppt.py
"""

import json
from pathlib import Path

import pandas as pd
from pptx.util import Inches

import pptkit as k

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
TUNED_PARAMS = ROOT / "user_data" / "strategies" / "TrendTuned.json"
SOURCE = ("数据：OKX 现货 BTC/USDT、ETH/USDT（2018-01 至 2026-10）｜ 回测：Freqtrade 2026.9 ｜ "
          "成本：每边 0.15%（手续费 0.1% + 滑点 0.05%）")

TREND = "论文规则（TrendEnsemble）"
ML = "机器学习（MLXGBoost）"
ML_GROSS = "机器学习（不计成本）"
TUNED = "调参版（TrendTuned）"
TUNED_SAME = "同等仓位持有（调参版）"
HOLD = "BTC/ETH 各半持有"
BTC = "一直持有 BTC"
SAME = "同等仓位持有"
SHORT = {TREND: "论文原版", ML: "机器学习", HOLD: "各半持有", BTC: "持有 BTC"}
LOOKBACKS = (5, 10, 20, 30, 60, 90, 150, 250, 360)


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
    for name in ("trend", "ml", "tuned"):
        path = RES / f"lookahead_{name}.csv"
        if path.exists():
            look[name] = pd.read_csv(path).iloc[0]
    costs = pd.read_csv(RES / "costs.csv").set_index("策略")
    recon = json.load(open(RES / "recon.json", encoding="utf-8"))
    traits = pd.read_csv(RES / "traits.csv", index_col=0)
    traits_extra = json.load(open(RES / "traits.json", encoding="utf-8"))
    tuned_params = json.load(open(TUNED_PARAMS, encoding="utf-8"))["params"]["buy"]
    return metrics, fee, exposure, baseline, period, look, costs, recon, traits, traits_extra, tuned_params


def tuned_lookbacks(params) -> list[int]:
    """和 TrendTuned 的算法一致：整体缩放，再去掉最短的几个。"""
    scaled = [max(2, round(lb * params["lb_scale"])) for lb in LOOKBACKS]
    return scaled[params["drop_short"]:]


def main():
    (metrics, fee, exposure, baseline, period, look, costs, recon,
     traits, traits_extra, tuned_params) = load()
    t_full, t_in, t_post = (metrics[(TREND, p)] for p in ("全区间", "论文样本期内", "论文发表后"))
    u_full, u_in, u_post = (metrics[(TUNED, p)] for p in ("全区间", "论文样本期内", "论文发表后"))
    us_in, us_post = metrics[(TUNED_SAME, "论文样本期内")], metrics[(TUNED_SAME, "论文发表后")]
    h_full = metrics[(HOLD, "全区间")]
    b_post = metrics[(BTC, "论文发表后")]
    s_full, s_in, s_post = (metrics[(SAME, p)] for p in ("全区间", "论文样本期内", "论文发表后"))
    m_full, g_full = metrics[(ML, "全区间")], metrics[(ML_GROSS, "全区间")]
    c_t, c_m = costs.loc[TREND], costs.loc[ML]
    avg_exp, tuned_exp = baseline["trend_avg_exposure"], baseline["tuned_avg_exposure"]
    start, end = period["eval_start"][:7], period["eval_end"][:7]
    tb, te, csi, spx = (traits.loc[n] for n in ("BTC", "ETH", "沪深300", "标普500"))
    mom = traits_extra["BTC动量30天"]
    lbs = tuned_lookbacks(tuned_params)
    in_edge = u_in["年化收益"] - us_in["年化收益"]
    out_edge = u_post["年化收益"] - us_post["年化收益"]
    u_dd = -u_post["最大回撤"]
    over_cap = u_dd > 0.20
    tuned_verdict = [
        "和同等仓位持有比：",
        f"样本内每年多赚 **{in_edge * 100:.0f} 个点**",
        f"样本外只多 **{out_edge * 100:.1f} 个点**",
        f"样本外最多亏 {pct(u_dd)}，" + ("超过了 20% 的上限" if over_cap else "没超过 20% 的上限"),
    ]
    tuned_notes = (
        f"这页看调参版到底靠不靠谱。左边是调参用的那段数据：年化 {pct(u_in['年化收益'])}，最多只亏 {pct(-u_in['最大回撤'])}，"
        f"曲线非常漂亮，每年比同样仓位一直拿着多赚 {in_edge * 100:.0f} 个点。右边是调参时没见过的 19 个月："
        f"年化掉到 {pct(u_post['年化收益'])}，只比同样仓位的持有多 {out_edge * 100:.1f} 个点，"
        f"最多亏了 {pct(u_dd)}" + ("，还超过了我们调参时定的 20% 上限。" if over_cap else "。") +
        "说白了，500 组参数里挑出来的最好那组，多赚的部分大多是把历史行情背下来了。"
        "这也是我们主线用论文原版参数、不用调过的参数的原因。")
    tuned_conclusion = (f"4. 调参版：样本内年化 {pct(u_in['年化收益'])}，样本外只有 {pct(u_post['年化收益'])}，"
                        "纸面漂亮靠不住")
    tuned_conclusion_notes = (f"调参版在调参用的数据上年化 {pct(u_in['年化收益'])}，到了没见过的行情只剩 "
                              f"{pct(u_post['年化收益'])}，纸面上漂亮的曲线靠不住。")

    prs = k.new_deck()
    page = 1

    # 1 封面
    s = k.blank(prs)
    k.text_box(s, k.MARGIN, Inches(2.0), Inches(12), Inches(1.0),
               [("论文复刻VS机器学习？", {"bold": True})], size=44)
    k.text_box(s, k.MARGIN, Inches(3.1), Inches(12), Inches(0.8),
               "在 Freqtrade 里回测 BTC、ETH 的现货策略", size=22, color=k.MUTED)
    bar = s.shapes.add_shape(k.MSO_SHAPE.RECTANGLE, k.MARGIN, Inches(4.0), Inches(1.2), Inches(0.07))
    bar.fill.solid()
    bar.fill.fore_color.rgb = k.ACCENT
    bar.line.fill.background()
    k.text_box(s, k.MARGIN, Inches(4.3), Inches(12), Inches(1.0),
               [f"OKX 现货 BTC/USDT、ETH/USDT ｜ 回测区间 {start} 至 {end}",
                ("2026 年 10 月 22 日", {"color": k.MUTED})], size=16)
    k.notes(s, "大家好。我们做了两个加密货币策略的回测。一个是把 2025 年一篇论文的规则原样搬过来，"
               "另一个是用机器学习让模型自己找规律。另外我们还把论文的参数调了一版，"
               "看看调出来的漂亮曲线到底靠不靠谱。所有回测都在开源软件 Freqtrade 里跑。")

    # 2 数字货币的特点
    page += 1
    s = k.blank(prs)
    k.title(s, "数字货币有什么特点，适合什么策略")
    every = 1 / tb["单日涨跌超5%占比"]
    every_csi = 1 / csi["单日涨跌超5%占比"]
    k.table(s, k.MARGIN, Inches(1.6), Inches(12.1), [
        ["特点", "数据（2019-05 至 2026-10）", "所以策略要"],
        ["波动大", f"年化波动 BTC {pct(tb['年化波动'], 0)}、ETH {pct(te['年化波动'], 0)}；"
                  f"沪深 300 {pct(csi['年化波动'], 0)}、标普 500 {pct(spx['年化波动'], 0)}",
         "按波动率定仓位，波动越大买得越少"],
        ["跌起来很深", f"BTC 最多跌掉 {pct(-tb['最大回撤'], 0)}，单日最多跌 {pct(-tb['单日最大跌幅'], 0)}",
         "一定要有卖出规则，不能一直拿着硬扛"],
        ["大涨大跌是常态", f"BTC 平均 {every:.0f} 天就有 1 天涨跌超 5%；沪深 300 要 {round(every_csi, -2):.0f} 天",
         "别做太短的周期，日线就够了"],
        ["有趋势", f"BTC 上月涨，下月平均涨 {pct(mom['上段涨后下段平均'])}；"
                  f"上月跌，下月平均只涨 {pct(mom['上段跌后下段平均'])}",
         "顺着趋势做：创新高就买，跌破就卖"],
        ["没有现金流", "没有利润，也没有分红，算不出估值", "基本面、估值类的方法用不上，主要看价格"],
        ["全年不停", "一年 365 天、一天 24 小时都在交易，没有涨跌停", "交给程序自动执行"],
    ], col_widths=[1.7, 6.2, 4.2], size=14, row_height=0.62, left_cols=(0, 1, 2))
    k.callout(s, k.MARGIN, Inches(6.05), Inches(12.1), Inches(0.75),
              "所以我们选：趋势跟踪 + 按波动率定仓位，只做多现货，日线低频")
    k.footer(s, page, "BTC、ETH：OKX 日线；沪深 300、标普 500：新浪财经（akshare）｜ "
                      "“有趋势”一行是不重叠的 30 天区间，共 89 段，只作直观参考")
    k.notes(s, f"先说说数字货币和股票有什么不一样。第一是波动大，比特币一年的波动率有 {pct(tb['年化波动'], 0)}，"
               f"差不多是沪深 300 的 {tb['年化波动'] / csi['年化波动']:.1f} 倍。第二是跌起来很深，"
               f"比特币最多跌掉过 {pct(-tb['最大回撤'], 0)}。第三是大涨大跌很常见，"
               f"比特币大约每 {every:.0f} 天就有一天涨跌超过 5%。第四是它有趋势，涨起来容易接着涨，"
               "这个结论主要来自文献，表里这个数只是个直观的例子，样本不多。"
               "第五，它没有利润和分红，没法算估值，所以只能看价格本身。最后它全年不停地交易，适合交给程序。"
               "这几条合起来，就是我们选趋势跟踪、按波动率定仓位的原因。")

    # 3 文献
    page += 1
    s = k.blank(prs)
    k.title(s, "文献里的证据")
    k.text_box(s, k.MARGIN, Inches(1.65), Inches(12.1), Inches(4.2), [
        "**商品期货**：过去一年涨的，接下来还容易涨，一百多年的数据都是这样（Moskowitz 等 2012；Hurst 等 2017）",
        "**加密货币**：动量效应很强（Liu & Tsyvinski 2021，RFS）；用均线能明显减少比特币的回撤（Detzel 等 2021）",
        "**我们复现的论文**：多个周期的通道突破，再按波动率定仓位，扣完手续费夏普还在 1.5 以上（Zarattini、Pagani & Barbon 2025）",
        "**反例**：抄底类的规则 2022 年以后就不灵了（Quantpedia 2024）；很多技术指标换一段数据就失效（Hudson & Urquhart 2021）",
        "**要小心**：策略发表以后，收益平均会少一半以上（McLean & Pontiff 2016，JF）",
    ], size=17, spacing=12)
    k.callout(s, k.MARGIN, Inches(5.75), Inches(12.1), Inches(0.9),
              "我们想知道：这篇论文的参数一个不改，在它发表后的 19 个月里还灵不灵？")
    k.footer(s, page, "文献详见项目 docs/2026-10-20-策略文献调研.md")
    k.notes(s, "趋势跟踪在高波动的资产上证据最多。商品期货有一百多年的数据，加密货币上 2021 年 RFS 的论文也证实了动量很强。"
               "我们复现的是 2025 年 Zarattini 等人的论文。不过也有反例，抄底类的规则近几年就不灵了。"
               "还有一点要注意：McLean 和 Pontiff 发现，策略一发表，收益平均会少一半以上。"
               "所以我们最关心的，是这篇论文发表之后它还灵不灵。")

    # 4 策略一：论文复现
    page += 1
    s = k.blank(prs)
    k.title(s, "策略一：论文复现（TrendEnsemble）")
    w, gap, top, h = Inches(3.85), Inches(0.28), Inches(1.65), Inches(3.6)
    k.panel(s, k.MARGIN, top, w, h, "什么时候买",
            ["一共 9 个回看期，从 5 天到 360 天",
             "收盘价创出这段时间的新高，就买入一份",
             "9 份各管各的"])
    k.panel(s, k.MARGIN + w + gap, top, w, h, "什么时候卖",
            ["止损线是这段时间最高价和最低价的中间",
             "止损线只往上挪，不往下挪",
             "收盘跌破止损线，就卖掉这一份"])
    k.panel(s, k.MARGIN + 2 * (w + gap), top, w, h, "买多少",
            ["每份仓位 = 25% ÷ 最近 90 天的年化波动率，最多 2 倍",
             "9 份取平均，现货不加杠杆，最多 100%",
             "BTC、ETH 各分一半钱"])
    k.text_box(s, k.MARGIN, Inches(5.55), Inches(12.1), Inches(1.2), [
        "每天收盘后算信号，第二天开盘成交；每天把仓位调到目标，差不到 5% 就不动，省手续费",
        ("参数全部照抄论文，没有在我们的数据上调过", {"color": k.ACCENT, "bold": True}),
    ], size=15, spacing=8)
    k.footer(s, page, SOURCE)
    k.notes(s, "规则分三块。什么时候买：有 9 个长短不同的回看期，收盘价创出这段时间的新高，就买一份。"
               "什么时候卖：止损线放在这段时间最高价和最低价的中间，只往上挪，跌破就卖。"
               "买多少：波动越大买得越少。参数全是论文里的，我们一个都没改。")

    # 5 策略二：机器学习
    page += 1
    s = k.blank(prs)
    k.title(s, "策略二：机器学习（MLXGBoost）")
    k.text_box(s, k.MARGIN, Inches(1.65), Inches(7.3), Inches(4.9), [
        "**模型**：Freqtrade 自带的 FreqAI + XGBoost，做法参照 Bysik & Ślepaczuk (2026)",
        "**预测什么**：未来 24 小时的平均涨幅，用 1 小时 K 线",
        "**看什么**：58 个简单特征，比如不同周期的涨跌幅、波动率、离最近高点低点有多远、成交量、几点钟、星期几，还有另一个币的同类特征",
        "**怎么训练**：每周用过去 365 天的数据重新训练一次，所以每次预测的都是模型没见过的行情",
        "**什么时候买**：预测涨幅超过一买一卖总成本的 2 倍（0.6%）才买；预测转负就卖",
        "**买多少**：25% ÷ 年化波动率，最多用到这个币的一半资金",
    ], size=16, spacing=11)
    k.panel(s, Inches(8.25), Inches(1.75), Inches(4.45), Inches(3.3), "为什么这样设计",
            ["Jaquart 等 (2021)：预测周期太短，手续费会把收益吃光",
             "Cakici 等 (2024)：模型再复杂，提升也不大",
             "门槛和训练窗口事先定好，不看结果再改"], size=15)
    k.footer(s, page, SOURCE)
    k.notes(s, "第二个策略换个思路：不写死规则，让 XGBoost 从 58 个简单特征里自己学，预测未来 24 小时会涨多少。"
               "它每周只用过去一年的数据重新训练，所以每一次预测都是对没见过的行情做的。"
               "另外只有预测涨幅超过两倍成本才买，免得被手续费吃掉。")

    # 6 策略三：调参版
    page += 1
    s = k.blank(prs)
    k.title(s, "策略三：调参版（TrendTuned）")
    k.table(s, k.MARGIN, Inches(1.65), Inches(7.6), [
        ["参数", "论文", "调参后", "试过的范围"],
        ["目标波动率", "25%", pct(tuned_params["vol_target"], 0), "10% 到 100%"],
        ["算波动率用几天", "90 天", f"{tuned_params['vol_window']} 天", "30 到 180 天"],
        ["回看期", "5–360 天，9 个", f"{lbs[0]}–{lbs[-1]} 天，{len(lbs)} 个", "长度 ×0.5 到 ×1.25，最短的可去掉 0–4 个"],
        ["止损线位置", "中间（50%）", f"{tuned_params['stop_frac']:.0%}", "30% 到 70%"],
    ], col_widths=[1.8, 2.0, 2.0, 2.8], size=14, row_height=0.62)
    k.text_box(s, k.MARGIN, Inches(4.95), Inches(7.6), Inches(1.2), [
        ("规则一点没变，只改了论文里的几个数字", {"color": k.ACCENT, "bold": True}),
        "调出来的结果：回看期更短，止损更早，仓位更重",
    ], size=16, spacing=8)
    k.panel(s, Inches(8.55), Inches(1.65), Inches(4.2), Inches(3.75), "怎么调的",
            ["用 Freqtrade 自带的 hyperopt，试了 500 组参数",
             "只用 2019-05 到 2025-03 的数据，也就是论文的样本期",
             "目标：最大回撤不超过 20%，年化收益越高越好",
             "2025-03 以后的数据调参时一点没碰，留着检验"], size=15)
    k.footer(s, page, SOURCE)
    k.notes(s, "第三个策略是我们自己加的。规则和论文完全一样，只是把论文里的几个数字交给 Freqtrade 的 hyperopt 去调，"
               f"一共试了 500 组。调出来的结果是：回看期整体缩短一半、去掉最短的两个，止损线提高到 {tuned_params['stop_frac']:.0%} 的位置，"
               f"也就是更早卖；目标波动率从 25% 提到 {pct(tuned_params['vol_target'], 0)}，也就是仓位更重。我们给它定的目标是：最大回撤不超过 20%，在这个前提下年化收益越高越好。"
               "关键是我们只拿论文样本期的数据去调，2025 年 3 月以后的行情调参时完全没碰，"
               "这样才能看出调出来的参数是真有用，还是只是把历史背下来了。")

    # 7 检验方法
    page += 1
    s = k.blank(prs)
    k.title(s, "怎么保证结果可信")
    fee_hi = fee.iloc[-1]
    checked = [look[n] for n in ("trend", "ml", "tuned") if n in look]
    signals_ok = all(r["biased_entry_signals"] == 0 and r["biased_exit_signals"] == 0 for r in checked)
    look_text = (f"{len(checked)} 个策略各抽查 {int(checked[0]['total_signals'])} 笔交易，买卖点全部一致" if signals_ok
                 else "发现偏差，见稳健性那页")
    k.table(s, k.MARGIN, Inches(1.6), Inches(12.1), [
        ["检验", "怎么做", "结果"],
        ["1 算手续费", "每边 0.15%；另外测了 0、0.25%、0.5%",
         f"论文原版：成本翻 3 倍多，年化还有 {pct(fee_hi['年化收益'])}；机器学习：扣完手续费由赚变亏"],
        ["2 不偷看未来", "用 Freqtrade 的 lookahead-analysis：把后面的数据截掉重跑，逐笔比对", look_text],
        ["3 和一直持有比", "持有 BTC、ETH、各一半，外加“同等仓位持有”",
         f"仓位一样的情况下，论文原版年化 {pct(t_full['年化收益'])}，持有 {pct(s_full['年化收益'])}"],
        ["4 调参和检验分开", "以论文样本截止日 2025-03-15 为界；调参版只用之前的数据调；机器学习每周滚动训练",
         "2025-03 以后的结果，三个策略都没见过"],
    ], col_widths=[2.0, 5.0, 5.1], size=14, row_height=0.8, left_cols=(0, 1, 2))
    recon_text = "、".join(f"{label} {recon[key]:.2f}%" for key, label in
                          (("trend", "论文原版"), ("ml", "机器学习"), ("tuned", "调参版")) if key in recon)
    k.text_box(s, k.MARGIN, Inches(5.95), Inches(12.1), Inches(0.8), [
        f"另外：自己用逐笔订单重算净值，和 Freqtrade 账户记录逐日对比，最大差异 {recon_text}",
    ], size=14, color=k.MUTED)
    k.footer(s, page, SOURCE)
    k.notes(s, "为了让结果可信，我们做了四件事。第一，手续费按每边 0.15% 算，还试了不收费和更贵的情况。"
               "第二，用 Freqtrade 自带的工具查有没有偷看未来：把后面的数据截掉重跑，逐笔比对买卖点。"
               "第三，不只和一直持有比，还和一个仓位一样大的持有组合比，这样风险是对齐的。"
               "第四，调参和检验用不同的时间段，2025 年 3 月以后的行情三个策略都没见过。")

    # 8 全区间收益
    page += 1
    s = k.blank(prs)
    k.title(s, "全区间收益")
    k.image(s, RES / "equity_curves.png", k.MARGIN, Inches(1.5), width=Inches(9.0))
    k.text_box(s, k.MARGIN, Inches(5.85), Inches(9.0), Inches(0.8),
               [(f"蓝色虚线和论文原版仓位一样（{pct(avg_exp, 0)}），论文原版每年比它多赚约 "
                 f"{(t_full['年化收益'] - s_full['年化收益']) * 100:.0f} 个点", {"bold": True, "color": k.ACCENT})], size=16)
    k.panel(s, Inches(9.85), Inches(1.6), Inches(2.9), Inches(4.25), "数字",
            [f"论文原版：年化 **{pct(t_full['年化收益'])}**，最多亏 **{pct(-t_full['最大回撤'])}**",
             f"各半持有：年化 {pct(h_full['年化收益'])}，最多亏 {pct(-h_full['最大回撤'])}",
             f"论文原版平均只用了 **{pct(avg_exp, 0)}** 的钱",
             f"只放 {pct(avg_exp, 0)} 在币上一直拿着：年化 {pct(s_full['年化收益'])}",
             ("橙线是机器学习，后面单独讲", {"color": k.MUTED})], size=15)
    k.footer(s, page, SOURCE)
    k.notes(s, f"先看全区间。一直持有赚得最多，这没什么好说的，但它中间最多亏过 {pct(-h_full['最大回撤'], 0)}，"
               "一般人很难拿得住。论文原版平均只用了 "
               f"{pct(avg_exp, 0)} 的钱，所以拿它和满仓持有比不公平。我们加了一条虚线，同样只放 {pct(avg_exp, 0)} 在币上一直拿着，"
               f"它的年化是 {pct(s_full['年化收益'])}，论文原版是 {pct(t_full['年化收益'])}。最下面的橙线是机器学习，扣完手续费是亏的，后面单独说。")

    # 9 收益和风险
    page += 1
    s = k.blank(prs)
    k.title(s, "收益和风险")
    k.image(s, RES / "risk_return.png", k.MARGIN, Inches(1.5), height=Inches(5.3))
    rows = [["", "年化收益", "年化波动", "夏普", "最大回撤"]]
    for n in (TREND, ML, SAME, HOLD, BTC):
        r = metrics[(n, "全区间")]
        label = f"同等仓位（{pct(avg_exp, 0)}）" if n == SAME else SHORT.get(n, n)
        rows.append([label, pct(r["年化收益"]), pct(r["年化波动"]), f"{r['夏普']:.2f}", pct(r["最大回撤"])])
    k.table(s, Inches(8.0), Inches(1.75), Inches(4.75), rows, col_widths=[2.3, 1.3, 1.3, 1.0, 1.3],
            size=12, row_height=0.6)
    k.footer(s, page, SOURCE)
    k.notes(s, "这张图横轴是最大回撤，越往左越安全；纵轴是年化收益。一直持有在右上角，赚得多，但风险也大得多。"
               "论文原版在左边。和仓位一样大的持有组合比，它在差不多的风险下赚得更多，夏普也更高。"
               "机器学习在零线下面，扣完手续费是亏的。")

    # 10 论文发表后的表现
    page += 1
    s = k.blank(prs)
    k.title(s, "论文发表后的表现")
    k.image(s, RES / "post_paper.png", k.MARGIN, Inches(1.5), width=Inches(9.0))
    k.text_box(s, k.MARGIN, Inches(5.6), Inches(9.0), Inches(0.9),
               [("一直持有像坐过山车；论文原版几乎是一条平线，但和同等仓位持有（浅蓝）差不多重合",
                 {"bold": True, "color": k.ACCENT})], size=16)
    k.text_box(s, Inches(9.75), Inches(1.6), Inches(3.0), Inches(0.5),
               [("2025-03 以后", {"bold": True, "color": k.ACCENT})], size=18)
    rows = [["", "总收益", "最大回撤"]]
    for n, label in ((TREND, "论文原版"), (SAME, "同等仓位"), (BTC, "持有 BTC"), (ML, "机器学习")):
        r = metrics[(n, "论文发表后")]
        rows.append([label, pct(r["总收益"], sign=True), pct(r["最大回撤"])])
    k.table(s, Inches(9.75), Inches(2.2), Inches(3.0), rows, col_widths=[1.2, 0.9, 0.9], size=13,
            row_height=0.5)
    k.text_box(s, Inches(9.75), Inches(4.85), Inches(3.0), Inches(1.2),
               ["回撤还是小", "但没比同等仓位持有多赚", "符合“发表后收益缩水”"], size=14, spacing=2)
    k.footer(s, page, SOURCE)
    k.notes(s, "这页是我们最想让大家看的。论文写完的时候，后面这段行情它是没见过的，算是一场真正的考试。"
               f"这 19 个月比特币先涨后跌，一直拿着最多亏过 {pct(-b_post['最大回撤'], 0)}。"
               f"论文原版赚了 {pct(t_post['总收益'])}，最多只亏了 {pct(-t_post['最大回撤'], 0)}，稳是真的稳；"
               "但和同等仓位的持有组合比，基本打平，没有多赚。这跟 McLean 和 Pontiff 说的一样，"
               "策略一公开，多赚的那部分往往就缩水了。当然 19 个月还不算长，我们也不敢把话说死。")

    # 11 调参版：样本内 vs 样本外
    page += 1
    s = k.blank(prs)
    k.title(s, "调参版：样本内 vs 样本外")
    k.image(s, RES / "tuned.png", k.MARGIN, Inches(1.5), width=Inches(9.0))
    rows = [["", "样本内", "样本外"],
            ["调参版 年化", pct(u_in["年化收益"]), pct(u_post["年化收益"])],
            ["调参版 最大回撤", pct(u_in["最大回撤"]), pct(u_post["最大回撤"])],
            ["论文原版 年化", pct(t_in["年化收益"]), pct(t_post["年化收益"])],
            ["同等仓位 年化", pct(us_in["年化收益"]), pct(us_post["年化收益"])]]
    k.table(s, Inches(9.75), Inches(1.6), Inches(3.0), rows, col_widths=[1.6, 0.9, 0.9], size=12,
            row_height=0.55)
    k.text_box(s, Inches(9.75), Inches(4.5), Inches(3.0), Inches(1.8), tuned_verdict, size=14, spacing=4)
    k.footer(s, page, SOURCE)
    k.notes(s, tuned_notes)

    # 12 2022 年熊市
    page += 1
    s = k.blank(prs)
    k.title(s, "2022 年熊市里的仓位")
    k.image(s, RES / "trend_exposure.png", k.MARGIN, Inches(1.5), width=Inches(9.0))
    k.panel(s, Inches(9.85), Inches(1.6), Inches(2.9), Inches(4.25), "看点",
            ["涨的时候一点点加仓，跌破止损就撤",
             "2022 年几乎一直空仓或者轻仓",
             f"平均仓位 {pct(avg_exp, 0)}，最高 {pct(exposure.loc[TREND, '最高仓位'], 0)}",
             "代价是牛市里也只吃到一部分涨幅"], size=15)
    k.footer(s, page, SOURCE)
    k.notes(s, "回撤为什么小，看这张图就明白了。下面是论文原版在 BTC 上的仓位。涨的时候仓位一点点加上去，"
               "趋势一破就撤。2022 年比特币跌了七成多，它几乎一直在场外。代价是牛市里也只吃到一部分涨幅。")

    # 13 机器学习：手续费的影响
    page += 1
    s = k.blank(prs)
    k.title(s, "机器学习：手续费的影响")
    k.image(s, RES / "ml_costs.png", k.MARGIN, Inches(1.5), width=Inches(8.2))
    k.text_box(s, k.MARGIN, Inches(5.15), Inches(8.2), Inches(1.7), [
        (f"同样的买卖信号，不算手续费赚 {pct(g_full['总收益'], 0)}，算上手续费亏 {pct(-m_full['总收益'], 0)}",
         {"bold": True, "color": k.ACCENT, "size": 16}),
        f"一年交易 {c_m['每年交易笔数']:.0f} 笔，平均只拿 {c_m['平均持仓天数']:.1f} 天；"
        f"7.5 年手续费一共 {c_m['手续费合计']:,.0f} USDT，相当于本金的 {c_m['手续费合计'] / 10000:.0%}",
        "和 Jaquart 等 (2021) 一样：扣费前赚，扣费后亏",
        "Bysik 等 (2026) 说加了成本门槛就能赚，我们照着做了，没能复现",
    ], size=14, spacing=6)
    rows = [["", "论文原版", "机器学习"],
            ["每年交易", f"{c_t['每年交易笔数']:.0f} 笔", f"{c_m['每年交易笔数']:.0f} 笔"],
            ["平均持仓", f"{c_t['平均持仓天数']:.0f} 天", f"{c_m['平均持仓天数']:.1f} 天"],
            ["胜率", pct(c_t["计成本胜率"], 0), pct(c_m["计成本胜率"], 0)],
            ["不计成本年化", pct(c_t["不计成本年化"]), pct(c_m["不计成本年化"])],
            ["计成本年化", pct(c_t["计成本年化"]), pct(c_m["计成本年化"])],
            ["**成本每年吃掉**", f"**{c_t['成本每年吃掉'] * 100:.1f} 个点", f"**{c_m['成本每年吃掉'] * 100:.1f} 个点"]]
    k.table(s, Inches(9.1), Inches(1.75), Inches(3.65), rows, col_widths=[1.55, 1.05, 1.05], size=13,
            row_height=0.56)
    k.text_box(s, Inches(9.1), Inches(5.85), Inches(3.65), Inches(0.8),
               [("胜率高不代表赚钱：论文原版靠少数几笔大赚，机器学习每笔赚得太少", {"color": k.MUTED})], size=12)
    k.footer(s, page, SOURCE)
    k.notes(s, f"机器学习的结果挺有意思。虚线是不算手续费的净值，赚了 {pct(g_full['总收益'], 0)}；"
               f"实线是同样的买卖信号扣掉手续费，亏了 {pct(-m_full['总收益'], 0)}。"
               f"它一年交易 {c_m['每年交易笔数']:.0f} 笔，平均只拿 {c_m['平均持仓天数']:.1f} 天，"
               f"手续费一年就吃掉 {c_m['成本每年吃掉'] * 100:.0f} 个百分点；论文原版一年只交易 {c_t['每年交易笔数']:.0f} 笔，"
               "手续费一年还不到 1 个点。所以模型不是完全没用，它是有一点预测能力的，只是每笔赚得太少，付不起手续费。")

    # 14 稳健性检验
    page += 1
    s = k.blank(prs)
    k.title(s, "稳健性检验")
    rows = [["每边成本", "年化收益", "夏普", "最大回撤"]]
    for _, r in fee.iterrows():
        label = "0（不计成本）" if r["单边成本"] == 0 else pct(r["单边成本"], 2)
        rows.append([label, pct(r["年化收益"]), f"{r['夏普']:.2f}", pct(r["最大回撤"])])
    k.table(s, k.MARGIN, Inches(1.65), Inches(6.0), rows, col_widths=[1.8, 1.4, 1.1, 1.4], size=15,
            row_height=0.62)
    k.text_box(s, k.MARGIN, Inches(4.9), Inches(6.0), Inches(0.9),
               [("表里是论文原版 2019-05 至 2026-10 的结果", {"color": k.MUTED})], size=12)
    k.text_box(s, Inches(7.0), Inches(1.65), Inches(5.75), Inches(5.0), [
        f"**手续费**：成本从 0 提到 0.5%，年化只从 {pct(fee.iloc[0]['年化收益'])} 降到 {pct(fee_hi['年化收益'])}",
        "**偷看未来**：三个策略各抽查 20 笔交易，截断重跑，买卖点都一致",
        "**机器学习的“有差异”**：逐行查过，只是浮点误差，加上截断处最后一根 K 线没出预测",
        "**预热长度**：用 460 根和 999 根 K 线预热，结果完全一样",
        "**训练不越界**：机器学习每次训练都会丢掉最后 24 根 K 线，因为它们的答案要用到之后的价格",
        "**净值核对**：自己用逐笔订单重算的净值和 Freqtrade 的账户记录对得上",
    ], size=14, spacing=10)
    k.footer(s, page, SOURCE)
    k.notes(s, "再补充几项检查。论文原版的手续费从 0 提到 0.5%，年化只少两三个点，结论不变。"
               "Freqtrade 自带的检查工具没有发现买卖点受未来数据影响。机器学习被工具标了有差异，"
               "我们一行一行查过，一是小数点后第 14 位的浮点误差，二是截断重跑时最后一根 K 线没有预测，"
               "其他每一行的预测和信号都完全一样。我们还自己用逐笔订单重算了净值，和 Freqtrade 的记录逐日对得上。")

    # 15 结论和下一步
    page += 1
    s = k.blank(prs)
    k.title(s, "结论和下一步")
    k.text_box(s, k.MARGIN, Inches(1.6), Inches(7.0), Inches(5.2), [
        ("结论", {"bold": True, "color": k.ACCENT, "size": 19}),
        f"1. 论文原版在 2019 到 2025 年是有效的：仓位一样的情况下，年化 {pct(t_in['年化收益'])}，持有只有 {pct(s_in['年化收益'])}",
        f"2. 论文发表后：最多只亏 {pct(-t_post['最大回撤'])}，还是很稳；但没比持有多赚",
        f"3. 机器学习：不算手续费年化 {pct(g_full['年化收益'])}，算上手续费 {pct(m_full['年化收益'])}，交易太勤，钱都给了手续费",
        tuned_conclusion,
    ], size=16, spacing=12)
    k.panel(s, Inches(7.9), Inches(1.7), Inches(4.85), Inches(3.6), "下一步",
            ["资金费过滤：过热时降仓（BIS 2023）",
             "机器学习：预测更长的周期，少交易",
             "用永续合约做空，熊市也能赚",
             "扩到论文里的 20 个币",
             "在 Freqtrade 模拟盘上实时跑，和回测对比"], size=15)
    k.footer(s, page, SOURCE)
    k.notes(s, "总结一下。论文原版在它的样本期里确实有效；发表以后还是很稳，但没比持有多赚。"
               "机器学习有一点预测能力，可是交易太勤，手续费把收益吃光了。" + tuned_conclusion_notes +
               "下一步我们想加资金费过滤、让机器学习少交易、试试做空、扩到更多币，并且放到模拟盘上实时跑。谢谢大家。")

    # 16 附录：特征重要性
    page += 1
    s = k.blank(prs)
    k.title(s, "附录：机器学习看重哪些特征")
    k.image(s, RES / "ml_feature_importance.png", k.MARGIN, Inches(1.5), width=Inches(8.2))
    k.panel(s, Inches(9.1), Inches(1.6), Inches(3.65), Inches(4.5), "看点",
            ["最有用的是变化慢的：离最近 7 天、30 天高低点有多远，还有波动率，和论文规则用的是同一类信息",
             "1 到 4 小时的涨跌幅、成交量几乎没用，各占 0.5% 左右",
             "另一个币的特征占了一半：BTC 和 ETH 一起涨跌",
             "**有用的信息变得慢，它却交易得快**，所以被手续费吃掉"], size=14)
    k.footer(s, page, "780 个滚动训练的模型（390 周 × 2 个币）平均下来的特征重要性，按信息增益算")
    k.notes(s, "这页备用。780 个模型平均下来，最重要的是离最近 7 天、30 天高低点有多远，还有波动率，"
               "和论文规则用的是同一类信息；1 到 4 小时的短期特征几乎没用。模型能用的信息变化很慢，"
               "它却按小时进进出出，这就是手续费吃掉收益的原因。")

    out = RES / "展示_v2.pptx"
    prs.save(out)
    print("saved", out)


if __name__ == "__main__":
    main()
