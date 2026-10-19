"""
TrendEnsemble：复现 Zarattini, Pagani & Barbon (2025)
"Catching Crypto Trends: A Tactical Approach for Bitcoin and Altcoins"（SSRN 5209907）

规则（日线，现货只做多）：
- 9 个回看期 L ∈ {5, 10, 20, 30, 60, 90, 150, 250, 360}，每个 L 是一个子信号。
- 开仓：子信号空仓，并且当日收盘价高于前 L 日的最高收盘价。
- 止损：开仓时取近 L 日（含当日）最高与最低收盘价的中点；之后每天更新为
  max(昨日止损, 当日中点)；收盘价跌破止损就平掉这个子信号。
- 仓位：每个子信号权重 = min(0.25 / σ, 2)，σ 为近 90 日对数收益的年化标准差（×√365）。
  9 个子信号等权平均得到目标敞口；现货不能加杠杆，所以封顶 1。
- 资金：两个币各占一半。每天把实际仓位调到目标值，偏差小于该币资金的 5% 不调。
"""

from datetime import datetime

import numpy as np
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy


def run_channel(close: np.ndarray, prev_max: np.ndarray, mid: np.ndarray) -> np.ndarray:
    """单个回看期的持仓状态（1 持有 / 0 空仓）。止损只升不降，所以必须逐日递推。"""
    state = np.zeros(len(close))
    in_position = False
    stop = np.nan
    for i in range(len(close)):
        if in_position:
            stop = max(stop, mid[i])
            if close[i] < stop:
                in_position = False
        elif not np.isnan(prev_max[i]) and close[i] > prev_max[i]:
            in_position = True
            stop = mid[i]
        state[i] = 1.0 if in_position else 0.0
    return state


class TrendEnsemble(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    can_short = False

    # 出场完全由信号决定：关掉 ROI 和固定止损
    minimal_roi = {"0": 100.0}
    stoploss = -0.99
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = True
    process_only_new_candles = True

    position_adjustment_enable = True
    max_entry_position_adjustment = -1

    LOOKBACKS = (5, 10, 20, 30, 60, 90, 150, 250, 360)
    VOL_TARGET = 0.25
    VOL_WINDOW = 90
    MAX_SUB_WEIGHT = 2.0  # 论文允许的单个子信号杠杆上限
    MAX_EXPOSURE = 1.0  # 现货不加杠杆
    SLEEVE = 0.5  # 两个币各占一半资金
    REBALANCE_BAND = 0.05

    # 360 日回看 + 90 日波动率 + 余量
    startup_candle_count = 460

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"]
        log_ret = np.log(close).diff()
        dataframe["sigma"] = log_ret.rolling(self.VOL_WINDOW).std() * np.sqrt(365)
        sub_weight = (self.VOL_TARGET / dataframe["sigma"]).clip(upper=self.MAX_SUB_WEIGHT)

        close_arr = close.to_numpy(dtype=float)
        states = []
        for lookback in self.LOOKBACKS:
            prev_max = close.shift(1).rolling(lookback).max().to_numpy()
            mid = ((close.rolling(lookback).max() + close.rolling(lookback).min()) / 2).to_numpy()
            state = run_channel(close_arr, prev_max, mid)
            dataframe[f"state_{lookback}"] = state
            states.append(state)

        # 处于持仓状态的子信号占比；各子信号权重相同，所以平均权重 = 占比 × 权重
        dataframe["active"] = np.vstack(states).mean(axis=0)
        dataframe["target"] = (dataframe["active"] * sub_weight).clip(upper=self.MAX_EXPOSURE)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["target"] > 0) & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "trend")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["active"] == 0, ["exit_long", "exit_tag"]] = (1, "all_stops_hit")
        return dataframe

    def _latest(self, pair: str, column: str) -> float | None:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return None
        value = dataframe[column].iat[-1]
        return float(value) if np.isfinite(value) else None

    def _equity(self, pair: str, current_rate: float) -> float:
        """按市价估算的总资产：空闲资金 + 所有持仓的市值。"""
        total = self.wallets.get_free(self.config["stake_currency"])
        for trade in Trade.get_trades_proxy(is_open=True):
            rate = current_rate if trade.pair == pair else self._latest(trade.pair, "close")
            total += trade.amount * (rate or trade.open_rate)
        return total

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
        leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        target = self._latest(pair, "target")
        if not target:
            return 0
        desired = self._equity(pair, current_rate) * self.SLEEVE * target
        if min_stake and desired < min_stake:
            return 0
        return min(desired, max_stake)

    def adjust_trade_position(
        self,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        min_stake: float | None,
        max_stake: float,
        current_entry_rate: float,
        current_exit_rate: float,
        current_entry_profit: float,
        current_exit_profit: float,
        **kwargs,
    ) -> float | None | tuple[float | None, str | None]:
        if trade.has_open_orders:
            return None
        target = self._latest(trade.pair, "target")
        if not target:  # 目标为 0 时交给出场信号整笔平仓
            return None

        sleeve = self._equity(trade.pair, current_rate) * self.SLEEVE
        current_value = trade.amount * current_rate
        diff = sleeve * target - current_value
        if abs(diff) < self.REBALANCE_BAND * sleeve:
            return None
        if min_stake and abs(diff) < min_stake:
            return None

        if diff > 0:
            return min(diff, max_stake), "rebalance_up"
        # 减仓：Freqtrade 按 trade.stake_amount 的比例折算卖出数量
        fraction = min(-diff / current_value, 0.99)
        return -trade.stake_amount * fraction, "rebalance_down"
