"""Strict check of a parsed JSON reply against the request's JSON schema.

Every name in the schema's "required" list must be present in the reply and
not None. Only the field name goes into the error code; the reply text is never
logged.
"""

from llm_client.errors import ClientError


def strict_check(reply, schema) -> None:
    required = (schema or {}).get("required") or []
    present = reply if isinstance(reply, dict) else {}
    for name in required:
        if present.get(name) is None:
            raise ClientError(f"strict_check_missing_field:{name}")
