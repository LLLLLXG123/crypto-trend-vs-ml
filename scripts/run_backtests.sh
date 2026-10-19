#!/usr/bin/env bash
# 跑全部回测，并把每次结果另存为 user_data/backtest_results/named/<名字>.zip
# 用法（WSL，项目根目录）：bash scripts/run_backtests.sh [trend|ml|all]
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
  for fee in 0.0015 0.0025 0.005; do
    ft backtesting -c user_data/config_trend.json --userdir user_data --strategy TrendEnsemble \
      --timerange "$TREND_RANGE" --fee "$fee" --export trades --cache none
    save_as "trend_fee${fee}"
  done
}

run_ml() {
  ft backtesting -c user_data/config_ml.json --userdir user_data --strategy MLXGBoost \
    --freqaimodel XGBoostRegressor --timerange "$ML_RANGE" --fee 0.0015 --export trades --cache none
  save_as "ml_fee0.0015"
}

case "${1:-all}" in
  trend) run_trend ;;
  ml) run_ml ;;
  all) run_trend; run_ml ;;
esac
