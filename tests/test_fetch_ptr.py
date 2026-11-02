import os
import shutil

import pytest

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


def test_load_index_cached_reads_past_year_from_disk(tmp_path, monkeypatch):
    def no_net(url):
        raise AssertionError("network used")
    monkeypatch.setattr(ptr, "download", no_net)
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
    def idx(year, cache_dir, this_year, log=None):
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


def _fixture_zip_bytes():
    with open(os.path.join(FIX, "2026FD.zip"), "rb") as fh:
        return fh.read()


def test_load_index_cached_heals_corrupt_cache(tmp_path, monkeypatch):
    good = _fixture_zip_bytes()
    (tmp_path / "2026FD.zip").write_bytes(good[:50])  # truncated zip
    monkeypatch.setattr(ptr, "download", lambda url: good)
    rows = fetch_ptr.load_index_cached(2026, str(tmp_path), this_year=2027)
    assert rows
    assert (tmp_path / "2026FD.zip").read_bytes() == good


def test_load_index_cached_rejects_html_download(tmp_path, monkeypatch):
    monkeypatch.setattr(ptr, "download", lambda url: b"<html>blocked</html>")
    with pytest.raises(ptr.PtrError):
        fetch_ptr.load_index_cached(2026, str(tmp_path), this_year=2026)
    assert os.listdir(tmp_path) == []


def test_build_trades_skips_value_error_filing(tmp_path, monkeypatch):
    rows = [{"doc_id": d, "type": "P", "last": "Pelosi", "first": "Nancy",
             "name": "n", "filed": "2026-02-01", "url": "u"} for d in ("1", "2")]
    monkeypatch.setattr(fetch_ptr, "load_index_cached", lambda y, c, t, log=None: rows)

    def read(row, cache_dir):
        if row["doc_id"] == "1":
            raise ValueError("bad date")
        return {"rows": [{"type": "S", "ticker": "AAA", "asset_type": "ST"}]}

    monkeypatch.setattr(fetch_ptr, "read_filing", read)
    logs = []
    df = fetch_ptr.build_trades(["Pelosi"], 2026, 2026, str(tmp_path), log=logs.append)
    assert list(df["doc_id"]) == ["2"]
    assert any("ValueError" in m for m in logs)


# ---- final review fixes: items 1, 3, 8 ----

import http.client  # noqa: E402


def test_errors_include_http_exception():
    assert http.client.HTTPException in fetch_ptr.ERRORS


def test_download_retries_with_backoff(monkeypatch):
    calls, sleeps = [], []

    def flaky(url):
        calls.append(url)
        if len(calls) < 3:
            raise ptr.PtrError("transient")
        return b"data"

    monkeypatch.setattr(ptr, "download", flaky)
    monkeypatch.setattr(fetch_ptr.time, "sleep", sleeps.append)
    assert fetch_ptr._download("u") == b"data"
    assert len(calls) == 3 and sleeps == [2, 4]


def test_download_gives_up_after_three(monkeypatch):
    calls = []

    def down(url):
        calls.append(url)
        raise http.client.IncompleteRead(b"")

    monkeypatch.setattr(ptr, "download", down)
    monkeypatch.setattr(fetch_ptr.time, "sleep", lambda s: None)
    with pytest.raises(http.client.HTTPException):
        fetch_ptr._download("u")
    assert len(calls) == 3


def test_current_year_index_falls_back_to_last_good_copy(tmp_path, monkeypatch):
    good = _fixture_zip_bytes()
    (tmp_path / "2026FD.zip").write_bytes(good)

    def down(url):
        raise ptr.PtrError("down")

    monkeypatch.setattr(ptr, "download", down)
    monkeypatch.setattr(fetch_ptr.time, "sleep", lambda s: None)
    logs = []
    rows = fetch_ptr.load_index_cached(2026, str(tmp_path), this_year=2026, log=logs.append)
    assert rows and len(logs) == 1 and "2026" in logs[0]
    assert (tmp_path / "2026FD.zip").read_bytes() == good


def test_current_year_index_without_copy_still_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(ptr, "download", lambda url: (_ for _ in ()).throw(ptr.PtrError("x")))
    monkeypatch.setattr(fetch_ptr.time, "sleep", lambda s: None)
    with pytest.raises(ptr.PtrError):
        fetch_ptr.load_index_cached(2026, str(tmp_path), this_year=2026, log=lambda m: None)


def test_read_filing_retries_pdf_download(tmp_path, monkeypatch):
    calls = []

    def flaky(url):
        calls.append(url)
        if len(calls) == 1:
            raise ptr.PtrError("transient")
        return b"%PDF-1.4 x"

    monkeypatch.setattr(ptr, "download", flaky)
    monkeypatch.setattr(fetch_ptr.time, "sleep", lambda s: None)
    monkeypatch.setattr(ptr, "pdf_to_text", lambda path: None)
    row = {"doc_id": "9", "filed": "2026-01-01", "url": "http://x/9.pdf"}
    assert fetch_ptr.read_filing(row, str(tmp_path)) is None
    assert len(calls) == 2


def _row(filed):
    return {"doc_id": "1", "type": "P", "last": "Pelosi", "first": "Nancy",
            "name": "n", "filed": filed, "url": "u"}


def _rep(filed=None):
    return {"filed": filed, "rows": [{"type": "P", "ticker": "AAA", "asset_type": "ST"}]}


def test_build_trades_falls_back_to_report_filed(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_ptr, "load_index_cached", lambda y, c, t, log=None: [_row(None)])
    monkeypatch.setattr(fetch_ptr, "read_filing", lambda r, c: _rep("2026-03-04"))
    df = fetch_ptr.build_trades(["Pelosi"], 2026, 2026, str(tmp_path), log=lambda m: None)
    assert list(df["filed"]) == ["2026-03-04"]


def test_build_trades_skips_filing_without_any_filed_date(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_ptr, "load_index_cached", lambda y, c, t, log=None: [_row("")])
    monkeypatch.setattr(fetch_ptr, "read_filing", lambda r, c: _rep(None))
    logs = []
    df = fetch_ptr.build_trades(["Pelosi"], 2026, 2026, str(tmp_path), log=logs.append)
    assert df.empty and len(logs) == 1 and "filed" in logs[0]
