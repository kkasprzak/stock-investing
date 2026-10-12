#!/usr/bin/env python3
"""stock-market-data importer: a provider's export into this project's own candle store.

  python3 import_quotes.py --store DIR stooq <export.csv> --for PEO.PL

The write side of the store (quotes.py only reads it). One file per ISIN, <ISIN>.csv under --store;
the instrument is named with --for, a broker ticker or an ISIN from symbols.json. Import closed
sessions only: a row dated today is skipped and counted, a later one rejects the file. The first
problem rejects the whole file and leaves the store untouched. Prints a JSON report of what was
added and what changed; committing the store is the user's step (git diff is the review).
Never fetches quotes and never runs git.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                        # market_data/ sits next to this file (PYTHONSAFEPATH-proof)

from market_data.adapters.symbol_index import SymbolIndex   # noqa: E402

SYMBOLS = Path(HERE) / "symbols.json"
EXIT_REJECTED = 1                               # the export (or the store file) is not acceptable
EXIT_USAGE = 2                                  # same code argparse uses for a bad command line


def main(argv=None, *, today: date | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", required=True, metavar="DIR",
                    help="this project's own candle store, one CSV per ISIN; created when missing")
    ap.add_argument("provider", choices=("stooq",), help="whose export the file is")
    ap.add_argument("export", type=Path, metavar="FILE", help="the export, a daily CSV")
    ap.add_argument("--for", dest="key", required=True, metavar="TICKER",
                    help="the instrument the export is for: broker ticker or ISIN, e.g. PEO.PL")
    args = ap.parse_args(argv)

    if "${" in args.store:
        # A skill line whose ${CLAUDE_PROJECT_DIR} was not substituted: never create that directory.
        print(f"--store {args.store!r} holds an unsubstituted variable; pass the real path",
              file=sys.stderr)
        return EXIT_USAGE
    instrument = SymbolIndex(SYMBOLS).lookup(args.key)
    if instrument.isin is None:
        print(f"{args.key}: not in symbols.json, so no ISIN to name the store file by",
              file=sys.stderr)
        return EXIT_USAGE
    raise NotImplementedError("parse, merge and write land with the store's value types")


if __name__ == "__main__":
    sys.exit(main())
