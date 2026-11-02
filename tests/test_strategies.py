import pandas as pd

from backtest import strategies as st
from helpers import FakeStore, series

AAA = series("2020-01-01", [100 + i for i in range(300)])  # ends 2021-02-23
BBB = series("2020-01-01", [50] * 40)                        # stops trading 2020-02-25
END = AAA.index[-1]


def _events(rows):
    return pd.DataFrame(rows, columns=["fund", "filed", "ticker", "weight_fund", "weight_equal"])


def test_copycat_enters_next_day_and_exits_after_next_filing():
    ev = _events([("F", "2020-01-03", "AAA", 1.0, 1.0), ("F", "2020-04-01", "AAA", 1.0, 1.0)])
    t = st.copycat_trades(ev, FakeStore({"AAA": AAA}), END)
    assert list(t.columns) == st.TRADE_COLUMNS
    assert set(t["variant"]) == {"equal", "fund"}
    first = t[(t.variant == "equal") & (t.signal_date == "2020-01-03")].iloc[0]
    assert first.entry_date == "2020-01-06"   # Friday signal -> Monday entry
    assert first.entry_px == 103.0
    assert first.exit_date == "2020-04-02"    # first close after the next filing
    assert first.status == "ok"
    second = t[(t.variant == "equal") & (t.signal_date == "2020-04-01")].iloc[0]
    assert second.exit_date == "2020-07-30"   # fallback: 120 days after the filing
    assert second.status == "ok"


def test_copycat_statuses():
    ev = _events([
        ("F", "2020-01-03", "", 0.5, 0.5),
        ("F", "2020-01-03", "ZZZ", 0.5, 0.5),
        ("G", "2020-01-03", "BBB", 1.0, 1.0),
        ("G", "2020-04-01", "BBB", 1.0, 1.0),
        ("H", AAA.index[-10].date().isoformat(), "AAA", 1.0, 1.0),
        ("K", END.date().isoformat(), "AAA", 1.0, 1.0),
    ])
    t = st.copycat_trades(ev, FakeStore({"AAA": AAA, "BBB": BBB}), END)
    t = t[t.variant == "equal"]
    assert list(t[t.source == "F"].status) == ["no_price", "no_price"]
    g = t[(t.source == "G") & (t.signal_date == "2020-01-03")].iloc[0]
    assert (g.status, g.note, g.exit_date) == ("ok", "last_available", "2020-02-25")
    h = t[t.source == "H"].iloc[0]
    assert (h.status, h.exit_px) == ("open", float(AAA.iloc[-1]))
    assert t[t.source == "K"].iloc[0].status == "pending"


def _ptr(rows):
    return pd.DataFrame(rows, columns=["member", "filed", "ticker", "side"])


def test_congress_hold_and_until_sale():
    trades = _ptr([
        ("Pelosi", "2020-01-03", "AAA", "buy"),
        ("Khanna", "2020-02-03", "AAA", "sell"),   # other member: ignored
        ("Pelosi", "2020-03-02", "AAA", "sell"),
    ])
    t = st.congress_trades(trades, FakeStore({"AAA": AAA}), END, holds=(30,))
    assert set(t["variant"]) == {"hold30", "until_sale"}
    assert len(t) == 2  # sells never open trades
    h = t[t.variant == "hold30"].iloc[0]
    assert (h.entry_date, h.exit_date, h.source) == ("2020-01-06", "2020-02-05", "Pelosi")
    u = t[t.variant == "until_sale"].iloc[0]
    assert u.exit_date == "2020-03-03"


def test_congress_until_sale_without_sale_uses_max_days():
    t = st.congress_trades(_ptr([("Pelosi", "2020-01-03", "AAA", "buy")]),
                           FakeStore({"AAA": AAA}), END, holds=(), sale_max_days=365)
    u = t[t.variant == "until_sale"].iloc[0]
    assert u.exit_date == "2021-01-04"   # filed 2020-01-03 + 365 days = Sat -> Mon


def test_congress_empty_input():
    t = st.congress_trades(_ptr([]), FakeStore({}), END)
    assert t.empty and list(t.columns) == st.TRADE_COLUMNS


# ---- final review fixes: items 5, 7, 10 ----

def test_live_lag_boundary_open_vs_last_available():
    end = AAA.index[-1]
    rule = lambda e: ("on_or_after", e + pd.Timedelta(days=10000))
    assert st.LIVE_LAG_DAYS == 7
    live = AAA[AAA.index <= end - pd.Timedelta(days=7)]   # last bar exactly 7 days behind
    stale = AAA[AAA.index <= end - pd.Timedelta(days=8)]
    assert live.index[-1] == end - pd.Timedelta(days=7)
    a = st.price_trade(live, "2020-01-03", rule, end)
    b = st.price_trade(stale, "2020-01-03", rule, end)
    assert (a["status"], a["note"]) == ("open", "")
    assert (b["status"], b["note"]) == ("ok", "last_available")


def test_live_lag_boundary_pending_vs_no_price():
    end = AAA.index[-1]
    rule = lambda e: ("on_or_after", e)
    live = AAA[AAA.index <= end - pd.Timedelta(days=7)]
    stale = AAA[AAA.index <= end - pd.Timedelta(days=8)]
    sig = live.index[-1].date().isoformat()
    assert st.price_trade(live, sig, rule, end)["status"] == "pending"
    sig = stale.index[-1].date().isoformat()
    assert st.price_trade(stale, sig, rule, end)["status"] == "no_price"


def test_copycat_same_filed_date_keeps_latest_period_only():
    ev = pd.DataFrame([
        ("F", "2020-01-03", "AAA", 1.0, 1.0, "2019-06-30"),
        ("F", "2020-01-03", "BBB", 1.0, 1.0, "2019-09-30"),
    ], columns=["fund", "filed", "ticker", "weight_fund", "weight_equal", "period"])
    t = st.copycat_trades(ev, FakeStore({"AAA": AAA, "BBB": AAA}), END)
    assert set(t["ticker"]) == {"BBB"}


def test_copycat_without_period_column_keeps_all():
    ev = _events([("F", "2020-01-03", "AAA", 1.0, 1.0), ("F", "2020-01-03", "BBB", 1.0, 1.0)])
    t = st.copycat_trades(ev, FakeStore({"AAA": AAA, "BBB": AAA}), END)
    assert set(t["ticker"]) == {"AAA", "BBB"}


def test_congress_until_sale_fallback_anchored_on_filed_date():
    # a long gap between filing and the next trading day must not stretch the window
    t = st.congress_trades(_ptr([("Pelosi", "2020-01-03", "AAA", "buy")]),
                           FakeStore({"AAA": AAA}), END, holds=(), sale_max_days=100)
    u = t.iloc[0]
    assert u.exit_date == "2020-04-13"   # 2020-01-03 + 100 days = Sat 04-12 -> Mon 04-13
