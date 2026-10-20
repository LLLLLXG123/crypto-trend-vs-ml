#!/usr/bin/env bash
# 跑全部回测，并把每次结果另存为 user_data/backtest_results/named/<名字>.zip
# 用法（WSL，项目根目录）：bash scripts/run_backtests.sh [trend|ml|all|check]
# check：偷看未来和预热长度的检查，结果写到 results/
set -euo pipefail

PY=/mnt/e/miniconda/envs/freqtrade/python.exe
RES=user_data/backtest_results
TREND_RANGE=${TREND_RANGE:-20190501-20261019}
ML_RANGE=${ML_RANGE:-20190501-20261019}
mkdir -p "$RES/named"

ft() { "$PY" -X utf8 -m freqtrade "$@"; }

save_as() {
  local latest
  latest=$(python3 -c "import json;print(json.load(open('$RES/.last_result.json'))['latest_backtest'])")
  cp "$RES/$latest" "$RES/named/$1.zip"
  echo "saved $RES/named/$1.zip"
}

run_trend() {
  for fee in 0 0.0015 0.0025 0.005; do
    ft backtesting -c user_data/config_trend.json --userdir user_data --strategy TrendEnsemble \
      --timerange "$TREND_RANGE" --fee "$fee" --export trades --cache none
    save_as "trend_fee${fee}"
  done
}

run_ml() {
  # 第二遍成本为 0：直接读第一遍保存的预测，信号完全相同，用来看手续费吃掉了多少
  for fee in 0.0015 0; do
    ft backtesting -c user_data/config_ml.json --userdir user_data --strategy MLXGBoost \
      --freqaimodel XGBoostRegressor --timerange "$ML_RANGE" --fee "$fee" --export trades --cache none
    save_as "ml_fee${fee}"
  done
}

run_checks() {
  # 导出文件已存在时，Freqtrade 2026.9 会去更新旧行，在新版 pandas 下报错，所以先删掉
  rm -f results/lookahead_trend.csv results/lookahead_ml.csv results/lookahead_ml_diag.jsonl
  ft lookahead-analysis -c user_data/config_trend.json --userdir user_data --strategy TrendEnsemble \
    --timerange "$TREND_RANGE" --fee 0.0015 --lookahead-analysis-exportfilename results/lookahead_trend.csv
  ft recursive-analysis -c user_data/config_trend.json --userdir user_data --strategy TrendEnsemble \
    --timerange 20240101-20261019 --startup-candle 460 999
  # 机器学习每次截断重跑都要重新训练，所以只取两个月。配置用单独的 identifier，
  # 因为 lookahead-analysis 会删掉同名的模型目录。诊断包装逐列记录差异，见 scripts/lookahead_diag.py
  "$PY" -X utf8 scripts/lookahead_diag.py results/lookahead_ml_diag.jsonl lookahead-analysis \
    -c user_data/config_ml_lookahead.json --userdir user_data --strategy MLXGBoost \
    --freqaimodel XGBoostRegressor --timerange 20250601-20250801 --fee 0.0015 \
    --lookahead-analysis-exportfilename results/lookahead_ml.csv
}

case "${1:-all}" in
  trend) run_trend ;;
  ml) run_ml ;;
  all) run_trend; run_ml ;;
  check) run_checks ;;
esac
