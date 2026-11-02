import os
import shutil

from backtest import fetch_ptr
from vendor import ptr

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "pelosi")


def _report():
    with open(os.path.join(FIX, "ptr-20035143.txt"), encoding="utf-8") as fh:
        return ptr.parse_ptr_text(fh.read())


def test_trades_from_report_keeps_stocks_only():
    report = _report()
    trades = fetch_ptr.trades_from_report(report, "Pelosi", "20035143", report["filed"])
    assert trades
    assert any(r["asset_type"] == "OP" for r in report["rows"])  # fixture has options
    assert len(trades) < len(report["rows"])
    assert {t["side"] for t in trades} <= {"buy", "sell"}
    be_buys = [t for t in trades if t["ticker"] == "BE" and t["side"] == "buy"]
    st_rows = [r for r in report["rows"]
               if r["ticker"] == "BE" and r["type"] == "P" and r["asset_type"] == "ST"]
    assert len(be_buys) == len(st_rows)
    assert {"2026-07-24", "2026-07-28"} <= {t["txn_date"] for t in be_buys}
    assert all(t["member"] == "Pelosi" and t["filed"] == report["filed"] for t in trades)
    assert set(trades[0]) == set(fetch_ptr.COLUMNS)


def test_index_select_and_match_member():
    rows = ptr.load_index(2026, offline=os.path.join(FIX, "2026FD.zip"))
    sel = ptr.select(rows, members=["Pelosi"], kind="P")
    assert sel and all(r["last"] == "Pelosi" for r in sel)
    assert fetch_ptr.match_member(sel[0], ["Khanna", "Pelosi"]) == "Pelosi"
    assert fetch_ptr.match_member(sel[0], ["Khanna"]) is None


def test_read_filing_uses_cached_text(tmp_path):
    os.makedirs(tmp_path / "text")
    shutil.copy(os.path.join(FIX, "ptr-20035143.txt"), tmp_path / "text" / "20035143.txt")
    row = {"doc_id": "20035143", "filed": None, "url": "http://unused.invalid/x.pdf"}
    report = fetch_ptr.read_filing(row, str(tmp_path))
    assert report["rows"]


def test_load_index_cached_reads_past_year_from_disk(tmp_path):
    shutil.copy(os.path.join(FIX, "2026FD.zip"), tmp_path / "2026FD.zip")
    rows = fetch_ptr.load_index_cached(2026, str(tmp_path), this_year=2027)
    assert rows


def test_trades_from_report_skips_exchanges_options_and_no_ticker():
    def row(**kw):
        base = {"type": "P", "ticker": "AAA", "asset_type": "ST", "date": "2026-01-02",
                "amount_low": 1, "amount_high": 2, "owner_name": "Self"}
        base.update(kw)
        return base
    report = {"rows": [
        row(),
        row(type="S (partial)", ticker="BBB"),
        row(type="E", ticker="CCC"),
        row(ticker="DDD", option={"kind": "call"}),
        row(ticker=None),
        row(ticker="FFF", asset_type=None),
        row(ticker="GGG", asset_type="OP"),
    ]}
    trades = fetch_ptr.trades_from_report(report, "M", "1", "2026-02-01")
    assert [(t["ticker"], t["side"]) for t in trades] == [
        ("AAA", "buy"), ("BBB", "sell"), ("FFF", "buy")]


def test_build_trades_logs_and_skips(tmp_path, monkeypatch):
    def idx(year, cache_dir, this_year):
        if year == 2025:
            raise ptr.PtrError("index boom")
        return [{"doc_id": d, "type": "P", "last": "Pelosi", "first": "Nancy",
                 "name": "Hon. Nancy Pelosi", "filed": "2026-02-01", "url": "http://x/" + d}
                for d in ("1", "2", "3")]

    def read(row, cache_dir):
        if row["doc_id"] == "1":
            return None
        if row["doc_id"] == "2":
            raise ptr.PtrError("doc 2 broke")
        return {"rows": [{"type": "P", "ticker": "AAA", "asset_type": "ST",
                          "date": "2026-01-02", "amount_low": 1, "amount_high": 2,
                          "owner_name": "Self"}]}

    monkeypatch.setattr(fetch_ptr, "load_index_cached", idx)
    monkeypatch.setattr(fetch_ptr, "read_filing", read)
    logs = []
    df = fetch_ptr.build_trades(["Pelosi"], 2025, 2026, str(tmp_path), log=logs.append)
    assert list(df["doc_id"]) == ["3"]
    assert list(df["member"]) == ["Pelosi"]
    assert any("index boom" in m for m in logs)
    assert any("no text" in m for m in logs)
    assert any("2" in m and "doc 2 broke" in m for m in logs)


def test_load_index_cached_download_leaves_no_tmp(tmp_path, monkeypatch):
    with open(os.path.join(FIX, "2026FD.zip"), "rb") as fh:
        data = fh.read()
    monkeypatch.setattr(ptr, "download", lambda url: data)
    rows = fetch_ptr.load_index_cached(2026, str(tmp_path / "c"), this_year=2026)
    assert rows
    assert os.listdir(tmp_path / "c") == ["2026FD.zip"]
