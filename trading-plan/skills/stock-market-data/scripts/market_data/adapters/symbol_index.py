"""symbols.json read into Instruments, looked up by ISIN; any namespace's symbol found back to its
ISIN."""
from __future__ import annotations

import json
from pathlib import Path

from market_data.model import Instrument, Isin


class SymbolIndex:
    """Keyed by ISIN only (ADR 0003): a broker's ticker is found back to its ISIN with find, never
    looked up as an instrument, and no symbol is guessed. The file is read once, at construction; a
    key that is not a valid ISIN fails it there, and so does a symbol given to two ISINs in one
    namespace (the map would not say which one it names)."""

    def __init__(self, path: Path) -> None:
        with open(path) as f:
            data = json.load(f)
        symbols: dict[Isin, dict[str, str]] = {}
        by_symbol: dict[str, dict[str, Isin]] = {}     # namespace -> symbol -> ISIN
        names: dict[Isin, str | None] = {}
        for key, e in data["instruments"].items():
            isin = Isin.parse(key)
            symbols[isin] = dict(e.get("symbols", {}))
            names[isin] = e.get("name")
            for namespace, symbol in symbols[isin].items():
                seen = by_symbol.setdefault(namespace, {})
                if symbol in seen:
                    raise ValueError(f"symbols.json: {namespace} symbol {symbol!r} is given to both "
                                     f"{seen[symbol]} and {isin}")
                seen[symbol] = isin
        self._symbols = symbols
        self._by_symbol = by_symbol
        self._names = names

    def __contains__(self, isin: object) -> bool:
        """Whether the map has an entry for `isin`, with or without a symbol in any namespace."""
        return isin in self._symbols

    def find(self, namespace: str, symbol: str) -> Isin | None:
        """The ISIN that `namespace` (a broker, an exchange, a vendor) calls `symbol`; None when the
        map has no such symbol in that namespace. Exact text only, never across namespaces."""
        return self._by_symbol.get(namespace, {}).get(symbol)

    def name(self, isin: Isin) -> str | None:
        """The map's display name for `isin`; None when the ISIN is not in the map."""
        return self._names.get(isin)

    def lookup(self, isin: Isin) -> Instrument:
        """The instrument behind `isin`; an ISIN the map does not know is Instrument.unmapped(isin),
        which the own store still answers (its file is named by the ISIN)."""
        symbols = self._symbols.get(isin)
        if symbols is None:
            return Instrument.unmapped(isin)
        return Instrument(isin=isin, symbols=dict(symbols))
