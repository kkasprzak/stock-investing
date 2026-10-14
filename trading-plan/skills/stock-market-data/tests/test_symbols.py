"""scripts/symbols.py — a broker's ticker to an ISIN and back, on symbols.json. Never guessed."""
from __future__ import annotations

import contextlib
import io
import json
import unittest

import support  # noqa: F401  (puts scripts/ on sys.path)
import symbols


def run(argv):
    """main() -> (exit code, parsed stdout or None, stderr); argparse's SystemExit counts as an exit
    code."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = symbols.main(argv)
        except SystemExit as e:
            code = e.code
    text = out.getvalue()
    return code, json.loads(text) if text else None, err.getvalue()


class TestFromBroker(unittest.TestCase):
    """--from xtb TICKER...: the ISIN behind each broker ticker."""

    def test_known_tickers(self):
        code, out, _ = run(["--from", "xtb", "PKN.PL", "ALE.PL"])
        self.assertEqual(code, 0)
        self.assertEqual(out, {"PKN.PL": {"found": True, "isin": "PLPKN0000018", "name": "PKNORLEN"},
                               "ALE.PL": {"found": True, "isin": "LU2237380790", "name": "ALLEGRO"}})

    def test_spacex_is_in_the_map(self):
        _, out, _ = run(["--from", "xtb", "SPCX.US"])
        self.assertEqual(out, {"SPCX.US": {"found": True, "isin": "US84615Q1031", "name": "SpaceX"}})

    def test_rename_guard(self):            # the broker keeps the old root; the ISIN bridges it
        _, out, _ = run(["--from", "xtb", "CCC.PL"])
        self.assertEqual(out["CCC.PL"]["isin"], "PLCCC0000016")

    def test_unknown_ticker_is_not_found(self):     # never inferred from the GPW root
        _, out, _ = run(["--from", "xtb", "ZZZ.PL"])
        self.assertEqual(out, {"ZZZ.PL": {"found": False}})

    def test_a_vendor_symbol_is_not_a_broker_ticker(self):
        _, out, _ = run(["--from", "xtb", "PKN.WA"])
        self.assertEqual(out, {"PKN.WA": {"found": False}})

    def test_an_isin_is_not_a_broker_ticker(self):
        _, out, _ = run(["--from", "xtb", "PLPKN0000018"])
        self.assertEqual(out, {"PLPKN0000018": {"found": False}})

    def test_known_and_unknown_in_one_call(self):
        code, out, _ = run(["--from", "xtb", "ZZZ.PL", "PKN.PL"])
        self.assertEqual(code, 0)
        self.assertEqual(list(out), ["ZZZ.PL", "PKN.PL"])          # in the order given
        self.assertEqual(out["ZZZ.PL"], {"found": False})
        self.assertEqual(out["PKN.PL"]["isin"], "PLPKN0000018")


class TestToBroker(unittest.TestCase):
    """--to xtb ISIN...: the broker ticker for each ISIN."""

    def test_known_isin(self):
        code, out, _ = run(["--to", "xtb", "PLPKN0000018"])
        self.assertEqual(code, 0)
        self.assertEqual(out, {"PLPKN0000018": {"found": True, "xtb": "PKN.PL", "name": "PKNORLEN"}})

    def test_rename_guard(self):            # the broker keeps the old root; Yahoo moved off it
        _, out, _ = run(["--to", "xtb", "PLCCC0000016"])
        self.assertEqual(out["PLCCC0000016"]["xtb"], "CCC.PL")

    def test_mapped_but_not_offered_by_the_broker_is_null(self):
        _, out, _ = run(["--to", "xtb", "PLROBYG00321", "PLRXCNC00017"])
        self.assertEqual(out, {"PLROBYG00321": {"found": True, "xtb": None, "name": "ROBYG"},
                               "PLRXCNC00017": {"found": True, "xtb": None, "name": "REX"}})

    def test_valid_isin_outside_the_map_is_not_found(self):
        _, out, _ = run(["--to", "xtb", "US0378331005"])           # Apple: valid, not mapped
        self.assertEqual(out, {"US0378331005": {"found": False}})

    def test_invalid_isin(self):
        for text in ("PLPKN0000019",        # wrong check digit
                     "plpkn0000018",        # lower case: not normalised
                     " PLPKN0000018",       # surrounding space: not stripped
                     "PKN.PL",              # a broker ticker
                     "garbage"):
            with self.subTest(text=text):
                code, out, _ = run(["--to", "xtb", text])
                self.assertEqual(code, 0)
                self.assertEqual(out, {text: {"found": False, "reason": "invalid_isin"}})

    def test_mixed_keys_in_one_call(self):
        code, out, _ = run(["--to", "xtb", "PLPKN0000019", "PLPKN0000018", "PLROBYG00321",
                            "US0378331005"])
        self.assertEqual(code, 0)
        self.assertEqual(out, {
            "PLPKN0000019": {"found": False, "reason": "invalid_isin"},
            "PLPKN0000018": {"found": True, "xtb": "PKN.PL", "name": "PKNORLEN"},
            "PLROBYG00321": {"found": True, "xtb": None, "name": "ROBYG"},
            "US0378331005": {"found": False},
        })
        self.assertEqual(list(out), ["PLPKN0000019", "PLPKN0000018", "PLROBYG00321",
                                     "US0378331005"])


class TestUsage(unittest.TestCase):
    """Only brokers' and exchanges' names: a vendor's symbol belongs to its adapter (ADR 0003)."""

    def assert_usage_error(self, argv):
        code, out, err = run(argv)
        self.assertEqual(code, 2)
        self.assertIsNone(out)
        self.assertTrue(err)

    def test_yahoo_is_not_a_namespace(self):
        self.assert_usage_error(["--from", "yahoo", "PKN.WA"])
        self.assert_usage_error(["--to", "yahoo", "PLPKN0000018"])

    def test_unknown_namespace(self):
        self.assert_usage_error(["--from", "ibkr", "PKN"])
        self.assert_usage_error(["--to", "ibkr", "PLPKN0000018"])

    def test_direction_is_required_and_single(self):
        self.assert_usage_error(["PKN.PL"])
        self.assert_usage_error(["--from", "xtb", "--to", "xtb", "PKN.PL"])

    def test_at_least_one_key(self):
        self.assert_usage_error(["--from", "xtb"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
