"""
调参目标：每日市值净值的最大回撤不超过 20% 的前提下，年化收益越高越好。

Freqtrade 自带的回撤按已平仓交易算；TrendTuned 一笔交易要拿几十天、中途还会加减仓，
那样算会低估回撤。所以这里和 scripts/report.py 一样，用逐笔订单 + 每日收盘价重建市值净值。
"""

from datetime import datetime

import numpy as np
import pandas as pd
from pandas import DataFrame

from freqtrade.optimize.hyperopt import IHyperOptLoss

MAX_DRAWDOWN = 0.20
PENALTY = 5.0  # 回撤每超 1 个百分点，相当于年化少 5 个百分点


def daily_equity(results: DataFrame, processed: dict, starting_balance: float) -> pd.Series:
    closes = pd.DataFrame({pair: df.set_index("date")["close"] for pair, df in processed.items()}).sort_index()
    events = []
    for _, trade in results.iterrows():
        for order in trade["orders"]:
            is_buy = order["ft_order_side"] == "buy"
            qty = float(order["amount"])
            events.append((
                pd.Timestamp(order["order_filled_timestamp"], unit="ms", tz="UTC"),
                trade["pair"], qty if is_buy else -qty, float(order["safe_price"]),
                trade["fee_open"] if is_buy else trade["fee_close"],
            ))
    events.sort(key=lambda e: e[0])

    cash = starting_balance
    holdings = dict.fromkeys(closes.columns, 0.0)
    values = np.empty(len(closes))
    i = 0
    for k, day in enumerate(closes.index):
        day_end = day + pd.Timedelta(days=1)
        while i < len(events) and events[i][0] < day_end:
            _, pair, qty, price, fee = events[i]
            value = abs(qty) * price
            cash += -value * (1 + fee) if qty > 0 else value * (1 - fee)
            holdings[pair] += qty
            i += 1
        values[k] = cash + sum(holdings[p] * closes.at[day, p] for p in closes.columns)
    return pd.Series(values, index=closes.index)


class CappedDrawdownReturnLoss(IHyperOptLoss):
    @staticmethod
    def hyperopt_loss_function(
        results: DataFrame,
        min_date: datetime,
        max_date: datetime,
        processed: dict[str, DataFrame],
        starting_balance: float,
        *args,
        **kwargs,
    ) -> float:
        if results.empty:
            return 100.0
        equity = daily_equity(results, processed, starting_balance)
        years = (equity.index[-1] - equity.index[0]).days / 365
        cagr = (equity.iloc[-1] / starting_balance) ** (1 / years) - 1
        mdd = -(equity / equity.cummax() - 1).min()
        return -cagr + PENALTY * max(0.0, mdd - MAX_DRAWDOWN)
