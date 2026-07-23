"""Auto-pay tests.

Covers the eligibility rules (threshold, escalation, wallet presence, enable
flag), that eligible lines are paid server-side and recorded with
paid_method='auto', that ineligible lines are left for manual payment, that a
payer failure leaves the line unpaid (rolls forward, never lost), and that the
last auto-payment completes the batch.

Reuses DictSettlementStore from the settlement-cycle suite so auto-pay is
exercised against the same fake the cycle itself uses.
"""
from __future__ import annotations

import pytest

from app.services import autopay, settlement_cycle
from app.services.autopay import MockSettlementPayer, run_autopay, set_payer
from app.services.settlement_cycle import get_due_settlements, run_settlement_cycle

from tests.test_settlement_cycle import DictSettlementStore


@pytest.fixture
def store():
    s = DictSettlementStore()
    settlement_cycle.set_store(s)
    yield s
    settlement_cycle.set_store(None)


@pytest.fixture
def payer():
    p = MockSettlementPayer()
    set_payer(p)
    yield p
    set_payer(None)


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("AUTOPAY_ENABLED", "1")
    monkeypatch.setenv("AUTOPAY_MAX_USD", "5")


async def _open_batch(store, seller_amounts, escalated_sellers=()):
    """Create a due batch with one item per (seller, amount). Optionally force
    a seller's line to escalated via the missed-cycle roll-forward path."""
    for i, (seller, amount) in enumerate(seller_amounts):
        store.seed_seller(seller, wallet=f"W-{seller}")
        store.seed_contribution(seller, kwh=amount * 10, amount=amount)
    await run_settlement_cycle()
    for iid, item in store.items.items():
        if item["seller_id"] in escalated_sellers:
            item["escalated"] = True


@pytest.mark.asyncio
async def test_disabled_by_default(store, payer):
    # No AUTOPAY_ENABLED in the environment.
    await _open_batch(store, [("s1", 1.0)])
    result = await run_autopay()
    assert result == {"enabled": False}
    assert payer.payments == []


@pytest.mark.asyncio
async def test_pays_small_nonescalated_line(store, payer, enabled):
    await _open_batch(store, [("s1", 2.5)])
    result = await run_autopay()

    assert result["paid"] == 1
    assert result["paid_usd"] == pytest.approx(2.5)
    assert result["left_for_manual"] == 0
    assert len(payer.payments) == 1
    assert payer.payments[0]["wallet"] == "W-s1"

    # Paying the only line completes the batch, so inspect the store directly.
    item = next(iter(store.items.values()))
    assert item["paid"] is True
    assert item["paid_method"] == "auto"
    assert item["tx_signature"].startswith("AUTOPAY-SIM-")


@pytest.mark.asyncio
async def test_skips_over_threshold(store, payer, enabled):
    await _open_batch(store, [("big", 12.0)])
    result = await run_autopay()

    assert result["paid"] == 0
    assert result["left_for_manual"] == 1
    assert payer.payments == []
    due = await get_due_settlements()
    assert due["items"][0]["paid"] is False


@pytest.mark.asyncio
async def test_skips_escalated_even_if_small(store, payer, enabled):
    await _open_batch(store, [("s1", 1.0)], escalated_sellers={"s1"})
    result = await run_autopay()

    assert result["paid"] == 0
    assert result["left_for_manual"] == 1
    assert payer.payments == []


@pytest.mark.asyncio
async def test_mixed_batch_pays_only_eligible(store, payer, enabled):
    await _open_batch(
        store,
        [("small", 1.0), ("big", 9.0), ("mid", 4.99)],
        escalated_sellers=set(),
    )
    result = await run_autopay()

    assert result["paid"] == 2  # small + mid
    assert result["left_for_manual"] == 1  # big
    assert result["paid_usd"] == pytest.approx(5.99)

    due = {i["seller_id"]: i for i in (await get_due_settlements())["items"]}
    assert due["small"]["paid"] and due["small"]["paid_method"] == "auto"
    assert due["mid"]["paid"]
    assert not due["big"]["paid"]


@pytest.mark.asyncio
async def test_payer_failure_leaves_line_unpaid(store, enabled):
    class BoomPayer(MockSettlementPayer):
        async def pay(self, wallet, amount_usd):
            raise RuntimeError("rpc down")

    set_payer(BoomPayer())
    try:
        await _open_batch(store, [("s1", 1.0)])
        result = await run_autopay()
        assert result["paid"] == 0
        assert result["failed"] == 1
        assert result["left_for_manual"] == 1
        due = await get_due_settlements()
        assert due["items"][0]["paid"] is False  # rolls forward, never lost
    finally:
        set_payer(None)


@pytest.mark.asyncio
async def test_last_autopay_completes_batch(store, payer, enabled):
    await _open_batch(store, [("s1", 1.0), ("s2", 2.0)])
    await run_autopay()
    # Both lines eligible -> both paid -> batch has no open items left.
    assert await store.get_open_batch() is None
