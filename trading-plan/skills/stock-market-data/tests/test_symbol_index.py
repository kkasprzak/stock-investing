"""market_data.adapters.symbol_index — symbols.json read into Instruments, by ISIN or broker ticker."""
from __future__ import annotations

import json
import os
import tempfile
import unittest

import support  # noqa: F401  (puts scripts/ on sys.path)
import quotes
from market_data.adapters.symbol_index import SymbolIndex
from market_data.model import Instrument, Isin


class TestLookup(unittest.TestCase):
    def setUp(self):
        self.index = SymbolIndex(quotes.SYMBOLS)

    def test_by_isin(self):
        i = self.index.lookup("PLPKN0000018")
        self.assertEqual((i.key, i.isin), ("PLPKN0000018", Isin.parse("PLPKN0000018")))
        self.assertEqual(dict(i.symbols), {"xtb": "PKN.PL", "yahoo": "PKN.WA"})

    def test_by_broker_ticker(self):
        i = self.index.lookup("PKN.PL")
        self.assertEqual((i.key, i.isin), ("PKN.PL", Isin.parse("PLPKN0000018")))
        self.assertEqual(dict(i.symbols), {"xtb": "PKN.PL", "yahoo": "PKN.WA"})

    def test_rename_guard(self):            # xStation SPL.PL <-> Yahoo EBP.WA, bridged by ISIN
        i = self.index.lookup("SPL.PL")
        self.assertEqual((i.isin, i.symbols.get("yahoo")), (Isin.parse("PLBZ00000044"), "EBP.WA"))

    def test_unknown_key_is_unmapped(self):
        self.assertEqual(self.index.lookup("ZZZ.PL"), Instrument.unmapped("ZZZ.PL"))


class TestConstruction(unittest.TestCase):
    def test_a_bad_isin_in_the_map_fails_at_construction(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "symbols.json")
            with open(path, "w") as f:
                json.dump({"instruments": {"PLPKN0000018": {"symbols": {"xtb": "PKN.PL"}},
                                           "PLPEKAO00017": {"symbols": {"xtb": "PEO.PL"}}}}, f)
            with self.assertRaisesRegex(ValueError, "PLPEKAO00017"):
                SymbolIndex(path)


class TestBrokerSymbol(unittest.TestCase):
    """The execution-venue ticker a caller needs to name a state-file row. Never guessed."""

    def setUp(self):
        self.index = SymbolIndex(quotes.SYMBOLS)

    def xtb(self, key):
        return self.index.lookup(key).symbols.get("xtb")

    def test_by_isin(self):                 # sourcing keys by ISIN, writes the broker ticker
        self.assertEqual(self.xtb("PLPKN0000018"), "PKN.PL")

    def test_by_broker_ticker(self):        # already a broker ticker -> itself
        self.assertEqual(self.xtb("PKN.PL"), "PKN.PL")

    def test_rename_guard(self):            # broker keeps the old root; Yahoo moved off it
        self.assertEqual(self.xtb("PLCCC0000016"), "CCC.PL")

    def test_unlisted_is_none(self):        # mapped instrument the broker does not offer
        self.assertIsNone(self.xtb("PLROBYG00321"))

    def test_unmapped_is_none(self):        # never inferred from the GPW root
        self.assertIsNone(self.xtb("ZZZ.PL"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
