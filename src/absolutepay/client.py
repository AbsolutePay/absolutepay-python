"""The AbsolutePay API client. Compose once and reuse; each resource hangs off it.

Zero runtime dependencies — uses the standard library only (``urllib``, ``hashlib``, ...).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Mapping, Optional
from urllib.parse import urlparse

from .errors import AbsolutePayError
from .resources import (
    Balances,
    Conversions,
    Fees,
    GiftCards,
    Invoices,
    OffRamp,
    Payments,
    Payouts,
    Refunds,
    Subscriptions,
    Transactions,
)
from .signing import sign_request

#: The only public API origins. Anything else must be passed explicitly via ``base_url``.
PRODUCTION_BASE = "https://api.absolutepay.io"
SANDBOX_BASE = "https://sandbox-api.absolutepay.io"


class AbsolutePay:
    """AbsolutePay API client.

    Args:
        api_key: App API key (Bearer). Server-side only — never ship it to a browser.
        signing_secret: Request signing secret (``apisign_...``). Required for app keys;
            when set, every request is HMAC-signed automatically.
        sandbox: Target the public sandbox (``https://sandbox-api.absolutepay.io``) instead
            of production. Ignored when ``base_url`` is set.
        base_url: Override the API origin entirely. Takes precedence over ``sandbox``.
        timeout: Per-request timeout in seconds (default 30).
    """

    def __init__(
        self,
        api_key: str,
        *,
        signing_secret: Optional[str] = None,
        sandbox: bool = False,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("AbsolutePay: api_key is required")
        self._api_key = api_key
        self._signing_secret = signing_secret
        resolved = base_url or (SANDBOX_BASE if sandbox else PRODUCTION_BASE)
        self._base_url = resolved.rstrip("/")
        # Never send the API key + signing headers over cleartext. https required, except localhost for dev.
        parsed = urlparse(self._base_url)
        if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1"):
            raise ValueError(
                f'AbsolutePay: base_url must use https (got "{self._base_url}"); http is allowed only for localhost.'
            )
        self._timeout = timeout

        self.balances = Balances(self)
        self.fees = Fees(self)
        self.payments = Payments(self)
        self.payouts = Payouts(self)
        self.refunds = Refunds(self)
        self.conversions = Conversions(self)
        self.invoices = Invoices(self)
        self.subscriptions = Subscriptions(self)
        self.giftcards = GiftCards(self)
        self.offramp = OffRamp(self)
        self.transactions = Transactions(self)

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        extra_headers: Optional[Mapping[str, str]] = None,
    ) -> Any:
        """Low-level request. ``path`` is the path+query. Raises :class:`AbsolutePayError` on non-2xx.

        Most callers use the resource methods (``client.balances.list()`` etc.) rather than this.
        """
        body_str = json.dumps(body, separators=(",", ":")) if body is not None else ""
        headers: dict[str, str] = {"authorization": f"Bearer {self._api_key}"}
        if body is not None:
            headers["content-type"] = "application/json"
        if self._signing_secret:
            headers.update(sign_request(self._signing_secret, method, path, body_str))
        # Extra headers (e.g. Idempotency-Key) are NOT part of the signed canonical string, so merge after signing.
        if extra_headers:
            headers.update(extra_headers)

        data = body_str.encode("utf-8") if body is not None else None
        req = urllib.request.Request(self._base_url + path, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                text = resp.read().decode("utf-8")
                return json.loads(text) if text else None
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            request_id = e.headers.get("x-request-id")
            code, title, detail = "error", f"HTTP {e.code}", None
            try:
                p = json.loads(text)
                code = p.get("code", code)
                title = p.get("title", title)
                detail = p.get("detail")
            except (ValueError, AttributeError):
                if text:
                    detail = text[:300]
            raise AbsolutePayError(e.code, code, title, detail, request_id) from None
        except urllib.error.URLError as e:
            # Connection refused, DNS failure, timeout, TLS error, ...
            raise AbsolutePayError(0, "network_error", str(e.reason)) from None
