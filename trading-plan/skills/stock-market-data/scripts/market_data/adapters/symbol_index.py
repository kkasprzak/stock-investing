"""symbols.json read into Instruments, looked up by ISIN or by broker (xtb) ticker; any namespace's
symbol found back to its ISIN."""
from __future__ import annotations

import json
from pathlib import Path

from market_data.model import Instrument, Isin


class SymbolIndex:
    """Keyed by both ISIN and xtb ticker. Callers keyed by broker ticker (state files) hit the xtb
    key; callers keyed by ISIN (e.g. index-membership sourcing) hit the ISIN key — no suffix guess.
    The file is read once, at construction; a key that is not a valid ISIN fails it there, and so
    does a symbol given to two ISINs in one namespace (the map would not say which one it names)."""

    def __init__(self, path: Path) -> None:
        with open(path) as f:
            data = json.load(f)
        idx = {}
        by_symbol: dict[str, dict[str, Isin]] = {}     # namespace -> symbol -> ISIN
        names: dict[Isin, str | None] = {}
        for isin, e in data["instruments"].items():
            entry = {"isin": Isin.parse(isin), **e}
            idx[isin] = entry                          # resolve by ISIN (durable, rename-proof)
            names[entry["isin"]] = e.get("name")
            for namespace, symbol in e.get("symbols", {}).items():
                seen = by_symbol.setdefault(namespace, {})
                if symbol in seen:
                    raise ValueError(f"symbols.json: {namespace} symbol {symbol!r} is given to both "
                                     f"{seen[symbol]} and {isin}")
                seen[symbol] = entry["isin"]
            xtb = e.get("symbols", {}).get("xtb")
            if xtb:
                idx[xtb] = entry                       # and by broker ticker (state-file anchor)
        self._idx = idx
        self._by_symbol = by_symbol
        self._names = names

    def find(self, namespace: str, symbol: str) -> Isin | None:
        """The ISIN that `namespace` (a broker, an exchange, a vendor) calls `symbol`; None when the
        map has no such symbol in that namespace. Exact text only, never across namespaces."""
        return self._by_symbol.get(namespace, {}).get(symbol)

    def name(self, isin: Isin) -> str | None:
        """The map's display name for `isin`; None when the ISIN is not in the map."""
        return self._names.get(isin)

    def lookup(self, key: str) -> Instrument:
        """The instrument behind `key`; a key the map does not know is Instrument.unmapped(key)."""
        e = self._idx.get(key)
        if e is None:
            return Instrument.unmapped(key)
        return Instrument(key=key, isin=e["isin"], symbols=dict(e.get("symbols", {})))
