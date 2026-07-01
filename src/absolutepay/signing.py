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
    """Build the canonical string that gets signed. ``path`` is path+query as sent."""
    body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return f"{method.upper()}\n{path}\n{ts}\n{nonce}\n{body_hash}"


def sign_request(secret: str, method: str, path: str, body: str) -> dict[str, str]:
    """Return the signature headers for one request.

    ``path`` MUST be the path+query exactly as sent; ``body`` the exact serialized body ("" for none).
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
