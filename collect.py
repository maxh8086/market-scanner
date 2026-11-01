#!/usr/bin/env python3
"""Collector service: fetch and push data to databases.

Subcommands:
    run <source> [--trigger manual] [--dry-run]
        Run one source immediately (ignoring schedule)

    serve [--once] [--dry-run]
        Loop every 60 seconds: reload settings, run due sources, claim requests
        --once: single pass then exit
        --dry-run: report what would happen without fetching

    status
        Print settings, last run per source, next due time

Exit codes: 0 = ok, 3 = Postgres unreachable
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime

import psycopg
import pytz

from scanner.collect import sources as sources_module
from scanner.collect import scheduler, settings
from scanner.pg import db


def _get_source(name: str) -> sources_module.Source:
    """Get a source by name."""
    if name not in sources_module.SOURCES:
        raise ValueError(f"unknown source: {name}")
    return sources_module.SOURCES[name]


def cmd_run(args) -> int:
    """Run one source immediately."""
    try:
        source = _get_source(args.source)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Load settings
    try:
        with db.connect() as conn:
            all_settings = scheduler.get_settings(conn)
    except Exception:
        print("Error: Postgres unreachable", file=sys.stderr)
        return 3

    source_config = all_settings.get(args.source, {})
    params = source_config.get("params", {})

    # Run the source
    now = datetime.now(pytz.UTC)
    try:
        if args.dry_run:
            result = source.plan(params, now)
        else:
            result = source.run(params, now)
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    # Print result
    print(f"Source: {args.source}")
    print(f"  Fetched: {result['fetched']}")
    print(f"  New: {result['new']}")
    print(f"  From: {result.get('from')}")
    print(f"  To: {result.get('to')}")
    if result.get("message"):
        print(f"  Message: {result['message']}")

    return 0


def cmd_serve(args) -> int:
    """Loop: load settings, run due sources, claim requests."""
    # Set up graceful shutdown
    shutdown = False

    def handle_sigterm(signum, frame):
        nonlocal shutdown
        shutdown = True

    signal.signal(signal.SIGTERM, handle_sigterm)

    iteration = 0
    while True:
        iteration += 1
        now = datetime.now(pytz.UTC)

        # Load Postgres; if it's down, log and wait
        try:
            with db.connect() as conn:
                all_settings = scheduler.get_settings(conn)
                last_runs = scheduler.get_last_runs(conn)
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
                requests_list = scheduler.claim_requests(conn)
        except Exception as e:
            print(f"[{now:%Y-%m-%d %H:%M:%S}] Failed to claim requests: {e}", file=sys.stderr)
            requests_list = []

        # Run due sources and claimed requests (sequentially)
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

        for source_name, trigger in to_run:
            try:
                source = _get_source(source_name)
                all_settings = scheduler.get_settings(db.connect())
                source_config = all_settings.get(source_name, {})
                params = source_config.get("params", {})

                # Start a run record
                with db.connect() as conn:
                    run_id = scheduler.start_run(conn, source_name, trigger)

                # Execute
                try:
                    if args.dry_run:
                        result = source.plan(params, now)
                    else:
                        result = source.run(params, now)
                    status = "ok"
                except Exception as e:
                    result = {
                        "fetched": 0, "new": 0, "from": None, "to": None,
                        "message": f"{type(e).__name__}: {e}"
                    }
                    status = "failed"

                # Finish the run record
                with db.connect() as conn:
                    scheduler.finish_run(
                        conn, run_id, status,
                        result.get("fetched", 0),
                        result.get("new", 0),
                        result.get("from"),
                        result.get("to"),
                        result.get("message", "")
                    )

                print(f"[{now:%Y-%m-%d %H:%M:%S}] {source_name} ({trigger}): "
                      f"{result.get('fetched', 0)} fetched, {result.get('new', 0)} new, "
                      f"message='{result.get('message', '')}'")

            except Exception as e:
                print(f"[{now:%Y-%m-%d %H:%M:%S}] ERROR: {source_name}: {e}", file=sys.stderr)

        if args.once:
            return 0

        if shutdown:
            print(f"[{now:%Y-%m-%d %H:%M:%S}] SIGTERM received, exiting")
            return 0

        time.sleep(60)


def cmd_status(args) -> int:
    """Print current settings and last run per source."""
    try:
        with db.connect() as conn:
            all_settings = scheduler.get_settings(conn)
            last_runs_dict = scheduler.get_last_runs(conn)
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
    due = scheduler.due_sources(now, all_settings, last_runs_dict)
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
    sp_run.add_argument("--trigger", default="manual", help="trigger label (default: manual)")
    sp_run.add_argument("--dry-run", action="store_true", help="report what would happen")
    sp_run.set_defaults(func=cmd_run)

    # serve subcommand
    sp_serve = sp.add_parser("serve", help="Loop: run due sources, claim requests")
    sp_serve.add_argument("--once", action="store_true", help="single pass then exit")
    sp_serve.add_argument("--dry-run", action="store_true", help="report what would happen")
    sp_serve.set_defaults(func=cmd_serve)

    # status subcommand
    sp_status = sp.add_parser("status", help="Print current settings and runs")
    sp_status.set_defaults(func=cmd_status)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
