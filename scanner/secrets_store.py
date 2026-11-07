"""Runtime secrets and API keys, entered in the UI and kept outside git.

Values live in one dotenv-style file, ``data/secrets.env`` (override with SECRETS_FILE).
``data/`` is a mounted, gitignored volume, so every container and the UI see the same
file and nothing secret is ever baked into an image or committed. ``apply()`` loads the
file into os.environ; it runs when the ``scanner`` package is imported, so loaders
pick up a changed value on their next start.
"""
from __future__ import annotations

import os
from pathlib import Path

FIELDS: dict[str, dict] = {
    "UPSTOX_ANALYTICS_ACCESS_TOKEN": {
        "label": "Upstox analytics access token",
        "help": "Market data source. Generate at account.upstox.com/developer/apps.",
        "required": True, "secret": True},
    "KITE_API_KEY": {
        "label": "Kite Connect API key",
        "help": "API_KEY from your Zerodha app (Kite Connect developer console). Portfolio overlay only; leave blank to use a holdings file instead.",
        "required": False, "secret": False},
    "KITE_API_SECRET": {
        "label": "Kite Connect API secret",
        "help": "API_SECRET from the same Zerodha app. Portfolio overlay only.", "required": False, "secret": True},
    "KITE_ACCESS_TOKEN": {
        "label": "Kite access token",
        "help": "Daily token from the Kite login; optional.", "required": False, "secret": True},
    "SCREENER_USERNAME": {
        "label": "Screener.in e-mail",
        "help": "Optional. Logged in, fundamentals come back richer.",
        "required": False, "secret": False},
    "SCREENER_PASSWORD": {
        "label": "Screener.in password", "help": "Optional.", "required": False, "secret": True},
}


def path() -> Path:
    return Path(os.environ.get("SECRETS_FILE", "data/secrets.env"))


def read() -> dict[str, str]:
    p = path()
    out: dict[str, str] = {}
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() in FIELDS:
            out[k.strip()] = v.strip()
    return out


def apply() -> None:
    """Put stored values into os.environ; a stored value wins over an old .env."""
    for k, v in read().items():
        if v:
            os.environ[k] = v


def save(values: dict[str, str | None]) -> None:
    """Merge ``values`` into the file. None or "" leaves a key unchanged; "-" clears it."""
    current = read()
    for k, v in values.items():
        if k not in FIELDS or v is None or v == "":
            continue
        if v == "-":
            current.pop(k, None)
            os.environ.pop(k, None)
        else:
            current[k] = v.replace("\r", "").replace("\n", "")
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text("".join(f"{k}={v}\n" for k, v in current.items()), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, p)
    apply()


def status() -> dict:
    """Which keys are set, never their values (secrets are write-only from the UI)."""
    stored = read()
    fields = []
    for k, meta in FIELDS.items():
        val = stored.get(k) or os.environ.get(k, "")
        fields.append({"key": k, **meta, "set": bool(val),
                       "value": "" if meta["secret"] else val})
    missing = [f["key"] for f in fields if f["required"] and not f["set"]]
    return {"fields": fields, "needs_setup": bool(missing), "missing": missing}
