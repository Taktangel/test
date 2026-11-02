import os

import pandas as pd

from backtest import prices
from helpers import series


def test_yahoo_symbol():
    assert prices.yahoo_symbol("brk.b") == "BRK-B"
    assert prices.yahoo_symbol("BF/B") == "BF-B"


def test_parse_yahoo_uses_adjclose_and_drops_nulls():
    data = {"chart": {"result": [{
        "timestamp": [1577975400, 1578061800, 1578321000],  # 2020-01-02/03/06 14:30 UTC
        "indicators": {"quote": [{"close": [10.0, 11.0, 12.0]}],
                       "adjclose": [{"adjclose": [9.5, None, 11.5]}]},
    }]}}
    s = prices.parse_yahoo(data)
    assert list(s.index.strftime("%Y-%m-%d")) == ["2020-01-02", "2020-01-06"]
    assert list(s.values) == [9.5, 11.5]


def test_parse_yahoo_bad_payload_returns_none():
    assert prices.parse_yahoo({"chart": {"result": None, "error": {"code": "Not Found"}}}) is None


def test_parse_stooq():
    text = "Date,Open,High,Low,Close,Volume\n2020-01-03,1,1,1,5.5,10\n2020-01-02,1,1,1,5.0,10\n"
    s = prices.parse_stooq(text)
    assert list(s.index.strftime("%Y-%m-%d")) == ["2020-01-02", "2020-01-03"]
    assert list(s.values) == [5.0, 5.5]


def test_parse_stooq_garbage_returns_none():
    assert prices.parse_stooq("No data") is None


def test_store_falls_back_and_caches(tmp_path):
    good = series("2020-01-01", [1, 2, 3])
    calls = []

    def empty(symbol, start):
        calls.append(("empty", symbol))
        return None

    def full(symbol, start):
        calls.append(("full", symbol))
        return good

    store = prices.PriceStore(str(tmp_path), fetchers=[empty, full])
    s = store.get("brk.b")
    assert list(s.values) == [1.0, 2.0, 3.0]
    assert calls == [("empty", "BRK-B"), ("full", "BRK-B")]
    assert os.path.isfile(tmp_path / "BRK-B.csv")

    cached = prices.PriceStore(str(tmp_path), fetchers=[])
    s2 = cached.get("BRK.B")
    assert list(s2.values) == [1.0, 2.0, 3.0]
    assert isinstance(s2.index, pd.DatetimeIndex)


def test_store_returns_none_for_missing_and_blank(tmp_path):
    store = prices.PriceStore(str(tmp_path), fetchers=[lambda s, d: None])
    assert store.get("ZZZZ") is None
    assert store.get("") is None
    assert store.get(None) is None


def test_store_uses_stale_cache_when_sources_fail(tmp_path):
    prices.PriceStore(str(tmp_path), fetchers=[lambda s, d: series("2020-01-01", [7])]).get("AAA")
    os.utime(tmp_path / "AAA.csv", (0, 0))  # make the cache file ancient
    store = prices.PriceStore(str(tmp_path), fetchers=[lambda s, d: None])
    assert list(store.get("AAA").values) == [7.0]
