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
    Checkouts,
    Conversions,
    Deposits,
    Fees,
    GiftCards,
    Invoices,
    OffRamp,
    Payouts,
    Reconciliation,
    Refunds,
    Subscriptions,
)
from .signing import sign_request

#: The only public API origins. Anything else must be passed explicitly via ``base_url``.
PRODUCTION_BASE = "https://api.absolutepay.io"
SANDBOX_BASE = "https://sandbox-api.absolutepay.io"


def _sdk_version() -> str:
    """Resolve the installed package version (falls back when running from an uninstalled tree)."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("absolutepay")
        except PackageNotFoundError:
            return "0.0.0"
    except ImportError:  # pragma: no cover - importlib.metadata is stdlib on 3.9+
        return "0.0.0"


#: Default ``User-Agent`` sent on every request. Some edge/WAF layers (e.g. Cloudflare) block
#: urllib's default UA, so we identify the SDK explicitly. Overridable per request via
#: ``extra_headers``.
USER_AGENT = f"absolutepay-python/{_sdk_version()}"


class AbsolutePay:
    """AbsolutePay API client — compose once, then reach the REST surface via resource groups.

    Each API area hangs off the instance as an attribute: `balances`, `fees`,
    `payouts`, `refunds`, `conversions`, `checkouts`, `invoices`, `subscriptions` (with a nested
    `subscriptions.plans`), `giftcards`, `offramp`, `reconciliation`, and `deposits`. Every call
    returns parsed JSON and raises `AbsolutePayError` on a non-2xx response.

    This is a **server-side** client: the API key and signing secret authenticate as your
    workspace and must never reach a browser or mobile app. When `signing_secret` is set,
    every request is HMAC-signed automatically (see `absolutepay.signing`).

    Args:
        api_key: App API key sent as an HTTP Bearer token. Required; a `ValueError` is
            raised if empty. Server-side only.
        signing_secret: Per-request signing secret (`apisign_...`). Required for app/tenant
            keys; when provided, each request is signed with HMAC-SHA512 and the signature
            headers are attached automatically. Omit only for key types that don't require
            request signing.
        sandbox: When `True`, target the public sandbox origin
            (`https://sandbox-api.absolutepay.io`) instead of production. Ignored when
            `base_url` is given. Defaults to `False` (production).
        base_url: Override the API origin entirely (e.g. a local dev server). Takes
            precedence over `sandbox`. Must use `https`, except `localhost`/`127.0.0.1`
            which may use `http`; anything else raises `ValueError`.
        timeout: Per-request socket timeout in seconds. Defaults to `30.0`.

    Raises:
        ValueError: if `api_key` is empty, or `base_url` is non-https on a non-local host.

    Example:
        ```python
        from absolutepay import AbsolutePay

        client = AbsolutePay(
            api_key="ap_live_...",
            signing_secret="apisign_...",
        )
        balances = client.balances.list()
        checkout = client.checkouts.create(
            reference="order-2026-0001",
            amount={"amount": "10.00", "currency": "USDT"},
        )
        print(checkout["checkoutUrl"])
        ```
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
        self.payouts = Payouts(self)
        self.refunds = Refunds(self)
        self.conversions = Conversions(self)
        self.checkouts = Checkouts(self)
        self.invoices = Invoices(self)
        self.subscriptions = Subscriptions(self)
        self.giftcards = GiftCards(self)
        self.offramp = OffRamp(self)
        self.reconciliation = Reconciliation(self)
        self.deposits = Deposits(self)

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        extra_headers: Optional[Mapping[str, str]] = None,
    ) -> Any:
        """Send one signed HTTP request and return the parsed JSON body.

        This is the low-level transport shared by every resource method. Most callers use the
        resource helpers (`client.balances.list()`, `client.checkouts.create(...)`,
        etc.) instead of calling this directly. The `authorization: Bearer` header and, when a
        `signing_secret` is configured, the HMAC signature headers are attached here. Extra
        headers (e.g. `Idempotency-Key`) are merged *after* signing so they stay outside the
        signed canonical string.

        Args:
            method: HTTP verb (`"GET"`, `"POST"`, ...); case-insensitive.
            path: Request path including any query string, e.g. `"/v1/balances"` or
                `"/v1/invoices/abc?foo=bar"`. Must match exactly what gets signed.
            body: JSON-serializable request body, or `None` for no body. When present, it is
                compact-serialized and a `content-type: application/json` header is added.
            extra_headers: Optional additional headers merged after signing (not covered by
                the signature).

        Returns:
            The parsed JSON response (`dict`/`list`), or `None` for an empty response body.

        Raises:
            AbsolutePayError: on any non-2xx response (carrying `status`, `code`, `detail`,
                `request_id`), or on a network/connection failure (`status == 0`,
                `code == "network_error"`).
        """
        body_str = json.dumps(body, separators=(",", ":")) if body is not None else ""
        headers: dict[str, str] = {"authorization": f"Bearer {self._api_key}", "user-agent": USER_AGENT}
        if body is not None:
            headers["content-type"] = "application/json"
        if self._signing_secret:
            headers.update(sign_request(self._signing_secret, method, path, body_str))
        # Extra headers (e.g. Idempotency-Key, a caller-supplied User-Agent) are NOT part of the
        # signed canonical string, so merge after signing; a caller's user-agent overrides the default.
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
