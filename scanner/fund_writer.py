"""Write non-bank fund_derive Lines into fund_line (quarterly and annual series).

Pure conversion (fund_line_rows) is separated from the upsert (write_fund_lines) so the
row shape and bank refusal can be tested without a database. The app role has no DELETE
grant, so this module only ever upserts.
"""
from scanner.fund_derive import Line, is_bank

SOURCES = ("screener", "nse")
SECTIONS = ("quarters", "profit_loss", "balance_sheet", "cash_flow", "ratios", "shareholding")

_UPSERT = (
    "INSERT INTO fund_line (symbol, section, period, period_end, label, canonical, value, raw, source) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
    "ON CONFLICT (symbol, section, period, label, source) "
    "DO UPDATE SET period_end = EXCLUDED.period_end, canonical = EXCLUDED.canonical, "
    "value = EXCLUDED.value, raw = EXCLUDED.raw, fetched_at = now()"
)


class BankNotSupported(ValueError):
    """Raised for bank input, which needs its own row mapping (out of scope here)."""


def fund_line_rows(symbol: str, lines: list[Line], source: str = "screener") -> list[tuple]:
    """Convert Lines into fund_line parameter tuples, in SQL placeholder order.

    Keeps only Lines in SECTIONS. Duplicate (section, period, label) keys keep the last value
    at the position of the first occurrence. Raises BankNotSupported before any filtering.
    """
    sym = str(symbol).strip()
    if not sym:
        raise ValueError("symbol required")
    if source not in SOURCES:
        raise ValueError(f"unsupported source: {source!r}")

    lines = list(lines)
    if is_bank(lines):
        raise BankNotSupported(
            "bank input is not supported: balance sheet has a Deposits row; "
            "the bank row mapping is out of scope"
        )

    keyed: dict[tuple, Line] = {}
    for line in lines:
        if line.section not in SECTIONS:
            continue
        # Assigning an existing key keeps its first position and replaces its value.
        keyed[(line.section, line.period, line.label)] = line

    return [
        (sym, line.section, line.period, line.period_end, line.label, line.canonical,
         line.value, line.raw, source)
        for line in keyed.values()
    ]


def write_fund_lines(conn, symbol: str, lines: list[Line], source: str = "screener") -> int:
    """Upsert the non-bank Lines for one symbol in a single transaction. Returns the row count."""
    rows = fund_line_rows(symbol, lines, source=source)
    if not rows:
        return 0
    with conn.transaction():
        for row in rows:
            conn.execute(_UPSERT, row)
    return len(rows)
