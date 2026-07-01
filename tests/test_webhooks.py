import hashlib
import hmac
import json
import time

import pytest

from absolutepay import WebhookSignatureError, construct_event, verify_signature


def _sign(secret: str, ts: str, body: str) -> str:
    return hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha512).hexdigest()


def test_verify_signature_true_and_false():
    secret, body, ts = "whsec_x", '{"id":"e1"}', str(int(time.time() * 1000))
    sig = _sign(secret, ts, body)
    assert verify_signature(secret, body, ts, sig) is True
    assert verify_signature(secret, body, ts, "deadbeef") is False
    assert verify_signature("", body, ts, sig) is False


def test_construct_event_returns_parsed_payload():
    secret = "whsec_x"
    ts = str(int(time.time() * 1000))
    body = json.dumps({"id": "evt_1", "type": "payment.succeeded", "data": {"amount": "10"}})
    sig = _sign(secret, ts, body)
    event = construct_event(body, {"X-AbsolutePay-Timestamp": ts, "X-AbsolutePay-Signature": sig}, secret)
    assert event["type"] == "payment.succeeded"
    assert event["data"]["amount"] == "10"


def test_construct_event_rejects_bad_signature():
    ts = str(int(time.time() * 1000))
    with pytest.raises(WebhookSignatureError):
        construct_event("{}", {"x-absolutepay-timestamp": ts, "x-absolutepay-signature": "bad"}, "whsec_x")


def test_construct_event_rejects_stale_timestamp():
    secret = "whsec_x"
    ts = str(int(time.time() * 1000) - 10 * 60_000)  # 10 min old
    body = "{}"
    sig = _sign(secret, ts, body)
    with pytest.raises(WebhookSignatureError):
        construct_event(body, {"x-absolutepay-timestamp": ts, "x-absolutepay-signature": sig}, secret)
    # tolerance disabled -> accepted
    assert construct_event(body, {"x-absolutepay-timestamp": ts, "x-absolutepay-signature": sig}, secret, tolerance_ms=0) == {}


def test_verify_signature_accepts_bytes_body():
    secret, ts = "whsec_x", str(int(time.time() * 1000))
    body_bytes = b'{"id":"e1"}'
    sig = _sign(secret, ts, '{"id":"e1"}')
    assert verify_signature(secret, body_bytes, ts, sig) is True
