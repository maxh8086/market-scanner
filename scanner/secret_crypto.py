"""Encryption for app secrets (docs/designs/secrets-and-roles.md, decision 10).

AES-256-GCM. The 32-byte master key lives in a file (a Docker secret in the API
container) and is never stored in the database or logged. Each value gets a fresh
random 96-bit nonce. The associated data binds a ciphertext to its row, so a value
copied to another row fails to decrypt.

Nothing here logs, and no error message includes key or plaintext bytes.
"""
from __future__ import annotations

import base64
import binascii
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_FILE_ENV = "APP_MASTER_KEY_FILE"   # no default path: the location is set per machine
KEY_BYTES = 32
NONCE_BYTES = 12


class MasterKeyError(RuntimeError):
    """The master key file is missing, unreadable or malformed."""


class DecryptError(ValueError):
    """A ciphertext did not authenticate (wrong key, nonce, associated data or tampering)."""


def key_path() -> Path:
    value = os.environ.get(KEY_FILE_ENV, "").strip()
    if not value:
        raise MasterKeyError(f"{KEY_FILE_ENV} is not set; point it at the master key file")
    return Path(value)


def load_master_key(path: Path | None = None) -> bytes:
    """Read the master key: one line of base64 that decodes to 32 bytes."""
    p = path or key_path()
    try:
        raw = p.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        raise MasterKeyError(f"master key file not found: {p}") from None
    except (OSError, UnicodeDecodeError):
        raise MasterKeyError(f"master key file unreadable: {p}") from None
    try:
        key = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise MasterKeyError("master key is not valid base64") from None
    if len(key) != KEY_BYTES:
        raise MasterKeyError(f"master key must decode to {KEY_BYTES} bytes, got {len(key)}")
    return key


def write_new_key_file(path: Path) -> None:
    """Create a new master key file (mode 0600). Refuses to overwrite an existing file."""
    if path.exists():
        raise MasterKeyError(f"refusing to overwrite existing key file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = base64.b64encode(os.urandom(KEY_BYTES)) + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def aad_for(table: str, name: str, owner: str, key_version: int) -> bytes:
    """Associated data that binds a ciphertext to its row."""
    return "|".join([table, name, owner, str(key_version)]).encode("utf-8")


def encrypt(key: bytes, plaintext: str, aad: bytes) -> tuple[bytes, bytes]:
    """Return (nonce, ciphertext). The ciphertext includes the GCM tag."""
    nonce = os.urandom(NONCE_BYTES)
    return nonce, AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), aad)


def decrypt(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> str:
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, aad).decode("utf-8")
    except Exception:  # noqa: BLE001 - any failure is reported the same way, without detail
        raise DecryptError("decryption failed") from None
