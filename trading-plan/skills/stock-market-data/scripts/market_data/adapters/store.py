"""A store directory as a QuoteSource: one CSV per ISIN in a directory the project names (ADR 0000,
ADR 0001). The own candle store is one, the collected GPW quotation archive another (ADR 0005): the
same adapter serves each under its own name. Read-only; the writers are elsewhere. The file format
lives in store_file."""
from __future__ import annotations

import sys
from pathlib import Path

from market_data import store_file
from market_data.model import DailyBar, DailyQuote, DateRange, Instrument, Trust
from market_data.ports import (QuoteSeries, QuoteSourceUnavailableError, Resolution, ResolvedBy,
                               SourceFailure)

INCONSISTENT_OHLC = Trust.untrusted("inconsistent_ohlc")


class StoreQuotes:
    name = "store"                                      # the own candle store, unless named otherwise
    description = "own candle store (one CSV per ISIN)"

    def __init__(self, store_dir: Path, *, name: str | None = None,
                 description: str | None = None) -> None:
        """`name` goes on every bar, resolution and failure this source gives; `description` into
        the chain's header. A missing directory is no_store whatever the name: the failure already
        says which source it is."""
        self._dir = Path(store_dir)
        if name is not None:
            self.name = name
        if description is not None:
            self.description = description

    def daily(self, instrument: Instrument, period: DateRange, *, now: float) -> QuoteSeries:
        """Every stored session up to period.end, all complete. Not cut at period.start: the port
        allows more, and a cut there would hand the window's old edge to a lower source. `now` is
        unused: only closed sessions are ever stored."""
        if not self._dir.is_dir():          # the project has no store yet: say so on every record
            raise QuoteSourceUnavailableError((SourceFailure(self.name, "no_store"),))
        resolution = Resolution(self.name, str(instrument.isin), ResolvedBy.ISIN)
        path = self._dir / f"{instrument.isin}.csv"
        if not path.exists():               # exists, not is_file: a directory there is malformed
            return QuoteSeries((), (resolution,))
        try:
            rows = store_file.read(path)
        except store_file.StoreFileError as e:
            print(e, file=sys.stderr)
            raise QuoteSourceUnavailableError((SourceFailure(self.name, "malformed"),),
                                              (resolution,)) from e
        return QuoteSeries(tuple(self._bar(r.quote) for r in rows if r.quote.session <= period.end),
                           (resolution,))

    def _bar(self, q: DailyQuote) -> DailyBar:
        """A stored session as the port's bar. Its source is this adapter's name, not the provider
        the row came from; trusted, since only closed sessions are stored (ADR 0000, ADR 0005) —
        unless its low and high do not bracket its open and close: then it is served as stored,
        neither dropped nor corrected, but untrusted."""
        # The Stooq importer rejects such a row, so in the own store it can only appear after a
        # manual edit of the file. Reading it at all exists for the GPW store, whose rows are kept
        # as GPW published them, some of them like this (ADR 0005).
        trust = INCONSISTENT_OHLC if q.ohlc_breach else Trust.TRUSTED
        return DailyBar(q.session, q.open, q.high, q.low, q.close, q.volume, complete=True,
                        source=self.name, trust=trust)
