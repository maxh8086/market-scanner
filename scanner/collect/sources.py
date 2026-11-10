"""Data source classes: one per source type. Each has run(params) returning status."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pytz
import requests

from scanner import service_client
from scanner.mongo import _redact


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
            first_error = first_error or _redact(f"{type(exc).__name__}: {exc}")
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
            try:
                token = service_client.fetch_secret("upstox_analytics_token")
            except service_client.SecretUnavailable as exc:
                return {
                    "fetched": 0, "new": 0, "from": None, "to": None,
                    "message": f"skipped: upstox token unavailable ({exc})"
                }

            client = upstox.UpstoxClient(token)

            # Get symbols from constituents
            cons = constituents.load_constituents()
            # Instrument key per symbol, built from the constituents ISIN. Symbols
            # without an ISIN cannot be fetched, so they are skipped.
            keys = {}
            for _, crow in cons.iterrows():
                isin = crow.get("ISIN Code")
                if isinstance(isin, str) and isin.strip():
                    keys[str(crow["Symbol"]).strip()] = upstox.instrument_key(isin)
            symbols = list(keys)

            fetched, new, message = _collect_each(
                symbols, lambda symbol: history.collect_eod(client, keys[symbol], symbol, today))
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
                "message": _redact(f"{type(e).__name__}: {e}")
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
                "message": _redact(f"{type(e).__name__}: {e}")
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
                "message": _redact(f"{type(e).__name__}: {e}")
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
                "message": _redact(f"{type(e).__name__}: {e}")
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
                "message": _redact(f"{type(e).__name__}: {e}")
            }

    def plan(self, params: dict, now: Optional[datetime] = None) -> dict:
        return {
            "fetched": 0, "new": 0, "from": None, "to": None,
            "message": "dry-run: would refetch stale fundamentals"
        }


class AthScan(Source):
    """The ATH scan (ath_scan.py), run in-process so the collector can queue it.

    Queued by the UI "Run now" button and by the first-run watcher (scanner/collect/first_run.py),
    both through collector_settings.request_run. It calls ath_scan.main() with the default
    full-universe arguments and writes output/ath_scan_<date>.csv, as the scanner image does.
    A non-zero exit code from ath_scan.main() raises, so the run is recorded as failed.
    """

    def __init__(self):
        super().__init__("ath_scan")

    def run(self, params: dict, now: Optional[datetime] = None,
            dry_run: bool = False) -> dict:
        if dry_run:
            return self.plan(params, now)

        import glob
        import sys
        from pathlib import Path

        import ath_scan  # /app/ath_scan.py in the collector image

        out_dir = Path("output")
        before = set(glob.glob(str(out_dir / "ath_scan_*.csv")))
        saved_argv = sys.argv
        sys.argv = ["ath_scan.py", "--output-dir", str(out_dir)]
        try:
            code = ath_scan.main()  # progress prints go to the collector log
        finally:
            sys.argv = saved_argv

        if code:
            raise RuntimeError(f"ath_scan exited with code {code}")

        written = sorted(set(glob.glob(str(out_dir / "ath_scan_*.csv"))) - before)
        if not written:
            written = sorted(glob.glob(str(out_dir / "ath_scan_*.csv")))[-1:]
        if not written:
            raise RuntimeError("ath_scan finished but wrote no output/ath_scan_*.csv")

        import pandas as pd
        rows = len(pd.read_csv(written[-1], keep_default_na=False))
        return {
            "fetched": rows, "new": rows, "from": None, "to": None,
            "message": f"wrote {written[-1]}",
        }

    def plan(self, params: dict, now: Optional[datetime] = None) -> dict:
        return {
            "fetched": 0, "new": 0, "from": None, "to": None,
            "message": "dry-run: would run the full ATH scan (ath_scan.py)"
        }


class IndexEOD(Source):
    """End-of-day closes for the benchmark indices (scanner/index_candles.py).

    Stored under IDX:<NAME> in candles, so the UI can show the last close when the
    market is shut. Skips weekends and the market session (09:15 to 15:30 IST, when
    today's bar is partial). After 15:30 IST the target is today; before it, the
    previous weekday. The scheduler runs it at 15:45 and in an 08:45 retry; a manual
    refresh queued after 15:30 IST is not skipped.
    """

    OPEN_MIN = 9 * 60 + 15    # 09:15 IST
    CLOSE_MIN = 15 * 60 + 30  # 15:30 IST

    def __init__(self):
        super().__init__("index_eod")
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

    def _target_date(self, ist_now: datetime) -> date:
        """Latest completed trading day: today once 15:30 IST has passed, else the previous weekday."""
        day = ist_now.date()
        if ist_now.hour * 60 + ist_now.minute >= self.CLOSE_MIN:
            return day
        day -= timedelta(days=1)
        while not self._is_trading_day(day):
            day -= timedelta(days=1)
        return day

    @staticmethod
    def _skip(message: str) -> dict:
        return {"fetched": 0, "new": 0, "from": None, "to": None, "message": message}

    def run(self, params: dict, now: Optional[datetime] = None,
            dry_run: bool = False) -> dict:
        """Fetch index closes for the target day, or skip with a reason."""
        if dry_run:
            return self.plan(params, now)

        now = self._get_now(now)
        ist_now = now.astimezone(self.tz)
        today = ist_now.date()
        minutes = ist_now.hour * 60 + ist_now.minute

        if not self._is_trading_day(today):
            return self._skip(f"weekend ({today})")
        if self.OPEN_MIN <= minutes < self.CLOSE_MIN:
            return self._skip("market open, waiting for 15:30 IST")

        # Import late to avoid circular deps
        from dotenv import load_dotenv

        try:
            from scanner import index_candles

            target = self._target_date(ist_now)
            if all(
                (last := index_candles.last_stored_date(name)) is not None and last >= target
                for name in index_candles.INDEX_KEYS
            ):
                return self._skip(f"already stored through {target}")

            load_dotenv()
            try:
                token = service_client.fetch_secret("upstox_analytics_token")
            except service_client.SecretUnavailable as exc:
                return self._skip(f"skipped: upstox token unavailable ({exc})")

            from scanner import upstox
            client = upstox.UpstoxClient(token)
            include_today = minutes >= self.CLOSE_MIN

            fetched = new = failed = 0
            first_error = ""
            for name in index_candles.INDEX_KEYS:
                try:
                    key, rows, err = index_candles.resolve_and_fetch(
                        client, name, since=index_candles.last_stored_date(name),
                        today=today, include_today=include_today)
                    if rows:
                        fetched += len(rows)
                        new += index_candles.store(name, rows)
                    if key is None or err:
                        failed += 1
                        first_error = first_error or _redact(str(err or "no candles returned"))
                except Exception as exc:
                    failed += 1
                    first_error = first_error or _redact(f"{type(exc).__name__}: {exc}")

            total = len(index_candles.INDEX_KEYS)
            message = f"{failed} of {total} indices failed; first: {first_error}" if failed else ""
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
                "message": _redact(f"{type(e).__name__}: {e}")
            }

    def plan(self, params: dict, now: Optional[datetime] = None) -> dict:
        """Report what would be fetched, without fetching."""
        now = self._get_now(now)
        ist_now = now.astimezone(self.tz)
        today = ist_now.date()
        minutes = ist_now.hour * 60 + ist_now.minute

        if not self._is_trading_day(today):
            return self._skip(f"dry-run: would skip weekend ({today})")
        if self.OPEN_MIN <= minutes < self.CLOSE_MIN:
            return self._skip(f"dry-run: would wait for 15:30 IST (now {ist_now.strftime('%H:%M IST')})")
        return self._skip(f"dry-run: would fetch index closes through {self._target_date(ist_now)}")


# Registry of all sources
SOURCES = {
    "candles_eod": CandlesEOD(),
    "index_eod": IndexEOD(),
    "announcements": Announcements(),
    "corporate_actions": CorporateActions(),
    "filings": Filings(),
    "fundamentals": Fundamentals(),
    "ath_scan": AthScan(),
}
