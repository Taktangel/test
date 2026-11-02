"""13F-HR filings of the bundled funds -> one row per top-N stock position per filing."""
import os
import time

import pandas as pd

from vendor import edgar13f as e13

SUBMISSIONS_FILE = "https://data.sec.gov/submissions/%s"
KEYS = ("accessionNumber", "filingDate", "reportDate", "form", "primaryDocument")
COLUMNS = ["fund", "cik", "accession", "period", "filed", "rank", "ticker", "issuer",
           "weight_fund", "weight_equal"]
ARCHIVE_MARK = "/Archives/edgar/data/"


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
            except e13.EdgarError:
                if self.offline or attempt == 2 or (sec and not self.ua):
                    raise
                time.sleep(2 * (attempt + 1))
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        return data


def all_filings(fetcher, cik):
    """Every 13F filing of a filer, including the older pages SEC splits off."""
    sub = fetcher.get_json(e13.SUBMISSIONS % e13.cik10(cik))
    filings = sub.get("filings", {})
    recent = filings.get("recent", {})
    n0 = len(recent.get("accessionNumber", []))
    merged = {k: list(recent.get(k, [""] * n0)) for k in KEYS}
    for extra in filings.get("files", []):
        older = fetcher.get_json(SUBMISSIONS_FILE % extra["name"])
        n = len(older.get("accessionNumber", []))
        for k in KEYS:
            merged[k].extend(older.get(k, [""] * n))
    return e13.list_filings({"filings": {"recent": merged}})


def top_positions(fetcher, cik, filing, index, overrides, top_n, figi_key=None):
    base = e13.archive_url(cik, filing["accession"])
    table = e13.info_table_name(fetcher.get_json(base + "index.json"))
    rows = e13.parse_info_table(fetcher.get(base + table),
                                multiplier=e13.value_multiplier(filing["filed"]))
    positions, _total = e13.build({}, rows, index, overrides, combine=True)
    # Biggest stock positions whether or not a ticker was found: a missing ticker
    # becomes a no_price trade instead of silently pulling in the next position.
    stocks = [p for p in positions if e13.is_stock(p)][:top_n]
    if figi_key:
        missing = [p["cusip"] for p in stocks if not p.get("ticker")]
        if missing:
            found = e13.figi_lookup(fetcher, missing, api_key=figi_key)
            for p in stocks:
                if not p.get("ticker") and p["cusip"] in found:
                    p["ticker"] = found[p["cusip"]]
    total = sum(p["value"] for p in stocks)
    return [{"rank": rank, "ticker": p.get("ticker") or "", "issuer": p["issuer"],
             "weight_fund": p["value"] / total if total else 0.0,
             "weight_equal": 1.0 / len(stocks)}
            for rank, p in enumerate(stocks, 1)]


def build_events(fetcher, filers, start, top_n, index, overrides, figi_key=None, log=print):
    rows = []
    for f in filers:
        try:
            filings = all_filings(fetcher, f["cik"])
        except e13.EdgarError as exc:
            log("13F %s: %s" % (f["name"], exc))
            continue
        # One original 13F-HR per quarter: the earliest filed. Amendments are ignored.
        first = {}
        for x in sorted(filings, key=lambda x: x["filed"]):
            if x["form"] == "13F-HR" and x["filed"] >= start and x["period"] not in first:
                first[x["period"]] = x
        for filing in sorted(first.values(), key=lambda x: x["filed"]):
            try:
                tops = top_positions(fetcher, f["cik"], filing, index, overrides, top_n, figi_key)
            except e13.EdgarError as exc:
                log("13F %s %s: %s" % (f["name"], filing["accession"], exc))
                continue
            for t in tops:
                rows.append({"fund": f["name"], "cik": e13.cik10(f["cik"]),
                             "accession": filing["accession"], "period": filing["period"],
                             "filed": filing["filed"], **t})
    return pd.DataFrame(rows, columns=COLUMNS)
