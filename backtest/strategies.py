"""Signals -> trades with entry and exit prices. No lookahead: entry is the first
close strictly after the day the signal became public."""
import pandas as pd

TRADE_COLUMNS = ["strategy", "variant", "source", "ticker", "signal_date", "entry_date",
                 "entry_px", "exit_date", "exit_px", "weight", "status", "note"]


def first_after(series, day):
    i = series.index.searchsorted(pd.Timestamp(day), side="right")
    return None if i >= len(series) else (series.index[i], float(series.iloc[i]))


def first_on_or_after(series, day):
    i = series.index.searchsorted(pd.Timestamp(day), side="left")
    return None if i >= len(series) else (series.index[i], float(series.iloc[i]))


def _iso(ts):
    return ts.date().isoformat()


def price_trade(series, signal_date, exit_rule, market_end):
    out = {"entry_date": None, "entry_px": None, "exit_date": None, "exit_px": None,
           "status": "no_price", "note": ""}
    if series is None or len(series) == 0:
        return out
    last_ts, last_px = series.index[-1], float(series.iloc[-1])
    entry = first_after(series, signal_date)
    if entry is None:
        if last_ts >= market_end:
            out["status"] = "pending"
        return out
    out["entry_date"], out["entry_px"] = _iso(entry[0]), entry[1]
    kind, target = exit_rule(entry[0])
    finder = first_after if kind == "after" else first_on_or_after
    exit_ = finder(series, target)
    if exit_ is None:
        out["exit_date"], out["exit_px"] = _iso(last_ts), last_px
        if last_ts >= market_end:
            out["status"] = "open"
        else:
            out["status"], out["note"] = "ok", "last_available"
        return out
    out["exit_date"], out["exit_px"], out["status"] = _iso(exit_[0]), exit_[1], "ok"
    return out


def _ticker(value):
    return value.strip() if isinstance(value, str) else ""


def copycat_trades(events, store, market_end, fallback_days=120):
    rows = []
    for fund, g in events.groupby("fund"):
        dates = sorted(g["filed"].unique())
        for i, filed in enumerate(dates):
            if i + 1 < len(dates):
                rule = lambda e, d=dates[i + 1]: ("after", d)
            else:
                rule = lambda e, d=filed: ("on_or_after",
                                           pd.Timestamp(d) + pd.Timedelta(days=fallback_days))
            for ev in g[g["filed"] == filed].itertuples():
                ticker = _ticker(ev.ticker)
                priced = price_trade(store.get(ticker) if ticker else None, filed, rule, market_end)
                for variant, weight in (("equal", ev.weight_equal), ("fund", ev.weight_fund)):
                    rows.append({"strategy": "copycat", "variant": variant, "source": fund,
                                 "ticker": ticker, "signal_date": filed,
                                 "weight": float(weight), **priced})
    return pd.DataFrame(rows, columns=TRADE_COLUMNS)


def congress_trades(ptr_trades, store, market_end, holds=(30, 90, 180), sale_max_days=365):
    rows = []
    if ptr_trades.empty:
        return pd.DataFrame(rows, columns=TRADE_COLUMNS)
    sells = ptr_trades[ptr_trades["side"] == "sell"]
    for b in ptr_trades[ptr_trades["side"] == "buy"].itertuples():
        ticker = _ticker(b.ticker)
        series = store.get(ticker) if ticker else None
        rules = {"hold%d" % n: (lambda e, n=n: ("on_or_after", e + pd.Timedelta(days=n)))
                 for n in holds}
        limit = (pd.Timestamp(b.filed) + pd.Timedelta(days=sale_max_days)).date().isoformat()
        later = sells[(sells["member"] == b.member) & (sells["ticker"] == b.ticker)
                      & (sells["filed"] > b.filed) & (sells["filed"] <= limit)]
        if len(later):
            rules["until_sale"] = lambda e, d=later["filed"].min(): ("after", d)
        else:
            rules["until_sale"] = lambda e: ("on_or_after", e + pd.Timedelta(days=sale_max_days))
        for variant, rule in rules.items():
            rows.append({"strategy": "congress", "variant": variant, "source": b.member,
                         "ticker": ticker, "signal_date": b.filed, "weight": 1.0,
                         **price_trade(series, b.filed, rule, market_end)})
    return pd.DataFrame(rows, columns=TRADE_COLUMNS)
