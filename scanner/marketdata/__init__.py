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


def get_backend() -> str:
    """Active backend: 'postgres' or 'sqlite'.

    Defaults to 'postgres' if Postgres is available; falls back to 'sqlite'.
    """
    backend = os.environ.get("MARKETDATA_BACKEND", "").lower()
    if backend in ("postgres", "sqlite"):
        return backend

    # Auto-detect
    try:
        from scanner.pg.db import available
        return "postgres" if available() else "sqlite"
    except Exception:
        return "sqlite"


def get_history_impl() -> object:
    """Return the backend's history implementation."""
    backend = get_backend()
    if backend == "postgres":
        from . import postgres_backend
        return postgres_backend
    else:
        from . import sqlite_backend
        return sqlite_backend


def get_factors_impl() -> object:
    """Return the backend's factors implementation."""
    backend = get_backend()
    if backend == "postgres":
        from . import postgres_backend
        return postgres_backend
    else:
        from . import sqlite_backend
        return sqlite_backend
