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


def _held(rows):
    """Open-trade rows: (ticker, entry, exit, weight)."""
    return pd.DataFrame([("s", "v", "F", tk, en, en, 100.0, ex, 100.0, w, "ok", "")
                         for tk, en, ex, w in rows], columns=TRADE_COLUMNS)


def test_daily_equity_period_boundary_counted_once():
    # Trade 1 exits on the day trade 2 enters: that day's return must be earned once.
    aaa = series("2020-01-01", [100, 110, 99, 105, 115])
    t = _held([("AAA", "2020-01-01", "2020-01-03", 1.0), ("AAA", "2020-01-03", "2020-01-07", 1.0)])
    eq = metrics.daily_equity(t, FakeStore({"AAA": aaa}), aaa.index)
    assert eq.loc["2020-01-03"] == pytest.approx(0.99)  # 1.1 * 0.9, not 1.1 * 0.9 * 0.9
    assert eq.iloc[-1] == pytest.approx(1.15)
    assert list(eq.pct_change(fill_method=None).dropna()) == pytest.approx(
        list(aaa.pct_change(fill_method=None).iloc[1:]))


def test_daily_equity_weighted_mean_of_held_returns():
    cal = series("2020-01-01", [0] * 5).index
    a = series("2020-01-01", [100, 120, 90, 99, 108])
    b = series("2020-01-01", [100, 95, 100, 90, 99])
    t = _held([("AAA", "2020-01-01", "2020-01-07", 0.75), ("BBB", "2020-01-01", "2020-01-07", 0.25)])
    eq = metrics.daily_equity(t, FakeStore({"AAA": a, "BBB": b}), cal)
    rw = (0.75 * a.pct_change(fill_method=None).fillna(0.0)
          + 0.25 * b.pct_change(fill_method=None).fillna(0.0))
    assert list(eq) == pytest.approx(list((1.0 + rw).cumprod()))


def test_daily_equity_flat_across_cash_gap():
    aaa = series("2020-01-01", [100, 110, 120, 50, 60, 70, 80, 90])
    t = _held([("AAA", "2020-01-01", "2020-01-03", 1.0), ("AAA", "2020-01-07", "2020-01-10", 1.0)])
    eq = metrics.daily_equity(t, FakeStore({"AAA": aaa}), aaa.index)
    # Nothing held on 01-06 and 01-07: the 50 print must not leak into equity.
    assert eq.loc["2020-01-06"] == pytest.approx(1.2)
    assert eq.loc["2020-01-07"] == pytest.approx(1.2)
    assert eq.iloc[-1] == pytest.approx(1.2 * 90 / 60)


def test_daily_equity_entry_on_ticker_holiday_uses_last_price():
    # Entry day 2020-01-01 has no print for AAA; last known price is 102 (2019-12-31).
    cal = series("2020-01-01", [0] * 6).index
    aaa = pd.Series([100.0, 102.0, 105.0, 110.0],
                    index=pd.to_datetime(["2019-12-30", "2019-12-31", "2020-01-03", "2020-01-06"]))
    t = _held([("AAA", "2020-01-01", "2020-01-06", 1.0)])
    eq = metrics.daily_equity(t, FakeStore({"AAA": aaa}), cal)
    assert eq.iloc[-1] == pytest.approx(110.0 / 102.0)
