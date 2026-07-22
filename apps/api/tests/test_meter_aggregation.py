"""Meter readings → contributions bridge (meter_aggregation service).

Raw meter telemetry must become priced contributions via the same
recommend/policy pipeline as POST /recommend, exactly once per reading.
"""
import pytest

from app.services import exception_queue, meter_aggregation
from app.services.meter_aggregation import AggregationStore, run_aggregation

from tests.test_exception_queue import DictReviewStore


class DictAggStore(AggregationStore):
    def __init__(self):
        self.readings: dict[str, dict] = {}
        self.pool = {"current_absorption_kwh": 0.0, "absorption_limit_kwh": 10000.0}
        self._next = 1

    def seed_reading(self, seller_id: str, grid_export_kwh: float) -> str:
        rid = f"r-{self._next}"
        self._next += 1
        self.readings[rid] = {
            "id": rid,
            "seller_id": seller_id,
            "grid_export_kwh": grid_export_kwh,
            "aggregated": False,
        }
        return rid

    async def get_unaggregated(self):
        return [
            {k: r[k] for k in ("id", "seller_id", "grid_export_kwh")}
            for r in self.readings.values()
            if not r["aggregated"]
        ]

    async def mark_aggregated(self, reading_ids):
        for rid in reading_ids:
            self.readings[rid]["aggregated"] = True

    async def get_pool_state(self):
        return self.pool


@pytest.fixture
def agg_store():
    s = DictAggStore()
    meter_aggregation.set_store(s)
    yield s
    meter_aggregation.set_store(None)


@pytest.fixture
def review_store():
    s = DictReviewStore()
    exception_queue.set_store(s)
    yield s
    exception_queue.set_store(None)


def _rows(review_store, status):
    return [r for r in review_store._reviews.values() if r["status"] == status]


async def test_readings_become_review_queue_entries_per_seller(
    agg_store, review_store
):
    """Local-pool surplus is priced at tariff + uplift, which sits outside the
    ±5% policy band — so aggregated meter surplus lands in the OPERATOR REVIEW
    QUEUE (AI recommends, operator decides), one line per seller, with the
    summed kWh. On approve it becomes a settled contribution and the next
    settlement cycle batches it for payout."""
    agg_store.seed_reading("s1", 0.30)
    agg_store.seed_reading("s1", 0.25)
    agg_store.seed_reading("s2", 0.60)

    summary = await run_aggregation()

    assert summary["readings"] == 3
    assert summary["sellers"] == 2
    assert summary["needs_review"] == 2
    assert summary["contributions"] == 0

    pending = {r["seller_id"]: r for r in _rows(review_store, "needs_review")}
    assert pending["s1"]["kwh_contributed"] == pytest.approx(0.55)
    assert pending["s2"]["kwh_contributed"] == pytest.approx(0.60)
    assert pending["s1"]["ai_recommended_price"] > 0


async def test_readings_swept_exactly_once(agg_store, review_store):
    agg_store.seed_reading("s1", 0.5)
    await run_aggregation()

    # Second run: nothing left to sweep, no duplicate queue entry.
    summary = await run_aggregation()
    assert summary == {
        "readings": 0, "sellers": 0, "contributions": 0, "needs_review": 0,
        "carried_forward": 0,
    }
    assert len(_rows(review_store, "needs_review")) == 1


async def test_sub_threshold_surplus_carries_forward(agg_store, review_store):
    """Below MIN_AGGREGATION_KWH a seller's export is real but too small to be
    worth an operator review line. It must NOT be priced, queued, or swept —
    the readings stay unaggregated and keep accruing until a later cycle pushes
    the running total over the threshold, at which point it goes through in one
    consolidated line."""
    agg_store.seed_reading("s1", 0.20)
    agg_store.seed_reading("s1", 0.15)  # running total 0.35 < 0.5

    summary = await run_aggregation()

    assert summary["sellers"] == 1
    assert summary["needs_review"] == 0
    assert summary["contributions"] == 0
    assert summary["carried_forward"] == 1
    # Left unswept so they accumulate — nothing reached the operator.
    assert not any(r["aggregated"] for r in agg_store.readings.values())
    assert review_store._reviews == {}

    # Next cycle a new reading tips the running total over 0.5 → one line.
    agg_store.seed_reading("s1", 0.30)  # total now 0.65 ≥ 0.5
    summary = await run_aggregation()

    assert summary["needs_review"] == 1
    assert summary["carried_forward"] == 0
    assert all(r["aggregated"] for r in agg_store.readings.values())
    pending = _rows(review_store, "needs_review")
    assert len(pending) == 1
    assert pending[0]["kwh_contributed"] == pytest.approx(0.65)


async def test_zero_export_marked_but_no_contribution(agg_store, review_store):
    agg_store.seed_reading("s1", 0.0)
    agg_store.seed_reading("s1", 0.0)

    summary = await run_aggregation()

    assert summary["contributions"] == 0
    assert summary["needs_review"] == 0
    assert all(r["aggregated"] for r in agg_store.readings.values())
    assert review_store._reviews == {}


async def test_failed_seller_readings_retried_next_run(agg_store, review_store):
    """A pricing/storage failure leaves that seller's readings unswept."""
    agg_store.seed_reading("s1", 0.5)

    class BrokenStore(DictReviewStore):
        async def add_pending_review(self, *a, **kw):
            raise RuntimeError("db down")

    exception_queue.set_store(BrokenStore())
    summary = await run_aggregation()
    assert summary["needs_review"] == 0
    assert not agg_store.readings["r-1"]["aggregated"]  # left for retry

    # Store recovers → next run sweeps it.
    exception_queue.set_store(review_store)
    summary = await run_aggregation()
    assert summary["needs_review"] == 1
    assert agg_store.readings["r-1"]["aggregated"]
