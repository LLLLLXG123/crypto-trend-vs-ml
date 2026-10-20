"""TrendTuned 平台版：TrendEnsemble 换成 hyperopt 在样本内（2019-05 到 2025-03）调出的参数。

参数来自 user_data/strategies/TrendTuned.json，规则和下面的论文原版完全一样。

原规则：复现 Zarattini, Pagani & Barbon (2025)
"Catching Crypto Trends: A Tactical Approach for Bitcoin and Altcoins"（SSRN 5209907）

和 Freqtrade 版（user_data/strategies/TrendEnsemble.py）是同一套规则，改成了 QuantLab 的写法：
- 9 个回看期 L，每个是一个子信号。子信号空仓、收盘价高于前 L 日最高收盘价就开仓。
- 止损：近 L 日（含当日）最高与最低收盘价之间的某一点（stop_frac=0.5 就是中点），只升不降，
  收盘跌破就平掉这个子信号。
- 仓位：每个子信号权重 min(vol_target / σ, 2)，σ 为近 vol_window 日对数收益的年化标准差（×√365）；
  持仓子信号占比 × 权重 = 目标敞口，现货封顶 1。
- 资金：两个币各占一半。实际仓位和目标差不到该币资金的 5% 就不调。

调参版（TrendTuned）只是换一组 PARAMS：
    vol_target=0.55, vol_window=90, lb_scale=0.5, drop_short=2, stop_frac=0.7

回测设置：周期 1d；标的 BTC/USDT、ETH/USDT；预热 460 根（360 日回看 + 90 日波动率 + 余量）。
"""

import math

PARAMS = {
    "vol_target": 0.55,  # 目标年化波动（原版 0.25）
    "vol_window": 90,  # 波动率窗口（天）
    "lb_scale": 0.5,  # 回看期整体缩放（原版 1.0）
    "drop_short": 2,  # 去掉最短的几个回看期（原版 0）
    "stop_frac": 0.7,  # 止损在通道里的位置（原版 0.5 = 中点）
    "max_sub_weight": 2.0,  # 单个子信号权重上限
    "sleeve": 0.5,  # 每个币占的资金比例
    "band": 0.05,  # 调仓容差（占该币资金）
}

LOOKBACKS = (5, 10, 20, 30, 60, 90, 150, 250, 360)


def lookbacks():
    scale = PARAMS["lb_scale"]
    return [max(2, round(lb * scale)) for lb in LOOKBACKS[int(PARAMS["drop_short"]) :]]


def step(state, closes, lookback):
    """把一个子信号推进一根 bar。state = [是否持仓, 止损价]，closes 截至当前（最后一个是当前收盘）。"""
    if len(closes) < lookback + 1:
        return
    window = closes[-lookback:]
    lo = min(window)
    stop_now = lo + PARAMS["stop_frac"] * (max(window) - lo)
    if state[0]:
        state[1] = max(state[1], stop_now)
        if closes[-1] < state[1]:
            state[0] = False
    elif closes[-1] > max(closes[-lookback - 1 : -1]):
        state[0] = True
        state[1] = stop_now


def sigma(closes, window):
    """近 window 日对数收益的年化标准差（样本标准差，和 pandas rolling().std() 一致）。"""
    if len(closes) < window + 1:
        return None
    rets = [math.log(b / a) for a, b in zip(closes[-window - 1 : -1], closes[-window:])]
    mean = sum(rets) / window
    var = sum((r - mean) ** 2 for r in rets) / (window - 1)
    return math.sqrt(var) * math.sqrt(365) if var > 0 else None


def initialize(ctx):
    set_benchmark(ctx.securities[0])
    g.states = {}  # {标的: [[是否持仓, 止损价], ...]}，每个回看期一个
    run_daily(rebalance, time="every_bar")


def rebalance(ctx):
    lbs = lookbacks()
    need = max(max(lbs), int(PARAMS["vol_window"])) + 1
    orders = []
    for s in ctx.securities:
        if s not in g.states:
            # 第一次调用：把预热期的 K 线从头递推一遍，和 Freqtrade 在整段数据上逐日递推一致
            g.states[s] = [[False, 0.0] for _ in lbs]
            closes = history(s, 5000)
            for i in range(1, len(closes) + 1):
                for st, lb in zip(g.states[s], lbs):
                    step(st, closes[max(0, i - lb - 1) : i], lb)
            closes = closes[-need:]
        else:
            closes = history(s, need)
            for st, lb in zip(g.states[s], lbs):
                step(st, closes, lb)

        active = sum(1 for st in g.states[s] if st[0]) / len(lbs)
        vol = sigma(closes, int(PARAMS["vol_window"]))
        if vol is None:
            continue
        target = min(active * min(PARAMS["vol_target"] / vol, PARAMS["max_sub_weight"]), 1.0)
        coin = s.split("/")[0].lower()
        record(**{f"{coin}_target": target})

        equity = ctx.total_value
        held = ctx.position(s).value
        sleeve = equity * PARAMS["sleeve"]
        want = sleeve * target
        if held > 0 and active == 0:
            orders.append((-held, s, 0.0, "all_stops_hit"))
        elif held <= 0 and target > 0:
            orders.append((want, s, PARAMS["sleeve"] * target, "trend"))
        elif held > 0 and abs(want - held) >= PARAMS["band"] * sleeve:
            reason = "rebalance_up" if want > held else "rebalance_down"
            orders.append((want - held, s, PARAMS["sleeve"] * target, reason))

    # 先卖后买，腾出现金
    for _, s, weight, reason in sorted(orders):
        order_target_percent(s, weight, reason=reason)


def snapshot(ctx):
    # 实时模拟写检查点时保存子信号状态，崩溃恢复后接着递推
    return {"states": g.states}


def restore(ctx, state):
    g.states = state["states"]
