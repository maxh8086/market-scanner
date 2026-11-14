#!/usr/bin/env python3
"""Collector service: fetch and push data to databases.

Subcommands:
    run <source> [--trigger manual] [--dry-run]
        Run one source immediately (ignoring schedule); writes one collector_runs row

    run-once --source <name> [--trigger manual] [--dry-run] [--request-id <uuid>]
        Run one source once and exit; writes one collector_runs row.
        --request-id links that collector_requests row to the run (the container path)

    init
        One-time start-up duties, run by start.ps1 after migrations: register new sources in
        collector_settings, run the first-run watcher, report settings rows with no collector.
        Exit 0 on success, 3 if Postgres is unreachable.

    serve [--once] [--dry-run]
        Loop every 60 seconds: first-run watcher, reload settings, run due sources, claim requests
        --once: single pass then exit
        --dry-run: report what would happen without fetching

    status
        Print settings, last run per source, next due time

Every path goes through execute_source, which takes the per-source advisory lock and writes
one collector_runs row (ok, failed or skipped).

Exit codes: 0 = ok (or dry run), 1 = failed or unknown source, 2 = skipped (already_running,
api_unavailable), 3 = Postgres unreachable
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
import time
import uuid
from datetime import datetime

import psycopg
import pytz
import requests

from scanner.collect import sources as sources_module
from scanner.collect import first_run, scheduler, services, settings
from scanner.pg import db


def _get_source(name: str) -> sources_module.Source:
    """Get a source by name."""
    if name not in sources_module.SOURCES:
        raise ValueError(f"unknown source: {name}")
    return sources_module.SOURCES[name]


_reported_missing: set[str] = set()  # names already reported this process, so the log is not repeated every minute
_reported_container: set[str] = set()  # sources skipped because a container runs them (logged once each)


def split_registered(pairs, registry) -> tuple[list, list[str]]:
    """Split (source_name, trigger) pairs into runnable pairs and names with no collector.

    collector_settings can hold rows for sources that sources.py no longer (or not yet)
    defines. Those rows must not fail every minute of the serve loop, so they are skipped here
    and reported once by the caller."""
    runnable = [(name, trig) for name, trig in pairs if name in registry]
    missing = sorted({name for name, _ in pairs if name not in registry})
    return runnable, missing


class PostgresUnavailable(RuntimeError):
    """Postgres could not be reached. No collector_runs row is written in that case."""


def api_base_url() -> str:
    """Base URL of the Fastify server. COLLECTOR_API_BASE_URL overrides the local default."""
    explicit = os.environ.get("COLLECTOR_API_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    return f"http://127.0.0.1:{os.environ.get('SERVER_PORT', '8081')}"


def api_is_up(timeout: float = 5.0) -> bool:
    """True when GET /api/health returns 200. Any error counts as down."""
    try:
        resp = requests.get(f"{api_base_url()}/api/health", timeout=timeout)
        return resp.status_code == 200
    except Exception:
        return False


def _outcome(status: str, reason, result: dict, run_id=None) -> dict:
    return {"status": status, "reason": reason, "result": result, "run_id": run_id}


def _register_sources() -> list[str]:
    """Insert collector_settings rows for SOURCES keys that have none (settings.ensure_sources).

    Shared by serve and init. Exceptions propagate; each caller decides what they mean."""
    added = settings.ensure_sources()
    if added:
        print(f"registered sources: {', '.join(added)}")
    return added


def _link_request(request_id, run_id) -> None:
    """Link a claimed manual request to the run it started (collector_requests.collector_run).

    A failure is logged and never raised, so one bad link cannot stop the serve loop."""
    try:
        with db.connect() as conn:
            scheduler.link_request_to_run(conn, request_id, run_id)
    except Exception as e:
        print(f"could not link request {request_id} to run {run_id}: {e}", file=sys.stderr)


def _record_skip(name: str, trigger: str, reason: str, request_id=None) -> dict:
    with db.connect() as conn:
        run_id = scheduler.record_skipped(conn, name, trigger, reason)
    if request_id is not None:
        _link_request(request_id, run_id)
    empty = {"fetched": 0, "new": 0, "from": None, "to": None, "message": reason}
    return _outcome("skipped", reason, empty, run_id)


def _run_locked(source, name: str, trigger: str, dry_run: bool, now: datetime,
                api_check, request_id=None) -> dict:
    """Body of execute_source once the lock is held.

    A source whose result has its own `status` ("failed" or "skipped", as run_cycle returns)
    is recorded with that status instead of "ok". Sources without the key are unchanged.
    """
    if getattr(source, "events", False):
        # Events sources write through the API, so a down API means no run (spec 4.5).
        if not (api_check or api_is_up)():
            return _record_skip(name, trigger, "api_unavailable", request_id)

    with db.connect() as conn:
        params = scheduler.get_settings(conn).get(name, {}).get("params", {})
        run_id = scheduler.start_run(conn, name, trigger)
    if request_id is not None:
        _link_request(request_id, run_id)

    try:
        result = source.plan(params, now) if dry_run else source.run(params, now)
        status = "ok"
    except Exception as e:
        result = {"fetched": 0, "new": 0, "from": None, "to": None,
                  "message": f"{type(e).__name__}: {e}"}
        status = "failed"

    reason = None
    message = result.get("message", "") or ""
    if not dry_run and status == "ok" and result.get("status") in ("failed", "skipped"):
        status = result["status"]
        if status == "skipped":
            reason = message or None
    if dry_run and status == "ok":
        # A plan is not a run. Recording it as ok would hide missed slots from catch-up.
        status, reason = "skipped", "dry_run"
        message = f"dry_run: {message}".rstrip(": ")

    with db.connect() as conn:
        scheduler.finish_run(
            conn, run_id, status,
            result.get("fetched", 0), result.get("new", 0),
            result.get("from"), result.get("to"), message,
        )
    return _outcome(status, reason, result, run_id)


def execute_source(name: str, trigger: str, *, request_id=None, dry_run: bool = False,
                   now: datetime | None = None, api_check=None) -> dict:
    """Run one source once and record exactly one collector_runs row.

    serve, run and run-once all call this. Order: validate the name and trigger, open the
    connection that holds the per-source advisory lock (spec 4.2), and take the lock. A held
    lock writes skipped/already_running. An events source is checked against the API first;
    a down API writes skipped/api_unavailable. Otherwise the row is started, the source runs
    (or plan() when dry_run), and the row is finished. When request_id is given, the request is
    linked to the run as soon as the run row exists (before the source runs), skipped rows too.

    Returns {"status": "ok"|"failed"|"skipped", "reason": str|None, "result": dict,
    "run_id": uuid|None}. run_id is the collector_runs row written for this call.
    Raises ValueError for an unknown source or trigger, and PostgresUnavailable when the
    database cannot be reached (no row is written).
    """
    if trigger not in scheduler.TRIGGERS:
        raise ValueError(f"trigger must be one of {', '.join(scheduler.TRIGGERS)}: {trigger}")
    source = _get_source(name)
    now = now or datetime.now(pytz.UTC)

    # Connect first. This also loads the project .env, so SERVER_PORT is set for api_is_up.
    try:
        lock_conn = db.connect()
    except Exception as e:
        raise PostgresUnavailable(str(e)) from e

    try:
        if not scheduler.try_lock(lock_conn, name):
            return _record_skip(name, trigger, "already_running", request_id)
        try:
            return _run_locked(source, name, trigger, dry_run, now, api_check, request_id)
        finally:
            scheduler.unlock(lock_conn, name)
    finally:
        lock_conn.close()


def _run_once_cli(name: str, trigger: str, dry_run: bool, request_id=None) -> int:
    """Shared body of `run` and `run-once`: execute_source plus a printed report."""
    try:
        outcome = execute_source(name, trigger, dry_run=dry_run, request_id=request_id)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except PostgresUnavailable as e:
        print(f"Error: Postgres unreachable: {e}", file=sys.stderr)
        return 3

    result = outcome["result"]
    label = outcome["status"] if outcome["reason"] is None else f"{outcome['status']} ({outcome['reason']})"
    print(f"Source: {name}")
    print(f"  Status: {label}")
    print(f"  Fetched: {result.get('fetched', 0)}")
    print(f"  New: {result.get('new', 0)}")
    print(f"  From: {result.get('from')}")
    print(f"  To: {result.get('to')}")
    if result.get("message"):
        print(f"  Message: {result['message']}")

    if outcome["status"] == "failed":
        return 1
    if outcome["status"] == "skipped" and outcome["reason"] != "dry_run":
        return 2
    return 0


def cmd_run(args) -> int:
    """Run one source immediately (ignoring schedule)."""
    return _run_once_cli(args.source, args.trigger, args.dry_run)


def cmd_run_once(args) -> int:
    """Run one source once and exit. Used by the per-source containers (spec 4.1)."""
    request_id = None
    if args.request_id is not None:
        try:
            request_id = uuid.UUID(args.request_id)
        except ValueError:
            print("Error: --request-id must be a UUID", file=sys.stderr)
            return 1
    return _run_once_cli(args.source, args.trigger, args.dry_run, request_id)


def cmd_serve(args) -> int:
    """Loop: load settings, run due sources, claim requests."""
    # Set up graceful shutdown
    shutdown = False

    def handle_sigterm(signum, frame):
        nonlocal shutdown
        shutdown = True

    signal.signal(signal.SIGTERM, handle_sigterm)

    # Register any new source from SOURCES in collector_settings (no migration needed).
    try:
        _register_sources()
    except Exception as e:
        print(f"could not register sources (will retry on the next start): {e}", file=sys.stderr)

    iteration = 0
    while True:
        iteration += 1
        now = datetime.now(pytz.UTC)

        # Sources with their own container (config/collector_services.json) are not run here.
        # A malformed file ends this pass: running a container-owned source would run it twice.
        try:
            container_sources = services.load_container_sources()
        except ValueError as e:
            print(f"[{now:%Y-%m-%d %H:%M:%S}] {e}", file=sys.stderr)
            if args.once:
                return 1
            time.sleep(60)
            continue

        # First-run watcher: queue the one-time first ATH scan once API details exist.
        # It never raises; a failure is logged and retried on the next pass.
        try:
            first_run.tick(now)
        except Exception as e:
            print(f"[{now:%Y-%m-%d %H:%M:%S}] first-run watcher error: {e}", file=sys.stderr)

        # Load Postgres; if it's down, log and wait
        try:
            with db.connect() as conn:
                all_settings = scheduler.get_settings(conn)
                last_runs = scheduler.get_last_attempts(conn)
        except Exception as e:
            print(f"[{now:%Y-%m-%d %H:%M:%S}] Postgres error: {e}", file=sys.stderr)
            if args.once:
                return 3
            time.sleep(60)
            continue

        # Find due sources
        due = scheduler.due_sources(now, all_settings, last_runs)

        # Claim and run requests
        try:
            with db.connect() as conn:
                requests_list = scheduler.claim_requests(conn, container_sources)
        except Exception as e:
            print(f"[{now:%Y-%m-%d %H:%M:%S}] Failed to claim requests: {e}", file=sys.stderr)
            requests_list = []

        # Run due sources and claimed requests (sequentially)
        request_ids = {request["source"]: request["id"] for request in requests_list}
        to_run = []
        try:
            with db.connect() as conn:
                for source_name in due:
                    if not scheduler.is_running(conn, source_name, timeout_seconds=3600):
                        to_run.append((source_name, "schedule"))

                for request in requests_list:
                    source_name = request["source"]
                    if not scheduler.is_running(conn, source_name, timeout_seconds=3600):
                        to_run.append((source_name, "manual"))
        except Exception as e:
            print(f"[{now:%Y-%m-%d %H:%M:%S}] Failed to check running status: {e}", file=sys.stderr)

        kept = []
        for source_name, trigger in to_run:
            if source_name in container_sources:
                if source_name not in _reported_container:
                    _reported_container.add(source_name)
                    print(f"[{now:%Y-%m-%d %H:%M:%S}] skipped: '{source_name}' runs in its own container "
                          f"(config/collector_services.json)", file=sys.stderr)
            else:
                kept.append((source_name, trigger))
        to_run = kept

        to_run, missing = split_registered(to_run, sources_module.SOURCES)
        for name in missing:
            if name not in _reported_missing:
                _reported_missing.add(name)
                print(f"[{now:%Y-%m-%d %H:%M:%S}] skipped: '{name}' has a collector_settings row "
                      f"but no collector in sources.py", file=sys.stderr)

        for source_name, trigger in to_run:
            request_id = request_ids.get(source_name) if trigger == "manual" else None
            try:
                outcome = execute_source(source_name, trigger, request_id=request_id,
                                         dry_run=args.dry_run, now=now)
                result = outcome["result"]
                status = outcome["status"] if outcome["reason"] is None \
                    else f"{outcome['status']}: {outcome['reason']}"
                print(f"[{now:%Y-%m-%d %H:%M:%S}] {source_name} ({trigger}) {status}: "
                      f"{result.get('fetched', 0)} fetched, {result.get('new', 0)} new, "
                      f"message='{result.get('message', '')}'")
            except PostgresUnavailable as e:
                print(f"[{now:%Y-%m-%d %H:%M:%S}] Postgres error: {e}", file=sys.stderr)
            except Exception as e:
                print(f"[{now:%Y-%m-%d %H:%M:%S}] ERROR: {source_name}: {e}", file=sys.stderr)

        if args.once:
            return 0

        if shutdown:
            print(f"[{now:%Y-%m-%d %H:%M:%S}] SIGTERM received, exiting")
            return 0

        time.sleep(60)


def cmd_init(args) -> int:
    """One-time start-up duties (M5), run by start.ps1 after migrations and before any service starts.

    Exit 0 on success, 3 if Postgres is unreachable, 1 for any other failure."""
    now = datetime.now(pytz.UTC)
    try:
        with db.connect():
            pass
    except Exception as e:
        print(f"Error: Postgres unreachable: {e}", file=sys.stderr)
        return 3

    try:
        _register_sources()
        first_run.tick(now)
        with db.connect() as conn:
            setting_names = list(scheduler.get_settings(conn))
    except psycopg.OperationalError as e:
        print(f"Error: Postgres unreachable: {e}", file=sys.stderr)
        return 3
    except Exception as e:
        print(f"Error: init failed: {e}", file=sys.stderr)
        return 1

    _, missing = split_registered([(name, None) for name in setting_names], sources_module.SOURCES)
    for name in missing:
        print(f"warning: '{name}' has a collector_settings row but no collector in sources.py",
              file=sys.stderr)
    return 0


def cmd_status(args) -> int:
    """Print current settings and last run per source."""
    try:
        with db.connect() as conn:
            all_settings = scheduler.get_settings(conn)
            last_runs_dict = scheduler.get_last_runs(conn)
            attempts_dict = scheduler.get_last_attempts(conn)
    except Exception as e:
        print(f"Error: Postgres unreachable: {e}", file=sys.stderr)
        return 3

    print("Collector Settings:")
    print()
    for source in sorted(sources_module.SOURCES.keys()):
        config = all_settings.get(source, {})
        mode = config.get("mode", "")
        cron = config.get("cron", "")
        params = config.get("params", {})
        print(f"  {source}")
        print(f"    mode:   {mode}")
        print(f"    cron:   {cron}")
        print(f"    params: {params}")

    print()
    print("Last Runs (per source):")
    print()
    for source in sorted(sources_module.SOURCES.keys()):
        last_run = last_runs_dict.get(source)
        if last_run:
            print(f"  {source}: {last_run}")
        else:
            print(f"  {source}: never")

    print()
    print("Next Due (at current time):")
    print()
    now = datetime.now(pytz.UTC)
    due = scheduler.due_sources(now, all_settings, attempts_dict)
    for source in sorted(sources_module.SOURCES.keys()):
        if source in due:
            print(f"  {source}: DUE")
        else:
            print(f"  {source}: not due")

    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sp = ap.add_subparsers(dest="cmd", required=True)

    # run subcommand
    sp_run = sp.add_parser("run", help="Run one source immediately")
    sp_run.add_argument("source", help="source name")
    sp_run.add_argument("--trigger", default="manual", choices=scheduler.TRIGGERS,
                        help="trigger label (default: manual)")
    sp_run.add_argument("--dry-run", action="store_true", help="report what would happen")
    sp_run.set_defaults(func=cmd_run)

    # run-once subcommand
    sp_once = sp.add_parser("run-once", help="Run one source once and exit")
    sp_once.add_argument("--source", required=True, help="source name")
    sp_once.add_argument("--trigger", default="manual", choices=scheduler.TRIGGERS,
                         help="trigger label (default: manual)")
    sp_once.add_argument("--dry-run", action="store_true", help="report what would happen")
    sp_once.add_argument("--request-id", type=str, default=None,
                         help="collector_requests id (UUID) this run answers")
    sp_once.set_defaults(func=cmd_run_once)

    # serve subcommand
    sp_serve = sp.add_parser("serve", help="Loop: run due sources, claim requests")
    sp_serve.add_argument("--once", action="store_true", help="single pass then exit")
    sp_serve.add_argument("--dry-run", action="store_true", help="report what would happen")
    sp_serve.set_defaults(func=cmd_serve)

    # init subcommand
    sp_init = sp.add_parser("init", help="One-time start-up duties (run by start.ps1)")
    sp_init.set_defaults(func=cmd_init)

    # status subcommand
    sp_status = sp.add_parser("status", help="Print current settings and runs")
    sp_status.set_defaults(func=cmd_status)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
