"""The quote-source port: what any provider of daily quotes (vendor API, own store, broker) offers.

Semantics every adapter keeps:

- Each adapter translates the Instrument into its own symbol (instrument.symbols.get(self.name),
  with its own fallback) and reports how it did so in QuoteSeries.resolved.
- The answer covers **at least** the requested period; it may carry more (a vendor returning a whole
  range bucket). Callers trim: the indicators read a fixed window anyway, the CLI cuts to --bars.
- **An empty tuple of bars means the source answered and has nothing for this instrument in this
  period** (e.g. a store that does not know the instrument). That is not a failure and does not
  raise. Callers ask for at least nine calendar days (the CLI enforces MIN_PERIOD_DAYS), so empty
  never means "weekend"; adapters do not check it.
- QuoteSourceUnavailableError only when the source **did not answer** (timeout, HTTP error, the
  vendor's not_found); the adapter translates those itself. That distinction is the point of the
  port. Any other exception is a bug, not an answer: it is not caught and ends the run.
- `now` (epoch) is injected: the adapter decides each bar's `complete` flag in the market's own
  time zone. It stays a float because session_end/stamp_complete compute on epochs.

Deliberately plain: an adapter's `name` is a str (an enum of known sources would break open-closed)
and so is a failure's `reason` (http_<code> is open-ended).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from market_data.model import DateRange, Instrument


class ResolvedBy(str, Enum):
    SYMBOLS_JSON = "symbols.json"
    SUFFIX_GUESS = "suffix_guess"


@dataclass(frozen=True)
class Resolution:
    source: str                 # adapter name
    symbol: str                 # the instrument's symbol at that provider
    by: ResolvedBy


@dataclass(frozen=True)
class SourceFailure:
    source: str
    reason: str                 # "rate_limited" | "not_found" | "http_503" | ... (open)


@dataclass(frozen=True)
class QuoteSeries:
    bars: tuple[dict, ...]      # daily bars, newest last; each carries "source": <adapter name>
    resolved: tuple[Resolution, ...]
    unavailable: tuple[SourceFailure, ...] = ()   # filled only by the composite


class QuoteSourceError(Exception):
    """Base for every error a quote source raises."""


class QuoteSourceUnavailableError(QuoteSourceError):
    """No source answered. Does NOT mean 'no session' nor 'the source does not know the instrument'."""

    def __init__(self, failures: tuple[SourceFailure, ...],
                 resolved: tuple[Resolution, ...] = ()) -> None:
        self.failures = tuple(failures)        # raw reasons, never joined into one string
        self.resolved = tuple(resolved)        # what got resolved before failing (for ok:false)
        super().__init__("; ".join(f"{f.source}: {f.reason}" for f in self.failures)
                         or "no quote source answered")


class QuoteSource(Protocol):
    name: str

    def daily(self, instrument: Instrument, period: DateRange, *, now: float) -> QuoteSeries: ...
