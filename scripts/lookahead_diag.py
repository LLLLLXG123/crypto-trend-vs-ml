"""
lookahead-analysis 的诊断包装：比较指标时逐列记录真实差异（排除两边都是 NaN 的格子），
每次比对写一行 JSON，说明差在哪几行、差多少。

Freqtrade 自带的比较只打印第一处差异，还把两边都是 NaN 的格子当成不相等，
看不出差异到底在哪、有多大；FreqAI 策略容易因此被标成 has_bias。用法（项目根目录）：
    python -X utf8 scripts/lookahead_diag.py results/lookahead_ml_diag.jsonl lookahead-analysis \\
        -c user_data/config_ml_lookahead.json --userdir user_data --strategy MLXGBoost \\
        --freqaimodel XGBoostRegressor --timerange 20250601-20250801 --fee 0.0015
"""
import json
import sys

import numpy as np
import pandas as pd

import freqtrade.optimize.analysis.lookahead as la

OUT = sys.argv[1]
orig = la.LookaheadAnalysis.analyze_indicators


def patched(self, full_vars, cut_vars, current_pair):
    cut_df = cut_vars.indicators[current_pair]
    full_df = full_vars.indicators[current_pair].loc[cut_df.index]
    report = {"pair": current_pair, "cut_to": str(cut_vars.to_dt), "rows": len(cut_df), "cols": {}}
    for col in cut_df.columns:
        a, b = full_df[col], cut_df[col]
        both_nan = a.isna() & b.isna()
        one_nan = a.isna() ^ b.isna()
        neq = ~both_nan & ~(a == b)
        if not neq.any():
            continue
        info = {"n_diff": int(neq.sum()), "n_one_nan": int(one_nan.sum())}
        dates = cut_df.loc[neq, "date"]
        info["first"], info["last"] = str(dates.iloc[0]), str(dates.iloc[-1])
        if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
            both = neq & ~one_nan
            if both.any():
                d = (a[both] - b[both]).abs()
                info["max_abs"] = float(d.max())
                info["max_rel"] = float((d / b[both].abs().replace(0, np.nan)).max())
        if one_nan.any():
            info["one_nan_examples"] = [
                (str(cut_df.loc[i, "date"]), repr(a.loc[i]), repr(b.loc[i])) for i in cut_df.index[one_nan][:3]
            ]
        report["cols"][col] = info
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(report, ensure_ascii=False) + "\n")
    return orig(self, full_vars, cut_vars, current_pair)


la.LookaheadAnalysis.analyze_indicators = patched

from freqtrade.main import main  # noqa: E402

main(sys.argv[2:])
