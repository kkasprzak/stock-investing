#!/usr/bin/env python3
"""stock-market-data names: a broker's or an exchange's ticker to an ISIN, and an ISIN back to it.

  python3 symbols.py --from xtb PKN.PL ALE.PL       # broker tickers -> ISINs
  python3 symbols.py --to xtb PLPKN0000018          # ISINs -> broker tickers

Reads the same symbols.json as quotes.py. The direction is always named. Every key comes back under
the text the caller passed, with "found" always present:
  --from: {"found": true, "isin": ..., "name": ...}, or {"found": false} for a ticker the map does
          not know (never guessed from its root).
  --to:   {"found": true, "<namespace>": ..., "name": ...}, where the ticker is null when the
          instrument is mapped but that broker does not offer it; {"found": false} for a valid ISIN
          outside the map; {"found": false, "reason": "invalid_isin"} for text that is no ISIN
          (checked strictly: no upper-casing, no trimming).
Namespaces are brokers' and exchanges' only. A data vendor's symbol (yahoo) belongs to that vendor's
adapter, not to callers, so it is not offered here. Never touches the network.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                        # market_data/ sits next to this file (PYTHONSAFEPATH-proof)

from market_data.adapters.symbol_index import SymbolIndex   # noqa: E402
from market_data.model import Isin                          # noqa: E402

SYMBOLS = Path(HERE) / "symbols.json"
NAMESPACES = ("xtb",)                           # brokers and exchanges; never a data vendor


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    direction = ap.add_mutually_exclusive_group(required=True)
    direction.add_argument("--from", dest="source", choices=NAMESPACES,
                           help="the keys are this broker's tickers; answer their ISINs")
    direction.add_argument("--to", dest="target", choices=NAMESPACES,
                           help="the keys are ISINs; answer this broker's tickers")
    ap.add_argument("keys", nargs="+", metavar="KEY", help="tickers with --from, ISINs with --to")
    args = ap.parse_args(argv)

    index = SymbolIndex(SYMBOLS)
    if args.source:
        result = {key: from_symbol(index, args.source, key) for key in args.keys}
    else:
        result = {key: to_symbol(index, args.target, key) for key in args.keys}
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


def from_symbol(index: SymbolIndex, namespace: str, symbol: str) -> dict:
    isin = index.find(namespace, symbol)
    if isin is None:
        return {"found": False}
    return {"found": True, "isin": str(isin), "name": index.name(isin)}


def to_symbol(index: SymbolIndex, namespace: str, text: str) -> dict:
    try:
        isin = Isin.parse(text)
    except ValueError:
        return {"found": False, "reason": "invalid_isin"}
    instrument = index.lookup(str(isin))
    if instrument.isin is None:
        return {"found": False}
    return {"found": True, namespace: instrument.symbols.get(namespace), "name": index.name(isin)}


if __name__ == "__main__":
    sys.exit(main())
