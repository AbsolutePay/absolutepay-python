"""Verify inbound callback (webhook) signatures — the safe way to consume a webhook.

The platform signs callbacks with HMAC-SHA512 over ``{timestamp}.{rawBody}`` using your
app's callback secret (``whsec_...``), sent in the ``X-AbsolutePay-Timestamp`` /
``X-AbsolutePay-Signature`` headers.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Mapping, Union

from .errors import WebhookSignatureError

Headers = Mapping[str, Union[str, list[str], None]]

_HEADER_TS = "x-absolutepay-timestamp"
_HEADER_SIG = "x-absolutepay-signature"

# Default freshness window for webhook timestamps (replay defense).
DEFAULT_WEBHOOK_TOLERANCE_MS = 5 * 60_000


def _header(headers: Headers, name: str) -> str:
    target = name.lower()
    for key, v in headers.items():
        if key.lower() == target:
            if isinstance(v, (list, tuple)):
                return v[0] if v else ""
            return v or ""
    return ""


def verify_signature(secret: str, raw_body: Union[str, bytes], timestamp: str, signature: str) -> bool:
    """Check a webhook signature without parsing or freshness-checking the payload.

    Recomputes HMAC-SHA512 over `{timestamp}.{rawBody}` with your app's callback secret and
    compares it to the provided signature in constant time. Prefer `construct_event`, which
    also enforces the freshness window and returns the parsed event; use this only when you
    need the raw boolean check.

    Args:
        secret: Your app's callback secret (`whsec_...`).
        raw_body: The EXACT raw request body as received — `str` or `bytes`. Do not re-serialize
            a parsed dict; the bytes must match what the platform signed.
        timestamp: The `X-AbsolutePay-Timestamp` header value (epoch milliseconds, as a string).
        signature: The `X-AbsolutePay-Signature` header value (hex HMAC-SHA512).

    Returns:
        `True` if the signature is valid; `False` if it does not match or a required argument
        is empty. Does not check timestamp freshness.
    """
    if not secret or not timestamp or not signature:
        return False
    body = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body
    msg = timestamp.encode("utf-8") + b"." + body
    expected = hmac.new(secret.encode("utf-8"), msg, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)


def construct_event(
    raw_body: Union[str, bytes],
    headers: Headers,
    secret: str,
    tolerance_ms: int = DEFAULT_WEBHOOK_TOLERANCE_MS,
) -> dict[str, Any]:
    """Verify a callback's signature + freshness, then return the parsed event.

    The safe way to consume a webhook: it reads the timestamp/signature headers, verifies the
    HMAC-SHA512 signature over `{timestamp}.{rawBody}`, enforces the freshness window (replay
    defense), and only then parses and returns the JSON body.

    Event `type` values you may receive include `payment.succeeded`, `charge.refunded`,
    `payout.settled`, `payout.partial`, and `payout.failed`.

    Args:
        raw_body: The EXACT raw request body as received — `str` or `bytes`. Must be the
            unmodified bytes the platform signed; never pass a re-serialized dict.
        headers: The inbound request headers (case-insensitive lookup). Must include
            `X-AbsolutePay-Timestamp` and `X-AbsolutePay-Signature`. Values may be a string or
            a list of strings (the first is used).
        secret: Your app's callback secret (`whsec_...`).
        tolerance_ms: Maximum allowed age of the webhook timestamp, in milliseconds. Defaults
            to 5 minutes (`DEFAULT_WEBHOOK_TOLERANCE_MS`). Pass `0` to disable the freshness
            (replay) check entirely.

    Returns:
        The parsed event as a `dict` (typically with `type`, `data`, and related fields).

    Raises:
        WebhookSignatureError: if the signature is invalid, a header is missing, or the
            timestamp is malformed or outside `tolerance_ms`.

    Example:
        ```python
        from absolutepay import construct_event, WebhookSignatureError

        try:
            event = construct_event(request.body, request.headers, "whsec_...")
        except WebhookSignatureError:
            return respond(400)  # reject; do not process

        if event["type"] == "payment.succeeded":
            ...
        ```
    """
    ts = _header(headers, _HEADER_TS)
    sig = _header(headers, _HEADER_SIG)
    if not verify_signature(secret, raw_body, ts, sig):
        raise WebhookSignatureError("invalid webhook signature")
    if tolerance_ms > 0:
        try:
            age = abs(int(time.time() * 1000) - int(ts))
        except ValueError:
            raise WebhookSignatureError("webhook timestamp outside tolerance") from None
        if age > tolerance_ms:
            raise WebhookSignatureError("webhook timestamp outside tolerance")
    return json.loads(raw_body)
