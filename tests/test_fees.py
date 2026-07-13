"""fees.preview — chain param (platform-179)."""

import pytest

from absolutepay import AbsolutePayError
from tests.test_client import client, install


def test_forwards_chain_for_withdrawal(monkeypatch):
    cap = install(monkeypatch, payload={"amount": "4.000000", "currency": "USDT", "paymentType": "WITHDRAWAL", "fee": "0.10", "net": "3.90"})
    client().fees.preview(amount="4.000000", currency="USDT", payment_type="WITHDRAWAL", chain="MATIC")
    assert cap["url"] == "https://api.test/v1/fees/preview?amount=4.000000&currency=USDT&paymentType=WITHDRAWAL&chain=MATIC"


@pytest.mark.parametrize("payment_type", ["WITHDRAWAL", "PAYOUT"])
def test_raises_chain_required_client_side(monkeypatch, payment_type):
    cap = install(monkeypatch)  # would raise KeyError if a request were made
    with pytest.raises(AbsolutePayError) as ei:
        client().fees.preview(amount="4", currency="USDT", payment_type=payment_type)
    assert ei.value.code == "chain_required"
    assert ei.value.status == 400
    assert cap == {}  # no HTTP request was made


def test_omits_chain_for_pay_in(monkeypatch):
    cap = install(monkeypatch, payload={"amount": "4", "currency": "USDT", "paymentType": "CHECKOUT", "fee": "0.04", "net": "3.96"})
    client().fees.preview(amount="4", currency="USDT")
    assert cap["url"] == "https://api.test/v1/fees/preview?amount=4&currency=USDT"
