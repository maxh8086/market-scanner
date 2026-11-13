"""Client-facing error type. Every refusal carries a stable code and an HTTP status."""

_STATUS_BY_CODE = {
    "token_missing": 401,
    "token_invalid": 401,
    "origin_mismatch": 409,
    "origin_not_https": 409,
    "provider_not_approved": 409,
    "key_missing": 409,
    "key_stale_version": 409,
    "route_mismatch": 409,
    "model_not_set": 422,
    "secrets_unavailable": 503,
    "provider_timeout": 504,
    "provider_unreachable": 502,
    "adapter_not_built": 501,
}

_STATUS_PREFIXES = ("provider_rejected:", "strict_check_missing_field:")


def status_for(code: str) -> int:
    if code in _STATUS_BY_CODE:
        return _STATUS_BY_CODE[code]
    if code.startswith(_STATUS_PREFIXES):
        return 502
    return 500


class ClientError(Exception):
    """A refusal or failure with a stable code. The body is {"error": code} plus detail when set."""

    def __init__(self, code: str, detail: str | None = None):
        super().__init__(code)
        self.code = code
        self.status = status_for(code)
        self.detail = detail
