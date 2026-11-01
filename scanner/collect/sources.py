"""Data source classes: one per source type. Each has run(params) returning status."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pytz
import requests


def _collect_each(symbols, fetch) -> tuple[int, int, str]:
    """Run fetch(symbol) for every symbol; one bad symbol must not stop the others.

    Returns (fetched, new, message). The message is empty when every symbol worked,
    otherwise it counts the failures and names the first error so the run history shows it.
    """
    fetched = new = failed = 0
    first_error = ""
    for symbol in symbols:
        try:
            result = fetch(symbol)
        except Exception as exc:
            failed += 1
            first_error = first_error or f"{type(exc).__name__}: {exc}"
            continue
        fetched += result.get("fetched", 0)
        new += result.get("new", 0)
    message = f"{failed} of {len(symbols)} symbols failed; first: {first_error}" if failed else ""
    return fetched, new, message


class Source(ABC):
    """Abstract base for a collectable data source."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def run(self, params: dict, now: Optional[datetime] = None,
            dry_run: bool = False) -> dict:
        """Fetch and store one source's data. Called by the scheduler.

        Args:
            params: source-specific parameters from collector_settings
            now: current time (for testing); defaults to datetime.now(UTC)
            dry_run: if True, call plan() instead of run() to report what would be fetched

        Returns:
            {
              "fetched": int (rows requested from provider),
              "new": int (rows new after de-duplication),
              "from": date | None (window start, ISO),
              "to": date | None (window end, ISO),
              "message": str (empty on success, error text on failure or skip reason)
            }
        """

    @abstractmethod
    def plan(self, params: dict, now: Optional[datetime] = None) -> dict:
        """Report what window would be fetched, without fetching.

        Used by --dry-run. Returns the same shape as run() but with
        fetched=0, new=0, and message explaining what would happen.
        """


class CandlesEOD(Source):
    """Daily candles from Upstox, end of day only.

    Time rule: refuses to run before 15:30 IST + margin on that trading day.
    Skips weekends. Never stores today's partial candle.
    """

    def __init__(self):
        super().__init__("candles_eod")
        self.tz = pytz.timezone("Asia/Kolkata")

    def _get_now(self, now: Optional[datetime]) -> datetime:
        if now is None:
            now = datetime.now(pytz.UTC)
        if now.tzinfo is None:
            now = pytz.UTC.localize(now)
        return now

    def _is_trading_day(self, d: date) -> bool:
        """Monday=0, ..., Sunday=6."""
        return d.weekday() < 5

    def _can_run_now(self, now: datetime, after_close_minutes: int) -> bool:
        """Check if it's after the market close (15:30 IST) plus margin."""
        ist_now = now.astimezone(self.tz)
        close_time = ist_now.replace(hour=15, minute=30, second=0, microsecond=0)
        min_run_time = close_time + timedelta(minutes=after_close_minutes)
        return ist_now >= min_run_time

    def run(self, params: dict, now: Optional[datetime] = None,
            dry_run: bool = False) -> dict:
        """Fetch candles for the last gap. Refuses if before market close + margin."""
        now = self._get_now(now)
        ist_now = now.astimezone(self.tz)
        today = ist_now.date()

        # Check if it's a trading day
        if not self._is_trading_day(today):
            return {
                "fetched": 0, "new": 0, "from": None, "to": None,
                "message": f"weekend ({today})"
            }

        # Check time gate
        after_close_minutes = params.get("after_close_minutes", 30)
        if not self._can_run_now(now, after_close_minutes):
            return {
                "fetched": 0, "new": 0, "from": None, "to": None,
                "message": f"before close+{after_close_minutes}m (at {ist_now.strftime('%H:%M IST')})"
            }

        if dry_run:
            return self.plan(params, now)

        # Import late to avoid circular deps
        from scanner import history, constituents, upstox
        from dotenv import load_dotenv

        try:
            # Load environment and Upstox credentials
            load_dotenv()
            token = __import__("os").environ.get("UPSTOX_ANALYTICS_ACCESS_TOKEN", "")
            if not token:
                return {
                    "fetched": 0, "new": 0, "from": None, "to": None,
                    "message": "skipped: UPSTOX_ANALYTICS_ACCESS_TOKEN not set"
                }

            client = upstox.UpstoxClient(token)

            # Get symbols from constituents
            cons = constituents.load_constituents()
            symbols = cons["Symbol"].tolist()

            fetched, new, message = _collect_each(
                symbols, lambda symbol: history.collect_eod(client, token, symbol, today))
            return {
                "fetched": fetched,
                "new": new,
                "from": None,
                "to": today,
                "message": message
            }
        except Exception as e:
            return {
                "fetched": 0, "new": 0, "from": None, "to": None,
                "message": f"{type(e).__name__}: {e}"
            }

    def plan(self, params: dict, now: Optional[datetime] = None) -> dict:
        """Report what window would be collected."""
        now = self._get_now(now)
        ist_now = now.astimezone(self.tz)
        today = ist_now.date()

        if not self._is_trading_day(today):
            return {
                "fetched": 0, "new": 0, "from": None, "to": None,
                "message": f"dry-run: would skip weekend ({today})"
            }

        after_close_minutes = params.get("after_close_minutes", 30)
        if not self._can_run_now(now, after_close_minutes):
            return {
                "fetched": 0, "new": 0, "from": None, "to": None,
                "message": f"dry-run: would wait for close+{after_close_minutes}m (now {ist_now.strftime('%H:%M IST')})"
            }

        return {
            "fetched": 0, "new": 0, "from": None, "to": None,
            "message": f"dry-run: would fetch candles for {today}"
        }


class Announcements(Source):
    """NSE announcements, as and when reported."""

    def __init__(self):
        super().__init__("announcements")

    def run(self, params: dict, now: Optional[datetime] = None,
            dry_run: bool = False) -> dict:
        """Fetch announcements for all scanned symbols, last 3 years."""
        if dry_run:
            return self.plan(params, now)

        # Import late
        from scanner import factors, constituents
        import requests
        try:
            # Get symbols from constituents
            cons = constituents.load_constituents()
            symbols = cons["Symbol"].tolist()

            session = requests.Session()
            fetched, new, message = _collect_each(
                symbols,
                lambda symbol: factors.collect_announcements(symbol, listing_date=None, session=session))
            return {
                "fetched": fetched,
                "new": new,
                "from": None,
                "to": date.today(),
                "message": message
            }
        except Exception as e:
            return {
                "fetched": 0, "new": 0, "from": None, "to": None,
                "message": f"{type(e).__name__}: {e}"
            }

    def plan(self, params: dict, now: Optional[datetime] = None) -> dict:
        return {
            "fetched": 0, "new": 0, "from": None, "to": None,
            "message": "dry-run: would fetch announcements"
        }


class CorporateActions(Source):
    """NSE corporate actions, as and when reported."""

    def __init__(self):
        super().__init__("corporate_actions")

    def run(self, params: dict, now: Optional[datetime] = None,
            dry_run: bool = False) -> dict:
        """Fetch corporate actions for all scanned symbols."""
        if dry_run:
            return self.plan(params, now)

        # Import late
        from scanner import factors, constituents
        import requests
        try:
            # Get symbols from constituents
            cons = constituents.load_constituents()
            symbols = cons["Symbol"].tolist()

            session = requests.Session()
            fetched, new, message = _collect_each(
                symbols,
                lambda symbol: factors.collect_corporate_actions(symbol, listing_date=None, session=session))
            return {
                "fetched": fetched,
                "new": new,
                "from": None,
                "to": date.today(),
                "message": message
            }
        except Exception as e:
            return {
                "fetched": 0, "new": 0, "from": None, "to": None,
                "message": f"{type(e).__name__}: {e}"
            }

    def plan(self, params: dict, now: Optional[datetime] = None) -> dict:
        return {
            "fetched": 0, "new": 0, "from": None, "to": None,
            "message": "dry-run: would fetch corporate actions"
        }


class Filings(Source):
    """Order/expansion/guidance filings from NSE, as and when published."""

    def __init__(self):
        super().__init__("filings")

    def run(self, params: dict, now: Optional[datetime] = None,
            dry_run: bool = False) -> dict:
        """Fetch new filings not yet in docstore."""
        if dry_run:
            return self.plan(params, now)

        try:
            from scanner import docstore, coverage
            import pandas as pd
            from pathlib import Path

            # Load the latest scan
            output_dir = Path("output")
            candidates = sorted(output_dir.glob("ath_scan_*.csv"))
            if not candidates:
                return {
                    "fetched": 0, "new": 0, "from": None, "to": None,
                    "message": "skipped: no ath_scan_*.csv in output/"
                }

            scan_path = candidates[-1]
            df = pd.read_csv(scan_path, keep_default_na=False)

            # Dynamically load enrich to get _candidate_filings and stage_filings
            import enrich
            today = date.today()
            candidates_list, funnel = enrich._candidate_filings(df, today)

            # Filter to only new ones
            db = docstore.open_db()
            todo = [c for c in candidates_list
                    if not docstore.has_filing_text(db, c["seq_id"])]

            if not todo:
                return {
                    "fetched": 0, "new": 0, "from": None, "to": None,
                    "message": f"skipped: all {len(candidates_list)} candidates already fetched"
                }

            # stage_filings handles the actual fetch
            enrich.stage_filings(db, df, limit=None, refetch=False)

            # Return a summary (actual counts come from the docstore changes)
            return {
                "fetched": len(todo),
                "new": len(todo),
                "from": None,
                "to": today,
                "message": ""
            }

        except FileNotFoundError:
            return {
                "fetched": 0, "new": 0, "from": None, "to": None,
                "message": "skipped: no ath_scan_*.csv in output/"
            }
        except Exception as e:
            return {
                "fetched": 0, "new": 0, "from": None, "to": None,
                "message": f"{type(e).__name__}: {e}"
            }

    def plan(self, params: dict, now: Optional[datetime] = None) -> dict:
        return {
            "fetched": 0, "new": 0, "from": None, "to": None,
            "message": "dry-run: would fetch new filings"
        }


class Fundamentals(Source):
    """Market cap and ratios from screener.in."""

    def __init__(self):
        super().__init__("fundamentals")

    def run(self, params: dict, now: Optional[datetime] = None,
            dry_run: bool = False) -> dict:
        """Refetch fundamentals only when stale or missing."""
        if dry_run:
            return self.plan(params, now)

        try:
            from scanner import docstore, constituents, fundamentals
            import pandas as pd
            from pathlib import Path

            # Load the latest scan
            output_dir = Path("output")
            candidates = sorted(output_dir.glob("ath_scan_*.csv"))
            if not candidates:
                return {
                    "fetched": 0, "new": 0, "from": None, "to": None,
                    "message": "skipped: no ath_scan_*.csv in output/"
                }

            scan_path = candidates[-1]
            df = pd.read_csv(scan_path, keep_default_na=False)
            symbols = [s for s in df["symbol"].tolist() if s]

            # Determine which symbols need refetching
            max_age_days = params.get("max_age_days", 30)
            db = docstore.open_db()

            to_fetch = []
            for symbol in symbols:
                age = docstore.fundamentals_age_days(db, symbol)
                if age is None or age > max_age_days:
                    to_fetch.append(symbol)

            if not to_fetch:
                return {
                    "fetched": 0, "new": 0, "from": None, "to": None,
                    "message": f"skipped: all {len(symbols)} symbols have fresh fundamentals"
                }

            # Fetch the stale ones
            results = fundamentals.fetch_many(db, to_fetch, force=False)
            ok = sum(1 for f in results.values() if f.ok)

            return {
                "fetched": len(to_fetch),
                "new": ok,
                "from": None,
                "to": date.today(),
                "message": "" if ok == len(to_fetch) else f"{ok} of {len(to_fetch)} succeeded"
            }

        except FileNotFoundError:
            return {
                "fetched": 0, "new": 0, "from": None, "to": None,
                "message": "skipped: no ath_scan_*.csv in output/"
            }
        except Exception as e:
            return {
                "fetched": 0, "new": 0, "from": None, "to": None,
                "message": f"{type(e).__name__}: {e}"
            }

    def plan(self, params: dict, now: Optional[datetime] = None) -> dict:
        return {
            "fetched": 0, "new": 0, "from": None, "to": None,
            "message": "dry-run: would refetch stale fundamentals"
        }


# Registry of all sources
SOURCES = {
    "candles_eod": CandlesEOD(),
    "announcements": Announcements(),
    "corporate_actions": CorporateActions(),
    "filings": Filings(),
    "fundamentals": Fundamentals(),
}
