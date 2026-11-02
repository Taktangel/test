# Trader Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Бэктест двух стратегий из trader-skill (копирование 13F фондов и сделок членов Палаты) с еженедельным обновлением статистики в GitHub Actions.

**Architecture:** Парсеры `edgar13f.py` и `ptr.py` из trader-skill копируются в `vendor/` без изменений. Поверх них пакет `backtest/`: загрузка событий (13F, PTR) в CSV, кеш цен, превращение событий в сделки, метрики, отчёт. Каждый шаг читает и пишет простые CSV/JSON, `run.py` склеивает шаги.

**Tech Stack:** Python 3.11, pandas 2.2, numpy, matplotlib 3.9, pytest 8, GitHub Actions.

Спецификация: `docs/superpowers/specs/2026-11-03-trader-backtest-design.md`.

## Global Constraints

- Python 3.11. Зависимости только `pandas==2.2.3`, `matplotlib==3.9.2`, `pytest==8.3.3` (numpy приходит с pandas).
- Код trader-skill берётся из коммита `5189e79` репо `https://github.com/Jakeschincariol/trader-skill` (MIT), файлы в `vendor/` не редактируются.
- Период: с `2014-01-01`. Топ-N для Copycat: `10`. Сроки удержания для Congress: `30`, `90`, `180` дней и `until_sale` (максимум `365` дней). Fallback выхода Copycat: `120` дней после публикации.
- Вход всегда по закрытию первого торгового дня строго после даты публикации (13F `filed` или PTR `filed`). Никогда не по дате конца квартала или дате сделки конгрессмена.
- К SEC не больше 10 запросов в секунду (`pause=0.12`), User-Agent из `SEC_USER_AGENT` обязателен.
- Статусы сделок: `ok`, `open`, `pending`, `no_price`. Доли выигрышных считаются только по `ok`.
- Сетевой код в тестах не вызывается: все тесты офлайн.
- Все команды выполняются из корня `trader-backtest/`.
- Перед первым коммитом в git должны быть заданы `user.name` и `user.email` (сейчас не заданы).

## File Structure

```
trader-backtest/
  requirements.txt
  pytest.ini
  config.json                 параметры бэктеста
  members.json                члены Палаты
  vendor/
    __init__.py
    LICENSE                   MIT trader-skill
    edgar13f.py               из trader-copycat/
    filers.json               из trader-copycat/
    share_classes.json        из trader-copycat/
    ptr.py                    из trader-pelosi/
  backtest/
    __init__.py
    prices.py                 цены: Yahoo → stooq, кеш CSV
    fetch_13f.py              13F → events_13f.csv
    fetch_ptr.py              PTR → trades_ptr.csv
    strategies.py             события → сделки
    metrics.py                доходности, сводки, кривые капитала
    report.py                 latest.md, trades.csv, summary.json, equity.png, errors.log
    run.py                    точка входа
  tests/
    helpers.py                синтетические ряды цен и FakeStore
    fixtures/copycat/         из trader-skill tests/fixtures/trader-copycat
    fixtures/pelosi/          из trader-skill tests/fixtures/trader-pelosi
    test_vendor.py
    test_prices.py
    test_fetch_13f.py
    test_fetch_ptr.py
    test_strategies.py
    test_metrics.py
    test_report.py
    test_run.py
  .github/workflows/backtest.yml
  README.md
  .gitignore
```

---

### Task 1: Каркас проекта и vendor

**Files:**
- Create: `requirements.txt`, `pytest.ini`, `.gitignore`, `vendor/__init__.py`, `backtest/__init__.py`, `tests/helpers.py`, `tests/test_vendor.py`
- Copy: `vendor/edgar13f.py`, `vendor/filers.json`, `vendor/share_classes.json`, `vendor/ptr.py`, `vendor/LICENSE`, `tests/fixtures/copycat/`, `tests/fixtures/pelosi/`

**Interfaces:**
- Produces: импорт `from vendor import edgar13f as e13` и `from vendor import ptr`; `tests/helpers.py`: `series(start: str, values: list) -> pd.Series` (рабочие дни с `start`), `class FakeStore(data: dict)` с методом `get(ticker) -> pd.Series | None`.

- [ ] **Step 1: Скопировать код и фикстуры trader-skill**

```bash
git clone https://github.com/Jakeschincariol/trader-skill.git ../_trader-skill-src
git -C ../_trader-skill-src checkout 5189e79
mkdir -p vendor backtest tests/fixtures
cp ../_trader-skill-src/trader-copycat/edgar13f.py ../_trader-skill-src/trader-copycat/filers.json ../_trader-skill-src/trader-copycat/share_classes.json vendor/
cp ../_trader-skill-src/trader-pelosi/ptr.py vendor/
cp ../_trader-skill-src/LICENSE vendor/LICENSE
cp -r ../_trader-skill-src/tests/fixtures/trader-copycat tests/fixtures/copycat
cp -r ../_trader-skill-src/tests/fixtures/trader-pelosi tests/fixtures/pelosi
```

- [ ] **Step 2: Создать служебные файлы**

`requirements.txt`:
```
pandas==2.2.3
matplotlib==3.9.2
pytest==8.3.3
```

`pytest.ini`:
```ini
[pytest]
testpaths = tests
pythonpath = .
```

`.gitignore`:
```
__pycache__/
.pytest_cache/
data/
.venv/
```

`vendor/__init__.py`:
```python
"""Unmodified parsers from trader-skill (MIT), commit 5189e79."""
```

`backtest/__init__.py`:
```python
"""Backtest of the trader-skill copycat (13F) and congress (PTR) strategies."""
```

`tests/helpers.py`:
```python
import pandas as pd


def series(start, values):
    """Prices on consecutive business days starting at `start`."""
    idx = pd.bdate_range(start, periods=len(values))
    return pd.Series([float(v) for v in values], index=idx)


class FakeStore:
    """Stands in for PriceStore: returns prepared series, None for unknown tickers."""

    def __init__(self, data):
        self.data = data

    def get(self, ticker):
        return self.data.get(ticker)
```

- [ ] **Step 3: Написать тест на vendor**

`tests/test_vendor.py`:
```python
from vendor import edgar13f as e13
from vendor import ptr


def test_vendor_modules_load():
    filers = e13.load_filers()
    assert len(filers) == 23
    assert filers[0]["cik"] == "0001067983"
    assert ptr.iso("8/21/2026") == "2026-08-21"


def test_share_class_overrides_load():
    overrides = e13.load_overrides([e13.CLASSES])
    assert overrides["02079K305"] == "GOOGL"
```

- [ ] **Step 4: Установить зависимости и прогнать тест**

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pytest tests/test_vendor.py -v
```
(на Linux/macOS: `.venv/bin/python`)
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "chore: scaffold project and vendor trader-skill parsers"
```

---

### Task 2: Цены (`prices.py`)

**Files:**
- Create: `backtest/prices.py`
- Test: `tests/test_prices.py`

**Interfaces:**
- Produces:
  - `yahoo_symbol(ticker: str) -> str` (`"BRK.B"` → `"BRK-B"`)
  - `parse_yahoo(data: dict) -> pd.Series | None`
  - `parse_stooq(text: str) -> pd.Series | None`
  - `fetch_yahoo(symbol: str, start: str) -> pd.Series | None`, `fetch_stooq(symbol: str, start: str) -> pd.Series | None`
  - `class PriceStore(cache_dir: str, start: str = "2014-01-01", fetchers: list | None = None, max_age_hours: float = 20)` с методом `get(ticker) -> pd.Series | None`. Ряд: скорректированные цены закрытия, индекс `DatetimeIndex` по датам без времени, отсортирован.

- [ ] **Step 1: Написать тесты**

`tests/test_prices.py`:
```python
import os

import pandas as pd

from backtest import prices
from helpers import series


def test_yahoo_symbol():
    assert prices.yahoo_symbol("brk.b") == "BRK-B"
    assert prices.yahoo_symbol("BF/B") == "BF-B"


def test_parse_yahoo_uses_adjclose_and_drops_nulls():
    data = {"chart": {"result": [{
        "timestamp": [1577975400, 1578061800, 1578321000],  # 2020-01-02/03/06 14:30 UTC
        "indicators": {"quote": [{"close": [10.0, 11.0, 12.0]}],
                       "adjclose": [{"adjclose": [9.5, None, 11.5]}]},
    }]}}
    s = prices.parse_yahoo(data)
    assert list(s.index.strftime("%Y-%m-%d")) == ["2020-01-02", "2020-01-06"]
    assert list(s.values) == [9.5, 11.5]


def test_parse_yahoo_bad_payload_returns_none():
    assert prices.parse_yahoo({"chart": {"result": None, "error": {"code": "Not Found"}}}) is None


def test_parse_stooq():
    text = "Date,Open,High,Low,Close,Volume\n2020-01-03,1,1,1,5.5,10\n2020-01-02,1,1,1,5.0,10\n"
    s = prices.parse_stooq(text)
    assert list(s.index.strftime("%Y-%m-%d")) == ["2020-01-02", "2020-01-03"]
    assert list(s.values) == [5.0, 5.5]


def test_parse_stooq_garbage_returns_none():
    assert prices.parse_stooq("No data") is None


def test_store_falls_back_and_caches(tmp_path):
    good = series("2020-01-01", [1, 2, 3])
    calls = []

    def empty(symbol, start):
        calls.append(("empty", symbol))
        return None

    def full(symbol, start):
        calls.append(("full", symbol))
        return good

    store = prices.PriceStore(str(tmp_path), fetchers=[empty, full])
    s = store.get("brk.b")
    assert list(s.values) == [1.0, 2.0, 3.0]
    assert calls == [("empty", "BRK-B"), ("full", "BRK-B")]
    assert os.path.isfile(tmp_path / "BRK-B.csv")

    cached = prices.PriceStore(str(tmp_path), fetchers=[])
    s2 = cached.get("BRK.B")
    assert list(s2.values) == [1.0, 2.0, 3.0]
    assert isinstance(s2.index, pd.DatetimeIndex)


def test_store_returns_none_for_missing_and_blank(tmp_path):
    store = prices.PriceStore(str(tmp_path), fetchers=[lambda s, d: None])
    assert store.get("ZZZZ") is None
    assert store.get("") is None
    assert store.get(None) is None


def test_store_uses_stale_cache_when_sources_fail(tmp_path):
    prices.PriceStore(str(tmp_path), fetchers=[lambda s, d: series("2020-01-01", [7])]).get("AAA")
    os.utime(tmp_path / "AAA.csv", (0, 0))  # make the cache file ancient
    store = prices.PriceStore(str(tmp_path), fetchers=[lambda s, d: None])
    assert list(store.get("AAA").values) == [7.0]
```

- [ ] **Step 2: Запустить и убедиться, что падают**

Run: `.venv/Scripts/python -m pytest tests/test_prices.py -v`
Expected: FAIL, `ImportError: cannot import name 'prices'`

- [ ] **Step 3: Реализация**

`backtest/prices.py`:
```python
"""Daily adjusted close prices with a disk cache. Yahoo first, stooq as a fallback."""
import io
import json
import os
import time
import urllib.error
import urllib.request

import pandas as pd

UA = "Mozilla/5.0 (trader-backtest)"
YAHOO = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
         "?period1=%d&period2=%d&interval=1d&events=div%%2Csplit&includeAdjustedClose=true")
STOOQ = "https://stooq.com/q/d/l/?s=%s&i=d"


def yahoo_symbol(ticker):
    return ticker.strip().upper().replace(".", "-").replace("/", "-")


def _clean(s):
    s = s.dropna()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s if not s.empty else None


def parse_yahoo(data):
    try:
        res = data["chart"]["result"][0]
        ts = res["timestamp"]
        ind = res["indicators"]
        closes = ind["adjclose"][0]["adjclose"] if ind.get("adjclose") else ind["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        return None
    idx = pd.to_datetime(ts, unit="s").normalize()
    return _clean(pd.Series(closes, index=idx, dtype="float64"))


def parse_stooq(text):
    try:
        df = pd.read_csv(io.StringIO(text))
    except (ValueError, pd.errors.ParserError):
        return None
    if "Date" not in df.columns or "Close" not in df.columns:
        return None
    s = pd.Series(pd.to_numeric(df["Close"], errors="coerce").values,
                  index=pd.to_datetime(df["Date"], errors="coerce"))
    return _clean(s[s.index.notna()])


def _http(url, timeout=30, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(2 * (i + 1))
    return None


def fetch_yahoo(symbol, start):
    p1 = int(pd.Timestamp(start).timestamp())
    p2 = int(time.time()) + 86400
    raw = _http(YAHOO % (symbol, p1, p2))
    if raw is None:
        return None
    try:
        return parse_yahoo(json.loads(raw.decode("utf-8")))
    except ValueError:
        return None


def fetch_stooq(symbol, start):
    raw = _http(STOOQ % (symbol.lower() + ".us"))
    if raw is None:
        return None
    s = parse_stooq(raw.decode("utf-8", "replace"))
    if s is None:
        return None
    return _clean(s[s.index >= pd.Timestamp(start)])


class PriceStore:
    """get(ticker) -> adjusted closes, cached as data/prices/<SYMBOL>.csv."""

    def __init__(self, cache_dir, start="2014-01-01", fetchers=None, max_age_hours=20):
        self.cache_dir = cache_dir
        self.start = start
        self.fetchers = [fetch_yahoo, fetch_stooq] if fetchers is None else fetchers
        self.max_age = max_age_hours * 3600
        self._mem = {}
        os.makedirs(cache_dir, exist_ok=True)

    def _path(self, symbol):
        return os.path.join(self.cache_dir, symbol + ".csv")

    def _read_cache(self, symbol, any_age=False):
        path = self._path(symbol)
        if not os.path.isfile(path):
            return None
        stale = time.time() - os.path.getmtime(path) > self.max_age
        if self.fetchers and stale and not any_age:
            return None
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return _clean(df["close"].astype(float))

    def get(self, ticker):
        if not isinstance(ticker, str) or not ticker.strip():
            return None
        symbol = yahoo_symbol(ticker)
        if symbol in self._mem:
            return self._mem[symbol]
        s = self._read_cache(symbol)
        if s is None:
            for fetch in self.fetchers:
                s = fetch(symbol, self.start)
                if s is not None and not s.empty:
                    s.rename("close").to_csv(self._path(symbol), index_label="date")
                    break
                s = None
            if s is None:
                # Sources down this time: an old cached copy beats no prices at all.
                s = self._read_cache(symbol, any_age=True)
        self._mem[symbol] = s
        return s
```

Примечание: при `fetchers=[]` кеш читается без проверки возраста (так работает второй стор в тесте и режим `--skip-fetch` не нужен для цен).

- [ ] **Step 4: Запустить тесты**

Run: `.venv/Scripts/python -m pytest tests/test_prices.py -v`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add backtest/prices.py tests/test_prices.py
git commit -m "feat: price store with Yahoo/stooq fallback and disk cache"
```

---

### Task 3: События 13F (`fetch_13f.py`)

**Files:**
- Create: `backtest/fetch_13f.py`
- Test: `tests/test_fetch_13f.py`

**Interfaces:**
- Consumes: `vendor.edgar13f` (`Fetcher`, `SUBMISSIONS`, `cik10`, `list_filings`, `archive_url`, `info_table_name`, `parse_info_table`, `value_multiplier`, `build`, `is_stock`, `figi_lookup`, `EdgarError`).
- Produces:
  - `class CachedFetcher(cache_dir: str, **fetcher_kwargs)`: `e13.Fetcher`, который навсегда кеширует файлы `/Archives/edgar/data/...` на диск.
  - `all_filings(fetcher, cik) -> list[dict]` (ключи как у `e13.list_filings`: `form`, `accession`, `filed`, `period`, `primary`).
  - `top_positions(fetcher, cik, filing: dict, index, overrides: dict, top_n: int, figi_key: str | None = None) -> list[dict]` с ключами `rank`, `ticker` (`""` если не найден), `issuer`, `weight_fund`, `weight_equal`.
  - `build_events(fetcher, filers: list[dict], start: str, top_n: int, index, overrides: dict, figi_key=None, log=print) -> pd.DataFrame` с колонками `COLUMNS = ["fund", "cik", "accession", "period", "filed", "rank", "ticker", "issuer", "weight_fund", "weight_equal"]`.

- [ ] **Step 1: Написать тесты**

`tests/test_fetch_13f.py`:
```python
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
```

- [ ] **Step 2: Запустить и убедиться, что падают**

Run: `.venv/Scripts/python -m pytest tests/test_fetch_13f.py -v`
Expected: FAIL, `ImportError: cannot import name 'fetch_13f'`

- [ ] **Step 3: Реализация**

`backtest/fetch_13f.py`:
```python
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
                if self.offline or attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)
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
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv/Scripts/python -m pytest tests/test_fetch_13f.py -v`
Expected: `3 passed`. Если в фикстуре есть 13F-HR, для которого нет папки с файлами, он попадёт в `errors`, и это нормально: тест проверяет только Q1 и Q2.

- [ ] **Step 5: Commit**

```bash
git add backtest/fetch_13f.py tests/test_fetch_13f.py
git commit -m "feat: collect top-N 13F positions per filing with full filing history"
```

---

### Task 4: Сделки Конгресса (`fetch_ptr.py`)

**Files:**
- Create: `backtest/fetch_ptr.py`
- Test: `tests/test_fetch_ptr.py`

**Interfaces:**
- Consumes: `vendor.ptr` (`load_index`, `select`, `member_match`, `download`, `pdf_to_text`, `parse_ptr_text`, `INDEX_URL`, `PtrError`).
- Produces:
  - `COLUMNS = ["member", "doc_id", "filed", "txn_date", "ticker", "side", "amount_low", "amount_high", "owner"]`; `side` ∈ `{"buy", "sell"}`.
  - `match_member(row: dict, members: list[str]) -> str | None` (возвращает запись из `members`, а не имя из индекса).
  - `trades_from_report(report: dict, member: str, doc_id: str, filed: str) -> list[dict]`.
  - `load_index_cached(year: int, cache_dir: str, this_year: int) -> list[dict]`.
  - `read_filing(row: dict, cache_dir: str) -> dict | None` (`None`, если в PDF нет текста).
  - `build_trades(members: list[str], start_year: int, this_year: int, cache_dir: str, log=print) -> pd.DataFrame`.

- [ ] **Step 1: Написать тесты**

`tests/test_fetch_ptr.py`:
```python
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
```

- [ ] **Step 2: Запустить и убедиться, что падают**

Run: `.venv/Scripts/python -m pytest tests/test_fetch_ptr.py -v`
Expected: FAIL, `ImportError: cannot import name 'fetch_ptr'`

- [ ] **Step 3: Реализация**

`backtest/fetch_ptr.py`:
```python
"""House PTRs of chosen members -> one row per stock transaction."""
import os

import pandas as pd

from vendor import ptr

COLUMNS = ["member", "doc_id", "filed", "txn_date", "ticker", "side", "amount_low",
           "amount_high", "owner"]
SIDES = {"P": "buy", "S": "sell", "S (partial)": "sell"}


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


def load_index_cached(year, cache_dir, this_year):
    path = os.path.join(cache_dir, "%dFD.zip" % year)
    if year >= this_year or not os.path.isfile(path):
        data = ptr.download(ptr.INDEX_URL % (year, "FD"))
        os.makedirs(cache_dir, exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
    return ptr.load_index(year, offline=path)


def read_filing(row, cache_dir):
    text_path = os.path.join(cache_dir, "text", row["doc_id"] + ".txt")
    if os.path.isfile(text_path):
        with open(text_path, encoding="utf-8") as fh:
            text = fh.read()
    else:
        pdf_path = os.path.join(cache_dir, "pdf", row["doc_id"] + ".pdf")
        if not os.path.isfile(pdf_path):
            data = ptr.download(row["url"])
            if not data.startswith(b"%PDF"):
                raise ptr.PtrError("doc %s did not come back as a PDF" % row["doc_id"])
            os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
            with open(pdf_path, "wb") as fh:
                fh.write(data)
        text = ptr.pdf_to_text(pdf_path)
        if not text or not text.strip():
            return None
        os.makedirs(os.path.dirname(text_path), exist_ok=True)
        with open(text_path, "w", encoding="utf-8") as fh:
            fh.write(text)
    return ptr.parse_ptr_text(text, filed=row["filed"])


def build_trades(members, start_year, this_year, cache_dir, log=print):
    out = []
    for year in range(start_year, this_year + 1):
        try:
            rows = load_index_cached(year, cache_dir, this_year)
        except ptr.PtrError as exc:
            log("PTR index %d: %s" % (year, exc))
            continue
        for r in ptr.select(rows, members=members, kind="P"):
            member = match_member(r, members)
            try:
                report = read_filing(r, cache_dir)
            except ptr.PtrError as exc:
                log("PTR %s %s: %s" % (member, r["doc_id"], exc))
                continue
            if report is None:
                log("PTR %s %s: no text (scanned PDF or pdftotext missing)" % (member, r["doc_id"]))
                continue
            out.extend(trades_from_report(report, member, r["doc_id"], r["filed"]))
    return pd.DataFrame(out, columns=COLUMNS)
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv/Scripts/python -m pytest tests/test_fetch_ptr.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add backtest/fetch_ptr.py tests/test_fetch_ptr.py
git commit -m "feat: collect stock trades from House PTRs of chosen members"
```

---

### Task 5: Стратегии (`strategies.py`)

**Files:**
- Create: `backtest/strategies.py`
- Test: `tests/test_strategies.py`

**Interfaces:**
- Consumes: DataFrame событий из Task 3 (`fund`, `filed`, `ticker`, `weight_fund`, `weight_equal`), DataFrame из Task 4 (`member`, `filed`, `ticker`, `side`), любой объект с `get(ticker) -> pd.Series | None`.
- Produces:
  - `TRADE_COLUMNS = ["strategy", "variant", "source", "ticker", "signal_date", "entry_date", "entry_px", "exit_date", "exit_px", "weight", "status", "note"]`; даты строками `YYYY-MM-DD`.
  - `first_after(series, day) -> (pd.Timestamp, float) | None`, `first_on_or_after(series, day) -> (pd.Timestamp, float) | None`.
  - `price_trade(series, signal_date: str, exit_rule, market_end: pd.Timestamp) -> dict`, где `exit_rule(entry_ts) -> ("after" | "on_or_after", date)`.
  - `copycat_trades(events, store, market_end, fallback_days=120) -> pd.DataFrame` (варианты `equal`, `fund`).
  - `congress_trades(ptr_trades, store, market_end, holds=(30, 90, 180), sale_max_days=365) -> pd.DataFrame` (варианты `hold30`, `hold90`, `hold180`, `until_sale`).

- [ ] **Step 1: Написать тесты**

`tests/test_strategies.py`:
```python
import pandas as pd

from backtest import strategies as st
from helpers import FakeStore, series

AAA = series("2020-01-01", [100 + i for i in range(300)])  # ends 2021-02-23
BBB = series("2020-01-01", [50] * 40)                        # stops trading 2020-02-25
END = AAA.index[-1]


def _events(rows):
    return pd.DataFrame(rows, columns=["fund", "filed", "ticker", "weight_fund", "weight_equal"])


def test_copycat_enters_next_day_and_exits_after_next_filing():
    ev = _events([("F", "2020-01-03", "AAA", 1.0, 1.0), ("F", "2020-04-01", "AAA", 1.0, 1.0)])
    t = st.copycat_trades(ev, FakeStore({"AAA": AAA}), END)
    assert list(t.columns) == st.TRADE_COLUMNS
    assert set(t["variant"]) == {"equal", "fund"}
    first = t[(t.variant == "equal") & (t.signal_date == "2020-01-03")].iloc[0]
    assert first.entry_date == "2020-01-06"   # Friday signal -> Monday entry
    assert first.entry_px == 103.0
    assert first.exit_date == "2020-04-02"    # first close after the next filing
    assert first.status == "ok"
    second = t[(t.variant == "equal") & (t.signal_date == "2020-04-01")].iloc[0]
    assert second.exit_date == "2020-07-30"   # fallback: 120 days after the filing
    assert second.status == "ok"


def test_copycat_statuses():
    ev = _events([
        ("F", "2020-01-03", "", 0.5, 0.5),
        ("F", "2020-01-03", "ZZZ", 0.5, 0.5),
        ("G", "2020-01-03", "BBB", 1.0, 1.0),
        ("G", "2020-04-01", "BBB", 1.0, 1.0),
        ("H", AAA.index[-10].date().isoformat(), "AAA", 1.0, 1.0),
        ("K", END.date().isoformat(), "AAA", 1.0, 1.0),
    ])
    t = st.copycat_trades(ev, FakeStore({"AAA": AAA, "BBB": BBB}), END)
    t = t[t.variant == "equal"]
    assert list(t[t.source == "F"].status) == ["no_price", "no_price"]
    g = t[(t.source == "G") & (t.signal_date == "2020-01-03")].iloc[0]
    assert (g.status, g.note, g.exit_date) == ("ok", "last_available", "2020-02-25")
    h = t[t.source == "H"].iloc[0]
    assert (h.status, h.exit_px) == ("open", float(AAA.iloc[-1]))
    assert t[t.source == "K"].iloc[0].status == "pending"


def _ptr(rows):
    return pd.DataFrame(rows, columns=["member", "filed", "ticker", "side"])


def test_congress_hold_and_until_sale():
    trades = _ptr([
        ("Pelosi", "2020-01-03", "AAA", "buy"),
        ("Khanna", "2020-02-03", "AAA", "sell"),   # other member: ignored
        ("Pelosi", "2020-03-02", "AAA", "sell"),
    ])
    t = st.congress_trades(trades, FakeStore({"AAA": AAA}), END, holds=(30,))
    assert set(t["variant"]) == {"hold30", "until_sale"}
    assert len(t) == 2  # sells never open trades
    h = t[t.variant == "hold30"].iloc[0]
    assert (h.entry_date, h.exit_date, h.source) == ("2020-01-06", "2020-02-05", "Pelosi")
    u = t[t.variant == "until_sale"].iloc[0]
    assert u.exit_date == "2020-03-03"


def test_congress_until_sale_without_sale_uses_max_days():
    t = st.congress_trades(_ptr([("Pelosi", "2020-01-03", "AAA", "buy")]),
                           FakeStore({"AAA": AAA}), END, holds=(), sale_max_days=365)
    u = t[t.variant == "until_sale"].iloc[0]
    assert u.exit_date == "2021-01-05"   # entry 2020-01-06 + 365 days


def test_congress_empty_input():
    t = st.congress_trades(_ptr([]), FakeStore({}), END)
    assert t.empty and list(t.columns) == st.TRADE_COLUMNS
```

- [ ] **Step 2: Запустить и убедиться, что падают**

Run: `.venv/Scripts/python -m pytest tests/test_strategies.py -v`
Expected: FAIL, `ImportError: cannot import name 'strategies'`

- [ ] **Step 3: Реализация**

`backtest/strategies.py`:
```python
"""Signals -> trades with entry and exit prices. No lookahead: entry is the first
close strictly after the day the signal became public."""
import pandas as pd

TRADE_COLUMNS = ["strategy", "variant", "source", "ticker", "signal_date", "entry_date",
                 "entry_px", "exit_date", "exit_px", "weight", "status", "note"]


def first_after(series, day):
    i = series.index.searchsorted(pd.Timestamp(day), side="right")
    return None if i >= len(series) else (series.index[i], float(series.iloc[i]))


def first_on_or_after(series, day):
    i = series.index.searchsorted(pd.Timestamp(day), side="left")
    return None if i >= len(series) else (series.index[i], float(series.iloc[i]))


def _iso(ts):
    return ts.date().isoformat()


def price_trade(series, signal_date, exit_rule, market_end):
    out = {"entry_date": None, "entry_px": None, "exit_date": None, "exit_px": None,
           "status": "no_price", "note": ""}
    if series is None or len(series) == 0:
        return out
    last_ts, last_px = series.index[-1], float(series.iloc[-1])
    entry = first_after(series, signal_date)
    if entry is None:
        if last_ts >= market_end:
            out["status"] = "pending"
        return out
    out["entry_date"], out["entry_px"] = _iso(entry[0]), entry[1]
    kind, target = exit_rule(entry[0])
    finder = first_after if kind == "after" else first_on_or_after
    exit_ = finder(series, target)
    if exit_ is None:
        out["exit_date"], out["exit_px"] = _iso(last_ts), last_px
        if last_ts >= market_end:
            out["status"] = "open"
        else:
            out["status"], out["note"] = "ok", "last_available"
        return out
    out["exit_date"], out["exit_px"], out["status"] = _iso(exit_[0]), exit_[1], "ok"
    return out


def _ticker(value):
    return value.strip() if isinstance(value, str) else ""


def copycat_trades(events, store, market_end, fallback_days=120):
    rows = []
    for fund, g in events.groupby("fund"):
        dates = sorted(g["filed"].unique())
        for i, filed in enumerate(dates):
            if i + 1 < len(dates):
                rule = lambda e, d=dates[i + 1]: ("after", d)
            else:
                rule = lambda e, d=filed: ("on_or_after",
                                           pd.Timestamp(d) + pd.Timedelta(days=fallback_days))
            for ev in g[g["filed"] == filed].itertuples():
                ticker = _ticker(ev.ticker)
                priced = price_trade(store.get(ticker) if ticker else None, filed, rule, market_end)
                for variant, weight in (("equal", ev.weight_equal), ("fund", ev.weight_fund)):
                    rows.append({"strategy": "copycat", "variant": variant, "source": fund,
                                 "ticker": ticker, "signal_date": filed,
                                 "weight": float(weight), **priced})
    return pd.DataFrame(rows, columns=TRADE_COLUMNS)


def congress_trades(ptr_trades, store, market_end, holds=(30, 90, 180), sale_max_days=365):
    rows = []
    if ptr_trades.empty:
        return pd.DataFrame(rows, columns=TRADE_COLUMNS)
    sells = ptr_trades[ptr_trades["side"] == "sell"]
    for b in ptr_trades[ptr_trades["side"] == "buy"].itertuples():
        ticker = _ticker(b.ticker)
        series = store.get(ticker) if ticker else None
        rules = {"hold%d" % n: (lambda e, n=n: ("on_or_after", e + pd.Timedelta(days=n)))
                 for n in holds}
        limit = (pd.Timestamp(b.filed) + pd.Timedelta(days=sale_max_days)).date().isoformat()
        later = sells[(sells["member"] == b.member) & (sells["ticker"] == b.ticker)
                      & (sells["filed"] > b.filed) & (sells["filed"] <= limit)]
        if len(later):
            rules["until_sale"] = lambda e, d=later["filed"].min(): ("after", d)
        else:
            rules["until_sale"] = lambda e: ("on_or_after", e + pd.Timedelta(days=sale_max_days))
        for variant, rule in rules.items():
            rows.append({"strategy": "congress", "variant": variant, "source": b.member,
                         "ticker": ticker, "signal_date": b.filed, "weight": 1.0,
                         **price_trade(series, b.filed, rule, market_end)})
    return pd.DataFrame(rows, columns=TRADE_COLUMNS)
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv/Scripts/python -m pytest tests/test_strategies.py -v`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add backtest/strategies.py tests/test_strategies.py
git commit -m "feat: turn 13F and PTR signals into priced trades without lookahead"
```

---

### Task 6: Метрики (`metrics.py`)

**Files:**
- Create: `backtest/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: DataFrame сделок из Task 5, ряд SPY (`pd.Series`), стор с `get`.
- Produces:
  - `add_returns(trades, spy) -> pd.DataFrame`: добавляет `ret`, `spy_ret`, `excess` (доли, не проценты), `win_abs`, `win_spy` (bool).
  - `SUMMARY_COLUMNS = ["trades", "win_abs_pct", "win_spy_pct", "mean_ret_pct", "median_ret_pct", "mean_excess_pct", "open", "no_price"]`.
  - `summarize(trades, keys: list[str]) -> pd.DataFrame` (колонки `keys + SUMMARY_COLUMNS`; `trades` и доли только по `status == "ok"`).
  - `daily_equity(trades, store, calendar: pd.DatetimeIndex) -> pd.Series | None` (капитал с 1.0).
  - `cagr(equity) -> float`, `max_drawdown(equity) -> float` (доли, просадка отрицательная).
  - `BOOK_COLUMNS = ["strategy", "variant", "start", "end", "cagr_pct", "spy_cagr_pct", "max_dd_pct", "spy_max_dd_pct"]`.
  - `book_stats(trades, store, spy) -> (pd.DataFrame, dict[str, pd.Series])`; ключ словаря `"strategy/variant"`.

- [ ] **Step 1: Написать тесты**

`tests/test_metrics.py`:
```python
import math

import pandas as pd
import pytest

from backtest import metrics
from backtest.strategies import TRADE_COLUMNS
from helpers import FakeStore, series

SPY = series("2020-01-01", [100, 100, 100, 100, 110])  # 01-01 .. 01-07


def _trades():
    rows = [
        ("copycat", "equal", "F", "AAA", "2020-01-01", "2020-01-02", 50.0, "2020-01-07", 60.0, 1.0, "ok", ""),
        ("copycat", "equal", "F", "BBB", "2020-01-01", "2020-01-02", 100.0, "2020-01-07", 95.0, 1.0, "ok", ""),
        ("copycat", "equal", "G", "CCC", "2020-01-01", "2020-01-02", 10.0, "2020-01-07", 20.0, 1.0, "open", ""),
        ("copycat", "equal", "G", "", "2020-01-01", None, None, None, None, 1.0, "no_price", ""),
    ]
    return pd.DataFrame(rows, columns=TRADE_COLUMNS)


def test_add_returns():
    t = metrics.add_returns(_trades(), SPY)
    assert t.loc[0, "ret"] == pytest.approx(0.2)
    assert t.loc[0, "spy_ret"] == pytest.approx(0.1)
    assert t.loc[0, "excess"] == pytest.approx(0.1)
    assert bool(t.loc[0, "win_abs"]) and bool(t.loc[0, "win_spy"])
    assert t.loc[1, "ret"] == pytest.approx(-0.05)
    assert not bool(t.loc[1, "win_abs"]) and not bool(t.loc[1, "win_spy"])
    assert math.isnan(t.loc[3, "ret"])


def test_summarize_counts_only_closed_trades():
    s = metrics.summarize(metrics.add_returns(_trades(), SPY), ["strategy", "variant"])
    row = s.iloc[0]
    assert list(s.columns) == ["strategy", "variant"] + metrics.SUMMARY_COLUMNS
    assert row.trades == 2
    assert row.win_abs_pct == pytest.approx(50.0)
    assert row.win_spy_pct == pytest.approx(50.0)
    assert row.mean_ret_pct == pytest.approx(7.5)
    assert row.median_ret_pct == pytest.approx(7.5)
    assert row.mean_excess_pct == pytest.approx(-2.5)
    assert (row.open, row.no_price) == (1, 1)


def test_daily_equity_single_trade():
    aaa = series("2020-01-01", [100, 100, 105, 110, 120])
    cal = aaa.index
    t = pd.DataFrame([("x", "y", "s", "AAA", "2020-01-01", "2020-01-02", 100.0, "2020-01-06", 110.0, 1.0, "ok", "")],
                     columns=TRADE_COLUMNS)
    eq = metrics.daily_equity(t, FakeStore({"AAA": aaa}), cal)
    assert list(eq.index.strftime("%Y-%m-%d")) == ["2020-01-02", "2020-01-03", "2020-01-06"]
    assert list(eq.round(6)) == [1.0, 1.05, 1.1]


def test_cagr_and_drawdown():
    eq = pd.Series([1.0, 1.21], index=pd.to_datetime(["2020-01-01", "2022-01-01"]))
    assert metrics.cagr(eq) == pytest.approx(0.1, abs=1e-3)
    dd = pd.Series([1.0, 1.2, 0.9, 1.0], index=pd.bdate_range("2020-01-01", periods=4))
    assert metrics.max_drawdown(dd) == pytest.approx(-0.25)


def test_book_stats():
    aaa = series("2020-01-01", [100, 100, 105, 110, 120])
    spy = series("2020-01-01", [100, 100, 101, 102, 103])
    t = pd.DataFrame([("copycat", "equal", "F", "AAA", "2020-01-01", "2020-01-02", 100.0, "2020-01-07", 120.0, 1.0, "ok", "")],
                     columns=TRADE_COLUMNS)
    books, curves = metrics.book_stats(t, FakeStore({"AAA": aaa}), spy)
    assert list(books.columns) == metrics.BOOK_COLUMNS
    assert books.iloc[0].start == "2020-01-02"
    assert "copycat/equal" in curves
    assert curves["copycat/equal"].iloc[-1] == pytest.approx(1.2)
```

- [ ] **Step 2: Запустить и убедиться, что падают**

Run: `.venv/Scripts/python -m pytest tests/test_metrics.py -v`
Expected: FAIL, `ImportError: cannot import name 'metrics'`

- [ ] **Step 3: Реализация**

`backtest/metrics.py`:
```python
"""Per-trade returns against SPY, summaries and daily equity curves."""
import numpy as np
import pandas as pd

PRICED = ("ok", "open")
SUMMARY_COLUMNS = ["trades", "win_abs_pct", "win_spy_pct", "mean_ret_pct", "median_ret_pct",
                   "mean_excess_pct", "open", "no_price"]
BOOK_COLUMNS = ["strategy", "variant", "start", "end", "cagr_pct", "spy_cagr_pct",
                "max_dd_pct", "spy_max_dd_pct"]


def add_returns(trades, spy):
    t = trades.copy()
    entry = pd.to_numeric(t["entry_px"], errors="coerce")
    exit_ = pd.to_numeric(t["exit_px"], errors="coerce")
    priced = t["status"].isin(PRICED)
    t["ret"] = np.where(priced, exit_ / entry - 1.0, np.nan)
    spy_ret = []
    for row in t.itertuples():
        if row.status in PRICED:
            a = spy.asof(pd.Timestamp(row.entry_date))
            b = spy.asof(pd.Timestamp(row.exit_date))
            spy_ret.append(b / a - 1.0)
        else:
            spy_ret.append(np.nan)
    t["spy_ret"] = np.array(spy_ret, dtype="float64")
    t["excess"] = t["ret"] - t["spy_ret"]
    t["win_abs"] = t["ret"] > 0
    t["win_spy"] = t["ret"] > t["spy_ret"]
    return t


def summarize(trades, keys):
    rows = []
    for key, g in trades.groupby(keys, sort=True):
        key = key if isinstance(key, tuple) else (key,)
        closed = g[g["status"] == "ok"]
        n = len(closed)
        rows.append({**dict(zip(keys, key)),
                     "trades": n,
                     "win_abs_pct": 100.0 * closed["win_abs"].mean() if n else np.nan,
                     "win_spy_pct": 100.0 * closed["win_spy"].mean() if n else np.nan,
                     "mean_ret_pct": 100.0 * closed["ret"].mean() if n else np.nan,
                     "median_ret_pct": 100.0 * closed["ret"].median() if n else np.nan,
                     "mean_excess_pct": 100.0 * closed["excess"].mean() if n else np.nan,
                     "open": int((g["status"] == "open").sum()),
                     "no_price": int((g["status"] == "no_price").sum())})
    return pd.DataFrame(rows, columns=list(keys) + SUMMARY_COLUMNS)


def daily_equity(trades, store, calendar):
    """Weighted mean of the daily returns of every position held that day; cash at 0 %
    when nothing is held. A trade earns the days after its entry up to its exit."""
    t = trades[trades["status"].isin(PRICED)]
    if t.empty:
        return None
    start = pd.Timestamp(t["entry_date"].min())
    end = pd.Timestamp(t["exit_date"].max())
    cal = calendar[(calendar >= start) & (calendar <= end)]
    if len(cal) == 0:
        return None
    num = np.zeros(len(cal))
    den = np.zeros(len(cal))
    daily = {}
    for row in t.itertuples():
        if row.ticker not in daily:
            s = store.get(row.ticker)
            daily[row.ticker] = (s.reindex(cal).ffill().pct_change(fill_method=None)
                                 .fillna(0.0).to_numpy())
        i0 = cal.searchsorted(pd.Timestamp(row.entry_date), side="right")
        i1 = cal.searchsorted(pd.Timestamp(row.exit_date), side="right")
        num[i0:i1] += row.weight * daily[row.ticker][i0:i1]
        den[i0:i1] += row.weight
    ret = np.divide(num, den, out=np.zeros_like(num), where=den > 0)
    return pd.Series(np.cumprod(1.0 + ret), index=cal)


def cagr(equity):
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    if years <= 0:
        return np.nan
    return (equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0


def max_drawdown(equity):
    return float((equity / equity.cummax() - 1.0).min())


def book_stats(trades, store, spy):
    out, curves = [], {}
    for (strategy, variant), g in trades.groupby(["strategy", "variant"], sort=True):
        eq = daily_equity(g, store, spy.index)
        if eq is None or len(eq) < 2:
            continue
        bench = spy[(spy.index >= eq.index[0]) & (spy.index <= eq.index[-1])]
        bench = bench / bench.iloc[0]
        out.append({"strategy": strategy, "variant": variant,
                    "start": eq.index[0].date().isoformat(),
                    "end": eq.index[-1].date().isoformat(),
                    "cagr_pct": 100.0 * cagr(eq), "spy_cagr_pct": 100.0 * cagr(bench),
                    "max_dd_pct": 100.0 * max_drawdown(eq),
                    "spy_max_dd_pct": 100.0 * max_drawdown(bench)})
        curves["%s/%s" % (strategy, variant)] = eq
    return pd.DataFrame(out, columns=BOOK_COLUMNS), curves
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv/Scripts/python -m pytest tests/test_metrics.py -v`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add backtest/metrics.py tests/test_metrics.py
git commit -m "feat: trade returns vs SPY, win rates and daily equity curves"
```

---

### Task 7: Отчёт (`report.py`)

**Files:**
- Create: `backtest/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: результаты Task 6.
- Produces:
  - `md_table(df: pd.DataFrame) -> str`.
  - `write_report(out_dir: str, trades, overall, by_source, books, curves: dict, errors: list[str], generated: str) -> None`: пишет `latest.md`, `trades.csv`, `summary.json`, `errors.log`, и `equity.png`, если `curves` не пуст.

- [ ] **Step 1: Написать тесты**

`tests/test_report.py`:
```python
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
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["overall"][0]["win_spy_pct"] is None
    assert summary["books"][0]["cagr_pct"] == 12.0
    assert (tmp_path / "trades.csv").is_file()
    assert (tmp_path / "equity.png").stat().st_size > 0
    assert (tmp_path / "errors.log").read_text(encoding="utf-8").strip() == "PTR x: no text"
```

- [ ] **Step 2: Запустить и убедиться, что падают**

Run: `.venv/Scripts/python -m pytest tests/test_report.py -v`
Expected: FAIL, `ImportError: cannot import name 'report'`

- [ ] **Step 3: Реализация**

`backtest/report.py`:
```python
"""Writes reports/: latest.md, trades.csv, summary.json, equity.png, errors.log."""
import json
import math
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

CAVEATS = [
    "Не финансовый совет. Это проверка правил на прошлых данных, а не прогноз.",
    "13F выходит до 45 дней после конца квартала и показывает только длинные позиции в акциях США.",
    "PTR подают до 45 дней после сделки, суммы указаны диапазонами. Учтены только акции, опционы пропущены.",
    "Комиссии, проскальзывание и налоги не учтены.",
    "Ошибка выжившего: по делистингованным тикерам цен часто нет, такие сделки в колонке «Без цены».",
    "Сделки в статусе «Открыто» оценены по последней цене и в доли выигрышных не входят.",
]
NAMES = {
    "strategy": "Стратегия", "variant": "Вариант", "source": "Источник",
    "trades": "Закрыто сделок", "win_abs_pct": "Доля в плюсе, %",
    "win_spy_pct": "Доля лучше SPY, %", "mean_ret_pct": "Средняя, %",
    "median_ret_pct": "Медиана, %", "mean_excess_pct": "Избыток над SPY, %",
    "open": "Открыто", "no_price": "Без цены", "start": "С", "end": "По",
    "cagr_pct": "CAGR, %", "spy_cagr_pct": "CAGR SPY, %", "max_dd_pct": "Просадка, %",
    "spy_max_dd_pct": "Просадка SPY, %",
}


def _cell(v):
    if isinstance(v, float):
        return "" if math.isnan(v) else "%.1f" % v
    return str(v)


def md_table(df):
    if df.empty:
        return "_нет данных_\n"
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for row in df.itertuples(index=False):
        lines.append("| " + " | ".join(_cell(v) for v in row) + " |")
    return "\n".join(lines) + "\n"


def _records(df):
    return df.astype(object).where(df.notna(), None).to_dict("records")


def _json_default(o):
    return o.item() if hasattr(o, "item") else str(o)


def _plot(curves, path):
    fig, ax = plt.subplots(figsize=(11, 6))
    for name, eq in sorted(curves.items()):
        ax.plot(eq.index, eq.values, label=name, linewidth=1.2)
    ax.set_yscale("log")
    ax.set_ylabel("Капитал (старт = 1.0)")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def write_report(out_dir, trades, overall, by_source, books, curves, errors, generated):
    os.makedirs(out_dir, exist_ok=True)
    trades.to_csv(os.path.join(out_dir, "trades.csv"), index=False)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump({"generated": generated, "overall": _records(overall),
                   "by_source": _records(by_source), "books": _records(books)},
                  fh, ensure_ascii=False, indent=2, default=_json_default)
    with open(os.path.join(out_dir, "errors.log"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(errors) + ("\n" if errors else ""))
    if curves:
        _plot(curves, os.path.join(out_dir, "equity.png"))

    top = overall.merge(books, on=["strategy", "variant"], how="left")
    md = ["# Бэктест: Copycat 13F и сделки Конгресса", "",
          "Обновлено: %s" % generated, ""]
    md += ["> %s" % c for c in CAVEATS]
    md += ["", "## Итог по стратегиям", "", md_table(top.rename(columns=NAMES))]
    if curves:
        md += ["![Кривая капитала](equity.png)", ""]
    for strategy, title in (("copycat", "Copycat по фондам"), ("congress", "Конгресс по членам Палаты")):
        part = by_source[by_source["strategy"] == strategy].drop(columns=["strategy"])
        part = part.sort_values(["variant", "source"])
        md += ["## %s" % title, "", md_table(part.rename(columns=NAMES))]
    md += ["## Данные", "",
           "Проблем при сборе данных: %d (подробно в `errors.log`)." % len(errors),
           "Все сделки: `trades.csv`. Машиночитаемая сводка: `summary.json`.", ""]
    with open(os.path.join(out_dir, "latest.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))
```

- [ ] **Step 4: Запустить тесты**

Run: `.venv/Scripts/python -m pytest tests/test_report.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add backtest/report.py tests/test_report.py
git commit -m "feat: markdown, json, csv and chart report"
```

---

### Task 8: Точка входа (`run.py`) и конфиги

**Files:**
- Create: `backtest/run.py`, `config.json`, `members.json`
- Test: `tests/test_run.py`

**Interfaces:**
- Consumes: всё из Tasks 2–7.
- Produces:
  - `run_backtest(events, ptr_trades, store, cfg: dict) -> (trades, overall, by_source, books, curves)`; `SystemExit`, если у стора нет `SPY`.
  - CLI: `python -m backtest.run [--skip-fetch]`. Без флага скачивает 13F и PTR в `data/events_13f.csv` и `data/trades_ptr.csv`; с флагом берёт эти файлы как есть.

- [ ] **Step 1: Создать конфиги**

`config.json`:
```json
{
  "start": "2014-01-01",
  "top_n": 10,
  "holds": [30, 90, 180],
  "sale_max_days": 365,
  "copycat_fallback_days": 120,
  "data_dir": "data",
  "reports_dir": "reports"
}
```

`members.json`:
```json
{
  "note": "Matched against the House Clerk index by ptr.member_match: 'Last' or 'First Last' (first name is a prefix match).",
  "members": ["Pelosi", "Gottheimer", "Khanna", "McCaul", "Meuser", "Mark Green"]
}
```

- [ ] **Step 2: Написать тест**

`tests/test_run.py`:
```python
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
```

- [ ] **Step 3: Запустить и убедиться, что падает**

Run: `.venv/Scripts/python -m pytest tests/test_run.py -v`
Expected: FAIL, `ImportError: cannot import name 'run'`

- [ ] **Step 4: Реализация**

`backtest/run.py`:
```python
"""python -m backtest.run [--skip-fetch]"""
import argparse
import datetime as dt
import json
import os
import sys

import pandas as pd

from backtest import fetch_13f, fetch_ptr, metrics, report, strategies
from backtest.prices import PriceStore
from vendor import edgar13f as e13

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_json(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return json.load(fh)


def run_backtest(events, ptr_trades, store, cfg):
    spy = store.get("SPY")
    if spy is None:
        raise SystemExit("No SPY prices: nothing to compare against, stopping.")
    market_end = spy.index[-1]
    trades = pd.concat([
        strategies.copycat_trades(events, store, market_end, cfg["copycat_fallback_days"]),
        strategies.congress_trades(ptr_trades, store, market_end, tuple(cfg["holds"]),
                                   cfg["sale_max_days"]),
    ], ignore_index=True)
    trades = metrics.add_returns(trades, spy)
    overall = metrics.summarize(trades, ["strategy", "variant"])
    by_source = metrics.summarize(trades, ["strategy", "variant", "source"])
    books, curves = metrics.book_stats(trades, store, spy)
    return trades, overall, by_source, books, curves


def fetch_all(cfg, data_dir, log):
    ua = e13.user_agent(None, config_path=None)
    if not ua:
        raise SystemExit("Set SEC_USER_AGENT to 'Your Name you@example.com' (SEC requires it).")
    fetcher = fetch_13f.CachedFetcher(os.path.join(data_dir, "sec"), ua=ua, pause=0.12)
    index = e13.ticker_index(fetcher)
    overrides = e13.load_overrides([e13.CLASSES])
    events = fetch_13f.build_events(fetcher, e13.load_filers(), cfg["start"], cfg["top_n"],
                                    index, overrides, os.environ.get("OPENFIGI_API_KEY"), log)
    ptr_trades = fetch_ptr.build_trades(load_json("members.json")["members"],
                                        int(cfg["start"][:4]), dt.date.today().year,
                                        os.path.join(data_dir, "ptr"), log)
    return events, ptr_trades


def main(argv=None):
    ap = argparse.ArgumentParser(description="Backtest the trader-skill copycat and congress strategies.")
    ap.add_argument("--skip-fetch", action="store_true",
                    help="reuse data/events_13f.csv and data/trades_ptr.csv")
    args = ap.parse_args(argv)
    cfg = load_json("config.json")
    data_dir = os.path.join(ROOT, cfg["data_dir"])
    os.makedirs(data_dir, exist_ok=True)
    events_path = os.path.join(data_dir, "events_13f.csv")
    ptr_path = os.path.join(data_dir, "trades_ptr.csv")
    errors = []

    def log(msg):
        errors.append(msg)
        print(msg, file=sys.stderr)

    if not args.skip_fetch:
        events, ptr_trades = fetch_all(cfg, data_dir, log)
        events.to_csv(events_path, index=False)
        ptr_trades.to_csv(ptr_path, index=False)
    events = pd.read_csv(events_path, dtype={"cik": str, "ticker": str}, keep_default_na=False)
    ptr_trades = pd.read_csv(ptr_path, dtype=str, keep_default_na=False)

    store = PriceStore(os.path.join(data_dir, "prices"), start=cfg["start"])
    trades, overall, by_source, books, curves = run_backtest(events, ptr_trades, store, cfg)
    generated = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report.write_report(os.path.join(ROOT, cfg["reports_dir"]), trades, overall, by_source,
                        books, curves, errors, generated)
    print(overall.to_string(index=False))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Запустить все тесты**

Run: `.venv/Scripts/python -m pytest -v`
Expected: все тесты зелёные (31 штука).

- [ ] **Step 6: Commit**

```bash
git add backtest/run.py config.json members.json tests/test_run.py
git commit -m "feat: end-to-end backtest entry point and config"
```

---

### Task 9: GitHub Actions и README

**Files:**
- Create: `.github/workflows/backtest.yml`, `README.md`

**Interfaces:**
- Consumes: `python -m backtest.run`, `python -m pytest`.
- Produces: еженедельный прогон с коммитом `reports/`.

- [ ] **Step 1: Workflow**

`.github/workflows/backtest.yml`:
```yaml
name: backtest

on:
  schedule:
    - cron: "0 6 * * 0"   # Sunday 06:00 UTC
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: backtest
  cancel-in-progress: false

jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 150
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Install pdftotext
        run: sudo apt-get update && sudo apt-get install -y poppler-utils

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Tests
        run: python -m pytest -q

      - name: Restore data cache
        uses: actions/cache@v4
        with:
          path: data
          key: data-${{ github.run_id }}
          restore-keys: data-

      - name: Backtest
        env:
          SEC_USER_AGENT: ${{ secrets.SEC_USER_AGENT }}
          OPENFIGI_API_KEY: ${{ secrets.OPENFIGI_API_KEY }}
        run: python -m backtest.run

      - name: Commit report
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add reports
          git diff --cached --quiet || git commit -m "report: weekly backtest $(date -u +%F)"
          git push
```

- [ ] **Step 2: README**

`README.md`:
````markdown
# trader-backtest

Бэктест двух стратегий из [trader-skill](https://github.com/Jakeschincariol/trader-skill):

- **Copycat**: копировать топ-10 позиций 23 известных фондов в день выхода их 13F.
- **Congress**: покупать вслед за раскрытыми покупками акций членов Палаты (Пелоси и ещё 5 из `members.json`).

Каждая сделка сравнивается с SPY за то же окно. Свежий отчёт: [`reports/latest.md`](reports/latest.md).
Обновляется каждое воскресенье в GitHub Actions.

Не финансовый совет. Ничего не торгует.

## Запуск в GitHub

1. Залить репо на GitHub (подойдёт приватный).
2. Settings → Secrets and variables → Actions → New repository secret:
   - `SEC_USER_AGENT` = `Имя Фамилия you@example.com` (обязательно, этого требует SEC);
   - `OPENFIGI_API_KEY` (необязательно, помогает найти тикеры по CUSIP).
3. Actions → backtest → Run workflow. Первый прогон долгий (скачивается вся история), следующие быстрые за счёт кеша.

GitHub отключает расписание в репо без активности 60 дней. Еженедельные коммиты отчёта считаются активностью.

## Запуск локально

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pytest
```

```bash
SEC_USER_AGENT="Имя you@example.com" .venv/Scripts/python -m backtest.run
```

Для PTR нужен `pdftotext` (poppler). Без него сделки Конгресса не прочитаются и попадут в `reports/errors.log`.
Повторный расчёт без скачивания: `python -m backtest.run --skip-fetch`.

## Настройки

- `config.json`: период, топ-N, сроки удержания.
- `members.json`: члены Палаты.
- `vendor/filers.json`: фонды.
````

- [ ] **Step 3: Проверить, что YAML читается и тесты зелёные**

Run: `.venv/Scripts/python -c "import yaml" 2>/dev/null || .venv/Scripts/python -m pip install pyyaml==6.0.2` затем `.venv/Scripts/python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/backtest.yml')); print('ok')"`
Expected: `ok`

Run: `.venv/Scripts/python -m pytest -q`
Expected: все тесты зелёные.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/backtest.yml README.md
git commit -m "ci: weekly backtest workflow and README"
```

- [ ] **Step 5: Ручная проверка (после пуша на GitHub, делает пользователь)**

1. Добавить секрет `SEC_USER_AGENT`.
2. Запустить workflow вручную.
3. Убедиться, что появился коммит `report: weekly backtest ...` с `reports/latest.md`, `equity.png`, и что в таблице «Итог по стратегиям» 6 строк (2 copycat + 4 congress; строк меньше, если у варианта нет сделок).
