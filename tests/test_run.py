import json
import os
import shutil

import pandas as pd
import pytest

from backtest import run
from helpers import FakeStore, series

CFG = {"holds": [30], "sale_max_days": 365, "copycat_fallback_days": 120}


def _inputs():
    events = pd.DataFrame([
        {"fund": "F", "filed": "2020-01-03", "ticker": "AAA", "weight_fund": 1.0, "weight_equal": 1.0},
        {"fund": "F", "filed": "2020-04-01", "ticker": "AAA", "weight_fund": 1.0, "weight_equal": 1.0},
    ])
    ptr_trades = pd.DataFrame([{"member": "Pelosi", "filed": "2020-02-03", "ticker": "AAA", "side": "buy"}])
    store = FakeStore({"SPY": series("2020-01-01", [100 + i * 0.1 for i in range(300)]),
                       "AAA": series("2020-01-01", [100 + i for i in range(300)])})
    return events, ptr_trades, store


def test_run_backtest_end_to_end():
    trades, overall, by_source, books, curves = run.run_backtest(*_inputs(), CFG)
    assert set(trades["strategy"]) == {"copycat", "congress"}
    assert len(overall) == 4  # copycat equal/fund, congress hold30/until_sale
    assert (overall["win_abs_pct"] == 100.0).all()
    assert (overall["win_spy_pct"] == 100.0).all()
    assert set(by_source["source"]) == {"F", "Pelosi"}
    assert set(curves) == {"copycat/equal", "copycat/fund", "congress/hold30", "congress/until_sale"}
    assert (books["cagr_pct"] > books["spy_cagr_pct"]).all()


def test_run_backtest_needs_spy():
    events, ptr_trades, _ = _inputs()
    with pytest.raises(SystemExit):
        run.run_backtest(events, ptr_trades, FakeStore({}), CFG)


def test_main_skip_fetch_offline(tmp_path, monkeypatch):
    for name in ("config.json", "members.json"):
        shutil.copy(os.path.join(run.ROOT, name), tmp_path / name)
    (tmp_path / "data").mkdir()
    events, ptr_trades, store = _inputs()
    events.to_csv(tmp_path / "data" / "events_13f.csv", index=False)
    ptr_trades.to_csv(tmp_path / "data" / "trades_ptr.csv", index=False)

    seen = {}

    def factory(cache_dir, **kwargs):
        seen.update(kwargs)
        return store

    monkeypatch.setattr(run, "ROOT", str(tmp_path))
    monkeypatch.setattr(run, "PriceStore", factory)
    run.main(["--skip-fetch"])

    assert callable(seen.get("log"))
    reports = tmp_path / "reports"
    assert (reports / "latest.md").exists()
    assert (reports / "summary.json").exists()
    assert (reports / "errors.log").exists()
    json.loads((reports / "summary.json").read_text(encoding="utf-8"))
