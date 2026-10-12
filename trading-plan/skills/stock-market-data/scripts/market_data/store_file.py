"""The candle store's file: one CSV per ISIN, the contract between the importer and the adapter.

<ISIN>.csv, header HEADER, LF line endings, UTF-8 without a BOM; rows ascending by a unique date,
working days only, closed sessions only. date is ISO, prices are str(Price), volume is
str(Volume), source is the provider of the row (e.g. "stooq").
"""
from __future__ import annotations

from dataclasses import dataclass

from market_data.model import DailyQuote

HEADER = ("date", "open", "high", "low", "close", "volume", "source")
LINE_TERMINATOR = "\n"
ENCODING = "utf-8"          # not utf-8-sig: the file carries no BOM


@dataclass(frozen=True)
class StoredQuote:
    """One row of the file. source is provenance of the stored row, not part of the quote; the
    set of providers is open, so it stays a str."""

    quote: DailyQuote
    source: str


def to_bar(stored: StoredQuote) -> dict:
    """The row as a port bar, numbers as float/int like Yahoo's. The bar's source is the adapter
    that served it ("store"), not the provider the row came from."""
    q = stored.quote
    return {"date": q.session.isoformat(), "o": float(q.open.value), "h": float(q.high.value),
            "l": float(q.low.value), "c": float(q.close.value), "v": q.volume.value,
            "complete": True, "source": "store"}
