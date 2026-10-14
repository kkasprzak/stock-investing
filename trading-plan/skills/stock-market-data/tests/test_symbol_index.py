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


class TestFind(unittest.TestCase):
    """The ISIN behind one namespace's symbol: a reverse lookup, never across namespaces."""

    def setUp(self):
        self.index = SymbolIndex(quotes.SYMBOLS)

    def test_broker_ticker(self):
        self.assertEqual(self.index.find("xtb", "PKN.PL"), Isin.parse("PLPKN0000018"))

    def test_rename_guard(self):            # xStation SPL.PL <-> Yahoo EBP.WA, bridged by ISIN
        self.assertEqual(self.index.find("xtb", "SPL.PL"), Isin.parse("PLBZ00000044"))
        self.assertEqual(self.index.find("yahoo", "EBP.WA"), Isin.parse("PLBZ00000044"))

    def test_spacex(self):
        self.assertEqual(self.index.find("xtb", "SPCX.US"), Isin.parse("US84615Q1031"))
        self.assertEqual(self.index.find("yahoo", "SPCX"), Isin.parse("US84615Q1031"))

    def test_another_namespaces_symbol_is_not_found(self):
        self.assertIsNone(self.index.find("xtb", "PKN.WA"))
        self.assertIsNone(self.index.find("yahoo", "PKN.PL"))

    def test_an_isin_is_not_a_symbol(self):
        self.assertIsNone(self.index.find("xtb", "PLPKN0000018"))

    def test_unknown(self):
        self.assertIsNone(self.index.find("xtb", "ZZZ.PL"))
        self.assertIsNone(self.index.find("ibkr", "PKN.PL"))


class TestName(unittest.TestCase):
    def setUp(self):
        self.index = SymbolIndex(quotes.SYMBOLS)

    def test_mapped(self):
        self.assertEqual(self.index.name(Isin.parse("PLPKN0000018")), "PKNORLEN")
        self.assertEqual(self.index.name(Isin.parse("US84615Q1031")), "SpaceX")

    def test_mapped_without_a_broker_symbol(self):
        self.assertEqual(self.index.name(Isin.parse("PLROBYG00321")), "ROBYG")

    def test_outside_the_map_is_none(self):
        self.assertIsNone(self.index.name(Isin.parse("US0378331005")))


class TestTheMap(unittest.TestCase):
    def test_every_entry_is_indexed(self):
        with open(quotes.SYMBOLS) as f:
            isins = list(json.load(f)["instruments"])
        self.assertEqual(len(isins), 145)
        index = SymbolIndex(quotes.SYMBOLS)
        self.assertEqual([i for i in isins if index.name(Isin.parse(i)) is None], [])


def write_map(tmp, instruments):
    path = os.path.join(tmp, "symbols.json")
    with open(path, "w") as f:
        json.dump({"instruments": instruments}, f)
    return path


class TestConstruction(unittest.TestCase):
    def test_a_bad_isin_in_the_map_fails_at_construction(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_map(tmp, {"PLPKN0000018": {"symbols": {"xtb": "PKN.PL"}},
                                   "PLPEKAO00017": {"symbols": {"xtb": "PEO.PL"}}})
            with self.assertRaisesRegex(ValueError, "PLPEKAO00017"):
                SymbolIndex(path)

    def test_a_symbol_twice_in_one_namespace_fails_at_construction(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_map(tmp, {"PLPKN0000018": {"symbols": {"xtb": "PKN.PL"}},
                                   "PLPEKAO00016": {"symbols": {"xtb": "PKN.PL"}}})
            with self.assertRaisesRegex(ValueError, r"xtb.*PKN\.PL.*PLPKN0000018.*PLPEKAO00016"):
                SymbolIndex(path)

    def test_one_symbol_in_two_namespaces_is_fine(self):     # V80A.DE at the broker and at Yahoo
        with tempfile.TemporaryDirectory() as tmp:
            path = write_map(tmp, {"IE00BMVB5R75": {"symbols": {"xtb": "V80A.DE",
                                                                "yahoo": "V80A.DE"}}})
            index = SymbolIndex(path)
            self.assertEqual(index.find("xtb", "V80A.DE"), index.find("yahoo", "V80A.DE"))


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
