"""Per-trade returns against SPY, summaries and daily equity curves."""
import numpy as np
import pandas as pd

PRICED = ("ok", "open")
SUMMARY_COLUMNS = ["trades", "win_abs_pct", "win_spy_pct", "mean_ret_pct", "median_ret_pct",
                   "mean_excess_pct", "open", "no_price"]
BOOK_COLUMNS = ["strategy", "variant", "start", "end", "cagr_pct", "spy_cagr_pct",
                "max_dd_pct", "spy_max_dd_pct"]


def add_returns(trades, spy):
    t = trades.copy()
    entry = pd.to_numeric(t["entry_px"], errors="coerce")
    exit_ = pd.to_numeric(t["exit_px"], errors="coerce")
    priced = t["status"].isin(PRICED)
    t["ret"] = np.where(priced, exit_ / entry - 1.0, np.nan)
    spy_ret = []
    for row in t.itertuples():
        if row.status in PRICED:
            a = spy.asof(pd.Timestamp(row.entry_date))
            b = spy.asof(pd.Timestamp(row.exit_date))
            spy_ret.append(b / a - 1.0)
        else:
            spy_ret.append(np.nan)
    t["spy_ret"] = np.array(spy_ret, dtype="float64")
    t["excess"] = t["ret"] - t["spy_ret"]
    t["win_abs"] = t["ret"] > 0
    t["win_spy"] = t["ret"] > t["spy_ret"]
    return t


def summarize(trades, keys):
    rows = []
    for key, g in trades.groupby(keys, sort=True):
        key = key if isinstance(key, tuple) else (key,)
        closed = g[g["status"] == "ok"]
        n = len(closed)
        rows.append({**dict(zip(keys, key)),
                     "trades": n,
                     "win_abs_pct": 100.0 * closed["win_abs"].mean() if n else np.nan,
                     "win_spy_pct": 100.0 * closed["win_spy"].mean() if n else np.nan,
                     "mean_ret_pct": 100.0 * closed["ret"].mean() if n else np.nan,
                     "median_ret_pct": 100.0 * closed["ret"].median() if n else np.nan,
                     "mean_excess_pct": 100.0 * closed["excess"].mean() if n else np.nan,
                     "open": int((g["status"] == "open").sum()),
                     "no_price": int((g["status"] == "no_price").sum())})
    return pd.DataFrame(rows, columns=list(keys) + SUMMARY_COLUMNS)


def daily_equity(trades, store, calendar):
    """Weighted mean of the daily returns of every position held that day; cash at 0 %
    when nothing is held. A trade earns the days after its entry up to its exit."""
    t = trades[trades["status"].isin(PRICED)]
    if t.empty:
        return None
    start = pd.Timestamp(t["entry_date"].min())
    end = pd.Timestamp(t["exit_date"].max())
    cal = calendar[(calendar >= start) & (calendar <= end)]
    if len(cal) == 0:
        return None
    num = np.zeros(len(cal))
    den = np.zeros(len(cal))
    daily = {}
    for row in t.itertuples():
        if row.ticker not in daily:
            s = store.get(row.ticker)
            daily[row.ticker] = (s.reindex(s.index.union(cal)).ffill().reindex(cal)
                                 .pct_change(fill_method=None)
                                 .fillna(0.0).to_numpy())
        i0 = cal.searchsorted(pd.Timestamp(row.entry_date), side="right")
        i1 = cal.searchsorted(pd.Timestamp(row.exit_date), side="right")
        num[i0:i1] += row.weight * daily[row.ticker][i0:i1]
        den[i0:i1] += row.weight
    ret = np.divide(num, den, out=np.zeros_like(num), where=den > 0)
    return pd.Series(np.cumprod(1.0 + ret), index=cal)


def cagr(equity):
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    if years <= 0:
        return np.nan
    return (equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0


def max_drawdown(equity):
    return float((equity / equity.cummax() - 1.0).min())


def book_stats(trades, store, spy):
    out, curves = [], {}
    for (strategy, variant), g in trades.groupby(["strategy", "variant"], sort=True):
        eq = daily_equity(g, store, spy.index)
        if eq is None or len(eq) < 2:
            continue
        bench = spy[(spy.index >= eq.index[0]) & (spy.index <= eq.index[-1])]
        bench = bench / bench.iloc[0]
        out.append({"strategy": strategy, "variant": variant,
                    "start": eq.index[0].date().isoformat(),
                    "end": eq.index[-1].date().isoformat(),
                    "cagr_pct": 100.0 * cagr(eq), "spy_cagr_pct": 100.0 * cagr(bench),
                    "max_dd_pct": 100.0 * max_drawdown(eq),
                    "spy_max_dd_pct": 100.0 * max_drawdown(bench)})
        curves["%s/%s" % (strategy, variant)] = eq
    return pd.DataFrame(out, columns=BOOK_COLUMNS), curves
