"""API resource groups. Each hangs off the client and mirrors the REST surface.

A ``Money`` is a plain dict: ``{"amount": "10.00", "currency": "USDT"}``.
Methods return the parsed JSON (dict / list); they raise :class:`AbsolutePayError` on non-2xx.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Sequence

from ._util import clean, path_seg, qs

if TYPE_CHECKING:
    from .client import AbsolutePay

Money = dict[str, str]
Json = Any


class _Resource:
    def __init__(self, client: "AbsolutePay") -> None:
        self._c = client


class Balances(_Resource):
    """Read the workspace's asset balances (scope: `balances:read`)."""

    def list(self) -> Json:
        """List every asset balance held by the workspace.

        Returns:
            A list of per-asset balance entries (each with the currency and available/held
            amounts as decimal strings).

        Raises:
            AbsolutePayError: on a non-2xx response (e.g. 401/403 auth, 429 rate limit).

        Example:
            ```python
            for bal in client.balances.list():
                print(bal["currency"], bal["available"])
            ```
        """
        return self._c.request("GET", "/v1/balances")

    def summary(self, *, quote: Optional[str] = None) -> Json:
        """Get the combined balance valued (via FX) into a single quote currency.

        Args:
            quote: Currency to value the total in (e.g. `"USDT"`, `"USD"`). Optional; defaults
                to USDT server-side.

        Returns:
            A dict with the combined valued total and the per-asset breakdown.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("GET", "/v1/balances/summary" + qs({"quote": quote}))


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


class Payments(_Resource):
    """Create and look up pay-in checkouts (scope: `payments:write`)."""

    def create_checkout(
        self,
        *,
        amount: Money,
        chain: str,
        merchant_user_id: int,
        goods_name: str,
        merchant_trade_no: Optional[str] = None,
        terminal_type: Optional[str] = None,
        expires_in: Optional[int] = None,
        method: Optional[str] = None,
    ) -> Json:
        """Create a pay-in order (a checkout the customer pays into).

        Args:
            amount: The order amount as a `Money` dict
                `{"amount": "10.00", "currency": "USDT"}` — the amount is a decimal STRING,
                never a float.
            chain: Settlement chain / network for the payment (e.g. `"TRX"`, `"ETH"`).
            merchant_user_id: Your integer id for the paying customer.
            goods_name: Human-readable description of what is being purchased.
            merchant_trade_no: Your unique reference for this order; used to look it up later
                via `get_checkout`. Optional — the platform generates one if omitted.
            terminal_type: Originating terminal hint (e.g. `"WEB"`, `"APP"`). Optional.
            expires_in: Time-to-live for the checkout, in seconds. Optional.
            method: Checkout method / rendering mode. Optional.

        Returns:
            A dict describing the created order (checkout/pay URL, order reference, amount,
            and status).

        Raises:
            AbsolutePayError: on a non-2xx response (e.g. 403 missing `payments:write`).

        Example:
            ```python
            order = client.payments.create_checkout(
                amount={"amount": "25.00", "currency": "USDT"},
                chain="TRX",
                merchant_user_id=1001,
                goods_name="Annual subscription",
                merchant_trade_no="order-2026-0001",
            )
            print(order["url"])
            ```
        """
        body = clean(
            {
                "amount": amount,
                "chain": chain,
                "merchantUserId": merchant_user_id,
                "goodsName": goods_name,
                "merchantTradeNo": merchant_trade_no,
                "terminalType": terminal_type,
                "expiresIn": expires_in,
                "method": method,
            }
        )
        return self._c.request("POST", "/v1/checkout", body)

    def get_checkout(self, merchant_trade_no: str) -> Json:
        """Look up a previously created checkout by its merchant trade number.

        Args:
            merchant_trade_no: The `merchant_trade_no` used (or returned) when creating the
                checkout.

        Returns:
            A dict with the current order state (status, amount, paid details).

        Raises:
            AbsolutePayError: on a non-2xx response (e.g. 404 if unknown).
        """
        return self._c.request("GET", f"/v1/checkout/{path_seg(merchant_trade_no)}")


class Payouts(_Resource):
    """Send batch crypto payouts (scope: `payouts:write`; reads use `payouts:read`)."""

    def create(self, items: Sequence[dict], *, idempotency_key: Optional[str] = None) -> Json:
        """Submit a batch of crypto payouts in a single request.

        Args:
            items: The payout line items — a sequence of dicts, one per recipient (each
                specifying the destination address/chain, currency, and amount as a decimal
                STRING). Sent as the `items` array.
            idempotency_key: Optional client-chosen key that makes retries safe: replaying the
                same key returns the ORIGINAL batch instead of paying out again. Strongly
                recommended for any request you might retry. Sent as the `Idempotency-Key`
                header (outside the request signature).

        Returns:
            A dict describing the created payout batch (batch id and per-item status).

        Raises:
            AbsolutePayError: on a non-2xx response (e.g. 403 missing `payouts:write`,
                insufficient balance).

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
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self._c.request("POST", "/v1/payouts", {"items": list(items)}, headers)

    def options(self, *, currency: str) -> Json:
        """List the chains a currency can be paid out on, with per-chain fees and limits.

        Args:
            currency: The payout currency, e.g. `"USDT"`.

        Returns:
            A dict/list of supported chains and their withdraw fee and min/max limits.

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
    """Refund settled pay-in collections (scope: `payments:write`)."""

    def create(self, *, merchant_trade_no: str, amount: Money, reason: Optional[str] = None) -> Json:
        """Refund all or part of a settled checkout back to the payer.

        Args:
            merchant_trade_no: The trade number of the original settled checkout to refund.
            amount: The amount to refund as a `Money` dict
                `{"amount": "10.00", "currency": "USDT"}` — decimal STRING, never a float. May
                be less than the original for a partial refund.
            reason: Optional human-readable reason recorded with the refund.

        Returns:
            A dict describing the refund request, including its `refundRequestId` and status.

        Raises:
            AbsolutePayError: on a non-2xx response (e.g. 403, or original not refundable).

        Example:
            ```python
            refund = client.refunds.create(
                merchant_trade_no="order-2026-0001",
                amount={"amount": "25.00", "currency": "USDT"},
                reason="customer request",
            )
            print(refund["refundRequestId"])
            ```
        """
        body = clean({"merchantTradeNo": merchant_trade_no, "amount": amount, "reason": reason})
        return self._c.request("POST", "/v1/refunds", body)

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

    def execute(self, *, quote_id: str, sell: Money, buy: Money) -> Json:
        """Execute a conversion against a quote from `quote` (this moves funds).

        Args:
            quote_id: The `quoteId` returned by `quote`.
            sell: The sell side as a `Money` dict (from the quote's `sellAmount`/`sellCurrency`).
            buy: The buy side as a `Money` dict (from the quote's `buyAmount`/`buyCurrency`).

        Returns:
            A dict describing the executed conversion and resulting balances.

        Raises:
            AbsolutePayError: on a non-2xx response (e.g. expired quote, insufficient balance).
        """
        return self._c.request("POST", "/v1/conversions", {"quoteId": quote_id, "sell": sell, "buy": buy})

    def convert(
        self,
        *,
        sell_currency: str,
        buy_currency: str,
        sell_amount: Optional[str] = None,
        buy_amount: Optional[str] = None,
    ) -> Json:
        """Quote and execute a conversion in one call (convenience wrapper).

        Calls `quote` then immediately `execute` with the returned amounts. Because the rate
        can move between the two steps, use `quote` + `execute` yourself if you need to show
        the rate to a user before committing. Specify EXACTLY ONE of `sell_amount` /
        `buy_amount` (decimal STRINGS).

        Args:
            sell_currency: The currency being sold, e.g. `"USDT"`.
            buy_currency: The currency being bought, e.g. `"BTC"`.
            sell_amount: Amount to sell as a decimal string. Provide this OR `buy_amount`.
            buy_amount: Amount to receive as a decimal string. Provide this OR `sell_amount`.

        Returns:
            A dict describing the executed conversion (same shape as `execute`).

        Raises:
            AbsolutePayError: on a non-2xx response at either the quote or execute step.

        Example:
            ```python
            result = client.conversions.convert(
                sell_currency="USDT",
                buy_currency="BTC",
                sell_amount="100.00",
            )
            ```
        """
        q = self.quote(
            sell_currency=sell_currency,
            buy_currency=buy_currency,
            sell_amount=sell_amount,
            buy_amount=buy_amount,
        )
        return self.execute(
            quote_id=q["quoteId"],
            sell={"amount": q["sellAmount"], "currency": q["sellCurrency"]},
            buy={"amount": q["buyAmount"], "currency": q["buyCurrency"]},
        )


class _PublicInvoices(_Resource):
    """Payer-facing invoice endpoints for building a custom hosted checkout page.

    These back the public payment page a customer sees; they are keyed by the invoice's public
    `token` (not by tenant credentials). Reachable via `client.invoices.public`.
    """

    def get(self, token: str) -> Json:
        """Fetch the public invoice details for a payment page.

        Args:
            token: The invoice's public token (from the hosted link / invoice creation).

        Returns:
            A dict with the payer-visible invoice details (amount, description, status).

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("GET", f"/v1/public/invoices/{path_seg(token)}")

    def assets(self, token: str) -> Json:
        """List the assets/chains the payer may use to pay this invoice.

        Args:
            token: The invoice's public token.

        Returns:
            A dict/list of selectable currency + chain options.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("GET", f"/v1/public/invoices/{path_seg(token)}/assets")

    def deposit(self, token: str, *, currency: str, chain: str, full_curr_type: str) -> Json:
        """Mint (or fetch) the deposit address for the payer's chosen asset.

        Args:
            token: The invoice's public token.
            currency: The chosen currency, e.g. `"USDT"`.
            chain: The chosen chain/network, e.g. `"TRX"`.
            full_curr_type: The provider's full currency-type identifier for the selection
                (sent as `fullCurrType`).

        Returns:
            A dict with the deposit `address` (and chain/memo where applicable).

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        body = {"currency": currency, "chain": chain, "fullCurrType": full_curr_type}
        return self._c.request("POST", f"/v1/public/invoices/{path_seg(token)}/deposit", body)

    def quote(self, token: str, *, currency: str) -> Json:
        """Quote how much of a chosen currency is needed to settle the invoice.

        Args:
            token: The invoice's public token.
            currency: The currency the payer intends to pay in.

        Returns:
            A dict with the crypto amount due and the rate used.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("POST", f"/v1/public/invoices/{path_seg(token)}/quote", {"currency": currency})

    def status(self, token: str) -> Json:
        """Poll the current payment status of a public invoice.

        Args:
            token: The invoice's public token.

        Returns:
            A dict with the current status (e.g. open / paid).

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("GET", f"/v1/public/invoices/{path_seg(token)}/status")

    def track_open(self, token: str) -> Json:
        """Record that the payer opened the hosted invoice page (analytics beacon).

        A fire-and-forget signal used only for open-rate analytics; it does not change the
        invoice state and needs no authentication.

        Args:
            token: The invoice's public token.

        Returns:
            A dict acknowledging the recorded open (typically empty).

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("POST", f"/v1/public/invoices/{path_seg(token)}/open")


class Invoices(_Resource):
    """Invoices and hosted payment links (scope: `invoices:write`; reads use `invoices:read`).

    Writes/reads for your own invoices go through this class; the payer-facing endpoints for a
    hosted page live under `client.invoices.public` (a `_PublicInvoices`).
    """

    def __init__(self, client: "AbsolutePay") -> None:
        """Wire up the invoices resource and its public (payer-facing) sub-resource.

        Args:
            client: The parent `AbsolutePay` client used for requests.
        """
        super().__init__(client)
        self.public = _PublicInvoices(client)

    def create(
        self,
        *,
        reference: str,
        amount: Money,
        description: Optional[str] = None,
        customer_email: Optional[str] = None,
        expires_at: Optional[int] = None,
        chain: Optional[str] = None,
    ) -> Json:
        """Create an invoice for a fixed amount.

        Args:
            reference: Your unique reference for this invoice (idempotency/lookup handle).
            amount: The invoice amount as a `Money` dict
                `{"amount": "10.00", "currency": "USDT"}` — decimal STRING, never a float.
            description: Optional human-readable description shown to the payer.
            customer_email: Optional payer email (used for receipts/notifications).
            expires_at: Optional expiry as epoch MILLISECONDS.
            chain: Optional chain/network; passing it mints the deposit address up front
                instead of letting the payer choose an asset later.

        Returns:
            A dict describing the created invoice (its `token`, hosted URL, amount, status, and
            — if `chain` was given — the deposit address).

        Raises:
            AbsolutePayError: on a non-2xx response.

        Example:
            ```python
            invoice = client.invoices.create(
                reference="inv-1001",
                amount={"amount": "49.99", "currency": "USDT"},
                customer_email="buyer@example.com",
                chain="TRX",
            )
            print(invoice["url"])
            ```
        """
        body = clean(
            {
                "reference": reference,
                "amount": amount,
                "description": description,
                "customerEmail": customer_email,
                "expiresAt": expires_at,
                "chain": chain,
            }
        )
        return self._c.request("POST", "/v1/invoices", body)

    def create_checkout(
        self,
        *,
        reference: str,
        amount: Money,
        description: Optional[str] = None,
        customer_email: Optional[str] = None,
        expires_at: Optional[int] = None,
    ) -> Json:
        """Create a hosted checkout link where the payer picks the asset on the page.

        Unlike `create`, no `chain` is fixed up front — the payer chooses their currency/chain
        on the hosted page.

        Args:
            reference: Your unique reference for this checkout link.
            amount: The amount as a `Money` dict
                `{"amount": "10.00", "currency": "USDT"}` — decimal STRING, never a float.
            description: Optional human-readable description shown to the payer.
            customer_email: Optional payer email.
            expires_at: Optional expiry as epoch MILLISECONDS.

        Returns:
            A dict describing the created checkout link (its `token` and hosted URL).

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        body = clean(
            {
                "reference": reference,
                "amount": amount,
                "description": description,
                "customerEmail": customer_email,
                "expiresAt": expires_at,
            }
        )
        return self._c.request("POST", "/v1/checkouts", body)

    def list(
        self,
        *,
        limit: Optional[int] = None,
        status: Optional[str] = None,
        kind: Optional[str] = None,
        before: Optional[str] = None,
        q: Optional[str] = None,
    ) -> Json:
        """List invoices and hosted checkout links (keyset-paginated).

        Args:
            limit: Max items per page. Optional.
            status: Filter by status (e.g. open / paid / void). Optional.
            kind: Filter by kind (invoice vs. checkout link). Optional.
            before: Keyset cursor — pass the previous page's opaque `nextCursor` to fetch the
                next page. Optional; omit for the first page.
            q: Free-text search over reference/description. Optional.

        Returns:
            A dict with the page of items and a `nextCursor` (opaque; feed back as `before`;
            `None`/null on the last page).

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request(
            "GET",
            "/v1/invoices" + qs({"limit": limit, "status": status, "kind": kind, "before": before, "q": q}),
        )

    def stats(self) -> Json:
        """Get aggregate invoice statistics for the workspace.

        Returns:
            A dict of summary counts/totals across invoices.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("GET", "/v1/invoices/stats")

    def pause(self, token: str, *, paused: bool) -> Json:
        """Pause or resume an open invoice/link, toggling whether it accepts payment.

        Args:
            token: The invoice/link token.
            paused: `True` to stop accepting payment; `False` to resume.

        Returns:
            A dict with the updated invoice state.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("POST", f"/v1/invoices/{path_seg(token)}/pause", {"paused": paused})

    def void(self, token: str) -> Json:
        """Void an invoice/link so it can no longer be paid (terminal — cannot be undone).

        Args:
            token: The invoice/link token.

        Returns:
            A dict with the voided invoice state.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("POST", f"/v1/invoices/{path_seg(token)}/void")


class Subscriptions(_Resource):
    """Recurring billing — plans and subscriptions (scope: `subscriptions:write`; reads use `subscriptions:read`)."""

    def list_plans(self) -> Json:
        """List all subscription plans defined for the workspace.

        Returns:
            A list of plan objects.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("GET", "/v1/subscription-plans")

    def create_plan(
        self,
        *,
        merchant_plan_no: str,
        name: str,
        amount: Money,
        interval: str,
        interval_count: int,
        total_cycles: int,
    ) -> Json:
        """Create a subscription plan that subscriptions can later be attached to.

        Args:
            merchant_plan_no: Your unique reference for the plan.
            name: Human-readable plan name.
            amount: The per-cycle charge as a `Money` dict
                `{"amount": "10.00", "currency": "USDT"}` — decimal STRING, never a float.
            interval: Billing interval unit (e.g. `"DAY"`, `"WEEK"`, `"MONTH"`).
            interval_count: Number of interval units between charges (e.g. `1` = every month).
            total_cycles: Total number of charges before the plan completes.

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
        return self._c.request("POST", "/v1/subscription-plans", body)

    def list(self, *, limit: Optional[int] = None, before: Optional[str] = None, status: Optional[str] = None) -> Json:
        """List subscriptions (keyset-paginated).

        Args:
            limit: Max items per page. Optional.
            before: Keyset cursor — pass the previous page's opaque `nextCursor` for the next
                page. Optional; omit for the first page. `nextCursor` is `None`/null on the
                last page.
            status: Filter by subscription status. Optional.

        Returns:
            A dict with the page of subscriptions and a `nextCursor`.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("GET", "/v1/subscriptions" + qs({"limit": limit, "before": before, "status": status}))

    def create(self, *, merchant_sub_no: str, plan_no: str, callback_url: Optional[str] = None) -> Json:
        """Subscribe a customer to a plan.

        Args:
            merchant_sub_no: Your unique reference for this subscription.
            plan_no: The plan number to subscribe to (from `create_plan`/`list_plans`).
            callback_url: Optional per-subscription callback URL for lifecycle notifications.

        Returns:
            A dict describing the created subscription (status, next charge, authorization link
            if applicable).

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        body = clean({"merchantSubNo": merchant_sub_no, "planNo": plan_no, "callbackUrl": callback_url})
        return self._c.request("POST", "/v1/subscriptions", body)

    def deductions(self, merchant_sub_no: str) -> Json:
        """Get the per-cycle deduction (charge) history for a subscription.

        Args:
            merchant_sub_no: The subscription's merchant reference.

        Returns:
            A list of past deductions/charges for the subscription.

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
            A list of template objects, each with a `templateId` to pass to `create`.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("GET", "/v1/giftcards/templates")

    def list(self, *, limit: Optional[int] = None, before: Optional[str] = None, status: Optional[str] = None) -> Json:
        """List issued gift cards (keyset-paginated).

        Args:
            limit: Max items per page. Optional.
            before: Keyset cursor — pass the previous page's opaque `nextCursor` for the next
                page. Optional; omit for the first page. `nextCursor` is `None`/null on the
                last page.
            status: Filter by gift-card status. Optional.

        Returns:
            A dict with the page of gift cards and a `nextCursor`.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("GET", "/v1/giftcards" + qs({"limit": limit, "before": before, "status": status}))

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

    def create(self, *, title: str, template_id: str, amount: Money) -> Json:
        """Issue a new gift card (scope: `payments:write`).

        Args:
            title: Human-readable title/label for the card.
            template_id: The design template id (from `templates`).
            amount: The card's face value as a `Money` dict
                `{"amount": "10.00", "currency": "USDT"}` — decimal STRING, never a float.

        Returns:
            A dict describing the issued gift card (card number, redemption info, status).

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("POST", "/v1/giftcards", {"title": title, "templateId": template_id, "amount": amount})


class OffRamp(_Resource):
    """Crypto -> fiat off-ramp to a bank account (scope: `payouts:write`; reads use `payouts:read`)."""

    def countries(self) -> Json:
        """List the countries the off-ramp supports.

        Returns:
            A list of supported countries (with the fiat currencies each allows).

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("GET", "/v1/offramp/countries")

    def banks(self) -> Json:
        """List the workspace's registered destination bank accounts.

        Returns:
            A list of bank accounts, each with a `bankAccountId` to pass to `withdraw`.

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
    ) -> Json:
        """Execute an off-ramp against a quote, paying fiat to a bank account (this moves funds).

        Args:
            quote_token: The `quoteToken` from `quote`.
            bank_account_id: Destination bank account id (from `banks`).
            crypto_currency: The crypto asset being sold (must match the quote).
            fiat_currency: The fiat currency to receive (must match the quote).
            crypto_amount: Amount of crypto to sell, as a decimal STRING (from the quote).
            fiat_amount: Amount of fiat to receive, as a decimal STRING (from the quote).

        Returns:
            A dict describing the created off-ramp order and its status.

        Raises:
            AbsolutePayError: on a non-2xx response (e.g. expired quote, insufficient balance).
        """
        body = {
            "quoteToken": quote_token,
            "bankAccountId": bank_account_id,
            "cryptoCurrency": crypto_currency,
            "fiatCurrency": fiat_currency,
            "cryptoAmount": crypto_amount,
            "fiatAmount": fiat_amount,
        }
        return self._c.request("POST", "/v1/offramp/withdraw", body)

    def orders(self, *, limit: Optional[int] = None, before: Optional[str] = None, status: Optional[str] = None) -> Json:
        """List off-ramp orders (keyset-paginated).

        Args:
            limit: Max items per page. Optional.
            before: Keyset cursor — pass the previous page's opaque `nextCursor` for the next
                page. Optional; omit for the first page. `nextCursor` is `None`/null on the
                last page.
            status: Filter by order status. Optional.

        Returns:
            A dict with the page of orders and a `nextCursor`.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("GET", "/v1/offramp/orders" + qs({"limit": limit, "before": before, "status": status}))

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

    def delete_bank(self, bank_account_id: str) -> Json:
        """Remove a registered destination bank account.

        Args:
            bank_account_id: The bank account id to delete (from `banks`).

        Returns:
            A dict acknowledging the deletion (typically empty).

        Raises:
            AbsolutePayError: on a non-2xx response (e.g. 404 if unknown).
        """
        return self._c.request("DELETE", f"/v1/offramp/banks/{path_seg(bank_account_id)}")

    def submit_bank_materials(self, bank_account_id: str, *, certificate: Sequence[dict], passport: Sequence[dict]) -> Json:
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
        offset: Optional[int] = None,
    ) -> Json:
        """List the settled pay-in ledger for reconciliation.

        Note: `from_` has a trailing underscore because `from` is a Python keyword; it maps to
        the `from` query parameter.

        Args:
            from_: Start of the time window, epoch MILLISECONDS (inclusive). Optional.
            to: End of the time window, epoch MILLISECONDS. Optional.
            limit: Max entries to return. Optional.
            offset: Number of entries to skip (for paging). Optional.

        Returns:
            A dict/list of settled pay-in ledger entries for the window.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request(
            "GET",
            "/v1/reconciliation/payments" + qs({"from": from_, "to": to, "limit": limit, "offset": offset}),
        )

    def withdrawals(
        self,
        *,
        from_: Optional[int] = None,
        to: Optional[int] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> Json:
        """List the settled withdrawal ledger for reconciliation.

        Note: `from_` has a trailing underscore because `from` is a Python keyword; it maps to
        the `from` query parameter.

        Args:
            from_: Start of the time window, epoch MILLISECONDS (inclusive). Optional.
            to: End of the time window, epoch MILLISECONDS. Optional.
            limit: Max entries to return. Optional.
            offset: Number of entries to skip (for paging). Optional.

        Returns:
            A dict/list of settled withdrawal ledger entries for the window.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request(
            "GET",
            "/v1/reconciliation/withdrawals" + qs({"from": from_, "to": to, "limit": limit, "offset": offset}),
        )


class Deposits(_Resource):
    """Direct on-chain deposits into the workspace balance (scope: `balances:read`)."""

    def chains(self) -> Json:
        """List the chains/networks a deposit address can be created on.

        Returns:
            A list of supported chains (with per-chain currency/network details).

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("GET", "/v1/deposits/chains")

    def create_address(self, *, chain: str) -> Json:
        """Create (or fetch) the permanent deposit address for a network.

        The address is permanent and reusable — any funds sent to it credit the workspace
        balance.

        Args:
            chain: The chain/network to deposit on, e.g. `"TRX"` (from `chains`).

        Returns:
            A dict with the deposit `address` (and chain/memo where applicable).

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request("POST", "/v1/deposits/address", {"chain": chain})


class Transactions(_Resource):
    """Unified funds ledger for reconciliation (scope: `ledger:read`)."""

    def list(
        self,
        *,
        currency: Optional[str] = None,
        from_: Optional[int] = None,
        to: Optional[int] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        format: Optional[str] = None,
    ) -> Json:
        """List ledger entries across all funds movements, for reconciliation.

        Note: `from_` has a trailing underscore because `from` is a Python keyword; it maps to
        the `from` query parameter. Unlike the cursor-paginated resources, this endpoint uses
        classic `limit`/`offset` paging.

        Args:
            currency: Filter to a single currency, e.g. `"USDT"`. Optional.
            from_: Start of the time window, epoch MILLISECONDS (inclusive). Optional.
            to: End of the time window, epoch MILLISECONDS. Optional.
            limit: Max entries to return. Optional.
            offset: Number of entries to skip (for paging). Optional.
            format: Response format hint (e.g. a CSV export mode). Optional.

        Returns:
            A dict/list of ledger entries for the window.

        Raises:
            AbsolutePayError: on a non-2xx response.
        """
        return self._c.request(
            "GET",
            "/v1/transactions"
            + qs({"currency": currency, "from": from_, "to": to, "limit": limit, "offset": offset, "format": format}),
        )
