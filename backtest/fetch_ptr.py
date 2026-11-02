"""House PTRs of chosen members -> one row per stock transaction."""
import http.client
import os
import time
import zipfile

import pandas as pd

from vendor import ptr

COLUMNS = ["member", "doc_id", "filed", "txn_date", "ticker", "side", "amount_low",
           "amount_high", "owner"]
ERRORS = (ptr.PtrError, zipfile.BadZipFile, ValueError, OSError, http.client.HTTPException)
SIDES = {"P": "buy", "S": "sell", "S (partial)": "sell"}


def _write_atomic(path, data, binary=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    if binary:
        with open(tmp, "wb") as fh:
            fh.write(data)
    else:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(data)
    os.replace(tmp, path)


def match_member(row, members):
    for m in members:
        if ptr.member_match(row, m):
            return m
    return None


def trades_from_report(report, member, doc_id, filed):
    out = []
    for r in report.get("rows", []):
        side = SIDES.get(r.get("type"))
        if not side or not r.get("ticker") or r.get("option"):
            continue
        # [ST] is a stock. Old filings may carry no asset code at all; options are [OP].
        if r.get("asset_type") not in ("ST", None):
            continue
        out.append({"member": member, "doc_id": doc_id, "filed": filed,
                    "txn_date": r.get("date"), "ticker": r["ticker"], "side": side,
                    "amount_low": r.get("amount_low"), "amount_high": r.get("amount_high"),
                    "owner": r.get("owner_name")})
    return out


def _download(url, tries=3):
    """ptr.download with a pause (2 s, 4 s) between attempts."""
    for attempt in range(tries):
        try:
            return ptr.download(url)
        except (ptr.PtrError, OSError, http.client.HTTPException):
            if attempt == tries - 1:
                raise
            time.sleep(2 * 2 ** attempt)


def _download_index(year, path):
    data = _download(ptr.INDEX_URL % (year, "FD"))
    rows = ptr.parse_index(ptr.read_index_bytes(data), year)  # validate before caching
    if not rows:
        raise ptr.PtrError("index %d came back empty or not an index" % year)
    _write_atomic(path, data, binary=True)
    return rows


def load_index_cached(year, cache_dir, this_year, log=print):
    path = os.path.join(cache_dir, "%dFD.zip" % year)
    if year >= this_year:
        # The current year changes all the time: refresh it, but keep the last good copy.
        try:
            return _download_index(year, path)
        except ERRORS as exc:
            if not os.path.isfile(path):
                raise
            log("PTR index %d: %s: %s; using the saved copy" % (year, type(exc).__name__, exc))
            return ptr.load_index(year, offline=path)
    if not os.path.isfile(path):
        return _download_index(year, path)
    try:
        return ptr.load_index(year, offline=path)
    except (ptr.PtrError, zipfile.BadZipFile):
        os.remove(path)  # corrupt cache: fetch it again once
        return _download_index(year, path)


def read_filing(row, cache_dir):
    text_path = os.path.join(cache_dir, "text", row["doc_id"] + ".txt")
    if os.path.isfile(text_path):
        with open(text_path, encoding="utf-8") as fh:
            text = fh.read()
    else:
        pdf_path = os.path.join(cache_dir, "pdf", row["doc_id"] + ".pdf")
        if not os.path.isfile(pdf_path):
            data = _download(row["url"])
            if not data.startswith(b"%PDF"):
                raise ptr.PtrError("doc %s did not come back as a PDF" % row["doc_id"])
            _write_atomic(pdf_path, data, binary=True)
        text = ptr.pdf_to_text(pdf_path)
        if not text or not text.strip():
            return None
        _write_atomic(text_path, text)
    return ptr.parse_ptr_text(text, filed=row["filed"] or None)


def build_trades(members, start_year, this_year, cache_dir, log=print):
    out = []
    for year in range(start_year, this_year + 1):
        try:
            rows = load_index_cached(year, cache_dir, this_year, log)
        except ERRORS as exc:
            log("PTR index %d: %s: %s" % (year, type(exc).__name__, exc))
            continue
        for r in ptr.select(rows, members=members, kind="P"):
            member = match_member(r, members)
            try:
                report = read_filing(r, cache_dir)
            except ERRORS as exc:
                log("PTR %s %s: %s: %s" % (member, r["doc_id"], type(exc).__name__, exc))
                continue
            if report is None:
                log("PTR %s %s: no text (scanned PDF or pdftotext missing)" % (member, r["doc_id"]))
                continue
            filed = r["filed"] or report.get("filed")
            if not filed:
                log("PTR %s %s: no filed date in the index or the report, skipped"
                    % (member, r["doc_id"]))
                continue
            out.extend(trades_from_report(report, member, r["doc_id"], filed))
    return pd.DataFrame(out, columns=COLUMNS)
