"""Pure helpers for broker login: secret names and token expiry (broker login, phase 1).

Per-profile per-broker secrets are named broker_<profile>_<broker>_<kind>. The profile has no
underscores, so the name splits unambiguously. A Kite access token expires at the next 06:00
Asia/Kolkata after it was stored (Upstox, later: 03:30). Expiry is computed from
app_secret.updated_at, so app_secret needs no extra column.

Nothing here touches the network or the database.
"""
from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
UTC = dt.timezone.utc
DEFAULT_PROFILE = "default"
PROFILE_RE = re.compile(r"[a-z][a-z0-9]{0,15}")
SECRET_NAME_RE = re.compile(
    r"^broker_([a-z][a-z0-9]{0,15})_(kite|upstox)_(access_token|api_key|api_secret)$")
BROKERS = ("kite", "upstox")
KINDS = ("access_token", "api_key", "api_secret")
_CUTOFF_IST = {"kite": dt.time(6, 0), "upstox": dt.time(3, 30)}


def validate_profile(profile: str) -> str:
    if not isinstance(profile, str) or not PROFILE_RE.fullmatch(profile):
        raise ValueError("invalid profile id")
    return profile


def secret_name(profile: str, broker: str, kind: str) -> str:
    validate_profile(profile)
    if broker not in BROKERS:
        raise ValueError("unknown broker")
    if kind not in KINDS:
        raise ValueError("unknown secret kind")
    return f"broker_{profile}_{broker}_{kind}"


def parse_secret_name(name: str) -> tuple[str, str, str] | None:
    """(profile, broker, kind) for a broker secret name, or None for any other name."""
    match = SECRET_NAME_RE.fullmatch(name) if isinstance(name, str) else None
    if match is None:
        return None
    return match.group(1), match.group(2), match.group(3)


def _require_aware(value: dt.datetime) -> None:
    if not isinstance(value, dt.datetime) or value.utcoffset() is None:
        raise ValueError("a timezone-aware datetime is required")


def token_expiry(broker: str, issued_at: dt.datetime) -> dt.datetime:
    """The first broker cut-off strictly after issued_at, as an aware UTC datetime."""
    _require_aware(issued_at)
    if broker not in _CUTOFF_IST:
        raise ValueError("unknown broker")
    local = issued_at.astimezone(IST)
    cutoff = dt.datetime.combine(local.date(), _CUTOFF_IST[broker], tzinfo=IST)
    if cutoff <= local:
        cutoff += dt.timedelta(days=1)
    return cutoff.astimezone(UTC)


def is_expired(broker: str, issued_at: dt.datetime, now: dt.datetime) -> bool:
    _require_aware(now)
    return now >= token_expiry(broker, issued_at)
