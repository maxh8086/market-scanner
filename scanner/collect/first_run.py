"""First-run watcher: trigger the first ATH scan once, as soon as broker API details exist.

Runs inside the collector's `serve` loop (collect.py), once per loop pass (about 60 seconds),
so the first run starts within about a minute of the details appearing. It never queues more
than one run: a marker file (`data/first_run_done`) records that the first run was triggered.

The run is queued through the same collector request table the UI's "Run now" uses
(`collector_settings.request_run`); the serve loop then claims and executes it. Nothing here
calls ath_scan.py directly.

Decision table (`decide`):
    marker present                      -> done   (nothing to do)
    Upstox token not set                -> wait
    run already in progress             -> mark   (counts as the first run; no second run queued)
    otherwise                           -> queue  (queue one run, then write the marker)
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from scanner import secrets_store

# Collector source name for the ATH scan. Must be registered in scanner.collect.sources.SOURCES
# before a request can be queued; until then request_run raises ValueError and nothing is marked.
ATH_SCAN_SOURCE = "ath_scan"

# Stored secret that must exist before the first run may start (required field in secrets_store).
REQUIRED_KEY = "UPSTOX_ANALYTICS_ACCESS_TOKEN"

# A run started within this many seconds that is still 'running' counts as in progress.
RUN_TIMEOUT_SECONDS = 3600


def marker_path() -> Path:
    return Path(os.environ.get("FIRST_RUN_MARKER", "data/first_run_done"))


def decide(details_present: bool, marker_present: bool, run_in_progress: bool) -> tuple[str, str]:
    """Pure decision. Returns (action, reason); action is done | wait | mark | queue."""
    if marker_present:
        return "done", "marker present: first run already triggered"
    if not details_present:
        return "wait", f"{REQUIRED_KEY} not set; waiting for broker API details"
    if run_in_progress:
        return "mark", "a run is already in progress; counting it as the first run"
    return "queue", "API details present, no marker, no run in progress: queuing first run"


def _details_present() -> bool:
    """True when the required Upstox token is stored or in the environment."""
    return REQUIRED_KEY not in secrets_store.status()["missing"]


def _run_in_progress() -> bool:
    from scanner.pg import db
    from scanner.collect import scheduler
    with db.connect() as conn:
        return scheduler.is_running(conn, ATH_SCAN_SOURCE, timeout_seconds=RUN_TIMEOUT_SECONDS)


def _queue_run() -> bool:
    from scanner.collect import settings
    return settings.request_run(ATH_SCAN_SOURCE)


def _write_marker(path: Path, now: datetime, action: str, queued: Optional[bool]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"triggered_at": now.isoformat(), "action": action,
                               "queued": queued}) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def tick(now: datetime, *,
         path: Optional[Path] = None,
         details_present: Callable[[], bool] = _details_present,
         run_in_progress: Callable[[], bool] = _run_in_progress,
         queue_run: Callable[[], bool] = _queue_run,
         log: Callable[[str], None] = print) -> str:
    """One watcher pass. Returns the action taken: done | wait | mark | queue | error.

    Never raises: a failure is logged and retried on the next pass, with no marker written.
    """
    path = path or marker_path()
    stamp = f"[{now:%Y-%m-%d %H:%M:%S}] first-run"
    marker_present = path.is_file()

    try:
        has_details = details_present()
    except Exception as e:
        log(f"{stamp}: error: could not read API details ({type(e).__name__}: {e}); retry next pass")
        return "error"

    running = False
    if has_details and not marker_present:
        try:
            running = run_in_progress()
        except Exception as e:
            log(f"{stamp}: error: could not check running status ({type(e).__name__}: {e}); retry next pass")
            return "error"

    action, reason = decide(has_details, marker_present, running)

    if action == "queue":
        try:
            queued = queue_run()
        except Exception as e:
            log(f"{stamp}: error: could not queue {ATH_SCAN_SOURCE} ({type(e).__name__}: {e}); "
                f"no marker written, retry next pass")
            return "error"
        _write_marker(path, now, action, queued)
        log(f"{stamp}: queued {ATH_SCAN_SOURCE} (queued={queued}); marker written to {path}")
        return "queue"

    if action == "mark":
        _write_marker(path, now, action, None)
        log(f"{stamp}: {reason}; marker written to {path}")
        return "mark"

    log(f"{stamp}: {action}: {reason}")
    return action
