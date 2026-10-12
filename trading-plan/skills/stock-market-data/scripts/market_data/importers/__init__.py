"""Importers: each one turns one provider's export into rows of the own candle store (the write
side); nothing outside it knows that export's format."""
from __future__ import annotations
