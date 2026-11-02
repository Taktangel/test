import math

import pandas as pd
import pytest

from backtest import metrics
from backtest.strategies import TRADE_COLUMNS
from helpers import FakeStore, series

SPY = series("2020-01-01", [100, 100, 100, 100, 110])  # 01-01 .. 01-07


def _trades():
    rows = [
        ("copycat", "equal", "F", "AAA", "2020-01-01", "2020-01-02", 50.0, "2020-01-07", 60.0, 1.0, "ok", ""),
        ("copycat", "equal", "F", "BBB", "2020-01-01", "2020-01-02", 100.0, "2020-01-07", 95.0, 1.0, "ok", ""),
        ("copycat", "equal", "G", "CCC", "2020-01-01", "2020-01-02", 10.0, "2020-01-07", 20.0, 1.0, "open", ""),
        ("copycat", "equal", "G", "", "2020-01-01", None, None, None, None, 1.0, "no_price", ""),
    ]
    return pd.DataFrame(rows, columns=TRADE_COLUMNS)


def test_add_returns():
    t = metrics.add_returns(_trades(), SPY)
    assert t.loc[0, "ret"] == pytest.approx(0.2)
    assert t.loc[0, "spy_ret"] == pytest.approx(0.1)
    assert t.loc[0, "excess"] == pytest.approx(0.1)
    assert bool(t.loc[0, "win_abs"]) and bool(t.loc[0, "win_spy"])
    assert t.loc[1, "ret"] == pytest.approx(-0.05)
    assert not bool(t.loc[1, "win_abs"]) and not bool(t.loc[1, "win_spy"])
    assert math.isnan(t.loc[3, "ret"])


def test_summarize_counts_only_closed_trades():
    s = metrics.summarize(metrics.add_returns(_trades(), SPY), ["strategy", "variant"])
    row = s.iloc[0]
    assert list(s.columns) == ["strategy", "variant"] + metrics.SUMMARY_COLUMNS
    assert row.trades == 2
    assert row.win_abs_pct == pytest.approx(50.0)
    assert row.win_spy_pct == pytest.approx(50.0)
    assert row.mean_ret_pct == pytest.approx(7.5)
    assert row.median_ret_pct == pytest.approx(7.5)
    assert row.mean_excess_pct == pytest.approx(-2.5)
    assert (row.open, row.no_price) == (1, 1)


def test_daily_equity_single_trade():
    aaa = series("2020-01-01", [100, 100, 105, 110, 120])
    cal = aaa.index
    t = pd.DataFrame([("x", "y", "s", "AAA", "2020-01-01", "2020-01-02", 100.0, "2020-01-06", 110.0, 1.0, "ok", "")],
                     columns=TRADE_COLUMNS)
    eq = metrics.daily_equity(t, FakeStore({"AAA": aaa}), cal)
    assert list(eq.index.strftime("%Y-%m-%d")) == ["2020-01-02", "2020-01-03", "2020-01-06"]
    assert list(eq.round(6)) == [1.0, 1.05, 1.1]


def test_cagr_and_drawdown():
    eq = pd.Series([1.0, 1.21], index=pd.to_datetime(["2020-01-01", "2022-01-01"]))
    assert metrics.cagr(eq) == pytest.approx(0.1, abs=1e-3)
    dd = pd.Series([1.0, 1.2, 0.9, 1.0], index=pd.bdate_range("2020-01-01", periods=4))
    assert metrics.max_drawdown(dd) == pytest.approx(-0.25)


def test_book_stats():
    aaa = series("2020-01-01", [100, 100, 105, 110, 120])
    spy = series("2020-01-01", [100, 100, 101, 102, 103])
    t = pd.DataFrame([("copycat", "equal", "F", "AAA", "2020-01-01", "2020-01-02", 100.0, "2020-01-07", 120.0, 1.0, "ok", "")],
                     columns=TRADE_COLUMNS)
    books, curves = metrics.book_stats(t, FakeStore({"AAA": aaa}), spy)
    assert list(books.columns) == metrics.BOOK_COLUMNS
    assert books.iloc[0].start == "2020-01-02"
    assert "copycat/equal" in curves
    assert curves["copycat/equal"].iloc[-1] == pytest.approx(1.2)
