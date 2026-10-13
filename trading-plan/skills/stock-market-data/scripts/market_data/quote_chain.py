"""QuoteChain: several quote sources behind the one port, asked in trust order (ADR 0000)."""
from __future__ import annotations

from typing import Sequence

from market_data.model import DateRange, Instrument
from market_data.ports import QuoteSeries, QuoteSource, QuoteSourceUnavailableError


class QuoteChain:
    """A QuoteSource over `sources`, most trusted first. Every source is asked for the whole period
    (the chain knows no exchange calendar, so it cannot ask for gaps). A date a higher source already
    answered is skipped in the lower ones, even when the higher source's bar is untrusted and the
    lower one's trusted (which cannot happen while the only higher source is the store, whose bars
    are always trusted); within one source bars pass unchanged, two bars sharing a date included. A source that raises QuoteSourceUnavailableError is recorded in `unavailable` and
    the next one is asked; only when none answered does the chain raise. Any other exception
    propagates. An empty answer is an answer."""

    name = "chain"

    def __init__(self, sources: Sequence[QuoteSource]) -> None:
        self._sources = tuple(sources)
        self.description = " > ".join(s.description for s in self._sources)   # trust order

    def daily(self, instrument: Instrument, period: DateRange, *, now: float) -> QuoteSeries:
        bars, resolved, failures = [], [], []
        taken = set()                                   # dates answered by higher sources
        answered = False
        for source in self._sources:
            try:
                series = source.daily(instrument, period, now=now)
            except QuoteSourceUnavailableError as e:
                failures.extend(e.failures)
                resolved.extend(e.resolved)
                continue
            answered = True
            resolved.extend(series.resolved)
            fresh = [b for b in series.bars if b.session not in taken]
            bars.extend(fresh)
            taken.update(b.session for b in fresh)      # after the whole source, not per bar
        if not answered:
            raise QuoteSourceUnavailableError(tuple(failures), tuple(resolved))
        bars.sort(key=lambda b: b.session)              # stable: same-date bars keep their order
        return QuoteSeries(tuple(bars), tuple(resolved), tuple(failures))
