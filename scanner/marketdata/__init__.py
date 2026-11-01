"""Storage interface for market data (candles, announcements, corporate actions).

Implementations:
  - sqlite_backend: data/history.db and data/factors.db (the original)
  - postgres_backend: Postgres tables (migration target)

The public API in history.py and factors.py is backend-agnostic. Consumers
never import from this module; they call history.get_history() and
factors.build_factor_table(), which delegate to the active backend.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date
    import pandas as pd
    from scanner.history import SymbolHistory


_ALLOWED_BACKENDS = ("postgres", "sqlite")


def get_backend() -> str:
    """Active market-data backend: 'postgres' or 'sqlite'.

    MARKETDATA_BACKEND unset or empty selects 'postgres' (the live store).
    'sqlite' is used only when it is set explicitly (case-insensitive).
    There is no auto-detect and no silent fallback to local files: if
    Postgres is down, the caller fails. Any other non-empty value raises
    ValueError.
    """
    raw = os.environ.get("MARKETDATA_BACKEND", "")
    backend = raw.strip().lower()
    if not backend:
        return "postgres"
    if backend in _ALLOWED_BACKENDS:
        return backend
    raise ValueError(
        f"MARKETDATA_BACKEND={raw!r} is not valid; "
        f"allowed values are {', '.join(_ALLOWED_BACKENDS)} (unset means postgres)"
    )


def get_history_impl() -> object:
    """Return the backend's history implementation.

    No callers exist in this checkout. The sqlite module is not present.
    """
    backend = get_backend()
    if backend == "postgres":
        from . import postgres_backend
        return postgres_backend
    raise NotImplementedError(
        "sqlite backend module is not in this checkout; use MARKETDATA_BACKEND=postgres"
    )


def get_factors_impl() -> object:
    """Return the backend's factors implementation.

    No callers exist in this checkout. The sqlite module is not present.
    """
    backend = get_backend()
    if backend == "postgres":
        from . import postgres_backend
        return postgres_backend
    raise NotImplementedError(
        "sqlite backend module is not in this checkout; use MARKETDATA_BACKEND=postgres"
    )
