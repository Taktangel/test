import json

import numpy as np
import pandas as pd

from backtest import metrics, report


def _frames():
    overall = pd.DataFrame([{"strategy": "copycat", "variant": "equal", "trades": 2,
                             "win_abs_pct": 50.0, "win_spy_pct": np.nan, "mean_ret_pct": 7.5,
                             "median_ret_pct": 7.5, "mean_excess_pct": 1.0, "open": 0,
                             "no_price": 1}])
    by_source = overall.assign(source="F")
    books = pd.DataFrame([{"strategy": "copycat", "variant": "equal", "start": "2020-01-02",
                           "end": "2020-01-07", "cagr_pct": 12.0, "spy_cagr_pct": 10.0,
                           "max_dd_pct": -5.0, "spy_max_dd_pct": -3.0}],
                         columns=metrics.BOOK_COLUMNS)
    curve = pd.Series([1.0, 1.1], index=pd.to_datetime(["2020-01-02", "2020-01-03"]))
    trades = pd.DataFrame([{"strategy": "copycat", "ticker": "AAA"}])
    return trades, overall, by_source, books, {"copycat/equal": curve}


def test_md_table_formats_and_blanks_nan():
    out = report.md_table(pd.DataFrame([{"a": 1.234, "b": np.nan, "c": "x"}]))
    assert out.splitlines()[0] == "| a | b | c |"
    assert out.splitlines()[2] == "| 1.2 |  | x |"


def test_write_report(tmp_path):
    trades, overall, by_source, books, curves = _frames()
    report.write_report(str(tmp_path), trades, overall, by_source, books, curves,
                        ["PTR x: no text"], "2026-11-03T06:00:00Z")
    md = (tmp_path / "latest.md").read_text(encoding="utf-8")
    assert "Доля в плюсе, %" in md and "Не финансовый совет" in md
    assert "2026-11-03T06:00:00Z" in md
    assert "Проблем при сборе данных: 1" in md
    assert "Copycat: вес позиций без цены делится между остальными позициями периода, а не держится в кэше." in md
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["overall"][0]["win_spy_pct"] is None
    assert summary["books"][0]["cagr_pct"] == 12.0
    assert (tmp_path / "trades.csv").is_file()
    assert (tmp_path / "equity.png").stat().st_size > 0
    assert (tmp_path / "errors.log").read_text(encoding="utf-8").strip() == "PTR x: no text"
