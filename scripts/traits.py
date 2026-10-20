"""
数字货币和股票指数的对比数字，给 PPT 的“数字货币的特点”那页用。

用法（项目根目录，用装了 akshare 的环境，例如 conda 环境 securities）：
    python -X utf8 scripts/traits.py

指数日线第一次从 akshare（新浪）下载，存到 results/index_daily.csv，之后直接读缓存。
输出 results/traits.csv（各资产指标）和 results/traits.json（动量、相关性等补充数字）。
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "user_data" / "data" / "okx"
OUT = ROOT / "results"
START, END = "2019-05-02", "2026-10-18"  # 和回测区间一致
INDEX_CACHE = OUT / "index_daily.csv"


def load_crypto() -> dict[str, pd.Series]:
    out = {}
    for coin in ("BTC", "ETH"):
        df = pd.read_feather(DATA / f"{coin}_USDT-1d.feather")
        s = df.set_index("date")["close"]
        s.index = s.index.tz_localize(None)
        out[coin] = s
    return out


def load_indices() -> dict[str, pd.Series]:
    if not INDEX_CACHE.exists():
        import akshare as ak

        csi = ak.stock_zh_index_daily(symbol="sh000300").set_index("date")["close"]
        spx = ak.index_us_stock_sina(symbol=".INX").set_index("date")["close"]
        pd.DataFrame({"沪深300": csi, "标普500": spx}).to_csv(INDEX_CACHE, encoding="utf-8-sig")
    df = pd.read_csv(INDEX_CACHE, index_col=0, parse_dates=True)
    return {name: df[name].dropna() for name in df.columns}


def stats(close: pd.Series) -> dict:
    c = close.loc[START:END]
    r = np.log(c).diff().dropna()
    per_year = len(r) / ((c.index[-1] - c.index[0]).days / 365)
    simple = c.pct_change().dropna()
    return {
        "每年交易天数": per_year,
        "年化波动": r.std() * np.sqrt(per_year),
        "最大回撤": (c / c.cummax() - 1).min(),
        "单日涨跌超5%占比": (simple.abs() > 0.05).mean(),
        "单日最大跌幅": simple.min(),
        "超额峰度": r.kurt(),
    }


def momentum(close: pd.Series, days: int = 30) -> dict:
    """不重叠的 30 天区间：上一段涨了 / 跌了，下一段的平均收益。只作描述。"""
    c = close.loc[START:END].iloc[::days]
    r = c.pct_change().dropna()
    prev, nxt = r.shift(1).dropna(), r.iloc[1:]
    return {
        "上段涨后下段平均": float(nxt[prev > 0].mean()),
        "上段跌后下段平均": float(nxt[prev <= 0].mean()),
        "样本段数": int(len(nxt)),
        "相邻两段收益相关": float(np.corrcoef(prev, nxt)[0, 1]),
    }


def main():
    series = {**load_crypto(), **load_indices()}
    table = pd.DataFrame({name: stats(s) for name, s in series.items()}).T
    table.index.name = "资产"
    table.to_csv(OUT / "traits.csv", encoding="utf-8-sig")
    print(table.round(4))

    btc, eth = series["BTC"].loc[START:END], series["ETH"].loc[START:END]
    extra = {
        "BTC_ETH日收益相关": float(np.log(btc).diff().corr(np.log(eth).diff())),
        "BTC动量30天": momentum(series["BTC"]),
        "ETH动量30天": momentum(series["ETH"]),
        "BTC_2018起最大回撤": float((series["BTC"] / series["BTC"].cummax() - 1).min()),
    }
    (OUT / "traits.json").write_text(json.dumps(extra, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(extra, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
