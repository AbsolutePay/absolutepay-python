import hashlib
import hmac

from absolutepay import canonical_request, sign_request


def test_canonical_request_format():
    c = canonical_request("get", "/v1/balances", "1700000000000", "nonce-1", "")
    empty_hash = hashlib.sha256(b"").hexdigest()
    assert c == f"GET\n/v1/balances\n1700000000000\nnonce-1\n{empty_hash}"


def test_sign_request_headers_and_signature_verify():
    secret = "apisign_test"
    h = sign_request(secret, "POST", "/v1/refunds", '{"a":1}')
    assert set(h) == {"x-absolutepay-timestamp", "x-absolutepay-nonce", "x-absolutepay-signature"}
    # 128 hex chars = SHA-512
    assert len(h["x-absolutepay-signature"]) == 128
    # recompute and confirm it matches the canonical string
    canon = canonical_request("POST", "/v1/refunds", h["x-absolutepay-timestamp"], h["x-absolutepay-nonce"], '{"a":1}')
    expected = hmac.new(secret.encode(), canon.encode(), hashlib.sha512).hexdigest()
    assert h["x-absolutepay-signature"] == expected


def test_nonce_is_unique_per_call():
    a = sign_request("s", "GET", "/x", "")
    b = sign_request("s", "GET", "/x", "")
    assert a["x-absolutepay-nonce"] != b["x-absolutepay-nonce"]
