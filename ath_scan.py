#!/usr/bin/env python
"""Market Scanner CLI — find Nifty Total Market constituents at or near their
all-time high, using Upstox market data.

Market data comes from Upstox (long-lived analytics token, so no daily
interactive login); portfolio/holdings stay on Kite. Instruments are
addressed as `NSE_EQ|{ISIN}` straight from the constituents CSV's `ISIN Code`
column, so no broker instrument dump or token resolution step is needed.

Usage:
    python ath_scan.py                  # full scan, 26% cutoff
    python ath_scan.py --max-dist 10    # tighter cutoff
    python ath_scan.py --symbols INFY,TCS --verbose
    python ath_scan.py --rebuild        # re-download all history
"""
from __future__ import annotations

import argparse
import re
import sys
import traceback
from datetime import datetime, timedelta, timezone

import pandas as pd

from scanner import ath, factors, history, indicators, report
from scanner.constituents import load_constituents
from scanner.upstox import QUOTE_BATCH_SIZE, UpstoxClient, instrument_key

IST = timezone(timedelta(hours=5, minutes=30))
MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE = 15, 30
EXIT_BACKEND = 3
_BACKEND_HINT = (
    "Start Postgres with scripts/ensure_postgres.ps1, "
    "or set MARKETDATA_BACKEND=sqlite for an offline run."
)
_CONFIG_FILES = ("scanner/pg/db.py", "scanner/mongo.py")


def _backend_line(prefix: str, exc: BaseException) -> str:
    """One stderr line for a backend failure. Only the class name and the first
    line of the message are shown, with any password or URL credentials redacted."""
    first = (str(exc).splitlines() or [""])[0]
    first = re.sub(r"(password|pwd)\s*=\s*\S+", r"\1=***", first, flags=re.IGNORECASE)
    first = re.sub(r"://[^@/\s]+@", "://***@", first)
    return f"{prefix}: {type(exc).__name__}: {first}. {_BACKEND_HINT}"


def _check_backend() -> str | None:
    """Return an error line if the Postgres backend is unusable, else None.
    The sqlite backend is not checked here."""
    from scanner.marketdata import get_backend
    try:
        if get_backend() != "postgres":
            return None
    except ValueError as exc:
        return _backend_line("Backend check failed", exc)
    try:
        from scanner.pg import db
        with db.connect() as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception as exc:  # noqa: BLE001
        return _backend_line("Backend check failed", exc)
    return None


def _is_backend_failure(exc: Exception) -> bool:
    """True for infrastructure errors that would hit every symbol: a dropped or
    refused Postgres connection, or a configuration error raised from the
    Postgres or Mongo connection code. Per-symbol errors return False."""
    try:
        import psycopg
    except ImportError:
        psycopg = None
    if psycopg is not None and isinstance(exc, psycopg.OperationalError):
        return True
    if isinstance(exc, RuntimeError):
        frames = traceback.extract_tb(exc.__traceback__)
        return any(f.filename.replace("\\", "/").endswith(_CONFIG_FILES) for f in frames)
    return False


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scan Nifty Total Market for ATH proximity.")
    p.add_argument("--max-dist", type=float, default=26.0, help="Max %% below ATH to include (default 26)")
    p.add_argument("--constituents", type=str, default=None, help="Path to a local constituents CSV override")
    p.add_argument("--symbols", type=str, default=None, help="Comma-separated symbols to scan instead of the full index")
    p.add_argument("--verbose", action="store_true", help="Verbose logging")
    p.add_argument("--rebuild", action="store_true", help="Re-download constituents, instruments, and all history")
    p.add_argument("--refresh-history", type=str, default=None, help="Comma-separated symbols to force-refresh history for")
    p.add_argument("--no-factors", action="store_true", help="Skip corporate factors enrichment")
    p.add_argument("--refresh-factors", action="store_true", help="Force re-fetch corporate factors data")
    p.add_argument("--output-dir", type=str, default="output", help="Directory for output files")
    return p.parse_args()


def now_ist() -> datetime:
    return datetime.now(IST)


def is_intraday(now: datetime) -> bool:
    close = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0, microsecond=0)
    return now < close


def batched(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def main() -> int:
    args = parse_args()
    now = now_ist()
    today = now.date()
    intraday = is_intraday(now)
    refresh_symbols = set(
        s.strip().upper() for s in args.refresh_history.split(",")
    ) if args.refresh_history else set()

    backend_error = _check_backend()
    if backend_error:
        print(backend_error, file=sys.stderr)
        return EXIT_BACKEND

    print("Connecting to Upstox market data...")
    client = UpstoxClient()

    print("Loading Nifty Total Market constituents...")
    constituents_df = load_constituents(override_path=args.constituents, refresh=args.rebuild)
    if args.verbose:
        print(f"  {len(constituents_df)} constituents (DUMMY rows already dropped)")

    if args.symbols:
        wanted = [s.strip().upper() for s in args.symbols.split(",")]
        constituents_df = constituents_df[constituents_df["Symbol"].str.upper().isin(wanted)].reset_index(drop=True)
        missing = set(wanted) - set(constituents_df["Symbol"].str.upper())
        for sym in missing:
            constituents_df.loc[len(constituents_df)] = {
                "Company Name": sym,
                "Industry": "",
                "Symbol": sym,
                "Series": "EQ",
                "ISIN Code": "",
            }

    # Instruments resolve directly from the CSV's ISIN -- no broker instrument
    # dump, and no tradingsymbol matching that a rename could break.
    skipped: list[dict] = []
    resolved: dict[str, dict] = {}  # symbol -> {"key", "company", "industry"}

    for _, crow in constituents_df.iterrows():
        symbol = str(crow["Symbol"]).strip()
        isin = str(crow.get("ISIN Code", "")).strip()
        if not isin:
            # Only reachable via --symbols for a ticker outside the index,
            # where there is no ISIN to build an instrument_key from.
            skipped.append(
                {
                    "symbol": symbol,
                    "company": crow.get("Company Name", ""),
                    "reason": "no ISIN available (not in constituents CSV)",
                }
            )
            continue
        resolved[symbol] = {
            "key": instrument_key(isin),
            "company": crow.get("Company Name", ""),
            "industry": crow.get("Industry", ""),
        }

    print(f"Resolved {len(resolved)} / {len(constituents_df)} symbols to instrument keys.")

    print("Fetching live quotes...")
    quotes: dict[str, object] = {}
    symbol_list = list(resolved)

    for batch in batched(symbol_list, QUOTE_BATCH_SIZE):
        keys_by_symbol = {s: resolved[s]["key"] for s in batch}
        try:
            snaps, unmatched = client.quote_ohlc(keys_by_symbol)
        except Exception as exc:  # noqa: BLE001
            for sym in batch:
                skipped.append({"symbol": sym, "company": resolved[sym]["company"], "reason": f"quote fetch failed: {exc}"})
            continue
        quotes.update(snaps)
        if unmatched and args.verbose:
            print(f"  warning: {len(unmatched)} unmappable quote keys: {unmatched[:5]}")

    for sym in symbol_list:
        if sym not in quotes:
            skipped.append({"symbol": sym, "company": resolved[sym]["company"], "reason": "no quote data returned"})

    print(f"Fetching history for {len(quotes)} symbols (cached runs are fast)...")
    rows = []
    total = len(quotes)
    for idx, sym in enumerate(quotes.keys(), start=1):
        info = resolved[sym]
        snap = quotes[sym]
        ltp = snap.ltp
        today_high = snap.today_high

        if ltp is None or today_high is None:
            skipped.append({"symbol": sym, "company": info["company"], "reason": "missing ltp/high in quote"})
            continue

        if args.verbose and idx % 50 == 0:
            print(f"  [{idx}/{total}] {sym}...")

        try:
            hist = history.get_history(
                client,
                info["key"],
                sym,
                force_refresh=(args.rebuild or sym in refresh_symbols),
                today=today,
            )
        except Exception as exc:  # noqa: BLE001
            if _is_backend_failure(exc):
                # Every remaining symbol would fail the same way: stop the run.
                print(_backend_line("Backend failure mid-run", exc), file=sys.stderr)
                return EXIT_BACKEND
            skipped.append({"symbol": sym, "company": info["company"], "reason": f"history fetch failed: {exc}"})
            continue

        prior_candles = [
            ath.Candle(d=row.date, high=row.high, close=row.close)
            for row in hist.candles.itertuples(index=False)
        ]

        try:
            result = ath.scan_symbol(prior_candles, today_high, ltp, today, max_dist=args.max_dist)
        except ValueError as exc:
            skipped.append({"symbol": sym, "company": info["company"], "reason": str(exc)})
            continue

        if result is None:
            continue  # more than max_dist below ATH; not an error, just excluded

        # Moving averages. Cached candles stop at yesterday, so today's live
        # price is appended as today's close -- otherwise "trading above" would
        # answer yesterday's question. Costs no extra request.
        closes = [float(c) for c in hist.candles["close"].tolist()]
        closes.append(float(ltp))
        trend = indicators.compute_trend(closes, float(ltp))

        rows.append(
            {
                "symbol": sym,
                # Carried through so enrich.py can match NSE announcements, which
                # are keyed by ISIN and not by symbol. It is already in hand from
                # the constituents CSV, and re-deriving it downstream would mean
                # re-reading that file and re-doing the resolution.
                "isin": info["key"].split("|")[1],
                "company": info["company"],
                "industry": info["industry"],
                "ltp": ltp,
                "today_high": today_high,
                "ath_high": result.ath_high,
                "ath_date": result.ath_date,
                "ath_close": result.ath_close,
                "distance_pct": round(result.distance_pct, 4),
                "bucket": result.bucket,
                "days_since_ath": result.days_since_ath,
                "listed_days": result.listed_days,
                "recent_ipo": result.recent_ipo,
                **trend,
            }
        )

    df = pd.DataFrame(rows)
    as_of_str = today.isoformat()

    # Enrich with corporate factors if enabled
    if not args.no_factors and not df.empty:
        print("Enriching with corporate factors...")
        try:
            # Corporate actions: one cheap request, so take the widest window
            # any classifier needs. It must run PAST today -- a demerger that is
            # "about to happen" has a future ex-date, and capping at today makes
            # the UPCOMING branch unreachable.
            ca_from = factors._subtract_months(
                today, max(factors.BONUS_LOOKBACK_MONTHS, factors.DEMERGER_LOOKBACK_MONTHS)
            )
            ca_to = factors._add_months(today, factors.DEMERGER_FORWARD_MONTHS)

            # Announcements are ~17k rows/month of free text, so fetch only as
            # far back as the announcement-based classifiers actually look.
            ann_from = factors._subtract_months(
                today,
                max(
                    factors.ORDERBOOK_LOOKBACK_MONTHS,
                    factors.EXPANSION_LOOKBACK_MONTHS,
                    factors.DEMERGER_ANN_LOOKBACK_MONTHS,
                ),
            )
            ann_to = today  # filings cannot be dated in the future

            # Fetch with caching
            ca_rows = factors.fetch_corporate_actions(ca_from, ca_to, refresh=args.refresh_factors)
            ann_rows = factors.fetch_announcements(ann_from, ann_to, refresh=args.refresh_factors)

            # Build factor table indexed by ISIN
            isins = [resolved[sym]["key"].split("|")[1] for sym in df["symbol"]]
            factor_table = factors.build_factor_table(ca_rows, ann_rows, isins, today)

            # Merge factors into dataframe
            factors_data = []
            for sym in df["symbol"]:
                key = resolved[sym]["key"]
                isin = key.split("|")[1]
                factor_row = factor_table.get(isin, {
                    "bonus_issue": "",
                    "demerger": "",
                    "orderbook_signal": "",
                    "expansion_signal": "",
                    "factors_matched": 0,
                })
                factors_data.append(factor_row)

            factors_df = pd.DataFrame(factors_data)
            df = pd.concat([df, factors_df], axis=1)
            print(f"  Enriched {len(df)} rows with corporate factors")
        except Exception as e:  # noqa: BLE001
            print(f"Warning: factor enrichment failed: {e}")
            print("  Proceeding with empty factor columns")
            # Add empty factor columns so output is consistent
            df["bonus_issue"] = ""
            df["demerger"] = ""
            df["orderbook_signal"] = ""
            df["expansion_signal"] = ""
            df["factors_matched"] = 0
    elif not args.no_factors:
        # No rows matched, but add empty columns for consistency
        df["bonus_issue"] = ""
        df["demerger"] = ""
        df["orderbook_signal"] = ""
        df["expansion_signal"] = ""
        df["factors_matched"] = 0

    csv_path, xlsx_path = report.write_outputs(df, as_of_str, max_dist=args.max_dist, output_dir=args.output_dir)
    report.print_summary(df, now.strftime("%Y-%m-%d %H:%M IST"), intraday, max_dist=args.max_dist)
    report.write_skipped(skipped)

    print(f"\nWrote {csv_path} and {xlsx_path}")
    st = client.stats()
    print(f"Upstox: {st['requests_made']} requests, {st['responses_429']} rate-limited (429), "
          f"{st['seconds_waiting']}s spent throttling")
    print(f"Skipped {len(skipped)} symbols — see logs/skipped.csv")
    if intraday:
        print("Note: run during market hours — today's high/LTP are intraday, not final.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
