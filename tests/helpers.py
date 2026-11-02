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
