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
    """Tenant balances (scope: ``balances:read``)."""

    def list(self) -> Json:
        """All asset balances for the workspace."""
        return self._c.request("GET", "/v1/balances")

    def summary(self, *, quote: Optional[str] = None) -> Json:
        """FX-valued combined balance in a quote currency (default USDT)."""
        return self._c.request("GET", "/v1/balances/summary" + qs({"quote": quote}))


class Fees(_Resource):
    """Fee preview from the pricing matrix (scope: ``balances:read``)."""

    def preview(self, *, amount: str, currency: str, payment_type: Optional[str] = None) -> Json:
        """Preview the total fee on an amount for a payment type (default CHECKOUT)."""
        return self._c.request(
            "GET", "/v1/fees/preview" + qs({"amount": amount, "currency": currency, "paymentType": payment_type})
        )


class Payments(_Resource):
    """Hosted/native pay-in checkouts (scope: ``payments:write``)."""

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
        """Create a pay-in order."""
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
        """Look up a checkout by merchant trade number."""
        return self._c.request("GET", f"/v1/checkout/{path_seg(merchant_trade_no)}")


class Payouts(_Resource):
    """Batch crypto payouts (scopes: ``payouts:write`` / ``payouts:read``)."""

    def create(self, items: Sequence[dict], *, idempotency_key: Optional[str] = None) -> Json:
        """Submit a batch payout. Pass ``idempotency_key`` to make retries safe."""
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self._c.request("POST", "/v1/payouts", {"items": list(items)}, headers)

    def options(self, *, currency: str) -> Json:
        """Supported chains + per-chain withdraw fee/limits for a currency."""
        return self._c.request("GET", "/v1/payouts/options" + qs({"currency": currency}))

    def get(self, id: str) -> Json:
        """Look up a payout batch by id."""
        return self._c.request("GET", f"/v1/payouts/{path_seg(id)}")


class Refunds(_Resource):
    """Refunds on settled collections (scope: ``payments:write``)."""

    def create(self, *, merchant_trade_no: str, amount: Money, reason: Optional[str] = None) -> Json:
        body = clean({"merchantTradeNo": merchant_trade_no, "amount": amount, "reason": reason})
        return self._c.request("POST", "/v1/refunds", body)

    def get(self, id: str) -> Json:
        """Look up a refund by its ``refundRequestId``."""
        return self._c.request("GET", f"/v1/refunds/{path_seg(id)}")


class Conversions(_Resource):
    """Stablecoin/crypto conversions (scope: ``convert:write``)."""

    def quote(
        self,
        *,
        sell_currency: str,
        buy_currency: str,
        sell_amount: Optional[str] = None,
        buy_amount: Optional[str] = None,
    ) -> Json:
        """Preview a conversion (no funds move). Specify exactly one of sell_amount / buy_amount."""
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
        """Execute a previously-quoted conversion."""
        return self._c.request("POST", "/v1/conversions", {"quoteId": quote_id, "sell": sell, "buy": buy})

    def convert(
        self,
        *,
        sell_currency: str,
        buy_currency: str,
        sell_amount: Optional[str] = None,
        buy_amount: Optional[str] = None,
    ) -> Json:
        """Convenience: quote then execute in one call."""
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
    """Public (no-auth) payer endpoints for a hosted invoice/checkout page."""

    def get(self, token: str) -> Json:
        return self._c.request("GET", f"/v1/public/invoices/{path_seg(token)}")

    def assets(self, token: str) -> Json:
        return self._c.request("GET", f"/v1/public/invoices/{path_seg(token)}/assets")

    def deposit(self, token: str, *, currency: str, chain: str, full_curr_type: str) -> Json:
        body = {"currency": currency, "chain": chain, "fullCurrType": full_curr_type}
        return self._c.request("POST", f"/v1/public/invoices/{path_seg(token)}/deposit", body)

    def quote(self, token: str, *, currency: str) -> Json:
        return self._c.request("POST", f"/v1/public/invoices/{path_seg(token)}/quote", {"currency": currency})

    def status(self, token: str) -> Json:
        return self._c.request("GET", f"/v1/public/invoices/{path_seg(token)}/status")


class Invoices(_Resource):
    """Invoices + hosted payment links (scopes: ``invoices:write`` / ``invoices:read``)."""

    def __init__(self, client: "AbsolutePay") -> None:
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
        """Create an invoice; pass ``chain`` to mint the deposit address up front."""
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
        """Create a hosted checkout link (the payer picks the asset on the page)."""
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
        """List invoices and checkout links (keyset-paginated with ``limit`` + ``before`` cursor)."""
        return self._c.request(
            "GET",
            "/v1/invoices" + qs({"limit": limit, "status": status, "kind": kind, "before": before, "q": q}),
        )

    def stats(self) -> Json:
        return self._c.request("GET", "/v1/invoices/stats")

    def pause(self, token: str, *, paused: bool) -> Json:
        """Pause or unpause an open invoice/link so it (stops) accepting payment."""
        return self._c.request("POST", f"/v1/invoices/{path_seg(token)}/pause", {"paused": paused})

    def void(self, token: str) -> Json:
        """Void an invoice/link so it can no longer be paid (terminal)."""
        return self._c.request("POST", f"/v1/invoices/{path_seg(token)}/void")


class Subscriptions(_Resource):
    """Recurring billing: plans + subscriptions (scopes: ``subscriptions:read`` / ``subscriptions:write``)."""

    def list_plans(self) -> Json:
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
        body = {
            "merchantPlanNo": merchant_plan_no,
            "name": name,
            "amount": amount,
            "interval": interval,
            "intervalCount": interval_count,
            "totalCycles": total_cycles,
        }
        return self._c.request("POST", "/v1/subscription-plans", body)

    def list(self) -> Json:
        return self._c.request("GET", "/v1/subscriptions")

    def create(self, *, merchant_sub_no: str, plan_no: str, callback_url: Optional[str] = None) -> Json:
        body = clean({"merchantSubNo": merchant_sub_no, "planNo": plan_no, "callbackUrl": callback_url})
        return self._c.request("POST", "/v1/subscriptions", body)

    def deductions(self, merchant_sub_no: str) -> Json:
        """Per-cycle deduction history for a subscription."""
        return self._c.request("GET", f"/v1/subscriptions/{path_seg(merchant_sub_no)}/deductions")

    def cancel(self, merchant_sub_no: str) -> Json:
        return self._c.request("POST", f"/v1/subscriptions/{path_seg(merchant_sub_no)}/cancel")


class GiftCards(_Resource):
    """Gift cards (scopes: ``balances:read`` to read, ``payments:write`` to issue)."""

    def templates(self) -> Json:
        return self._c.request("GET", "/v1/giftcards/templates")

    def list(self) -> Json:
        return self._c.request("GET", "/v1/giftcards")

    def get(self, card_num: str) -> Json:
        return self._c.request("GET", f"/v1/giftcards/{path_seg(card_num)}")

    def create(self, *, title: str, template_id: str, amount: Money) -> Json:
        return self._c.request("POST", "/v1/giftcards", {"title": title, "templateId": template_id, "amount": amount})


class OffRamp(_Resource):
    """Crypto -> fiat off-ramp to a bank account (scopes: ``payouts:read`` / ``payouts:write``)."""

    def countries(self) -> Json:
        return self._c.request("GET", "/v1/offramp/countries")

    def banks(self) -> Json:
        """List the tenant's registered bank accounts."""
        return self._c.request("GET", "/v1/offramp/banks")

    def quote(self, *, crypto_currency: str, fiat_currency: str, crypto_amount: str) -> Json:
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
        body = {
            "quoteToken": quote_token,
            "bankAccountId": bank_account_id,
            "cryptoCurrency": crypto_currency,
            "fiatCurrency": fiat_currency,
            "cryptoAmount": crypto_amount,
            "fiatAmount": fiat_amount,
        }
        return self._c.request("POST", "/v1/offramp/withdraw", body)

    def orders(self) -> Json:
        return self._c.request("GET", "/v1/offramp/orders")


class Transactions(_Resource):
    """Unified funds ledger (scope: ``ledger:read``)."""

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
        """List ledger entries. Filter with ``from_``/``to`` (epoch ms), page with ``limit``/``offset``."""
        return self._c.request(
            "GET",
            "/v1/transactions"
            + qs({"currency": currency, "from": from_, "to": to, "limit": limit, "offset": offset, "format": format}),
        )
