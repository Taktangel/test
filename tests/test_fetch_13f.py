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


# ---- final review fixes: items 1-3 ----

import gzip  # noqa: E402
import http.client  # noqa: E402
import json  # noqa: E402
import xml.etree.ElementTree as ET  # noqa: E402

from backtest import run  # noqa: E402


@pytest.mark.parametrize("exc", [OSError("reset"), http.client.IncompleteRead(b"x"),
                                 gzip.BadGzipFile("bad"), EOFError("eof")])
def test_cached_fetcher_converts_low_level_errors(tmp_path, monkeypatch, exc):
    calls = []

    def boom(self, url, sec=True):
        calls.append(url)
        raise exc

    monkeypatch.setattr(e13.Fetcher, "get", boom)
    monkeypatch.setattr(fetch_13f.time, "sleep", lambda s: None)
    f = fetch_13f.CachedFetcher(str(tmp_path), ua="Test test@example.com")
    with pytest.raises(e13.EdgarError):
        f.get(ARCH)
    assert len(calls) == 3


def test_cached_fetcher_retries_low_level_error_then_succeeds(tmp_path, monkeypatch):
    calls = []

    def flaky(self, url, sec=True):
        calls.append(url)
        if len(calls) == 1:
            raise http.client.IncompleteRead(b"x")
        return b"ok"

    monkeypatch.setattr(e13.Fetcher, "get", flaky)
    monkeypatch.setattr(fetch_13f.time, "sleep", lambda s: None)
    f = fetch_13f.CachedFetcher(str(tmp_path), ua="Test test@example.com")
    assert f.get(ARCH) == b"ok"


@pytest.mark.parametrize("exc", [ValueError("v"), KeyError("k"), TypeError("t"),
                                 ET.ParseError("p")])
def test_build_events_skips_parse_errors(monkeypatch, exc):
    fetcher = MultiStub(_recent([("A-bad", "2026-02-10", "2025-12-31", "13F-HR"),
                                 ("A-ok", "2026-05-15", "2026-03-31", "13F-HR")]))

    def fake_top(fetcher, cik, filing, *a, **k):
        if filing["accession"] == "A-bad":
            raise exc
        return [{"rank": 1, "ticker": "X", "issuer": "X", "weight_fund": 1.0,
                 "weight_equal": 1.0}]

    monkeypatch.setattr(fetch_13f, "top_positions", fake_top)
    logs = []
    ev = fetch_13f.build_events(fetcher, [FUND], "2026-01-01", 5, {}, {}, log=logs.append)
    assert list(ev["accession"]) == ["A-ok"]
    assert len(logs) == 1 and type(exc).__name__ in logs[0] and "A-bad" in logs[0]


def test_build_events_skips_fund_when_filings_unparsable(monkeypatch):
    def bad(fetcher, cik, *a):
        raise KeyError("filings")

    monkeypatch.setattr(fetch_13f, "all_filings", bad)
    logs = []
    ev = fetch_13f.build_events(MultiStub({}), [FUND], "2026-01-01", 5, {}, {}, log=logs.append)
    assert ev.empty and len(logs) == 1 and "KeyError" in logs[0]


def _top_setup(monkeypatch, positions):
    monkeypatch.setattr(e13, "info_table_name", lambda idx: "t.xml")
    monkeypatch.setattr(e13, "parse_info_table", lambda data, multiplier=1: [])
    monkeypatch.setattr(e13, "build", lambda *a, **k: (positions, 100))


class _F:
    def get_json(self, url, sec=True):
        return {}

    def get(self, url, sec=True):
        return b""


FILING = {"accession": "0000000001-26-000001", "filed": "2026-02-10"}


def test_top_positions_figi_failure_keeps_filing(monkeypatch):
    _top_setup(monkeypatch, [_pos("AAA", "A CO", 50), _pos("", "B CO", 30)])

    def boom(*a, **k):
        raise e13.EdgarError("figi down")

    monkeypatch.setattr(e13, "figi_lookup", boom)
    logs = []
    got = fetch_13f.top_positions(_F(), "1", FILING, {}, {}, 2, figi_key="k", log=logs.append)
    assert [g["ticker"] for g in got] == ["AAA", ""]
    assert len(logs) == 1 and "figi" in logs[0].lower()


def test_top_positions_figi_cache_and_pause(tmp_path, monkeypatch):
    cache = str(tmp_path / "figi.json")
    with open(cache, "w") as fh:
        json.dump({"B CO": "BBB"}, fh)
    _top_setup(monkeypatch, [_pos("AAA", "A CO", 50), _pos("", "B CO", 30), _pos("", "C CO", 20)])
    asked = []

    def fake(fetcher, cusips, api_key=None, batch=None, pause=2.5):
        asked.append((list(cusips), pause))
        return {"C CO": "CCC"}

    monkeypatch.setattr(e13, "figi_lookup", fake)
    got = fetch_13f.top_positions(_F(), "1", FILING, {}, {}, 3, figi_key="k", figi_cache=cache)
    assert [g["ticker"] for g in got] == ["AAA", "BBB", "CCC"]
    assert asked[0][0] == ["C CO"] and asked[0][1] >= 0.25
    with open(cache) as fh:
        assert json.load(fh) == {"B CO": "BBB", "C CO": "CCC"}
    assert [p.name for p in tmp_path.iterdir()] == ["figi.json"]  # no tmp left
    # second call: everything cached, no lookup
    _top_setup(monkeypatch, [_pos("AAA", "A CO", 50), _pos("", "B CO", 30), _pos("", "C CO", 20)])
    asked.clear()
    got = fetch_13f.top_positions(_F(), "1", FILING, {}, {}, 3, figi_key="k", figi_cache=cache)
    assert asked == [] and [g["ticker"] for g in got] == ["AAA", "BBB", "CCC"]


def _cached(tmp_path):
    f = fetch_13f.CachedFetcher(str(tmp_path / "sec"), ua="Test test@example.com")
    return f


def test_all_filings_caches_submissions_and_falls_back(tmp_path, monkeypatch):
    f = _cached(tmp_path)
    main_url = e13.SUBMISSIONS % "0000000001"
    extra_url = fetch_13f.SUBMISSIONS_FILE % "CIK0000000001-submissions-001.json"
    pages = {main_url: {"filings": {"recent": _page("A-2", "2020-05-15", "2020-03-31"),
                                    "files": [{"name": "CIK0000000001-submissions-001.json"}]}},
             extra_url: _page("A-1", "2014-05-15", "2014-03-31")}
    monkeypatch.setattr(f, "get_json", lambda url, sec=True: pages[url])
    first = fetch_13f.all_filings(f, "1")
    assert (tmp_path / "sec" / "submissions").is_dir()

    def down(url, sec=True):
        raise e13.EdgarError("down")

    monkeypatch.setattr(f, "get_json", down)
    logs = []
    second = fetch_13f.all_filings(f, "1", log=logs.append)
    assert second == first and len(logs) == 2


def test_all_filings_no_cache_no_network_raises(tmp_path, monkeypatch):
    f = _cached(tmp_path)

    def down(url, sec=True):
        raise e13.EdgarError("down")

    monkeypatch.setattr(f, "get_json", down)
    with pytest.raises(e13.EdgarError):
        fetch_13f.all_filings(f, "1", log=lambda m: None)


def test_load_ticker_index_caches_and_falls_back(tmp_path, monkeypatch):
    data = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}

    class F:
        fail = False

        def get_json(self, url, sec=True):
            if self.fail:
                raise e13.EdgarError("down")
            return data

    f = F()
    logs = []
    idx = run.load_ticker_index(f, str(tmp_path), logs.append)
    assert idx is not None and (tmp_path / "sec" / "company_tickers.json").is_file()
    f.fail = True
    idx2 = run.load_ticker_index(f, str(tmp_path), logs.append)
    assert idx2 is not None and len(logs) == 1
    (tmp_path / "sec" / "company_tickers.json").unlink()
    assert run.load_ticker_index(f, str(tmp_path), logs.append) is None
    assert len(logs) == 3
