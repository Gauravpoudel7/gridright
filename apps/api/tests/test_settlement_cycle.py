"""30-minute settlement cycle tests.

Covers: batch creation grouping per seller, settlement exclusion
(wallet_status != active), the missed-deadline roll-forward rule (+1 miss per
cycle, amounts accumulate, sellers never lose money), escalation at 3
consecutive misses, batch completion on last payment, payout_wallet snapshot
stability across a mid-cycle wallet change, and the API endpoints.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import settlement_cycle
from app.services.settlement_cycle import (
    CYCLE_MINUTES,
    ESCALATION_MISS_THRESHOLD,
    SettlementStore,
    get_due_settlements,
    record_item_paid,
    run_settlement_cycle,
)


class DictSettlementStore(SettlementStore):
    def __init__(self):
        self.batches: dict[str, dict] = {}
        self.items: dict[str, dict] = {}
        self.contributions: dict[str, dict] = {}  # id -> row
        self.profiles: dict[str, dict] = {}       # seller_id -> profile
        self._n = 0

    def _id(self, prefix):
        self._n += 1
        return f"{prefix}-{self._n}"

    # -- seeding helpers ------------------------------------------------------
    def seed_seller(self, seller_id, wallet_status="active", wallet="WALLET-1"):
        self.profiles[seller_id] = {
            "id": seller_id, "wallet_status": wallet_status,
            "wallet_address": wallet,
        }

    def seed_contribution(self, seller_id, kwh, amount, status="settled",
                          payout_wallet=None, tx_signature=None):
        cid = self._id("c")
        self.contributions[cid] = {
            "id": cid, "seller_id": seller_id, "kwh_contributed": kwh,
            "payout_amount": amount, "status": status,
            "payout_wallet": payout_wallet, "tx_signature": tx_signature,
            "settlement_item_id": None,
        }
        return cid

    # -- store interface ------------------------------------------------------
    async def get_open_batch(self):
        for b in self.batches.values():
            if b["status"] == "due":
                return dict(b)
        return None

    async def get_items(self, batch_id):
        return [dict(i) for i in self.items.values() if i["batch_id"] == batch_id]

    async def close_batch(self, batch_id, status, completed_at=None):
        self.batches[batch_id]["status"] = status
        if completed_at:
            self.batches[batch_id]["completed_at"] = completed_at

    async def create_batch(self, cycle_start, due_at, escalated):
        bid = self._id("b")
        self.batches[bid] = {
            "id": bid, "cycle_start": cycle_start, "due_at": due_at,
            "status": "due", "escalated": escalated, "completed_at": None,
        }
        return bid

    async def create_item(self, item):
        iid = self._id("i")
        self.items[iid] = {**item, "id": iid, "paid": False,
                           "tx_signature": None, "paid_at": None,
                           "paid_method": None}
        return iid

    async def get_eligible_contributions(self):
        out = []
        for row in self.contributions.values():
            prof = self.profiles.get(row["seller_id"])
            if not prof or prof["wallet_status"] != "active":
                continue
            if row["status"] != "settled" or row["tx_signature"] is not None:
                continue
            if row["settlement_item_id"] is not None:
                continue
            out.append({
                "id": row["id"], "seller_id": row["seller_id"],
                "kwh_contributed": row["kwh_contributed"],
                "payout_amount": row["payout_amount"],
                "payout_wallet": row["payout_wallet"] or prof["wallet_address"],
            })
        return out

    async def assign_contributions(self, contribution_ids, item_id):
        for cid in contribution_ids:
            self.contributions[cid]["settlement_item_id"] = item_id

    async def reassign_item_contributions(self, old_item_id, new_item_id):
        for row in self.contributions.values():
            if row["settlement_item_id"] == old_item_id:
                row["settlement_item_id"] = new_item_id

    async def get_item(self, item_id):
        row = self.items.get(item_id)
        return dict(row) if row else None

    async def mark_item_paid(self, item_id, tx_signature, paid_at, paid_method="manual"):
        self.items[item_id].update(
            paid=True, tx_signature=tx_signature, paid_at=paid_at,
            paid_method=paid_method,
        )
        for row in self.contributions.values():
            if row["settlement_item_id"] == item_id:
                row["tx_signature"] = tx_signature


@pytest.fixture
def store():
    s = DictSettlementStore()
    settlement_cycle.set_store(s)
    yield s
    settlement_cycle.set_store(None)


@pytest.mark.asyncio
async def test_run_groups_per_seller(store):
    store.seed_seller("s1", wallet="W1")
    store.seed_seller("s2", wallet="W2")
    store.seed_contribution("s1", 10, 1.0)
    store.seed_contribution("s1", 5, 0.5)
    store.seed_contribution("s2", 8, 0.8)

    result = await run_settlement_cycle()
    assert result["skipped"] is False
    assert result["item_count"] == 2
    assert result["total_amount"] == pytest.approx(2.3)

    due = await get_due_settlements()
    by_seller = {i["seller_id"]: i for i in due["items"]}
    assert by_seller["s1"]["total_kwh"] == pytest.approx(15)
    assert by_seller["s1"]["total_amount"] == pytest.approx(1.5)
    assert by_seller["s1"]["contribution_count"] == 2
    assert by_seller["s1"]["payout_wallet"] == "W1"
    assert by_seller["s2"]["total_amount"] == pytest.approx(0.8)
    # Contributions are linked to their items
    assert all(
        c["settlement_item_id"] is not None
        for c in store.contributions.values()
    )


@pytest.mark.asyncio
async def test_excludes_inactive_wallets_and_undecided_rows(store):
    store.seed_seller("active", wallet="W1")
    store.seed_seller("inactive", wallet_status="not_connected")
    store.seed_contribution("active", 10, 1.0)
    store.seed_contribution("inactive", 99, 9.9)          # excluded: wallet
    store.seed_contribution("active", 3, 0.3, status="needs_review")  # undecided
    store.seed_contribution("active", 4, 0.4, tx_signature="sig")     # already paid

    result = await run_settlement_cycle()
    assert result["item_count"] == 1
    due = await get_due_settlements()
    assert due["items"][0]["total_amount"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_empty_cycle_creates_no_batch(store):
    result = await run_settlement_cycle()
    assert result["skipped"] is True
    assert result["batch_id"] is None
    assert store.batches == {}


@pytest.mark.asyncio
async def test_paying_all_items_completes_batch(store):
    store.seed_seller("s1")
    store.seed_contribution("s1", 10, 1.0)
    await run_settlement_cycle()
    due = await get_due_settlements()
    item_id = due["items"][0]["id"]

    result = await record_item_paid(item_id, "tx-sig-1")
    assert result["batch_completed"] is True
    batch_id = store.items[item_id]["batch_id"]
    assert store.batches[batch_id]["status"] == "completed"
    # tx stamped through to the contributions
    assert all(c["tx_signature"] == "tx-sig-1" for c in store.contributions.values())
    # Nothing due anymore
    assert (await get_due_settlements())["batch"] is None


@pytest.mark.asyncio
async def test_missed_deadline_rolls_forward_and_accumulates(store):
    """THE RULE: an unpaid batch rolls into the next cycle — amounts carry,
    misses increment, the seller never loses the payout."""
    store.seed_seller("s1", wallet="W1")
    store.seed_contribution("s1", 10, 1.0)
    first = await run_settlement_cycle()

    # Deadline missed (nothing paid). New surplus arrives meanwhile.
    store.seed_contribution("s1", 6, 0.6)
    second = await run_settlement_cycle()

    assert second["rolled_over"] == 1
    assert store.batches[first["batch_id"]]["status"] == "rolled_over"

    due = await get_due_settlements()
    assert len(due["items"]) == 1
    item = due["items"][0]
    assert item["missed_cycles"] == 1
    assert item["total_amount"] == pytest.approx(1.6)   # accumulated, not lost
    assert item["total_kwh"] == pytest.approx(16)
    assert item["escalated"] is False
    # All contributions re-pointed at the new item
    assert all(
        c["settlement_item_id"] == item["id"]
        for c in store.contributions.values()
    )


@pytest.mark.asyncio
async def test_escalation_after_three_missed_cycles(store):
    store.seed_seller("s1")
    store.seed_contribution("s1", 10, 1.0)
    await run_settlement_cycle()

    for cycle in range(1, ESCALATION_MISS_THRESHOLD + 1):
        result = await run_settlement_cycle()

    due = await get_due_settlements()
    item = due["items"][0]
    assert item["missed_cycles"] == ESCALATION_MISS_THRESHOLD
    assert item["escalated"] is True
    assert due["batch"]["escalated"] is True
    assert result["escalated"] == 1


@pytest.mark.asyncio
async def test_partial_payment_only_unpaid_rolls(store):
    store.seed_seller("s1", wallet="W1")
    store.seed_seller("s2", wallet="W2")
    store.seed_contribution("s1", 10, 1.0)
    store.seed_contribution("s2", 8, 0.8)
    await run_settlement_cycle()

    due = await get_due_settlements()
    s1_item = next(i for i in due["items"] if i["seller_id"] == "s1")
    await record_item_paid(s1_item["id"], "tx-s1")

    result = await run_settlement_cycle()
    assert result["rolled_over"] == 1
    due = await get_due_settlements()
    assert len(due["items"]) == 1
    assert due["items"][0]["seller_id"] == "s2"
    assert due["items"][0]["missed_cycles"] == 1
    # s1's paid contribution is not re-batched
    s1_rows = [c for c in store.contributions.values() if c["seller_id"] == "s1"]
    assert all(c["tx_signature"] == "tx-s1" for c in s1_rows)


@pytest.mark.asyncio
async def test_carried_item_keeps_original_payout_wallet(store):
    """Spec §3.3: a wallet change never redirects an in-flight payout — the
    carried item keeps the wallet it was computed against."""
    store.seed_seller("s1", wallet="OLD-WALLET")
    store.seed_contribution("s1", 10, 1.0)
    await run_settlement_cycle()

    # Seller changes wallet mid-cycle; deadline is then missed.
    store.profiles["s1"]["wallet_address"] = "NEW-WALLET"
    await run_settlement_cycle()

    due = await get_due_settlements()
    assert due["items"][0]["payout_wallet"] == "OLD-WALLET"


@pytest.mark.asyncio
async def test_record_paid_validations(store):
    store.seed_seller("s1")
    store.seed_contribution("s1", 10, 1.0)
    await run_settlement_cycle()
    item_id = (await get_due_settlements())["items"][0]["id"]

    with pytest.raises(settlement_cycle.SettlementCycleError) as exc:
        await record_item_paid("missing-item", "tx")
    assert exc.value.status_code == 404

    with pytest.raises(settlement_cycle.SettlementCycleError) as exc:
        await record_item_paid(item_id, "   ")
    assert exc.value.status_code == 422

    await record_item_paid(item_id, "tx-1")
    with pytest.raises(settlement_cycle.SettlementCycleError) as exc:
        await record_item_paid(item_id, "tx-2")   # double-pay guard
    assert exc.value.status_code == 409


# --- endpoint wiring ---------------------------------------------------------

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_endpoints_run_and_record(client, store):
    """Endpoints wire to the service (conftest's permissive operator verifier
    covers auth; scheduler-token auth is covered by the forecast tests)."""
    store.seed_seller("s1")
    store.seed_contribution("s1", 10, 1.0)

    run = client.post("/api/v1/settlements/run",
                      headers={"Authorization": "Bearer op"})
    assert run.status_code == 200
    assert run.json()["item_count"] == 1

    due = client.get("/api/v1/operator/settlements",
                     headers={"Authorization": "Bearer op"})
    assert due.status_code == 200
    item_id = due.json()["items"][0]["id"]
    assert due.json()["items"][0]["missed_cycles"] == 0

    paid = client.post(
        f"/api/v1/operator/settlements/items/{item_id}/paid",
        json={"tx_signature": "tx-endpoint"},
        headers={"Authorization": "Bearer op"},
    )
    assert paid.status_code == 200
    assert paid.json()["batch_completed"] is True


# -- deploy-skew guard --------------------------------------------------------

class _SkewTable:
    """Stub Supabase table: UPDATEs touching paid_method raise like PostgREST
    does when the 20250723000016_autopay migration hasn't been applied yet."""

    def __init__(self, log):
        self._log = log
        self._payload = None

    def update(self, payload):
        self._payload = payload
        return self

    def eq(self, *_):
        return self

    def execute(self):
        if self._payload and "paid_method" in self._payload:
            raise RuntimeError(
                "Could not find the 'paid_method' column of 'settlement_items'"
            )
        self._log.append(self._payload)
        return self


def test_mark_item_paid_survives_missing_paid_method_column():
    """API deployed before the autopay migration: the paid_method stamp fails,
    but the payment itself must still be recorded (retry without the column)."""
    from app.services.settlement_cycle import SupabaseSettlementStore
    import asyncio

    store = SupabaseSettlementStore.__new__(SupabaseSettlementStore)  # skip __init__
    writes: list[dict] = []
    store._client = type("C", (), {"table": lambda self, name: _SkewTable(writes)})()

    asyncio.run(store.mark_item_paid("item-1", "tx-sig", "2026-07-23T00:00:00Z", "auto"))

    # Two successful writes: the degraded item update + the contributions stamp.
    item_write = writes[0]
    assert item_write["paid"] is True
    assert item_write["tx_signature"] == "tx-sig"
    assert "paid_method" not in item_write
