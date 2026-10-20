# 论文复刻VS机器学习？——BTC、ETH 现货策略回测

课堂作业：在 [Freqtrade](https://github.com/freqtrade/freqtrade) 里开发并回测三个加密货币现货策略，再把两个规则策略接入 [QuantLab](https://github.com/NagisaShip/quantlab) 平台重跑一遍。仅用于课程研究，不构成投资建议。

数据：OKX 现货 BTC/USDT、ETH/USDT，回测区间 2019-05 至 2026-10，每边成本 0.15%。论文样本截止 2025-03-15，之后的行情当作样本外。

## 三个策略

| 策略 | 做法 |
|---|---|
| 趋势追踪（TrendEnsemble） | 复现 Zarattini, Pagani & Barbon (2025)，参数一个没改。9 个回看期（5 到 360 天），收盘价创新高就买一份；止损线在通道中间，只升不降，收盘跌破就卖。每份仓位 = 25% ÷ 近 90 天年化波动率，9 份取平均，不加杠杆；BTC、ETH 各一半资金。日线，只做多 |
| 机器学习（MLXGBoost） | FreqAI + XGBoost，1 小时 K 线、58 个简单特征，预测未来 24 小时平均涨幅；超过两倍成本（0.6%）才买，预测转负就卖；每周用过去一年的数据重训 |
| 调参版（TrendTuned） | 规则同趋势追踪，参数用 hyperopt 试了 500 组，只用 2025-03-15 以前的数据调 |

## 主要结论

1. 趋势追踪在论文样本期有效：年化 19.8%，同等仓位一直持有只有 12.3%。
2. 论文发表后它还是很稳，最多只亏 14.3%，但没比同等仓位持有多赚。
3. 机器学习不算手续费年化 7.2%，算上手续费 -5.8%，交易太勤，钱都给了手续费。
4. 调参版样本内年化 42.2%，样本外只有 6.4%，纸面上漂亮的曲线靠不住。
5. 两个规则策略换到 QuantLab 上重跑，结论一样：

| | QuantLab | Freqtrade |
|---|---|---|
| 趋势追踪 全区间年化 | 15.7% | 16.0% |
| 趋势追踪 最大回撤 | -15.8% | -16.8% |
| 趋势追踪 年化：发表前 → 后 | 19.5% → 2.7% | 19.8% → 3.1% |
| 调参版 全区间年化 | 34.0% | 33.6% |
| 调参版 年化：样本内 → 样本外 | 42.6% → 6.3% | 42.2% → 6.4% |
| 交易笔数（趋势追踪 / 调参版） | 148 / 161 | 150 / 162 |

## 目录

| 路径 | 内容 |
|---|---|
| `results/展示_v2_手改.pptx` | 汇报 PPT 最终版（17 页）；`展示.pptx`、`展示_v2.pptx` 是脚本生成的早期版本 |
| `results/演讲稿.txt` | 汇报讲稿 |
| `results/*.png`、`*.csv` | PPT 里的图，以及数字的出处（分段指标、手续费敏感性、交易统计、未来数据检查等） |
| `user_data/strategies/` | 三个 Freqtrade 策略；`TrendTuned.json` 是调出来的参数 |
| `user_data/hyperopts/` | 调参目标：最大回撤不超过 20%，年化越高越好 |
| `user_data/config_*.json` | 回测配置（交易所密钥留空） |
| `quantlab/` | 接入 QuantLab 的趋势追踪和调参版 |
| `scripts/` | 回测（`run_backtests.sh`）、出指标和图（`report.py`）、生成 PPT（`make_ppt.py`）等脚本 |
| `docs/` | 文献调研、设计与实现记录、QuantLab 接入步骤 |

行情数据和 Freqtrade 的原始回测结果没有上传，按下面的命令可以重新生成。

## 怎么运行

### Freqtrade（2026.9）

```bash
freqtrade download-data -c user_data/config_trend.json --userdir user_data -t 1d 1h --timerange 20180101-
freqtrade backtesting -c user_data/config_trend.json --userdir user_data --strategy TrendEnsemble --timerange 20190501-20261019 --fee 0.0015
freqtrade backtesting -c user_data/config_trend.json --userdir user_data --strategy TrendTuned --timerange 20190501-20261019 --fee 0.0015
freqtrade backtesting -c user_data/config_ml.json --userdir user_data --strategy MLXGBoost --freqaimodel XGBoostRegressor --timerange 20190501-20261019 --fee 0.0015
```

全部回测、调参和未来数据检查在 `scripts/run_backtests.sh` 里，跑完再用 `python -X utf8 scripts/report.py` 出指标和图。脚本开头的 Python 路径要换成自己的。

### QuantLab

1. 启动平台前设置 `QAGENT_SANDBOX_MEMORY_MB=4096`，否则多核电脑上回测可能报 MemoryError。
2. 新建策略：周期 1d，标的池 `BTC/USDT,ETH/USDT`，把 `quantlab/` 里文件的内容粘贴进编辑器。
3. 回测设置：2019-05-01 至 2026-10-19，初始资金 10000，只用真实行情，交易所 OKX，手续费 0.15%，滑点 0，价差 0，预热 460 根，下一根开盘成交。

详细步骤见 `docs/2026-10-20-QuantLab接入步骤.md`。
