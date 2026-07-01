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
    """True iff HMAC-SHA512 over ``{timestamp}.{rawBody}`` matches ``signature`` (constant-time)."""
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
    """Verify a callback's signature + freshness and return the parsed event.

    Pass the RAW request body, the request headers, and your app's callback secret
    (``whsec_...``). Raises :class:`WebhookSignatureError` on any failure. Set
    ``tolerance_ms=0`` to disable the freshness (replay) check.
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
