"""symbols.json read into Instruments, looked up by ISIN or by broker (xtb) ticker."""
from __future__ import annotations

import json
from pathlib import Path

from market_data.model import Instrument, Isin


class SymbolIndex:
    """Keyed by both ISIN and xtb ticker. Callers keyed by broker ticker (state files) hit the xtb
    key; callers keyed by ISIN (e.g. index-membership sourcing) hit the ISIN key — no suffix guess.
    The file is read once, at construction; a key that is not a valid ISIN fails it there."""

    def __init__(self, path: Path) -> None:
        with open(path) as f:
            data = json.load(f)
        idx = {}
        for isin, e in data["instruments"].items():
            entry = {"isin": Isin.parse(isin), **e}
            idx[isin] = entry                          # resolve by ISIN (durable, rename-proof)
            xtb = e.get("symbols", {}).get("xtb")
            if xtb:
                idx[xtb] = entry                       # and by broker ticker (state-file anchor)
        self._idx = idx

    def lookup(self, key: str) -> Instrument:
        """The instrument behind `key`; a key the map does not know is Instrument.unmapped(key)."""
        e = self._idx.get(key)
        if e is None:
            return Instrument.unmapped(key)
        return Instrument(key=key, isin=e["isin"], symbols=dict(e.get("symbols", {})))
