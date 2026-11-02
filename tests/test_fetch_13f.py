import os

import pytest

from backtest import fetch_13f
from vendor import edgar13f as e13

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "copycat")
BRK = {"cik": "0001067983", "name": "Berkshire Hathaway Inc"}
Q2 = "0001193125-26-352200"
Q1 = "0001193125-26-226661"


def test_cached_fetcher_keeps_archives_only(tmp_path, monkeypatch):
    calls = []

    def fake_get(self, url, sec=True):
        calls.append(url)
        return b"<x/>"

    monkeypatch.setattr(e13.Fetcher, "get", fake_get)
    f = fetch_13f.CachedFetcher(str(tmp_path), ua="Test test@example.com")
    arch = "https://www.sec.gov/Archives/edgar/data/1067983/000119312526352200/index.json"
    assert f.get(arch) == b"<x/>"
    assert f.get(arch) == b"<x/>"
    assert len(calls) == 1
    assert (tmp_path / "1067983" / "000119312526352200" / "index.json").is_file()

    sub = "https://data.sec.gov/submissions/CIK0001067983.json"
    f.get(sub)
    f.get(sub)
    assert len(calls) == 3


class StubFetcher:
    def __init__(self, pages):
        self.pages = pages

    def get_json(self, url, sec=True):
        return self.pages[url]


def _page(acc, filed, period, form="13F-HR"):
    return {"accessionNumber": [acc], "filingDate": [filed], "reportDate": [period],
            "form": [form], "primaryDocument": ["primary_doc.xml"]}


def test_all_filings_merges_older_pages():
    recent = _page("A-2", "2020-05-15", "2020-03-31")
    older = _page("A-1", "2014-05-15", "2014-03-31")
    fetcher = StubFetcher({
        e13.SUBMISSIONS % "0000000001": {"filings": {
            "recent": recent, "files": [{"name": "CIK0000000001-submissions-001.json"}]}},
        fetch_13f.SUBMISSIONS_FILE % "CIK0000000001-submissions-001.json": older,
    })
    got = fetch_13f.all_filings(fetcher, "1")
    assert [f["accession"] for f in got] == ["A-2", "A-1"]
    assert got[1]["period"] == "2014-03-31"


def _offline(tmp_path):
    return fetch_13f.CachedFetcher(str(tmp_path / "cache"), offline=FIX)


def test_build_events_berkshire_fixture(tmp_path):
    fetcher = _offline(tmp_path)
    index = e13.ticker_index(fetcher)
    overrides = e13.load_overrides([e13.CLASSES])
    errors = []
    ev = fetch_13f.build_events(fetcher, [BRK], "2026-01-01", 5, index, overrides,
                                log=errors.append)
    assert list(ev.columns) == fetch_13f.COLUMNS
    assert {Q1, Q2} <= set(ev["accession"])
    q2 = ev[ev["accession"] == Q2].sort_values("rank")
    assert list(q2["ticker"]) == ["AAPL", "AXP", "GOOGL", "KO", "BAC"]
    assert q2["weight_fund"].sum() == pytest.approx(1.0)
    assert q2.iloc[0]["weight_fund"] == pytest.approx(0.3067, abs=0.002)
    assert set(q2["weight_equal"]) == {0.2}
    assert (q2["filed"] > q2["period"]).all()


class MultiStub:
    def __init__(self, recent):
        self.recent = recent

    def get_json(self, url, sec=True):
        return {"filings": {"recent": self.recent}}


def _recent(items):
    return {"accessionNumber": [i[0] for i in items], "filingDate": [i[1] for i in items],
            "reportDate": [i[2] for i in items], "form": [i[3] for i in items],
            "primaryDocument": ["primary_doc.xml"] * len(items)}


FUND = {"cik": "1", "name": "Fund One"}


def test_build_events_filing_selection(monkeypatch):
    fetcher = MultiStub(_recent([
        ("A-late", "2026-03-01", "2025-12-31", "13F-HR"),
        ("A-first", "2026-02-10", "2025-12-31", "13F-HR"),
        ("A-amend", "2026-01-20", "2025-12-31", "13F-HR/A"),
        ("A-old", "2025-11-14", "2025-09-30", "13F-HR"),
        ("A-q1", "2026-05-15", "2026-03-31", "13F-HR"),
    ]))
    monkeypatch.setattr(fetch_13f, "top_positions", lambda *a, **k: [
        {"rank": 1, "ticker": "X", "issuer": "X INC", "weight_fund": 1.0, "weight_equal": 1.0}])
    ev = fetch_13f.build_events(fetcher, [FUND], "2026-01-01", 5, {}, {})
    assert list(ev["accession"]) == ["A-first", "A-q1"]
    assert list(ev["filed"]) == ["2026-02-10", "2026-05-15"]


def test_build_events_logs_and_skips_failed_filing(monkeypatch):
    fetcher = MultiStub(_recent([
        ("A-bad", "2026-02-10", "2025-12-31", "13F-HR"),
        ("A-ok", "2026-05-15", "2026-03-31", "13F-HR"),
    ]))

    def fake_top(fetcher, cik, filing, *a, **k):
        if filing["accession"] == "A-bad":
            raise e13.EdgarError("boom")
        return [{"rank": 1, "ticker": "X", "issuer": "X INC",
                 "weight_fund": 1.0, "weight_equal": 1.0}]

    monkeypatch.setattr(fetch_13f, "top_positions", fake_top)
    logs = []
    ev = fetch_13f.build_events(fetcher, [FUND], "2026-01-01", 5, {}, {}, log=logs.append)
    assert list(ev["accession"]) == ["A-ok"]
    assert len(logs) == 1 and "Fund One" in logs[0] and "A-bad" in logs[0]


def _pos(ticker, issuer, value):
    return {"ticker": ticker, "issuer": issuer, "value": value, "cusip": issuer,
            "share_type": "SH", "put_call": ""}


def test_top_positions_keeps_tickerless_slot(monkeypatch):
    positions = [_pos("AAA", "A CO", 50), _pos("", "B CO", 30), _pos("CCC", "C CO", 20)]
    monkeypatch.setattr(e13, "info_table_name", lambda idx: "t.xml")
    monkeypatch.setattr(e13, "parse_info_table", lambda data, multiplier=1: [])
    monkeypatch.setattr(e13, "build", lambda *a, **k: (positions, 100))

    class F:
        def get_json(self, url, sec=True):
            return {}

        def get(self, url, sec=True):
            return b""

    filing = {"accession": "0000000001-26-000001", "filed": "2026-02-10"}
    got = fetch_13f.top_positions(F(), "1", filing, {}, {}, 2)
    assert [g["rank"] for g in got] == [1, 2]
    assert [g["ticker"] for g in got] == ["AAA", ""]
    assert [g["weight_fund"] for g in got] == pytest.approx([50 / 80, 30 / 80])
    assert [g["weight_equal"] for g in got] == [0.5, 0.5]


ARCH = "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/index.json"


def test_cached_fetcher_retries_then_succeeds(tmp_path, monkeypatch):
    calls = []

    def flaky(self, url, sec=True):
        calls.append(url)
        if len(calls) < 3:
            raise e13.EdgarError("transient")
        return b"ok"

    monkeypatch.setattr(e13.Fetcher, "get", flaky)
    monkeypatch.setattr(fetch_13f.time, "sleep", lambda s: None)
    f = fetch_13f.CachedFetcher(str(tmp_path), ua="Test test@example.com")
    assert f.get(ARCH) == b"ok"
    assert len(calls) == 3


def test_cached_fetcher_fails_fast_without_user_agent(tmp_path, monkeypatch):
    calls = []

    def nope(self, url, sec=True):
        calls.append(url)
        raise e13.EdgarError("no user agent")

    monkeypatch.setattr(e13.Fetcher, "get", nope)
    monkeypatch.setattr(fetch_13f.time, "sleep", lambda s: None)
    f = fetch_13f.CachedFetcher(str(tmp_path), ua="")
    with pytest.raises(e13.EdgarError):
        f.get(ARCH)
    assert len(calls) == 1


def test_cached_fetcher_write_is_atomic(tmp_path, monkeypatch):
    monkeypatch.setattr(e13.Fetcher, "get", lambda self, url, sec=True: b"full content")
    f = fetch_13f.CachedFetcher(str(tmp_path), ua="Test test@example.com")
    f.get(ARCH)
    d = tmp_path / "1" / "000000000126000001"
    assert (d / "index.json").read_bytes() == b"full content"
    assert [p.name for p in d.iterdir()] == ["index.json"]


def test_cached_fetcher_failed_write_leaves_no_final_file(tmp_path, monkeypatch):
    monkeypatch.setattr(e13.Fetcher, "get", lambda self, url, sec=True: b"data")

    def boom(src, dst):
        raise OSError("disk")

    monkeypatch.setattr(fetch_13f.os, "replace", boom)
    f = fetch_13f.CachedFetcher(str(tmp_path), ua="Test test@example.com")
    with pytest.raises(OSError):
        f.get(ARCH)
    assert not (tmp_path / "1" / "000000000126000001" / "index.json").exists()
