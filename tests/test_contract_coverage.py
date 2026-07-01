"""Contract-first drift guard.

Loads the vendored customer OpenAPI spec and asserts that every operationId is either
mapped to a real, callable SDK method (OP_MAP) or explicitly listed as intentionally
unwrapped (UNWRAPPED). A new operation added to the contract fails this test until it is
either wrapped or consciously deferred — so the SDK can never silently drift from the API.

Refresh the fixture from the platform on contract changes:
    cp <platform>/packages/contracts/openapi/absolutepay-customer.json tests/openapi/
"""

import json
from pathlib import Path

import pytest

from absolutepay import AbsolutePay

SPEC = Path(__file__).parent / "openapi" / "absolutepay-customer.json"

# operationId -> dotted attribute path of the wrapping method on an AbsolutePay instance.
OP_MAP = {
    "getBalances": "balances.list",
    "getBalanceSummary": "balances.summary",
    "previewFee": "fees.preview",
    "createCheckout": "payments.create_checkout",
    "getCheckout": "payments.get_checkout",
    "createRefund": "refunds.create",
    "getRefund": "refunds.get",
    "createPayout": "payouts.create",
    "listWithdrawOptions": "payouts.options",
    "getPayout": "payouts.get",
    "previewConversion": "conversions.quote",
    "executeConversion": "conversions.execute",
    "createSubscriptionPlan": "subscriptions.create_plan",
    "listSubscriptionPlans": "subscriptions.list_plans",
    "createSubscription": "subscriptions.create",
    "listSubscriptions": "subscriptions.list",
    "listDeductions": "subscriptions.deductions",
    "cancelSubscription": "subscriptions.cancel",
    "createCheckoutLink": "invoices.create_checkout",
    "createInvoice": "invoices.create",
    "listInvoices": "invoices.list",
    "getCheckoutStats": "invoices.stats",
    "pauseInvoice": "invoices.pause",
    "voidInvoice": "invoices.void",
    "getPublicInvoice": "invoices.public.get",
    "listInvoiceAssets": "invoices.public.assets",
    "quoteInvoicePayIn": "invoices.public.quote",
    "createInvoiceDeposit": "invoices.public.deposit",
    "getInvoiceStatus": "invoices.public.status",
    "listOffRampCountries": "offramp.countries",
    "listOffRampBanks": "offramp.banks",
    "offRampQuote": "offramp.quote",
    "offRampWithdraw": "offramp.withdraw",
    "listOffRampOrders": "offramp.orders",
    "listGiftTemplates": "giftcards.templates",
    "createGiftCard": "giftcards.create",
    "listGiftCards": "giftcards.list",
    "getGiftCard": "giftcards.get",
    "listTransactions": "transactions.list",
}

# Operations deliberately NOT wrapped in this first cut (documented gaps, not drift).
UNWRAPPED = {
    "trackInvoiceOpen",          # analytics beacon; payer page only
    "registerOffRampBank",       # bank onboarding (docs + review flow)
    "deleteOffRampBank",
    "submitOffRampBankMaterials",
    "listReconciliationPayments",
    "listReconciliationWithdrawals",
    "listDepositChains",
    "createDepositAddress",
}


def _spec_operation_ids() -> set[str]:
    spec = json.loads(SPEC.read_text())
    ids = set()
    for path_item in spec["paths"].values():
        for method, op in path_item.items():
            if method in ("get", "post", "put", "patch", "delete") and "operationId" in op:
                ids.add(op["operationId"])
    return ids


def _resolve(client, dotted: str):
    obj = client
    for part in dotted.split("."):
        obj = getattr(obj, part)
    return obj


def test_every_operation_is_mapped_or_deferred():
    ids = _spec_operation_ids()
    known = set(OP_MAP) | UNWRAPPED
    missing = ids - known
    assert not missing, f"contract has operations neither wrapped nor deferred: {sorted(missing)}"


def test_no_operation_double_listed():
    overlap = set(OP_MAP) & UNWRAPPED
    assert not overlap, f"operations listed as both wrapped and deferred: {sorted(overlap)}"


def test_map_targets_do_not_reference_stale_operations():
    # Every OP_MAP / UNWRAPPED key must still exist in the contract.
    ids = _spec_operation_ids()
    stale = (set(OP_MAP) | UNWRAPPED) - ids
    assert not stale, f"OP_MAP/UNWRAPPED reference operations no longer in the contract: {sorted(stale)}"


@pytest.mark.parametrize("op_id,dotted", sorted(OP_MAP.items()))
def test_mapped_method_exists_and_is_callable(op_id, dotted):
    client = AbsolutePay("ap_test_x", base_url="http://localhost")
    method = _resolve(client, dotted)
    assert callable(method), f"{op_id} -> {dotted} is not callable"
