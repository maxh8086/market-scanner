"""Data source classes: one per source type. Each has run(params) returning status."""
from __future__ import annotations

import os
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

    # True for sources that write through the API events endpoints. execute_source checks the
    # API health endpoint before such a source runs (spec 4.5). HomeFilings sets this.
    events: bool = False

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
            from scanner import docstore, coverage, ath_scan_store

            # Load the newest scan from the candidate table
            with ath_scan_store.connect() as conn:
                found = ath_scan_store.read_latest_scan(conn)
            if found is None:
                return {
                    "fetched": 0, "new": 0, "from": None, "to": None,
                    "message": "skipped: no ath_scan_candidates rows"
                }
            df, _ = found

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
            from scanner import docstore, constituents, fundamentals, ath_scan_store

            # Load the newest scan from the candidate table
            with ath_scan_store.connect() as conn:
                found = ath_scan_store.read_latest_scan(conn)
            if found is None:
                return {
                    "fetched": 0, "new": 0, "from": None, "to": None,
                    "message": "skipped: no ath_scan_candidates rows"
                }
            df, _ = found
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
    full-universe arguments and --no-export, so the candidates go to the ath_scan_candidates table
    and no CSV is written. A non-zero exit code from ath_scan.main() raises, and so does a run
    that leaves zero candidates for the newest scan date.
    """

    def __init__(self):
        super().__init__("ath_scan")

    def run(self, params: dict, now: Optional[datetime] = None,
            dry_run: bool = False) -> dict:
        if dry_run:
            return self.plan(params, now)

        import sys

        import ath_scan  # /app/ath_scan.py in the collector image
        from scanner import ath_scan_store

        saved_argv = sys.argv
        sys.argv = ["ath_scan.py", "--no-export"]
        try:
            code = ath_scan.main()  # progress prints go to the collector log
        finally:
            sys.argv = saved_argv

        if code:
            raise RuntimeError(f"ath_scan exited with code {code}")

        with ath_scan_store.connect() as conn:
            scan_date = ath_scan_store.latest_scan_date(conn)
            rows = ath_scan_store.scan_row_count(conn, scan_date) if scan_date else 0
        if not rows:
            raise RuntimeError("ath_scan wrote zero candidates to ath_scan_candidates")
        return {
            "fetched": rows, "new": rows, "from": None, "to": None,
            "message": f"wrote {rows} candidates for {scan_date.isoformat()}",
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


class CompanyReference(Source):
    """Monthly reference refresh: NSE equity list, Upstox NSE master and index constituents.

    Calls scanner.company_reference_job.run_refresh with the loader role; loader_dsn reads the
    loader password from POSTGRES_LOADER_PASSWORD_FILE. The refresh is all-or-nothing: if any
    download or parse fails, nothing is written and last month's rows stay in place.
    """

    def __init__(self):
        super().__init__("company_reference")
        self.tz = pytz.timezone("Asia/Kolkata")

    def _today(self, now: Optional[datetime]) -> date:
        if now is None:
            now = datetime.now(pytz.UTC)
        if now.tzinfo is None:
            now = pytz.UTC.localize(now)
        return now.astimezone(self.tz).date()

    def run(self, params: dict, now: Optional[datetime] = None,
            dry_run: bool = False) -> dict:
        """Download and store the reference data. Success returns an empty message; `fetched`
        is the total number of rows written, and `new` is 0 because the refresh replaces the rows."""
        if dry_run:
            return self.plan(params, now)

        # Import late, as the other sources do
        import psycopg
        from scanner.company_reference_job import loader_dsn, run_refresh

        today = self._today(now)
        try:
            conn = psycopg.connect(loader_dsn())
            try:
                counts = run_refresh(conn, today=today)
            finally:
                conn.close()
        except Exception as e:
            return {
                "fetched": 0, "new": 0, "from": None, "to": None,
                "message": _redact(f"{type(e).__name__}: {e}")
            }
        return {
            "fetched": sum(counts.values()), "new": 0, "from": None, "to": today,
            "message": ""
        }

    def plan(self, params: dict, now: Optional[datetime] = None) -> dict:
        return {
            "fetched": 0, "new": 0, "from": None, "to": None,
            "message": "dry-run: would refresh NSE equity list, Upstox master and index constituents"
        }


_HOME_FILINGS_TOKEN_FILE_DEFAULT = "/run/app-keys/home_events_ingest_token"
_HOME_FILINGS_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _home_filings_failed(message: str) -> dict:
    return {"status": "failed", "fetched": 0, "new": 0, "from": None, "to": None,
            "message": message}


class HomeFilings(Source):
    """NSE exchange filings for the home events feed (spec 5.1, 4.5, 4.6, 6).

    Calls scanner.home_events.run_cycle with the NSE feed table, the company index from
    company_reference and the API ingest endpoint. The source is registered as `manual`
    (migration 052), so the serve loop does not run it. `events = True` makes execute_source
    check the API before the run. run() returns a `status` key ("ok", "failed" or
    "skipped"), which _run_locked records as the run status.
    """

    # Read by collect._run_locked through getattr(source, "events", False).
    events = True

    def __init__(self):
        super().__init__("home_filings")

    def plan(self, params: dict, now: Optional[datetime] = None) -> dict:
        """Count the enabled feeds without a network call, a DB connection or a token read."""
        from scanner import home_events

        try:
            _cfg, enabled = home_events._run_config(params, home_events.FEEDS)
        except home_events._ConfigError as exc:
            return {"fetched": 0, "new": 0, "from": None, "to": None,
                    "message": f"config:{exc.key}"}
        return {"fetched": 0, "new": 0, "from": None, "to": None,
                "message": f"dry-run: would fetch {len(enabled)} NSE feeds"}

    def run(self, params: dict, now: Optional[datetime] = None,
            dry_run: bool = False) -> dict:
        """Run one filings cycle. Every path returns the status shape; no exception escapes."""
        if dry_run:
            return self.plan(params, now)

        # Import late, as the other sources do; collect imports this module, so a top-level
        # import of collect would be circular.
        import random
        import time
        from collect import api_base_url
        from scanner import home_events
        from scanner.collect.cooldown import PgCooldown
        from scanner.company_reference import load_index_for_source
        from scanner.pg import db

        if now is None:
            now = datetime.now(pytz.UTC)
        elif now.tzinfo is None:
            now = pytz.UTC.localize(now)

        token_path = os.environ.get("HOME_EVENTS_INGEST_TOKEN_FILE", _HOME_FILINGS_TOKEN_FILE_DEFAULT)
        try:
            with open(token_path, encoding="utf-8") as fh:
                token = fh.read().strip()
        except Exception:
            # Neither the path nor the exception text is kept: both can name the secret location.
            return _home_filings_failed("token_unavailable")
        if not token:
            return _home_filings_failed("token_unavailable")

        try:
            with db.connect() as conn:
                index = load_index_for_source(conn, "nse_csv")
        except Exception as e:
            return _home_filings_failed(f"index_unavailable: {type(e).__name__}")

        session = requests.Session()
        session.headers.update({
            "User-Agent": _HOME_FILINGS_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

        try:
            base_url = api_base_url()
            timeout_s = params.get("post_timeout_s", 15)

            def post(rows: list[dict]) -> dict:
                return home_events.post_events(rows, base_url=base_url, token=token,
                                               http=requests, timeout_s=timeout_s)

            result = home_events.run_cycle(
                params, now,
                feeds=home_events.FEEDS,
                parse_fn=home_events.parse,
                universe=index.universe,
                by_name=index.by_name,
                session=session,
                post=post,
                sleep=time.sleep,
                rng=random.Random(),
                clock=lambda: datetime.now(pytz.UTC),
                cooldown=PgCooldown(),
            )
            return {
                "status": result["status"],
                "fetched": result["fetched"],
                "new": result["new"],
                "from": _iso_to_date(result.get("from")),
                "to": _iso_to_date(result.get("to")),
                "message": result.get("message", ""),
            }
        except Exception as e:
            return _home_filings_failed(_redact(f"{type(e).__name__}: {e}"))


def _iso_to_date(value: Optional[str]) -> Optional[date]:
    """The date part of run_cycle's ISO datetime string, or None."""
    return datetime.fromisoformat(value).date() if value else None


# Registry of all sources
SOURCES = {
    "candles_eod": CandlesEOD(),
    "index_eod": IndexEOD(),
    "announcements": Announcements(),
    "corporate_actions": CorporateActions(),
    "filings": Filings(),
    "fundamentals": Fundamentals(),
    "ath_scan": AthScan(),
    "company_reference": CompanyReference(),
    "home_filings": HomeFilings(),
}
