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
