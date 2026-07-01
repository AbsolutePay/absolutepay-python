"""Per-request signing for app (tenant) keys.

Binds the method + full path (with query) + a hash of the body, so a captured
signature can't be redirected to another operation.

Canonical string: ``METHOD\\npath\\ntimestamp\\nnonce\\nsha256hex(body)``;
signature = hex(HMAC_SHA512(secret, canonical)).
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid


def canonical_request(method: str, path: str, ts: str, nonce: str, body: str) -> str:
    """Build the canonical string that gets HMAC-signed for a request.

    The layout is `METHOD\\npath\\ntimestamp\\nnonce\\nsha256hex(body)`. Binding the method,
    full path, and a hash of the body means a captured signature can't be replayed against a
    different operation. Exposed mainly for testing/interop; `sign_request` calls it for you.

    Args:
        method: HTTP verb; upper-cased in the output.
        path: Request path including query string, exactly as sent.
        ts: Timestamp in epoch milliseconds, as a string.
        nonce: Unique per-request value (e.g. a UUID) for single-use replay defense.
        body: The exact serialized request body, or `""` when there is no body.

    Returns:
        The canonical string to sign.
    """
    body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return f"{method.upper()}\n{path}\n{ts}\n{nonce}\n{body_hash}"


def sign_request(secret: str, method: str, path: str, body: str) -> dict[str, str]:
    """Compute the signature headers for a single request.

    Generates a fresh millisecond timestamp and a random nonce, builds the canonical string
    (see `canonical_request`), and signs it with HMAC-SHA512. The `AbsolutePay` client calls
    this automatically for every request when a `signing_secret` is configured — you rarely
    need to call it directly.

    Args:
        secret: The app's request signing secret (`apisign_...`).
        method: HTTP verb (case-insensitive).
        path: Request path including query string, EXACTLY as sent (must match the request).
        body: The exact serialized request body, or `""` when there is no body.

    Returns:
        A dict of headers to attach to the request:
        `x-absolutepay-timestamp`, `x-absolutepay-nonce`, and `x-absolutepay-signature`.
    """
    ts = str(int(time.time() * 1000))  # milliseconds, matches the platform's clock
    nonce = str(uuid.uuid4())
    canonical = canonical_request(method, path, ts, nonce, body)
    signature = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha512).hexdigest()
    return {
        "x-absolutepay-timestamp": ts,
        "x-absolutepay-nonce": nonce,
        "x-absolutepay-signature": signature,
    }
