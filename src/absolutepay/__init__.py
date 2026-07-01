"""Official AbsolutePay API client for Python.

Server-side only — your API key and signing secret must never reach a browser.
"""

from __future__ import annotations

from .client import PRODUCTION_BASE, SANDBOX_BASE, AbsolutePay
from .errors import AbsolutePayError, WebhookSignatureError
from .signing import canonical_request, sign_request
from .webhooks import (
    DEFAULT_WEBHOOK_TOLERANCE_MS,
    construct_event,
    verify_signature,
)

__version__ = "0.2.0"

__all__ = [
    "AbsolutePay",
    "AbsolutePayError",
    "WebhookSignatureError",
    "construct_event",
    "verify_signature",
    "DEFAULT_WEBHOOK_TOLERANCE_MS",
    "sign_request",
    "canonical_request",
    "PRODUCTION_BASE",
    "SANDBOX_BASE",
    "__version__",
]
