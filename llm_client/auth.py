"""Bearer-token check for the chat endpoint."""

import hmac

from llm_client.errors import ClientError

_PREFIX = "Bearer "


def check_bearer(authorization_header, expected_token) -> None:
    # Fail closed: an unset expected token never admits a caller.
    if not expected_token:
        raise ClientError("token_invalid")
    if not authorization_header or not authorization_header.startswith(_PREFIX):
        raise ClientError("token_missing")
    presented = authorization_header[len(_PREFIX):]
    if not hmac.compare_digest(presented.encode("utf-8"), expected_token.encode("utf-8")):
        raise ClientError("token_invalid")
