"""
TrendTuned：TrendEnsemble 的调参版，用 Freqtrade hyperopt 调论文里的几个参数。

只在论文样本期（2019-05 至 2025-03-14）上调，之后的行情留作检验。规则结构和 TrendEnsemble
完全一样，可调的是：
- vol_target：目标波动率（论文 25%）
- vol_window：算波动率的天数（论文 90）
- lb_scale：9 个回看期整体放大或缩小的倍数（论文 1，即 5…360 天）
- drop_short：去掉最短的几个回看期（论文 0）
- stop_frac：止损线在区间最低到最高之间的位置（论文 0.5，即中点）

hyperopt 只在开始时跑一次 populate_indicators，所以这里把所有候选值的子信号都先算好，
populate_entry_trend 里再按本轮参数挑出来合成目标敞口。
"""

import numpy as np
import pandas as pd
from pandas import DataFrame

from freqtrade.strategy import CategoricalParameter, DecimalParameter, IntParameter

from TrendEnsemble import TrendEnsemble, run_channel

LB_SCALES = (0.5, 0.75, 1.0, 1.25)  # 最长 450 天，预热 460 根够用
STOP_FRACS = (0.3, 0.4, 0.5, 0.6, 0.7)
VOL_WINDOWS = (30, 60, 90, 120, 180)


def scaled(lookback: int, scale: float) -> int:
    return max(2, round(lookback * scale))


class TrendTuned(TrendEnsemble):
    vol_target = DecimalParameter(0.10, 1.00, decimals=2, default=0.25, space="buy")
    vol_window = CategoricalParameter(VOL_WINDOWS, default=90, space="buy")
    lb_scale = CategoricalParameter(LB_SCALES, default=1.0, space="buy")
    drop_short = IntParameter(0, 4, default=0, space="buy")
    stop_frac = CategoricalParameter(STOP_FRACS, default=0.5, space="buy")

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close = dataframe["close"]
        close_arr = close.to_numpy(dtype=float)
        log_ret = np.log(close).diff()
        cols = {}
        for window in VOL_WINDOWS:
            cols[f"sigma_{window}"] = log_ret.rolling(window).std() * np.sqrt(365)
        for scale in LB_SCALES:
            for lookback in self.LOOKBACKS:
                n = scaled(lookback, scale)
                prev_max = close.shift(1).rolling(n).max().to_numpy()
                hi = close.rolling(n).max()
                lo = close.rolling(n).min()
                for frac in STOP_FRACS:
                    stop_line = (lo + frac * (hi - lo)).to_numpy()
                    cols[f"state_{scale}_{lookback}_{frac}"] = run_channel(close_arr, prev_max, stop_line)
        return pd.concat([dataframe, DataFrame(cols, index=dataframe.index)], axis=1)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        scale, frac = self.lb_scale.value, self.stop_frac.value
        lookbacks = self.LOOKBACKS[self.drop_short.value:]
        states = dataframe[[f"state_{scale}_{lb}_{frac}" for lb in lookbacks]]
        sub_weight = (self.vol_target.value / dataframe[f"sigma_{self.vol_window.value}"]).clip(
            upper=self.MAX_SUB_WEIGHT
        )
        dataframe["active"] = states.mean(axis=1)
        dataframe["target"] = (dataframe["active"] * sub_weight).clip(upper=self.MAX_EXPOSURE)
        return super().populate_entry_trend(dataframe, metadata)
