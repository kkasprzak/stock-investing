"""market_data.store_file — the candle store's file schema, the stored row, and its bar."""
from __future__ import annotations

import csv
import os
import unittest
from datetime import date

import support  # noqa: F401  (puts scripts/ on sys.path)
from support import FX
from market_data.model import DailyQuote, Price, Volume
from market_data.store_file import ENCODING, HEADER, LINE_TERMINATOR, StoredQuote, to_bar

STORE_PKN = os.path.join(FX, "store", "PLPKN0000018.csv")


def stored(o="100.50", h="104", l="98.25", c="102", v="1500000", source="stooq"):  # noqa: E741
    q = DailyQuote(date(2026, 10, 9), Price.parse(o), Price.parse(h), Price.parse(l), Price.parse(c),
                   Volume.parse(v))
    return StoredQuote(q, source)


class TestSchema(unittest.TestCase):
    def test_header(self):
        self.assertEqual(HEADER, ("date", "open", "high", "low", "close", "volume", "source"))

    def test_lf_and_no_bom(self):
        self.assertEqual(LINE_TERMINATOR, "\n")
        self.assertEqual(ENCODING, "utf-8")      # not utf-8-sig: no BOM

    def test_the_store_fixture_follows_the_schema(self):
        with open(STORE_PKN, "rb") as f:
            raw = f.read()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", raw)
        with open(STORE_PKN, encoding=ENCODING, newline="") as f:
            rows = list(csv.reader(f))
        self.assertEqual(tuple(rows[0]), HEADER)
        self.assertEqual(len(rows) - 1, 6)
        for d, o, h, l, c, v, source in rows[1:]:  # noqa: E741
            DailyQuote(date.fromisoformat(d), Price.parse(o), Price.parse(h), Price.parse(l),
                       Price.parse(c), Volume.parse(v))
            self.assertEqual(source, "stooq")


class TestToBar(unittest.TestCase):
    def test_bar_shape(self):
        self.assertEqual(to_bar(stored()),
                         {"date": "2026-10-09", "o": 100.5, "h": 104.0, "l": 98.25, "c": 102.0,
                          "v": 1500000, "complete": True, "source": "store"})

    def test_numbers_are_float_and_int_like_yahoo(self):
        bar = to_bar(stored())
        self.assertEqual([type(bar[k]) for k in ("o", "h", "l", "c", "v")],
                         [float, float, float, float, int])

    def test_source_is_the_adapter_not_the_provider(self):
        self.assertEqual(to_bar(stored(source="stooq"))["source"], "store")


if __name__ == "__main__":
    unittest.main(verbosity=2)
