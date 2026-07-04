# absolutepay

Official AbsolutePay API client for Python. Server-side only — your API key and signing secret must never reach a browser.

> Every request from an app key is HMAC-signed automatically. Inbound webhooks are verified with one call. **Zero runtime dependencies** — standard library only.

## Install

```bash
pip install absolutepay
```

Requires Python 3.9+.

## Environments

| Config | Base URL |
|---|---|
| default | `https://api.absolutepay.io` (production) |
| `sandbox=True` | `https://sandbox-api.absolutepay.io` |
| `base_url="https://…"` | your override (takes precedence over `sandbox`) |

Use a dedicated sandbox app (sign up at [sandbox.absolutepay.io](https://sandbox.absolutepay.io)) with `sandbox=True` to test end-to-end without moving real funds.

## Quickstart

```python
import os
from absolutepay import AbsolutePay

ap = AbsolutePay(
    api_key=os.environ["ABSOLUTEPAY_API_KEY"],            # ap_live_… / ap_test_…
    signing_secret=os.environ["ABSOLUTEPAY_SIGNING_SECRET"],  # apisign_…  (required for app keys)
    # sandbox=True,             # → https://sandbox-api.absolutepay.io (default is production)
    # base_url="https://…",     # optional: override the origin entirely (wins over sandbox)
)

balances = ap.balances.list()
preview = ap.fees.preview(amount="100", currency="USDT")

invoice = ap.invoices.create(
    reference="order-123",
    amount={"amount": "25.00", "currency": "USDT"},
    chain="MATIC",  # mint the deposit address up front; omit to let the payer pick
    redirect_url="https://shop.example.com/thank-you",  # payer returns here when done
)
print(invoice["token"])
```

## Money

Amounts are plain dicts — a decimal string plus a currency code:

```python
{"amount": "10.00", "currency": "USDT"}
```

## Resources

`balances` · `fees` · `payouts` · `refunds` · `conversions` · `invoices` (+ `invoices.public`) · `subscriptions` · `giftcards` · `offramp` · `transactions`

```python
# Hosted checkout link — the payer picks which asset/chain to pay with
checkout = ap.invoices.create_checkout(
    reference="order-123",
    amount={"amount": "25.00", "currency": "USDT"},
)
print(checkout["checkoutUrl"])  # send the payer here; confirm via the payment.succeeded webhook
```

```python
# Batch payout (idempotent — a retry with the same key never pays twice)
ap.payouts.create(
    [{"recipientAddress": "0xabc…", "chain": "MATIC", "amount": {"amount": "5.00", "currency": "USDT"}}],
    idempotency_key="payroll-2026-07-01",
)

# Quote + execute a conversion in one call
order = ap.conversions.convert(sell_currency="USDT", buy_currency="ETH", sell_amount="100")

# Ledger, filtered by time range (epoch ms) and paginated
ledger = ap.transactions.list(from_=1_700_000_000_000, to=1_800_000_000_000, limit=50, offset=0)
```

## Errors

Non-2xx responses raise `AbsolutePayError`:

```python
from absolutepay import AbsolutePayError

try:
    ap.invoices.list()
except AbsolutePayError as e:
    print(e.status, e.code, e.detail, e.request_id)
    if e.is_rate_limited:  # 429 — back off and retry
        ...
    if e.is_auth:          # 401/403 — bad creds, missing scope, or bad signature
        ...
```

## Webhooks

Verify the signature and parse the event in one call. Pass the **raw** request body (bytes or str), the request headers, and your app's callback secret (`whsec_…`):

```python
from absolutepay import construct_event, WebhookSignatureError

# e.g. in a Flask handler
raw = request.get_data()  # RAW bytes — do not re-serialize
try:
    event = construct_event(raw, dict(request.headers), os.environ["ABSOLUTEPAY_WEBHOOK_SECRET"])
except WebhookSignatureError:
    return "", 400

if event["type"] == "payment.succeeded":
    fulfill(event["data"])
return "", 200
```

The freshness (replay) window defaults to 5 minutes; pass `tolerance_ms=0` to disable it.

## Security

- **Server-side only.** The API key + signing secret authenticate as your workspace — never ship them to a browser or mobile app.
- Requests are sent over HTTPS only (except `localhost` for local development).
- The `Idempotency-Key` header (on payouts) is intentionally **not** part of the signed canonical string.

## License

MIT
