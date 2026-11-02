"""python -m backtest.run [--skip-fetch]"""
import argparse
import datetime as dt
import json
import os
import sys

import pandas as pd

from backtest import fetch_13f, fetch_ptr, metrics, report, strategies
from backtest.prices import PriceStore
from vendor import edgar13f as e13

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_json(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return json.load(fh)


def run_backtest(events, ptr_trades, store, cfg):
    spy = store.get("SPY")
    if spy is None:
        raise SystemExit("No SPY prices: nothing to compare against, stopping.")
    market_end = spy.index[-1]
    trades = pd.concat([
        strategies.copycat_trades(events, store, market_end, cfg["copycat_fallback_days"]),
        strategies.congress_trades(ptr_trades, store, market_end, tuple(cfg["holds"]),
                                   cfg["sale_max_days"]),
    ], ignore_index=True)
    trades = metrics.add_returns(trades, spy)
    overall = metrics.summarize(trades, ["strategy", "variant"])
    by_source = metrics.summarize(trades, ["strategy", "variant", "source"])
    books, curves = metrics.book_stats(trades, store, spy)
    return trades, overall, by_source, books, curves


def fetch_all(cfg, data_dir, log):
    ua = e13.user_agent(None, config_path=None)
    if not ua:
        raise SystemExit("Set SEC_USER_AGENT to 'Your Name you@example.com' (SEC requires it).")
    fetcher = fetch_13f.CachedFetcher(os.path.join(data_dir, "sec"), ua=ua, pause=0.12)
    index = e13.ticker_index(fetcher)
    overrides = e13.load_overrides([e13.CLASSES])
    events = fetch_13f.build_events(fetcher, e13.load_filers(), cfg["start"], cfg["top_n"],
                                    index, overrides, os.environ.get("OPENFIGI_API_KEY"), log)
    ptr_trades = fetch_ptr.build_trades(load_json("members.json")["members"],
                                        int(cfg["start"][:4]), dt.date.today().year,
                                        os.path.join(data_dir, "ptr"), log)
    return events, ptr_trades


def main(argv=None):
    ap = argparse.ArgumentParser(description="Backtest the trader-skill copycat and congress strategies.")
    ap.add_argument("--skip-fetch", action="store_true",
                    help="reuse data/events_13f.csv and data/trades_ptr.csv")
    args = ap.parse_args(argv)
    cfg = load_json("config.json")
    data_dir = os.path.join(ROOT, cfg["data_dir"])
    os.makedirs(data_dir, exist_ok=True)
    events_path = os.path.join(data_dir, "events_13f.csv")
    ptr_path = os.path.join(data_dir, "trades_ptr.csv")
    errors = []

    def log(msg):
        errors.append(msg)
        print(msg, file=sys.stderr)

    if not args.skip_fetch:
        events, ptr_trades = fetch_all(cfg, data_dir, log)
        events.to_csv(events_path, index=False)
        ptr_trades.to_csv(ptr_path, index=False)
    events = pd.read_csv(events_path, dtype={"cik": str, "ticker": str}, keep_default_na=False)
    ptr_trades = pd.read_csv(ptr_path, dtype=str, keep_default_na=False)

    store = PriceStore(os.path.join(data_dir, "prices"), start=cfg["start"], log=log)
    trades, overall, by_source, books, curves = run_backtest(events, ptr_trades, store, cfg)
    generated = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report.write_report(os.path.join(ROOT, cfg["reports_dir"]), trades, overall, by_source,
                        books, curves, errors, generated)
    print(overall.to_string(index=False))


if __name__ == "__main__":
    main()
