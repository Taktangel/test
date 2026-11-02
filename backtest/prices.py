"""Daily adjusted close prices with a disk cache. Yahoo first, stooq as a fallback."""
import io
import json
import os
import time
import urllib.error
import urllib.request

import pandas as pd

UA = "Mozilla/5.0 (trader-backtest)"
YAHOO = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
         "?period1=%d&period2=%d&interval=1d&events=div%%2Csplit&includeAdjustedClose=true")
STOOQ = "https://stooq.com/q/d/l/?s=%s&i=d"


def yahoo_symbol(ticker):
    return ticker.strip().upper().replace(".", "-").replace("/", "-")


def _clean(s):
    s = s.dropna()
    s = s[s > 0]
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s if not s.empty else None


def parse_yahoo(data):
    try:
        res = data["chart"]["result"][0]
        ts = res["timestamp"]
        ind = res["indicators"]
        closes = ind["adjclose"][0]["adjclose"] if ind.get("adjclose") else ind["quote"][0]["close"]
        if not isinstance(ts, list):
            raise TypeError("timestamp is not a list")
        idx = pd.to_datetime(ts, unit="s").normalize()
        return _clean(pd.Series(closes, index=idx, dtype="float64"))
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def parse_stooq(text):
    try:
        df = pd.read_csv(io.StringIO(text))
    except (ValueError, pd.errors.ParserError):
        return None
    if "Date" not in df.columns or "Close" not in df.columns:
        return None
    s = pd.Series(pd.to_numeric(df["Close"], errors="coerce").values,
                  index=pd.to_datetime(df["Date"], errors="coerce"))
    return _clean(s[s.index.notna()])


def _http(url, timeout=30, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        if i < tries - 1:
            time.sleep(2 * (i + 1))
    return None


def fetch_yahoo(symbol, start):
    p1 = int(pd.Timestamp(start).timestamp())
    p2 = int(time.time()) + 86400
    raw = _http(YAHOO % (symbol, p1, p2))
    if raw is None:
        return None
    try:
        return parse_yahoo(json.loads(raw.decode("utf-8")))
    except ValueError:
        return None


def fetch_stooq(symbol, start):
    raw = _http(STOOQ % (symbol.lower() + ".us"))
    if raw is None:
        return None
    s = parse_stooq(raw.decode("utf-8", "replace"))
    if s is None:
        return None
    return _clean(s[s.index >= pd.Timestamp(start)])


class PriceStore:
    """get(ticker) -> adjusted closes, cached as data/prices/<SYMBOL>.csv."""

    def __init__(self, cache_dir, start="2014-01-01", fetchers=None, max_age_hours=20, log=None):
        self.cache_dir = cache_dir
        self.start = start
        self.fetchers = [fetch_yahoo, fetch_stooq] if fetchers is None else fetchers
        self.max_age = max_age_hours * 3600
        self._log = log if log is not None else (lambda msg: None)
        self._mem = {}
        os.makedirs(cache_dir, exist_ok=True)

    def _path(self, symbol):
        return os.path.join(self.cache_dir, symbol + ".csv")

    def _read_cache(self, symbol, any_age=False):
        path = self._path(symbol)
        if not os.path.isfile(path):
            return None
        stale = time.time() - os.path.getmtime(path) > self.max_age
        if self.fetchers and stale and not any_age:
            return None
        try:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            return _clean(df["close"].astype(float))
        except (pd.errors.EmptyDataError, pd.errors.ParserError, KeyError, ValueError):
            return None

    def get(self, ticker):
        if not isinstance(ticker, str) or not ticker.strip():
            return None
        symbol = yahoo_symbol(ticker)
        if symbol in self._mem:
            return self._mem[symbol]
        s = self._read_cache(symbol)
        if s is None:
            for fetch in self.fetchers:
                s = fetch(symbol, self.start)
                if s is not None and not s.empty:
                    path = self._path(symbol)
                    s.rename("close").to_csv(path + ".tmp", index_label="date")
                    os.replace(path + ".tmp", path)
                    break
                self._log("prices %s: %s returned no data"
                          % (symbol, getattr(fetch, "__name__", repr(fetch))))
                s = None
            if s is None:
                # Sources down this time: an old cached copy beats no prices at all.
                s = self._read_cache(symbol, any_age=True)
                if s is not None:
                    self._log("prices %s: sources failed, using stale cache" % symbol)
                else:
                    self._log("prices %s: no prices" % symbol)
        self._mem[symbol] = s
        return s
