import json
import urllib.error
import urllib.request
from io import BytesIO

import pytest

from absolutepay import AbsolutePay, AbsolutePayError
from absolutepay.client import PRODUCTION_BASE, SANDBOX_BASE


class _FakeResp:
    def __init__(self, body: str):
        self._body = body.encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def install(monkeypatch, status=200, payload=None, headers=None):
    """Patch urlopen; return a dict that captures the outgoing request."""
    cap: dict = {}
    payload = {} if payload is None else payload

    def fake_urlopen(req, timeout=None):
        cap["method"] = req.get_method()
        cap["url"] = req.full_url
        cap["headers"] = {k.lower(): v for k, v in req.headers.items()}
        cap["body"] = req.data.decode() if req.data else None
        if status >= 400:
            raise urllib.error.HTTPError(
                req.full_url, status, "err", hdrs=(headers or {}), fp=BytesIO(json.dumps(payload).encode())
            )
        return _FakeResp(json.dumps(payload))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return cap


def client():
    return AbsolutePay("ap_live_x", signing_secret="apisign_x", base_url="https://api.test")


def test_requires_api_key():
    with pytest.raises(ValueError, match="api_key"):
        AbsolutePay("")


def test_rejects_cleartext_baseurl_but_allows_localhost():
    with pytest.raises(ValueError, match="https"):
        AbsolutePay("k", base_url="http://api.evil.com")
    AbsolutePay("k", base_url="http://localhost:3000")  # no raise
    AbsolutePay("k", base_url="https://api.test")  # no raise


def test_signs_every_request_and_sends_bearer(monkeypatch):
    cap = install(monkeypatch, 200, [{"currency": "USDT", "available": "1", "locked": "0"}])
    client().balances.list()
    assert cap["url"] == "https://api.test/v1/balances"
    assert cap["method"] == "GET"
    assert cap["headers"]["authorization"] == "Bearer ap_live_x"
    assert cap["headers"]["x-absolutepay-signature"]
    assert cap["headers"]["x-absolutepay-nonce"]


def test_sends_default_user_agent(monkeypatch):
    # Cloudflare/WAF blocks urllib's default UA; we must identify the SDK explicitly.
    cap = install(monkeypatch, 200, {"items": []})
    client().balances.list()
    ua = cap["headers"]["user-agent"]
    assert ua.startswith("absolutepay-python/")
    assert "python-urllib" not in ua.lower()


def test_user_agent_is_overridable_via_extra_headers(monkeypatch):
    cap = install(monkeypatch, 200, {"items": []})
    client().request("GET", "/v1/balances", None, {"user-agent": "my-app/9.9"})
    assert cap["headers"]["user-agent"] == "my-app/9.9"


def test_builds_query_and_serializes_post_body(monkeypatch):
    cap = install(monkeypatch, 200, {"items": [], "nextCursor": None})
    client().checkouts.list(status="open", q="acme")
    assert cap["url"] == "https://api.test/v1/checkouts?status=open&q=acme"

    cap2 = install(monkeypatch, 201, {"token": "inv_1", "address": "T..."})
    client().invoices.create(reference="r1", amount={"amount": "1.00", "currency": "USDT"}, chain="MATIC")
    assert cap2["method"] == "POST"
    assert json.loads(cap2["body"]) == {"reference": "r1", "amount": {"amount": "1.00", "currency": "USDT"}, "chain": "MATIC"}
    assert cap2["headers"]["content-type"] == "application/json"


def test_checkouts_crud_hits_expected_routes(monkeypatch):
    amount = {"amount": "1.00", "currency": "USDT"}

    cap = install(monkeypatch, 201, {"token": "chk_1", "checkoutUrl": "https://pay.test/chk_1"})
    client().checkouts.create(reference="c1", amount=amount, redirect_url="https://shop.example.com/done")
    assert cap["method"] == "POST" and cap["url"] == "https://api.test/v1/checkouts"
    assert json.loads(cap["body"])["redirectUrl"] == "https://shop.example.com/done"

    cap2 = install(monkeypatch, 201, {"token": "chk_2"})
    client().checkouts.create(reference="c2", amount=amount)
    assert "redirectUrl" not in json.loads(cap2["body"])

    cap3 = install(monkeypatch, 200, {"token": "chk_1"})
    client().checkouts.get("chk_1")
    assert cap3["method"] == "GET" and cap3["url"] == "https://api.test/v1/checkouts/chk_1"

    cap4 = install(monkeypatch, 200, {"token": "chk_1"})
    client().checkouts.delete("chk_1")
    assert cap4["method"] == "DELETE" and cap4["url"] == "https://api.test/v1/checkouts/chk_1"


def test_update_only_sends_passed_fields_and_null_clears(monkeypatch):
    # Omitted fields are absent; an explicit None is sent as null (clears the field server-side).
    cap = install(monkeypatch, 200, {"token": "chk_1"})
    client().checkouts.update("chk_1", paused=True)
    assert cap["method"] == "PATCH" and cap["url"] == "https://api.test/v1/checkouts/chk_1"
    assert json.loads(cap["body"]) == {"paused": True}

    cap2 = install(monkeypatch, 200, {"token": "inv_1"})
    client().invoices.update("inv_1", redirect_url=None, description="note")
    assert cap2["url"] == "https://api.test/v1/invoices/inv_1"
    assert json.loads(cap2["body"]) == {"redirectUrl": None, "description": "note"}


def test_invoice_create_requires_chain():
    with pytest.raises(TypeError):
        client().invoices.create(reference="r", amount={"amount": "1", "currency": "USDT"})  # type: ignore[call-arg]


def test_list_returns_items_and_next_cursor(monkeypatch):
    page = {"items": [{"token": "chk_1"}, {"token": "chk_2"}], "nextCursor": "cur_abc"}
    install(monkeypatch, 200, page)
    out = client().checkouts.list(limit=2, order="desc")
    assert out == page
    assert out["items"][0]["token"] == "chk_1"
    assert out["nextCursor"] == "cur_abc"


def test_maps_non_2xx_into_error(monkeypatch):
    install(monkeypatch, 403, {"code": "forbidden", "title": "insufficient scope", "detail": "requires invoices:read"})
    with pytest.raises(AbsolutePayError) as ei:
        client().invoices.list()
    err = ei.value
    assert err.status == 403
    assert err.code == "forbidden"
    assert err.detail == "requires invoices:read"
    assert err.is_auth is True


def test_forwards_idempotency_key_after_signing(monkeypatch):
    cap = install(monkeypatch, 202, {"merchantBatchNo": "po_1", "status": "PROCESSING", "subOrders": []})
    client().payouts.create(
        [{"recipientAddress": "0xabc", "chain": "MATIC", "amount": {"amount": "1.00", "currency": "USDT"}}],
        idempotency_key="batch-001",
    )
    assert cap["headers"]["idempotency-key"] == "batch-001"
    assert cap["headers"]["x-absolutepay-signature"]  # still signed


def test_idempotency_key_wired_on_all_money_posts(monkeypatch):
    amount = {"amount": "1.00", "currency": "USDT"}
    cases = [
        lambda c: c.refunds.create(merchant_trade_no="t1", amount=amount, idempotency_key="k"),
        lambda c: c.conversions.execute(quote_id="q1", sell=amount, buy=amount, idempotency_key="k"),
        lambda c: c.offramp.withdraw(
            quote_token="qt", bank_account_id="b1", crypto_currency="USDT", fiat_currency="IDR",
            crypto_amount="1", fiat_amount="15000", idempotency_key="k",
        ),
        lambda c: c.giftcards.create(title="t", template_id="tpl", amount=amount, idempotency_key="k"),
        lambda c: c.subscriptions.create(merchant_sub_no="s1", plan_no="p1", idempotency_key="k"),
        lambda c: c.subscriptions.plans.create(
            merchant_plan_no="p1", name="Pro", amount=amount, interval="MONTH",
            interval_count=1, total_cycles=12, idempotency_key="k",
        ),
    ]
    for call in cases:
        cap = install(monkeypatch, 200, {})
        call(client())
        assert cap["headers"]["idempotency-key"] == "k"
        assert cap["headers"]["x-absolutepay-signature"]  # header stays outside the signature


def test_omits_idempotency_key_when_absent(monkeypatch):
    cap = install(monkeypatch, 202, {"merchantBatchNo": "po_1", "status": "PROCESSING", "subOrders": []})
    client().payouts.create([{"recipientAddress": "0xabc", "chain": "MATIC", "amount": {"amount": "1", "currency": "USDT"}}])
    assert "idempotency-key" not in cap["headers"]


def test_does_not_sign_without_secret(monkeypatch):
    cap = install(monkeypatch, 200, {"items": []})
    AbsolutePay("ap_test_x", base_url="https://api.test").balances.list()
    assert "x-absolutepay-signature" not in cap["headers"]


def test_history_lists_use_keyset_query_params(monkeypatch):
    # Refund / conversion / deposit histories are keyset-paginated: from/to + limit/before/order.
    cap = install(monkeypatch, 200, {"items": [], "total": 0, "nextCursor": None})
    client().refunds.list(from_=1000, to=2000, currency="USDT", limit=50, before="cur", order="asc")
    url = cap["url"]
    assert "from=1000" in url and "to=2000" in url and "limit=50" in url
    assert "before=cur" in url and "order=asc" in url and "currency=USDT" in url
    assert "offset=" not in url and "startTime" not in url

    cap2 = install(monkeypatch, 200, {"items": [], "nextCursor": None})
    client().deposits.list(chain="TRX", from_=1, to=2, order="desc")
    assert cap2["url"] == "https://api.test/v1/deposits?chain=TRX&from=1&to=2&order=desc"


def test_base_url_resolution(monkeypatch):
    for cfg, origin in (({}, PRODUCTION_BASE), ({"sandbox": True}, SANDBOX_BASE)):
        cap = install(monkeypatch, 200, [])
        AbsolutePay("k", **cfg).balances.list()
        assert cap["url"].startswith(origin)
    # base_url wins over sandbox
    cap = install(monkeypatch, 200, [])
    AbsolutePay("k", sandbox=True, base_url="https://api.test").balances.list()
    assert cap["url"].startswith("https://api.test")
