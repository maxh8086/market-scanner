"""Read-only client for the UI secrets API (internal endpoints).

The service token is read from its file on every call, so a rotated token is
picked up without a restart. Any failure other than 200 or 404 raises
secrets_unavailable, and the token value never appears in an error.
"""

import json
from urllib.parse import quote

import httpx

from llm_client.errors import ClientError

REQUEST_TIMEOUT_SECONDS = 10.0
KEY_FIELDS = ("value", "origin", "key_version")


class UiRegistry:
    def __init__(self, secrets_api_url, token_file_path, transport=None):
        self._base_url = secrets_api_url.rstrip("/")
        self._token_file_path = token_file_path
        self._transport = transport

    def _read_token(self) -> str:
        try:
            with open(self._token_file_path, encoding="utf-8") as f:
                token = f.read().strip()
        except OSError:
            raise ClientError("secrets_unavailable") from None
        if not token:
            raise ClientError("secrets_unavailable")
        return token

    def _get(self, path: str) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._read_token()}"}
        try:
            with httpx.Client(transport=self._transport, timeout=REQUEST_TIMEOUT_SECONDS) as client:
                return client.get(self._base_url + path, headers=headers)
        except httpx.HTTPError:
            raise ClientError("secrets_unavailable") from None

    def get_provider(self, provider_id: str):
        resp = self._get(f"/internal/llm/providers/{quote(str(provider_id), safe='')}")
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise ClientError("secrets_unavailable")
        try:
            body = resp.json()
        except ValueError:
            raise ClientError("secrets_unavailable") from None
        if not isinstance(body, dict):
            raise ClientError("secrets_unavailable")
        return body

    def get_key(self, key_ref: str):
        resp = self._get(f"/internal/secrets/{quote(str(key_ref or ''), safe='')}")
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise ClientError("secrets_unavailable")
        # The UI endpoint wraps the stored string as {"name": ..., "value": "<string>"}.
        # The string is itself a JSON record: {"value", "origin", "key_version"}.
        try:
            record = json.loads(resp.json()["value"])
        except (ValueError, KeyError, TypeError):
            raise ClientError("secrets_unavailable") from None
        if not isinstance(record, dict) or any(f not in record for f in KEY_FIELDS):
            raise ClientError("secrets_unavailable")
        return record
