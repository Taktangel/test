"""13F-HR filings of the bundled funds -> one row per top-N stock position per filing."""
import gzip
import http.client
import json
import os
import time
import xml.etree.ElementTree as ET

import pandas as pd

from vendor import edgar13f as e13

SUBMISSIONS_FILE = "https://data.sec.gov/submissions/%s"
KEYS = ("accessionNumber", "filingDate", "reportDate", "form", "primaryDocument")
COLUMNS = ["fund", "cik", "accession", "period", "filed", "rank", "ticker", "issuer",
           "weight_fund", "weight_equal"]
ARCHIVE_MARK = "/Archives/edgar/data/"
NET_ERRORS = (e13.EdgarError, OSError, http.client.HTTPException, gzip.BadGzipFile, EOFError)
# Anything a malformed filing can raise while it is parsed: skip that filing, keep the run.
PARSE_ERRORS = (e13.EdgarError, ValueError, KeyError, TypeError, ET.ParseError)
FIGI_PAUSE = 0.25


def _write_json_atomic(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)
    os.replace(tmp, path)


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


class CachedFetcher(e13.Fetcher):
    """Keeps EDGAR archive files on disk forever: a filed document never changes.
    Submissions and ticker lists are fetched fresh every time."""

    def __init__(self, cache_dir, **kwargs):
        super().__init__(**kwargs)
        self.cache_dir = cache_dir

    def cache_path(self, url):
        if ARCHIVE_MARK not in url:
            return None
        return os.path.join(self.cache_dir, *url.split(ARCHIVE_MARK, 1)[1].split("/"))

    def get(self, url, sec=True):
        path = self.cache_path(url)
        if path and os.path.isfile(path):
            with open(path, "rb") as fh:
                return fh.read()
        for attempt in range(3):
            try:
                data = super().get(url, sec=sec)
                break
            except NET_ERRORS as exc:
                if self.offline or attempt == 2 or (sec and not self.ua):
                    if isinstance(exc, e13.EdgarError):
                        raise
                    raise e13.EdgarError("%s: %s: %s" % (url, type(exc).__name__, exc)) from exc
                time.sleep(2 * (attempt + 1))
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        return data


def _submissions_json(fetcher, url, name, log):
    """Fresh submissions JSON, kept on disk; the saved copy stands in when SEC is down."""
    cache_dir = getattr(fetcher, "cache_dir", None)
    path = os.path.join(cache_dir, "submissions", name) if cache_dir else None
    try:
        data = fetcher.get_json(url)
    except (e13.EdgarError, OSError) as exc:
        saved = _read_json(path) if path else None
        if saved is None:
            raise
        log("13F submissions %s: %s; using the saved copy" % (name, exc))
        return saved
    if path:
        _write_json_atomic(path, data)
    return data


def all_filings(fetcher, cik, log=print):
    """Every 13F filing of a filer, including the older pages SEC splits off."""
    sub = _submissions_json(fetcher, e13.SUBMISSIONS % e13.cik10(cik),
                            "CIK%s.json" % e13.cik10(cik), log)
    filings = sub.get("filings", {})
    recent = filings.get("recent", {})
    n0 = len(recent.get("accessionNumber", []))
    merged = {k: list(recent.get(k, [""] * n0)) for k in KEYS}
    for extra in filings.get("files", []):
        older = _submissions_json(fetcher, SUBMISSIONS_FILE % extra["name"], extra["name"], log)
        n = len(older.get("accessionNumber", []))
        for k in KEYS:
            merged[k].extend(older.get(k, [""] * n))
    return e13.list_filings({"filings": {"recent": merged}})


def _figi_fill(fetcher, stocks, figi_key, figi_cache, log):
    """Best effort: a dead OpenFIGI leaves tickers empty but never loses the filing."""
    cache = (_read_json(figi_cache) if figi_cache else None) or {}
    for p in stocks:
        if not p.get("ticker") and cache.get(p["cusip"]):
            p["ticker"] = cache[p["cusip"]]
    missing = [p["cusip"] for p in stocks if not p.get("ticker")]
    if not missing:
        return
    try:
        found = e13.figi_lookup(fetcher, missing, api_key=figi_key, pause=FIGI_PAUSE)
    except (e13.EdgarError, OSError, ValueError, http.client.HTTPException) as exc:
        log("OpenFIGI: %s: %s" % (type(exc).__name__, exc))
        return
    for p in stocks:
        if not p.get("ticker") and p["cusip"] in found:
            p["ticker"] = found[p["cusip"]]
    if figi_cache and found:
        cache.update(found)
        try:
            _write_json_atomic(figi_cache, cache)
        except OSError as exc:
            log("OpenFIGI cache not saved: %s" % exc)


def top_positions(fetcher, cik, filing, index, overrides, top_n, figi_key=None,
                  log=print, figi_cache=None):
    base = e13.archive_url(cik, filing["accession"])
    table = e13.info_table_name(fetcher.get_json(base + "index.json"))
    rows = e13.parse_info_table(fetcher.get(base + table),
                                multiplier=e13.value_multiplier(filing["filed"]))
    positions, _total = e13.build({}, rows, index, overrides, combine=True)
    # Biggest stock positions whether or not a ticker was found: a missing ticker
    # becomes a no_price trade instead of silently pulling in the next position.
    stocks = [p for p in positions if e13.is_stock(p)][:top_n]
    if figi_key:
        _figi_fill(fetcher, stocks, figi_key, figi_cache, log)
    total = sum(p["value"] for p in stocks)
    return [{"rank": rank, "ticker": p.get("ticker") or "", "issuer": p["issuer"],
             "weight_fund": p["value"] / total if total else 0.0,
             "weight_equal": 1.0 / len(stocks)}
            for rank, p in enumerate(stocks, 1)]


def build_events(fetcher, filers, start, top_n, index, overrides, figi_key=None, log=print,
                 figi_cache=None):
    rows = []
    for f in filers:
        try:
            filings = all_filings(fetcher, f["cik"], log)
        except PARSE_ERRORS as exc:
            log("13F %s: %s: %s" % (f["name"], type(exc).__name__, exc))
            continue
        # One original 13F-HR per quarter: the earliest filed. Amendments are ignored.
        first = {}
        for x in sorted(filings, key=lambda x: x["filed"]):
            if x["form"] == "13F-HR" and x["filed"] >= start and x["period"] not in first:
                first[x["period"]] = x
        for filing in sorted(first.values(), key=lambda x: x["filed"]):
            try:
                tops = top_positions(fetcher, f["cik"], filing, index, overrides, top_n, figi_key,
                                     log, figi_cache)
            except PARSE_ERRORS as exc:
                log("13F %s %s: %s: %s" % (f["name"], filing["accession"],
                                           type(exc).__name__, exc))
                continue
            for t in tops:
                rows.append({"fund": f["name"], "cik": e13.cik10(f["cik"]),
                             "accession": filing["accession"], "period": filing["period"],
                             "filed": filing["filed"], **t})
    return pd.DataFrame(rows, columns=COLUMNS)
