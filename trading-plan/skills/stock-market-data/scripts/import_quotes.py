#!/usr/bin/env python3
"""stock-market-data importer: a provider's export into this project's own candle store.

  python3 import_quotes.py --store DIR stooq <export.csv> --for PEO.PL

The write side of the store (quotes.py only reads it). One file per ISIN, <ISIN>.csv under --store;
the instrument is named with --for, a broker ticker or an ISIN from symbols.json. A row in a daily
export is a closed session, so a row dated today is imported; one dated after today rejects the
file. The first problem rejects the whole file and leaves the store untouched. Prints a JSON report of what was
added and what changed; committing the store is the user's step (git diff is the review).
Never fetches quotes and never runs git.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                        # market_data/ sits next to this file (PYTHONSAFEPATH-proof)

from market_data import store_file                          # noqa: E402
from market_data.adapters.symbol_index import SymbolIndex   # noqa: E402
from market_data.importers import stooq                     # noqa: E402
from market_data.importers.stooq import StooqFormatError    # noqa: E402
from market_data.store_file import StoreFileError           # noqa: E402

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
    today = today or date.today()
    store = Path(args.store)
    path = store / f"{instrument.isin}.csv"

    try:
        rows = stooq.parse(args.export)
    except StooqFormatError as e:
        return _rejected(f"{args.export}: line {e.line}: {e.why}")
    except OSError as e:
        return _rejected(f"{args.export}: cannot read: {e.strerror or e}")
    # Once parse has accepted the file every row is one physical line after the header, so row i
    # sits on line i + 2.
    for i, r in enumerate(rows):
        if r.quote.session > today:
            return _rejected(f"{args.export}: line {i + 2}: session {r.quote.session} is after "
                             f"today {today}")
    # A row in a daily export is a closed session, today's included.
    incoming = rows

    report = {"isin": str(instrument.isin), "key": args.key, "file": str(path),
              "added": 0, "unchanged": 0, "changed": 0, "changed_dates": [],
              "imported": {"first": incoming[0].quote.session.isoformat() if incoming else None,
                           "last": incoming[-1].quote.session.isoformat() if incoming else None}}
    if incoming:
        try:
            existing = store_file.read(path) if path.exists() else []
        except StoreFileError as e:
            return _rejected(f"{e}; the store file was left as it is")
        merged = store_file.merge(existing, incoming)
        if merged.added or merged.changed:      # nothing new: leave the file (and its mtime) alone
            store.mkdir(parents=True, exist_ok=True)
            store_file.write(path, merged.rows)
        report.update(added=merged.added, unchanged=merged.unchanged, changed=merged.changed,
                      changed_dates=[d.isoformat() for d in merged.changed_dates])
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


def _rejected(why: str) -> int:
    print(f"import rejected, nothing written: {why}", file=sys.stderr)
    return EXIT_REJECTED


if __name__ == "__main__":
    sys.exit(main())
