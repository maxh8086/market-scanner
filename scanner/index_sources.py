"""Index constituent sources, shared by the monthly job (scanner/company_reference_job.py),
the fetch script (scripts/fetch_index_constituents.py) and the readers.

Index names are uppercase (design rule M-11). Each value is an ordered tuple of candidate CSV
URLs, tried in order: the primary host with up to MAX_VARIANTS filename variants first, then the
fallback host with the first filename variant (rule M-08). Add an index here and nowhere else.
"""
from __future__ import annotations

PRIMARY_BASE = "https://nsearchives.nseindia.com/content/indices/"
FALLBACK_BASE = "https://www.niftyindices.com/IndexConstituent/"
MAX_VARIANTS = 3

# index name -> filename variants; the first variant is the known candidate.
_FILENAMES: dict[str, list[str]] = {
    "NIFTY TOTAL MARKET": ["ind_niftytotalmarket_list.csv"],
    "NIFTY 50": ["ind_nifty50list.csv", "ind_nifty_50_list.csv", "ind_nifty50_list.csv"],
    "NIFTY NEXT 50": ["ind_niftynext50list.csv", "ind_nifty_next50_list.csv", "ind_niftynext50_list.csv"],
    "NIFTY MIDCAP 150": [
        "ind_niftymidcap150list.csv",
        "ind_nifty_midcap150_list.csv",
        "ind_niftymidcap_150list.csv",
    ],
    "NIFTY SMALLCAP 250": [
        "ind_niftysmallcap250list.csv",
        "ind_nifty_smallcap250_list.csv",
        "ind_niftysmallcap_250list.csv",
    ],
    "NIFTY MICROCAP 250": [
        "ind_niftymicrocap250_list.csv",
        "ind_niftymicrocap250list.csv",
        "ind_nifty_microcap250_list.csv",
    ],
    "NIFTY BANK": ["ind_niftybanklist.csv", "ind_nifty_bank_list.csv", "ind_niftybank_list.csv"],
}


def _candidates(variants: list[str]) -> tuple[str, ...]:
    primary = [PRIMARY_BASE + f for f in variants[:MAX_VARIANTS]]
    return tuple(primary + [FALLBACK_BASE + variants[0]])


INDEX_SOURCES: dict[str, tuple[str, ...]] = {name: _candidates(v) for name, v in _FILENAMES.items()}
INDEX_NAMES: tuple[str, ...] = tuple(INDEX_SOURCES)
