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


def test_builds_query_and_serializes_post_body(monkeypatch):
    cap = install(monkeypatch, 200, {"quote": "USDT", "total": "0", "lines": []})
    client().balances.summary(quote="USDT")
    assert cap["url"] == "https://api.test/v1/balances/summary?quote=USDT"

    cap2 = install(monkeypatch, 201, {"token": "inv_1"})
    client().invoices.create(reference="r1", amount={"amount": "1.00", "currency": "USDT"}, chain="MATIC")
    assert cap2["method"] == "POST"
    assert json.loads(cap2["body"]) == {"reference": "r1", "amount": {"amount": "1.00", "currency": "USDT"}, "chain": "MATIC"}
    assert cap2["headers"]["content-type"] == "application/json"


def test_maps_non_2xx_into_error(monkeypatch):
    install(monkeypatch, 403, {"code": "forbidden", "title": "requires invoices:read"})
    with pytest.raises(AbsolutePayError) as ei:
        client().invoices.list()
    err = ei.value
    assert err.status == 403
    assert err.code == "forbidden"
    assert err.is_auth is True


def test_forwards_idempotency_key_after_signing(monkeypatch):
    cap = install(monkeypatch, 202, {"merchantBatchNo": "po_1", "status": "PROCESSING", "subOrders": []})
    client().payouts.create(
        [{"recipientAddress": "0xabc", "chain": "MATIC", "amount": {"amount": "1.00", "currency": "USDT"}}],
        idempotency_key="batch-001",
    )
    assert cap["headers"]["idempotency-key"] == "batch-001"
    assert cap["headers"]["x-absolutepay-signature"]  # still signed


def test_omits_idempotency_key_when_absent(monkeypatch):
    cap = install(monkeypatch, 202, {"merchantBatchNo": "po_1", "status": "PROCESSING", "subOrders": []})
    client().payouts.create([{"recipientAddress": "0xabc", "chain": "MATIC", "amount": {"amount": "1", "currency": "USDT"}}])
    assert "idempotency-key" not in cap["headers"]


def test_does_not_sign_without_secret(monkeypatch):
    cap = install(monkeypatch, 200, [])
    AbsolutePay("ap_test_x", base_url="https://api.test").balances.list()
    assert "x-absolutepay-signature" not in cap["headers"]


def test_transactions_uses_correct_query_params(monkeypatch):
    # Regression: the ledger filters are from/to + limit/offset (NOT startTime/page).
    cap = install(monkeypatch, 200, {"entries": []})
    client().transactions.list(from_=1000, to=2000, limit=50, offset=100, currency="USDT")
    url = cap["url"]
    assert "from=1000" in url and "to=2000" in url and "limit=50" in url and "offset=100" in url
    assert "startTime" not in url and "page" not in url and "count" not in url


def test_base_url_resolution(monkeypatch):
    for cfg, origin in (({}, PRODUCTION_BASE), ({"sandbox": True}, SANDBOX_BASE)):
        cap = install(monkeypatch, 200, [])
        AbsolutePay("k", **cfg).balances.list()
        assert cap["url"].startswith(origin)
    # base_url wins over sandbox
    cap = install(monkeypatch, 200, [])
    AbsolutePay("k", sandbox=True, base_url="https://api.test").balances.list()
    assert cap["url"].startswith("https://api.test")
