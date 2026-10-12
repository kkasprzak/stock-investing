"""market_data.quote_chain — QuoteChain: the composite that asks sources in trust order.

Offline, no mocks: every source is a fake implementing the QuoteSource port. It answers with fixed
bars (or raises a fixed failure) and records the period it was asked for.
"""
from __future__ import annotations

import unittest
from datetime import date

import support  # noqa: F401  (puts scripts/ on sys.path)
from market_data.model import DateRange, Instrument
from market_data.ports import (QuoteSeries, QuoteSourceUnavailableError, Resolution, ResolvedBy,
                               SourceFailure)
from market_data.quote_chain import QuoteChain

INSTRUMENT = Instrument(key="PKN.PL", isin="PL0000000000", symbols={"yahoo": "PKN.WA"})
PERIOD = DateRange(date(2026, 7, 1), date(2026, 7, 24))
NOW = 1784973600.0


def bar(day, close, source):
    return {"date": day, "o": close, "h": close, "l": close, "c": close, "v": 1, "complete": True,
            "source": source}


class FakeSource:
    """A QuoteSource answering with `bars`, or raising `reason` as its unavailability."""

    def __init__(self, name, bars=(), reason=None):
        self.name = name
        self._bars = tuple(bars)
        self._reason = reason
        self.periods = []
        self.resolution = Resolution(name, f"{name.upper()}:PKN", ResolvedBy.SYMBOLS_JSON)

    def daily(self, instrument, period, *, now):
        self.periods.append(period)
        if self._reason is not None:
            raise QuoteSourceUnavailableError((SourceFailure(self.name, self._reason),),
                                              (self.resolution,))
        return QuoteSeries(self._bars, (self.resolution,))


def ask(*sources):
    return QuoteChain(list(sources)).daily(INSTRUMENT, PERIOD, now=NOW)


class TestQuoteChain(unittest.TestCase):
    def test_is_named_chain(self):
        self.assertEqual(QuoteChain([]).name, "chain")

    def test_higher_source_wins_a_shared_date_lower_fills_the_rest(self):
        a = FakeSource("a", [bar("2026-07-22", 10.0, "a"), bar("2026-07-24", 12.0, "a")])
        b = FakeSource("b", [bar("2026-07-22", 99.0, "b"), bar("2026-07-23", 11.0, "b")])
        s = ask(a, b)
        self.assertEqual([(x["date"], x["c"], x["source"]) for x in s.bars],
                         [("2026-07-22", 10.0, "a"), ("2026-07-23", 11.0, "b"),
                          ("2026-07-24", 12.0, "a")])

    def test_two_bars_with_one_date_from_one_source_both_stay(self):
        """Yahoo can return two bars dated alike after a backfill; dedup is only between sources."""
        a = FakeSource("a", [bar("2026-07-24", 10.0, "a"), bar("2026-07-24", 10.5, "a")])
        b = FakeSource("b", [bar("2026-07-24", 99.0, "b")])
        s = ask(a, b)
        self.assertEqual([(x["c"], x["source"]) for x in s.bars], [(10.0, "a"), (10.5, "a")])

    def test_every_source_is_asked_for_the_whole_period(self):
        a = FakeSource("a", [bar("2026-07-24", 10.0, "a")])
        b = FakeSource("b", [bar("2026-07-23", 11.0, "b")])
        ask(a, b)
        self.assertEqual((a.periods, b.periods), ([PERIOD], [PERIOD]))

    def test_one_raises_the_other_answers(self):
        a = FakeSource("a", reason="timeout")
        b = FakeSource("b", [bar("2026-07-24", 11.0, "b")])
        s = ask(a, b)
        self.assertEqual([x["source"] for x in s.bars], ["b"])
        self.assertEqual(s.unavailable, (SourceFailure("a", "timeout"),))

    def test_both_raise_with_both_failures_and_resolutions(self):
        a = FakeSource("a", reason="timeout")
        b = FakeSource("b", reason="not_found")
        with self.assertRaises(QuoteSourceUnavailableError) as cm:
            ask(a, b)
        self.assertEqual(cm.exception.failures,
                         (SourceFailure("a", "timeout"), SourceFailure("b", "not_found")))
        self.assertEqual(cm.exception.resolved, (a.resolution, b.resolution))

    def test_one_raises_the_other_answers_empty(self):
        """An empty answer is an answer: no exception, the failure goes to unavailable."""
        s = ask(FakeSource("a", reason="timeout"), FakeSource("b"))
        self.assertEqual(s.bars, ())
        self.assertEqual(s.unavailable, (SourceFailure("a", "timeout"),))

    def test_both_answer_empty(self):
        s = ask(FakeSource("a"), FakeSource("b"))
        self.assertEqual((s.bars, s.unavailable), ((), ()))

    def test_resolved_is_the_concatenation_including_failed_sources(self):
        a = FakeSource("a", [bar("2026-07-24", 10.0, "a")])
        b = FakeSource("b", reason="timeout")
        c = FakeSource("c", [bar("2026-07-23", 11.0, "c")])
        self.assertEqual(ask(a, b, c).resolved, (a.resolution, b.resolution, c.resolution))

    def test_result_is_sorted_by_date_stably(self):
        a = FakeSource("a", [bar("2026-07-24", 12.0, "a"), bar("2026-07-21", 9.0, "a"),
                             bar("2026-07-24", 12.5, "a")])
        b = FakeSource("b", [bar("2026-07-22", 10.0, "b"), bar("2026-07-20", 8.0, "b")])
        s = ask(a, b)
        self.assertEqual([(x["date"], x["c"]) for x in s.bars],
                         [("2026-07-20", 8.0), ("2026-07-21", 9.0), ("2026-07-22", 10.0),
                          ("2026-07-24", 12.0), ("2026-07-24", 12.5)])

    def test_a_single_source_passes_through_unchanged(self):
        bars = [bar("2026-07-23", 11.0, "a"), bar("2026-07-24", 12.0, "a")]
        s = ask(FakeSource("a", bars))
        self.assertEqual(list(s.bars), bars)
        self.assertEqual(s.unavailable, ())


if __name__ == "__main__":
    unittest.main()
