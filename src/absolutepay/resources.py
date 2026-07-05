"""API resource groups. Each hangs off the client and mirrors the REST surface.

A ``Money`` is a plain dict: ``{"amount": "10.00", "currency": "USDT"}``.
Methods return the parsed JSON; on non-2xx they raise :class:`AbsolutePayError`.

**List envelope.** Every ``list``-style method takes keyword filters plus ``limit`` /
``before`` / ``order`` and returns the raw ``{"items": [...], "nextCursor": ...}`` page
(reconciliation, refunds and conversions histories additionally carry ``total``). Page by
echoing ``nextCursor`` back as ``before``; ``nextCursor is None`` means the last page.

**Idempotency.** Money POSTs (``payouts.create``, ``refunds.create``,
``conversions.execute``, ``offramp.withdraw``, ``giftcards.create``,
``subscriptions.create``, ``subscriptions.plans.create``) accept ``idempotency_key=`` which is sent as the
``Idempotency-Key`` header (outside the request signature). Replaying the same key returns the
original result instead of acting twice; a ``409`` surfaces as a normal
:class:`AbsolutePayError` (inspect ``.code``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Sequence

from ._util import clean, path_seg, qs

if TYPE_CHECKING:
    from .client import AbsolutePay

Money = dict[str, str]
Json = Any

#: Sentinel distinguishing "field omitted" from "field explicitly set to null (clear it)".
_UNSET: Any = object()


def _idem(idempotency_key: Optional[str]) -> Optional[dict[str, str]]:
    """Build the ``Idempotency-Key`` header mapping, or ``None`` when no key was given."""
    return {"Idempotency-Key": idempotency_key} if idempotency_key else None


def _patch(**fields: Any) -> dict[str, Any]:
    """Keep only fields the caller actually passed. ``None`` is kept (sends null → clears)."""
    return {k: v for k, v in fields.items() if v is not _UNSET}


class _Resource:
    def __init__(self, client: "AbsolutePay") -> None:
        self._c = client


class Balances(_Resource):
    """Read the workspace's asset balances (scope: `balances:read`)."""

    def list(self) -> Json:
        """List every asset balance held by the workspace.

        Returns:
            ``{"items": [...]}`` — one entry per asset (currency plus available/held amounts as
            decimal strings).

        Raises:
            AbsolutePayError: on a non-2xx response (e.g. 401/403 auth, 429 rate limit).

        Example:
            ```python
            for bal in client.balances.list()["items"]:
                print(bal["currency"], bal["available"])
            ```
        """
        return self._c.request("GET", "/v1/balances")


class Fees(_Resource):
    """Preview fees from the pricing matrix (scope: `balances:read`)."""

    def preview(self, *, amount: str, currency: str, payment_type: Optional[str] = None) -> Json:
        """Preview the fee that would apply to an amount, without moving any funds.

        Args:
            amount: The amount as a decimal STRING (never a float), e.g. `"100.00"`.
            currency: The currency code, e.g. `"USDT"`.
            payment_type: Which flow to price (e.g. `"CHECKOUT"`, `"PAYOUT"`). Optional;
                defaults to `CHECKOUT` server-side.

        Returns:
            A dict describing the computed fee (network base + tier margin) and the net amount.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request(
            "GET", "/v1/fees/preview" + qs({"amount": amount, "currency": currency, "paymentType": payment_type})
        )


class Payouts(_Resource):
    """Send batch crypto payouts (scope: `payouts:write`; reads use `payouts:read`)."""

    def create(self, items: Sequence[dict], *, idempotency_key: Optional[str] = None) -> Json:
        """Submit a batch of crypto payouts in a single request (money POST).

        Args:
            items: The payout line items — a sequence of dicts, one per recipient (each
                specifying the destination address/chain, currency, and amount as a decimal
                STRING). Sent as the `items` array.
            idempotency_key: Optional client-chosen key that makes retries safe: replaying the
                same key returns the ORIGINAL batch instead of paying out again. Sent as the
                `Idempotency-Key` header (outside the request signature).

        Returns:
            A dict describing the created payout batch (batch id and per-item status).

        Raises:
            AbsolutePayError: on a non-2xx response (e.g. 403 missing `payouts:write`,
                insufficient balance, or 409 idempotency conflict).

        Example:
            ```python
            batch = client.payouts.create(
                [
                    {"address": "T...", "chain": "TRX",
                     "amount": {"amount": "50.00", "currency": "USDT"}},
                ],
                idempotency_key="payroll-2026-07-01",
            )
            ```
        """
        return self._c.request("POST", "/v1/payouts", {"items": list(items)}, _idem(idempotency_key))

    def options(self, *, currency: str) -> Json:
        """List the chains a currency can be paid out on, with per-chain fees and limits.

        Args:
            currency: The payout currency, e.g. `"USDT"`.

        Returns:
            ``{"items": [...]}`` — supported chains with their withdraw fee and min/max limits.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("GET", "/v1/payouts/options" + qs({"currency": currency}))

    def get(self, id: str) -> Json:
        """Look up a payout batch by its id (scope: `payouts:read`).

        Args:
            id: The payout batch id returned by `create`.

        Returns:
            A dict with the batch's current status and per-item results.

        Raises:
            AbsolutePayError: on a non-2xx response (e.g. 404 if unknown).
        """
        return self._c.request("GET", f"/v1/payouts/{path_seg(id)}")


class Refunds(_Resource):
    """Refund settled pay-in collections and read refund history (scope: `payments:write`)."""

    def create(
        self,
        *,
        merchant_trade_no: str,
        amount: Money,
        reason: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Json:
        """Refund all or part of a settled checkout back to the payer (money POST).

        Args:
            merchant_trade_no: The trade number of the original settled checkout to refund.
            amount: The amount to refund as a `Money` dict
                `{"amount": "10.00", "currency": "USDT"}` — decimal STRING, never a float. May
                be less than the original for a partial refund.
            reason: Optional human-readable reason recorded with the refund.
            idempotency_key: Optional retry-safety key; sent as the `Idempotency-Key` header.

        Returns:
            A dict describing the refund request, including its `refundRequestId` and status.

        Raises:
            AbsolutePayError: on a non-2xx response (e.g. 403, original not refundable, or 409).

        Example:
            ```python
            refund = client.refunds.create(
                merchant_trade_no="order-2026-0001",
                amount={"amount": "25.00", "currency": "USDT"},
                reason="customer request",
                idempotency_key="refund-0001",
            )
            print(refund["refundRequestId"])
            ```
        """
        body = clean({"merchantTradeNo": merchant_trade_no, "amount": amount, "reason": reason})
        return self._c.request("POST", "/v1/refunds", body, _idem(idempotency_key))

    def get(self, id: str) -> Json:
        """Look up a refund by its `refundRequestId`.

        Args:
            id: The `refundRequestId` returned by `create`.

        Returns:
            A dict with the refund's current status.

        Raises:
            AbsolutePayError: on a non-2xx response (e.g. 404 if unknown).
        """
        return self._c.request("GET", f"/v1/refunds/{path_seg(id)}")

    def list(
        self,
        *,
        from_: Optional[int] = None,
        to: Optional[int] = None,
        currency: Optional[str] = None,
        limit: Optional[int] = None,
        before: Optional[str] = None,
        order: Optional[str] = None,
    ) -> Json:
        """List the settled REFUND ledger history (keyset-paginated).

        Note: `from_` has a trailing underscore because `from` is a Python keyword; it maps to
        the `from` query parameter.

        Args:
            from_: Start of the time window, epoch MILLISECONDS (inclusive). Optional.
            to: End of the time window, epoch MILLISECONDS. Optional.
            currency: Filter to a single currency, e.g. `"USDT"`. Optional.
            limit: Max items per page. Optional.
            before: Keyset cursor — pass the previous page's `nextCursor`. Optional.
            order: Sort order, `"asc"` or `"desc"`. Optional.

        Returns:
            ``{"items": [...], "total": N, "nextCursor": ...}`` (`nextCursor is None` on the
            last page).

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request(
            "GET",
            "/v1/refunds"
            + qs({"from": from_, "to": to, "currency": currency, "limit": limit, "before": before, "order": order}),
        )


class Conversions(_Resource):
    """Convert between stablecoins/crypto assets (scope: `convert:write`)."""

    def quote(
        self,
        *,
        sell_currency: str,
        buy_currency: str,
        sell_amount: Optional[str] = None,
        buy_amount: Optional[str] = None,
    ) -> Json:
        """Preview a conversion rate without moving any funds.

        Specify EXACTLY ONE of `sell_amount` (I want to sell this much) or `buy_amount` (I want
        to receive this much); the other side is computed. Amounts are decimal STRINGS.

        Args:
            sell_currency: The currency being sold, e.g. `"USDT"`.
            buy_currency: The currency being bought, e.g. `"BTC"`.
            sell_amount: Amount to sell as a decimal string. Provide this OR `buy_amount`.
            buy_amount: Amount to receive as a decimal string. Provide this OR `sell_amount`.

        Returns:
            A dict with the quote — including `quoteId`, `sellAmount`, `sellCurrency`,
            `buyAmount`, `buyCurrency`, and the rate — to pass to `execute`.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        body = clean(
            {
                "sellCurrency": sell_currency,
                "buyCurrency": buy_currency,
                "sellAmount": sell_amount,
                "buyAmount": buy_amount,
            }
        )
        return self._c.request("POST", "/v1/conversions/quote", body)

    def execute(self, *, quote_id: str, sell: Money, buy: Money, idempotency_key: Optional[str] = None) -> Json:
        """Execute a conversion against a quote from `quote` (money POST — moves funds).

        Args:
            quote_id: The `quoteId` returned by `quote`.
            sell: The sell side as a `Money` dict (from the quote's `sellAmount`/`sellCurrency`).
            buy: The buy side as a `Money` dict (from the quote's `buyAmount`/`buyCurrency`).
            idempotency_key: Optional retry-safety key; sent as the `Idempotency-Key` header.

        Returns:
            A dict describing the executed conversion and resulting balances.

        Raises:
            AbsolutePayError: on a non-2xx response (e.g. expired quote, insufficient balance, 409).
        """
        body = {"quoteId": quote_id, "sell": sell, "buy": buy}
        return self._c.request("POST", "/v1/conversions", body, _idem(idempotency_key))

    def list(
        self,
        *,
        from_: Optional[int] = None,
        to: Optional[int] = None,
        currency: Optional[str] = None,
        limit: Optional[int] = None,
        before: Optional[str] = None,
        order: Optional[str] = None,
    ) -> Json:
        """List the settled CONVERT ledger history (keyset-paginated).

        Note: `from_` maps to the `from` query parameter (`from` is a Python keyword).

        Args:
            from_: Start of the time window, epoch MILLISECONDS (inclusive). Optional.
            to: End of the time window, epoch MILLISECONDS. Optional.
            currency: Filter to a single currency. Optional.
            limit: Max items per page. Optional.
            before: Keyset cursor — pass the previous page's `nextCursor`. Optional.
            order: Sort order, `"asc"` or `"desc"`. Optional.

        Returns:
            ``{"items": [...], "total": N, "nextCursor": ...}``.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request(
            "GET",
            "/v1/conversions"
            + qs({"from": from_, "to": to, "currency": currency, "limit": limit, "before": before, "order": order}),
        )


class Checkouts(_Resource):
    """Hosted checkout links — the payer picks the asset on the page (scope: `invoices:write`).

    A checkout does not fix a `chain` up front; the payer chooses their currency/chain on the
    hosted page. For the up-front address flow (mint the deposit address immediately), use
    `client.invoices` instead.
    """

    def create(
        self,
        *,
        reference: str,
        amount: Money,
        description: Optional[str] = None,
        customer_email: Optional[str] = None,
        expires_at: Optional[int] = None,
        redirect_url: Optional[str] = None,
    ) -> Json:
        """Create a hosted checkout link.

        Args:
            reference: Your unique reference for this checkout link.
            amount: The amount as a `Money` dict
                `{"amount": "10.00", "currency": "USDT"}` — decimal STRING, never a float.
            description: Optional human-readable description shown to the payer.
            customer_email: Optional payer email (used for receipts/notifications).
            expires_at: Optional expiry as epoch MILLISECONDS.
            redirect_url: Optional http(s) URL. When the hosted checkout reaches a terminal
                state the payer's browser is redirected here with
                `?token=<token>&status=<SUCCESS|EXPIRED|CANCELED>` appended (any existing query
                is preserved). Echoed back as `redirectUrl`.

        Returns:
            A dict with the created checkout link — `token` and `checkoutUrl`.

        Raises:
            AbsolutePayError: on a non-2xx response.

        Example:
            ```python
            chk = client.checkouts.create(
                reference="order-2026-0001",
                amount={"amount": "10.00", "currency": "USDT"},
            )
            print(chk["checkoutUrl"])
            ```
        """
        body = clean(
            {
                "reference": reference,
                "amount": amount,
                "description": description,
                "customerEmail": customer_email,
                "expiresAt": expires_at,
                "redirectUrl": redirect_url,
            }
        )
        return self._c.request("POST", "/v1/checkouts", body)

    def list(
        self,
        *,
        status: Optional[str] = None,
        q: Optional[str] = None,
        limit: Optional[int] = None,
        before: Optional[str] = None,
        order: Optional[str] = None,
    ) -> Json:
        """List checkout links (keyset-paginated).

        Args:
            status: Filter by status. Optional.
            q: Free-text search over reference/description. Optional.
            limit: Max items per page. Optional.
            before: Keyset cursor — pass the previous page's `nextCursor`. Optional.
            order: Sort order, `"asc"` or `"desc"`. Optional.

        Returns:
            ``{"items": [...], "nextCursor": ...}`` (`nextCursor is None` on the last page).

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request(
            "GET", "/v1/checkouts" + qs({"status": status, "q": q, "limit": limit, "before": before, "order": order})
        )

    def get(self, token: str) -> Json:
        """Fetch a checkout link (and its current settlement state) by token.

        This is the poll fallback for confirming settlement when you can't rely on the
        `payment.succeeded` webhook.

        Args:
            token: The checkout link's token.

        Returns:
            A dict with the checkout's details and status.

        Raises:
            AbsolutePayError: on a non-2xx response (e.g. 404 if unknown).
        """
        return self._c.request("GET", f"/v1/checkouts/{path_seg(token)}")

    def update(
        self,
        token: str,
        *,
        paused: Any = _UNSET,
        redirect_url: Any = _UNSET,
        expires_at: Any = _UNSET,
        description: Any = _UNSET,
    ) -> Json:
        """Update a checkout link. Only the fields you pass are changed; passing `None` clears one.

        Args:
            token: The checkout link's token.
            paused: `True` to stop accepting payment, `False` to resume. Omit to leave unchanged.
            redirect_url: New terminal-state redirect URL, or `None` to clear it. Omit to leave
                unchanged.
            expires_at: New expiry as epoch MILLISECONDS, or `None` to clear it. Omit to leave
                unchanged.
            description: New description, or `None` to clear it. Omit to leave unchanged.

        Returns:
            A dict with the updated checkout state.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        body = _patch(paused=paused, redirectUrl=redirect_url, expiresAt=expires_at, description=description)
        return self._c.request("PATCH", f"/v1/checkouts/{path_seg(token)}", body)

    def delete(self, token: str) -> Json:
        """Void a checkout link so it can no longer be paid (terminal — cannot be undone).

        Args:
            token: The checkout link's token.

        Returns:
            A dict with the voided checkout state.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("DELETE", f"/v1/checkouts/{path_seg(token)}")


class Invoices(_Resource):
    """Invoices — the up-front address flow (scope: `invoices:write`; reads use `invoices:read`).

    Unlike `client.checkouts`, an invoice fixes the `chain` at creation and mints the deposit
    address immediately, so you can show the payer a concrete address/QR without the hosted
    asset-picker page.
    """

    def create(
        self,
        *,
        reference: str,
        amount: Money,
        chain: str,
        description: Optional[str] = None,
        customer_email: Optional[str] = None,
        expires_at: Optional[int] = None,
        redirect_url: Optional[str] = None,
    ) -> Json:
        """Create an invoice with the deposit address minted up front (`chain` is required).

        Args:
            reference: Your unique reference for this invoice (idempotency/lookup handle).
            amount: The invoice amount as a `Money` dict
                `{"amount": "10.00", "currency": "USDT"}` — decimal STRING, never a float.
            chain: The chain/network to mint the deposit address on, e.g. `"TRX"` — REQUIRED.
            description: Optional human-readable description shown to the payer.
            customer_email: Optional payer email (used for receipts/notifications).
            expires_at: Optional expiry as epoch MILLISECONDS.
            redirect_url: Optional http(s) terminal-state redirect URL (see `checkouts.create`).

        Returns:
            A dict describing the created invoice — `token`, `address`, `chain`, `amount`, and
            the hosted URL.

        Raises:
            AbsolutePayError: on a non-2xx response.

        Example:
            ```python
            inv = client.invoices.create(
                reference="inv-1001",
                amount={"amount": "49.99", "currency": "USDT"},
                chain="TRX",
                customer_email="buyer@example.com",
            )
            print(inv["address"])
            ```
        """
        body = clean(
            {
                "reference": reference,
                "amount": amount,
                "chain": chain,
                "description": description,
                "customerEmail": customer_email,
                "expiresAt": expires_at,
                "redirectUrl": redirect_url,
            }
        )
        return self._c.request("POST", "/v1/invoices", body)

    def list(
        self,
        *,
        status: Optional[str] = None,
        q: Optional[str] = None,
        limit: Optional[int] = None,
        before: Optional[str] = None,
        order: Optional[str] = None,
    ) -> Json:
        """List invoices (keyset-paginated). Same shape as `checkouts.list`.

        Args:
            status: Filter by status. Optional.
            q: Free-text search over reference/description. Optional.
            limit: Max items per page. Optional.
            before: Keyset cursor — pass the previous page's `nextCursor`. Optional.
            order: Sort order, `"asc"` or `"desc"`. Optional.

        Returns:
            ``{"items": [...], "nextCursor": ...}``.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request(
            "GET", "/v1/invoices" + qs({"status": status, "q": q, "limit": limit, "before": before, "order": order})
        )

    def get(self, token: str) -> Json:
        """Fetch an invoice (and its current settlement state) by token.

        Args:
            token: The invoice token.

        Returns:
            A dict with the invoice's details and status.

        Raises:
            AbsolutePayError: on a non-2xx response (e.g. 404 if unknown).
        """
        return self._c.request("GET", f"/v1/invoices/{path_seg(token)}")

    def update(
        self,
        token: str,
        *,
        paused: Any = _UNSET,
        redirect_url: Any = _UNSET,
        expires_at: Any = _UNSET,
        description: Any = _UNSET,
    ) -> Json:
        """Update an invoice. Only the fields you pass are changed; passing `None` clears one.

        Args:
            token: The invoice token.
            paused: `True` to stop accepting payment, `False` to resume. Omit to leave unchanged.
            redirect_url: New terminal-state redirect URL, or `None` to clear. Omit to leave
                unchanged.
            expires_at: New expiry as epoch MILLISECONDS, or `None` to clear. Omit to leave
                unchanged.
            description: New description, or `None` to clear. Omit to leave unchanged.

        Returns:
            A dict with the updated invoice state.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        body = _patch(paused=paused, redirectUrl=redirect_url, expiresAt=expires_at, description=description)
        return self._c.request("PATCH", f"/v1/invoices/{path_seg(token)}", body)

    def delete(self, token: str) -> Json:
        """Void an invoice so it can no longer be paid (terminal — cannot be undone).

        Args:
            token: The invoice token.

        Returns:
            A dict with the voided invoice state.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("DELETE", f"/v1/invoices/{path_seg(token)}")


class Deposits(_Resource):
    """Own-balance receive addresses and settled deposit history (scope: `balances:read`)."""

    def chains(self) -> Json:
        """List the chains/networks a deposit address can be created on.

        Returns:
            ``{"items": [...]}`` — supported chains (with per-chain currency/network details).

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("GET", "/v1/deposits/chains")

    def create_address(self, *, chain: str) -> Json:
        """Create (or fetch) the permanent deposit address for a network — idempotent mint-or-return.

        The address is permanent and reusable — any funds sent to it credit the workspace
        balance. Calling again for the same chain returns the existing address.

        Args:
            chain: The chain/network to deposit on, e.g. `"TRX"` (from `chains`).

        Returns:
            A dict with the deposit `address` (and chain/memo where applicable).

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("POST", "/v1/deposits/address", {"chain": chain})

    def addresses(
        self,
        *,
        chain: Optional[str] = None,
        limit: Optional[int] = None,
        before: Optional[str] = None,
        order: Optional[str] = None,
    ) -> Json:
        """List the workspace's minted deposit addresses (keyset-paginated).

        Args:
            chain: Filter to a single chain. Optional.
            limit: Max items per page. Optional.
            before: Keyset cursor — pass the previous page's `nextCursor`. Optional.
            order: Sort order, `"asc"` or `"desc"`. Optional.

        Returns:
            ``{"items": [...], "nextCursor": ...}``.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request(
            "GET", "/v1/deposits/addresses" + qs({"chain": chain, "limit": limit, "before": before, "order": order})
        )

    def get_address(self, chain: str) -> Json:
        """Fetch the workspace's deposit address for a specific chain.

        Args:
            chain: The chain/network, e.g. `"TRX"`.

        Returns:
            A dict with the deposit `address` for that chain.

        Raises:
            AbsolutePayError: on a non-2xx response (e.g. 404 if none minted yet).
        """
        return self._c.request("GET", f"/v1/deposits/addresses/{path_seg(chain)}")

    def list(
        self,
        *,
        chain: Optional[str] = None,
        from_: Optional[int] = None,
        to: Optional[int] = None,
        before: Optional[str] = None,
        order: Optional[str] = None,
    ) -> Json:
        """List settled deposit HISTORY — funds received into the workspace balance (keyset-paginated).

        Note: `from_` maps to the `from` query parameter (`from` is a Python keyword).

        Args:
            chain: Filter to a single chain. Optional.
            from_: Start of the time window, epoch MILLISECONDS (inclusive). Optional.
            to: End of the time window, epoch MILLISECONDS. Optional.
            before: Keyset cursor — pass the previous page's `nextCursor`. Optional.
            order: Sort order, `"asc"` or `"desc"`. Optional.

        Returns:
            ``{"items": [...], "nextCursor": ...}``.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request(
            "GET", "/v1/deposits" + qs({"chain": chain, "from": from_, "to": to, "before": before, "order": order})
        )


class Plans(_Resource):
    """Subscription plans that subscriptions attach to (scope: `subscriptions:write`)."""

    def list(self) -> Json:
        """List all subscription plans defined for the workspace.

        Returns:
            ``{"items": [...]}`` — plan objects.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("GET", "/v1/subscription-plans")

    def create(
        self,
        *,
        merchant_plan_no: str,
        name: str,
        amount: Money,
        interval: str,
        interval_count: int,
        total_cycles: int,
        idempotency_key: Optional[str] = None,
    ) -> Json:
        """Create a subscription plan (money POST).

        Args:
            merchant_plan_no: Your unique reference for the plan.
            name: Human-readable plan name.
            amount: The per-cycle charge as a `Money` dict
                `{"amount": "10.00", "currency": "USDT"}` — decimal STRING, never a float.
            interval: Billing interval unit (e.g. `"DAY"`, `"WEEK"`, `"MONTH"`).
            interval_count: Number of interval units between charges (e.g. `1` = every month).
            total_cycles: Total number of charges before the plan completes.
            idempotency_key: Optional retry-safety key; sent as the `Idempotency-Key` header.

        Returns:
            A dict describing the created plan (including its plan number).

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        body = {
            "merchantPlanNo": merchant_plan_no,
            "name": name,
            "amount": amount,
            "interval": interval,
            "intervalCount": interval_count,
            "totalCycles": total_cycles,
        }
        return self._c.request("POST", "/v1/subscription-plans", body, _idem(idempotency_key))


class Subscriptions(_Resource):
    """Recurring subscriptions (scope: `subscriptions:write`; reads use `subscriptions:read`).

    Plans live on the nested `client.subscriptions.plans` resource (a `Plans`).
    """

    def __init__(self, client: "AbsolutePay") -> None:
        """Wire up the subscriptions resource and its nested `plans` sub-resource.

        Args:
            client: The parent `AbsolutePay` client used for requests.
        """
        super().__init__(client)
        self.plans = Plans(client)

    def list(
        self,
        *,
        status: Optional[str] = None,
        q: Optional[str] = None,
        limit: Optional[int] = None,
        before: Optional[str] = None,
        order: Optional[str] = None,
    ) -> Json:
        """List subscriptions (keyset-paginated).

        Args:
            status: Filter by subscription status. Optional.
            q: Free-text search. Optional.
            limit: Max items per page. Optional.
            before: Keyset cursor — pass the previous page's `nextCursor`. Optional.
            order: Sort order, `"asc"` or `"desc"`. Optional.

        Returns:
            ``{"items": [...], "nextCursor": ...}``.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request(
            "GET", "/v1/subscriptions" + qs({"status": status, "q": q, "limit": limit, "before": before, "order": order})
        )

    def create(
        self,
        *,
        merchant_sub_no: str,
        plan_no: str,
        callback_url: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Json:
        """Subscribe a customer to a plan (money POST).

        Args:
            merchant_sub_no: Your unique reference for this subscription.
            plan_no: The plan number to subscribe to (from `client.subscriptions.plans`).
            callback_url: Optional per-subscription callback URL for lifecycle notifications.
            idempotency_key: Optional retry-safety key; sent as the `Idempotency-Key` header.

        Returns:
            A dict describing the created subscription (status, next charge, authorization link
            if applicable).

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        body = clean({"merchantSubNo": merchant_sub_no, "planNo": plan_no, "callbackUrl": callback_url})
        return self._c.request("POST", "/v1/subscriptions", body, _idem(idempotency_key))

    def deductions(self, merchant_sub_no: str) -> Json:
        """Get the per-cycle deduction (charge) history for a subscription.

        Args:
            merchant_sub_no: The subscription's merchant reference.

        Returns:
            ``{"items": [...]}`` — past deductions/charges for the subscription.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("GET", f"/v1/subscriptions/{path_seg(merchant_sub_no)}/deductions")

    def cancel(self, merchant_sub_no: str) -> Json:
        """Cancel a subscription so no further cycles are charged.

        Args:
            merchant_sub_no: The subscription's merchant reference.

        Returns:
            A dict with the cancelled subscription state.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("POST", f"/v1/subscriptions/{path_seg(merchant_sub_no)}/cancel")


class GiftCards(_Resource):
    """Gift cards (scope: `balances:read` to read, `payments:write` to issue)."""

    def templates(self) -> Json:
        """List the available gift-card designs/templates that can be issued.

        Returns:
            ``{"items": [...]}`` — templates, each with a `templateId` to pass to `create`.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("GET", "/v1/giftcards/templates")

    def list(
        self,
        *,
        status: Optional[str] = None,
        q: Optional[str] = None,
        limit: Optional[int] = None,
        before: Optional[str] = None,
        order: Optional[str] = None,
    ) -> Json:
        """List issued gift cards (keyset-paginated).

        Args:
            status: Filter by gift-card status. Optional.
            q: Free-text search. Optional.
            limit: Max items per page. Optional.
            before: Keyset cursor — pass the previous page's `nextCursor`. Optional.
            order: Sort order, `"asc"` or `"desc"`. Optional.

        Returns:
            ``{"items": [...], "nextCursor": ...}``.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request(
            "GET", "/v1/giftcards" + qs({"status": status, "q": q, "limit": limit, "before": before, "order": order})
        )

    def get(self, card_num: str) -> Json:
        """Look up a single gift card by its card number.

        Args:
            card_num: The gift card's number.

        Returns:
            A dict with the gift card's details and status.

        Raises:
            AbsolutePayError: on a non-2xx response (e.g. 404 if unknown).
        """
        return self._c.request("GET", f"/v1/giftcards/{path_seg(card_num)}")

    def create(self, *, title: str, template_id: str, amount: Money, idempotency_key: Optional[str] = None) -> Json:
        """Issue a new gift card (money POST; scope: `payments:write`).

        Args:
            title: Human-readable title/label for the card.
            template_id: The design template id (from `templates`).
            amount: The card's face value as a `Money` dict
                `{"amount": "10.00", "currency": "USDT"}` — decimal STRING, never a float.
            idempotency_key: Optional retry-safety key; sent as the `Idempotency-Key` header.

        Returns:
            A dict describing the issued gift card (card number, redemption info, status).

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        body = {"title": title, "templateId": template_id, "amount": amount}
        return self._c.request("POST", "/v1/giftcards", body, _idem(idempotency_key))


class OffRamp(_Resource):
    """Crypto -> fiat off-ramp to a bank account (scope: `payouts:write`; reads use `payouts:read`)."""

    def countries(self) -> Json:
        """List the countries the off-ramp supports.

        Returns:
            ``{"items": [...]}`` — supported countries (with the fiat currencies each allows).

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("GET", "/v1/offramp/countries")

    def banks(self) -> Json:
        """List the workspace's registered destination bank accounts.

        Returns:
            ``{"items": [...]}`` — bank accounts, each with a `bankAccountId` for `withdraw`.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("GET", "/v1/offramp/banks")

    def quote(self, *, crypto_currency: str, fiat_currency: str, crypto_amount: str) -> Json:
        """Quote a crypto -> fiat off-ramp conversion (no funds move).

        Args:
            crypto_currency: The crypto asset being sold, e.g. `"USDT"`.
            fiat_currency: The fiat currency to receive, e.g. `"IDR"`.
            crypto_amount: Amount of crypto to sell, as a decimal STRING.

        Returns:
            A dict with a `quoteToken`, the resulting fiat amount, and the rate — pass these to
            `withdraw`.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        body = {"cryptoCurrency": crypto_currency, "fiatCurrency": fiat_currency, "cryptoAmount": crypto_amount}
        return self._c.request("POST", "/v1/offramp/quote", body)

    def withdraw(
        self,
        *,
        quote_token: str,
        bank_account_id: str,
        crypto_currency: str,
        fiat_currency: str,
        crypto_amount: str,
        fiat_amount: str,
        idempotency_key: Optional[str] = None,
    ) -> Json:
        """Execute an off-ramp against a quote, paying fiat to a bank account (money POST — moves funds).

        Args:
            quote_token: The `quoteToken` from `quote`.
            bank_account_id: Destination bank account id (from `banks`).
            crypto_currency: The crypto asset being sold (must match the quote).
            fiat_currency: The fiat currency to receive (must match the quote).
            crypto_amount: Amount of crypto to sell, as a decimal STRING (from the quote).
            fiat_amount: Amount of fiat to receive, as a decimal STRING (from the quote).
            idempotency_key: Optional retry-safety key; sent as the `Idempotency-Key` header.

        Returns:
            A dict describing the created off-ramp order and its status.

        Raises:
            AbsolutePayError: on a non-2xx response (e.g. expired quote, insufficient balance, 409).
        """
        body = {
            "quoteToken": quote_token,
            "bankAccountId": bank_account_id,
            "cryptoCurrency": crypto_currency,
            "fiatCurrency": fiat_currency,
            "cryptoAmount": crypto_amount,
            "fiatAmount": fiat_amount,
        }
        return self._c.request("POST", "/v1/offramp/withdraw", body, _idem(idempotency_key))

    def orders(
        self,
        *,
        status: Optional[str] = None,
        q: Optional[str] = None,
        limit: Optional[int] = None,
        before: Optional[str] = None,
        order: Optional[str] = None,
    ) -> Json:
        """List off-ramp orders (keyset-paginated).

        Args:
            status: Filter by order status. Optional.
            q: Free-text search. Optional.
            limit: Max items per page. Optional.
            before: Keyset cursor — pass the previous page's `nextCursor`. Optional.
            order: Sort order, `"asc"` or `"desc"`. Optional.

        Returns:
            ``{"items": [...], "nextCursor": ...}``.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request(
            "GET",
            "/v1/offramp/orders" + qs({"status": status, "q": q, "limit": limit, "before": before, "order": order}),
        )

    def register_bank(
        self,
        *,
        bank_account_name: str,
        bank_name: str,
        country_id: str,
        iban: str,
        file: dict,
        swift: Optional[str] = None,
        address: Optional[str] = None,
        remittance_line_number: Optional[str] = None,
    ) -> Json:
        """Register a destination bank account for the off-ramp (starts a review flow).

        The bank account is not immediately usable — it enters a manual review before it can
        receive fiat. Additional verification materials may need to be uploaded afterwards via
        `submit_bank_materials`.

        Args:
            bank_account_name: The account holder's name on the bank account.
            bank_name: The receiving bank's name.
            country_id: The off-ramp country id (from `countries`).
            iban: The destination account IBAN (or local account number).
            file: The primary supporting document as a dict with keys `filename`,
                `contentType`, and `dataBase64` (the file's bytes, base64-encoded).
            swift: The bank's SWIFT/BIC code. Optional.
            address: The account holder's address. Optional.
            remittance_line_number: An extra remittance/routing reference line. Optional.

        Returns:
            A dict describing the registered bank account (its `bankAccountId` and review
            status).

        Raises:
            AbsolutePayError: on a non-2xx response (e.g. 403 missing `payouts:write`).
        """
        body = clean(
            {
                "bankAccountName": bank_account_name,
                "bankName": bank_name,
                "countryId": country_id,
                "iban": iban,
                "file": file,
                "swift": swift,
                "address": address,
                "remittanceLineNumber": remittance_line_number,
            }
        )
        return self._c.request("POST", "/v1/offramp/banks", body)

    def remove_bank(self, bank_account_id: str) -> Json:
        """Remove a registered destination bank account.

        Args:
            bank_account_id: The bank account id to delete (from `banks`).

        Returns:
            A dict acknowledging the deletion (typically empty).

        Raises:
            AbsolutePayError: on a non-2xx response (e.g. 404 if unknown).
        """
        return self._c.request("DELETE", f"/v1/offramp/banks/{path_seg(bank_account_id)}")

    def submit_bank_materials(
        self, bank_account_id: str, *, certificate: Sequence[dict], passport: Sequence[dict]
    ) -> Json:
        """Upload the verification materials required to approve a registered bank account.

        Args:
            bank_account_id: The bank account id the materials are for (from `banks`).
            certificate: The certificate document(s) — a sequence of `DocFile` dicts, each with
                keys `filename`, `contentType`, and `dataBase64` (base64-encoded bytes).
            passport: The passport/ID document(s) — a sequence of `DocFile` dicts with the same
                shape as `certificate`.

        Returns:
            A dict acknowledging the submitted materials and the updated review status.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        body = {"certificate": list(certificate), "passport": list(passport)}
        return self._c.request("POST", f"/v1/offramp/banks/{path_seg(bank_account_id)}/materials", body)


class Reconciliation(_Resource):
    """Settled pay-in / withdrawal ledgers for reconciliation (scope: `ledger:read`)."""

    def payments(
        self,
        *,
        from_: Optional[int] = None,
        to: Optional[int] = None,
        limit: Optional[int] = None,
        before: Optional[str] = None,
        order: Optional[str] = None,
    ) -> Json:
        """List the settled pay-in ledger for reconciliation (keyset-paginated).

        Note: `from_` maps to the `from` query parameter (`from` is a Python keyword).

        Args:
            from_: Start of the time window, epoch MILLISECONDS (inclusive). Optional.
            to: End of the time window, epoch MILLISECONDS. Optional.
            limit: Max entries per page. Optional.
            before: Keyset cursor — pass the previous page's `nextCursor`. Optional.
            order: Sort order, `"asc"` or `"desc"`. Optional.

        Returns:
            ``{"items": [...], "total": N, "nextCursor": ...}``.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request(
            "GET",
            "/v1/reconciliation/payments" + qs({"from": from_, "to": to, "limit": limit, "before": before, "order": order}),
        )

    def withdrawals(
        self,
        *,
        from_: Optional[int] = None,
        to: Optional[int] = None,
        limit: Optional[int] = None,
        before: Optional[str] = None,
        order: Optional[str] = None,
    ) -> Json:
        """List the settled withdrawal ledger for reconciliation (keyset-paginated).

        Note: `from_` maps to the `from` query parameter (`from` is a Python keyword).

        Args:
            from_: Start of the time window, epoch MILLISECONDS (inclusive). Optional.
            to: End of the time window, epoch MILLISECONDS. Optional.
            limit: Max entries per page. Optional.
            before: Keyset cursor — pass the previous page's `nextCursor`. Optional.
            order: Sort order, `"asc"` or `"desc"`. Optional.

        Returns:
            ``{"items": [...], "total": N, "nextCursor": ...}``.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request(
            "GET",
            "/v1/reconciliation/withdrawals"
            + qs({"from": from_, "to": to, "limit": limit, "before": before, "order": order}),
        )
