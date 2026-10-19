"""
MLXGBoost：机器学习备份策略（FreqAI + XGBoost）
参照 Bysik & Ślepaczuk (2026)，arXiv 2606.00060：BTC 1 小时数据、XGBoost、滚动训练、成本过滤、只做多。

- 标签：未来 24 根 K 线平均收盘价相对当前收盘价的涨幅（FreqAI 示例里的 &-s_close 写法）。
- 特征：多周期涨跌幅、波动率、离区间高低点的距离、量比、小时和星期；BTC 与 ETH 互为相关币种。
- 训练：用过去 365 天训练，每 7 天重训一次（见 config_ml.json 的 freqai 段）。
- 交易：模型判断可预测（do_predict == 1），并且预测涨幅超过“成本门槛”时买入；预测 < 0 时卖出。
  成本门槛 = 一买一卖总成本 0.3% × COST_MULTIPLE。
- 仓位：min(0.25 / σ, 1) × 该币的一半资金，σ 为近 90 天的年化波动率。
"""

from datetime import datetime

import numpy as np
from pandas import DataFrame

from freqtrade.strategy import IStrategy, merge_informative_pair


class MLXGBoost(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1h"
    can_short = False

    minimal_roi = {"0": 100.0}
    stoploss = -0.99
    use_exit_signal = True
    exit_profit_only = False
    process_only_new_candles = True

    # 720 小时区间特征 + 余量（OKX 的 1 小时预热上限是 1499 根，所以 90 天波动率改用日线算）
    startup_candle_count = 800

    ROUND_TRIP_COST = 0.003
    COST_MULTIPLE = 2.0
    VOL_TARGET = 0.25
    SLEEVE = 0.5

    def feature_engineering_expand_all(
        self, dataframe: DataFrame, period: int, metadata: dict, **kwargs
    ) -> DataFrame:
        close = dataframe["close"]
        dataframe["%-ret-period"] = close.pct_change(period)
        dataframe["%-vol-period"] = np.log(close).diff().rolling(period).std()
        dataframe["%-dist_high-period"] = close / close.rolling(period).max() - 1
        dataframe["%-dist_low-period"] = close / close.rolling(period).min() - 1
        dataframe["%-volume_ratio-period"] = (
            dataframe["volume"] / dataframe["volume"].rolling(period).mean()
        )
        return dataframe

    def feature_engineering_expand_basic(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        close = dataframe["close"]
        dataframe["%-ret_1h"] = close.pct_change()
        dataframe["%-dist_high_720h"] = close / close.rolling(720).max() - 1
        dataframe["%-dist_low_720h"] = close / close.rolling(720).min() - 1
        return dataframe

    def feature_engineering_standard(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        dataframe["%-hour_of_day"] = dataframe["date"].dt.hour
        dataframe["%-day_of_week"] = dataframe["date"].dt.dayofweek
        return dataframe

    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        horizon = self.freqai_info["feature_parameters"]["label_period_candles"]
        dataframe["&-s_close"] = (
            dataframe["close"].shift(-horizon).rolling(horizon).mean() / dataframe["close"] - 1
        )
        return dataframe

    def informative_pairs(self):
        return [(pair, "1d") for pair in self.dp.current_whitelist()]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = self.freqai.start(dataframe, metadata, self)
        # 仓位用的 σ：近 90 天日对数收益的年化标准差；日线收盘后才可用（merge 时自动错开一天）
        daily = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe="1d")
        daily["sigma"] = np.log(daily["close"]).diff().rolling(90).std() * np.sqrt(365)
        dataframe = merge_informative_pair(
            dataframe, daily[["date", "sigma"]], self.timeframe, "1d", ffill=True
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        threshold = self.ROUND_TRIP_COST * self.COST_MULTIPLE
        dataframe.loc[
            (dataframe["do_predict"] == 1)
            & (dataframe["&-s_close"] > threshold)
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "ml_long")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["&-s_close"] < 0, ["exit_long", "exit_tag"]] = (1, "ml_negative")
        return dataframe

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
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        sigma = dataframe["sigma_1d"].iat[-1] if not dataframe.empty else np.nan
        if not np.isfinite(sigma) or sigma <= 0:
            return 0
        weight = min(self.VOL_TARGET / sigma, 1.0)
        desired = self.wallets.get_total_stake_amount() * self.SLEEVE * weight
        if min_stake and desired < min_stake:
            return 0
        return min(desired, max_stake)
