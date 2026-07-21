from datetime import datetime, timezone

import pytest

from app.services.decisions import decision_hash
from app.services.exception_queue import (
    OperatorAction,
    ReviewStore,
    add,
    list_pending,
    resolve,
    set_store,
)


class DictReviewStore(ReviewStore):
    def __init__(self):
        self._reviews: dict[str, dict] = {}
        self._next_id = 1

    async def add_pending_review(
        self,
        seller_id: str,
        kwh_contributed: float,
        ai_recommended_price: float,
        recommended_absorption_kwh: float,
        deviation_reason: str,
        direction: str = "local_pool",
        model_version: str = "rules",
    ) -> str:
        review_id = f"review-{self._next_id}"
        self._next_id += 1
        self._reviews[review_id] = {
            "id": review_id,
            "seller_id": seller_id,
            "kwh_contributed": kwh_contributed,
            "ai_recommended_price": ai_recommended_price,
            "recommended_absorption_kwh": recommended_absorption_kwh,
            "deviation_reason": deviation_reason,
            "direction": direction,
            "model_version": model_version,
            "status": "needs_review",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        return review_id

    async def add_auto_approved(
        self,
        seller_id: str,
        kwh_contributed: float,
        ai_recommended_price: float,
        direction: str = "local_pool",
        model_version: str = "rules",
    ) -> str:
        record_id = f"auto-{self._next_id}"
        self._next_id += 1
        decided_at = datetime.now(timezone.utc).isoformat()
        self._reviews[record_id] = {
            "id": record_id,
            "seller_id": seller_id,
            "kwh_contributed": kwh_contributed,
            "ai_recommended_price": ai_recommended_price,
            "direction": direction,
            "model_version": model_version,
            "status": "settled",
            "approval_type": "auto",
            "created_at": decided_at,
            "decided_at": decided_at,
            "decision_hash": decision_hash(
                record_id=record_id,
                seller_id=seller_id,
                ai_recommended_price=ai_recommended_price,
                kwh=kwh_contributed,
                decision="auto",
                final_price=ai_recommended_price,
                decided_at=decided_at,
                model_version=model_version,
            ),
        }
        return record_id

    async def list_pending_reviews(self) -> list[dict]:
        return [
            {
                "id": r["id"],
                "kwh_contributed": r["kwh_contributed"],
                "ai_recommended_price": r["ai_recommended_price"],
                "recommended_absorption_kwh": r["recommended_absorption_kwh"],
                "deviation_reason": r["deviation_reason"],
                "created_at": r["created_at"],
                "direction": r.get("direction", "local_pool"),
            }
            for r in self._reviews.values()
            if r["status"] == "needs_review"
        ]

    async def resolve_review(
        self,
        review_id: str,
        action: OperatorAction,
        reason: str,
        adjusted_price: float | None = None,
    ) -> dict | None:
        if not reason.strip():
            raise ValueError("Operator reason is required")

        review = self._reviews.get(review_id)
        if review is None or review["status"] != "needs_review":
            return None

        now = datetime.now(timezone.utc).isoformat()
        final_price = review["ai_recommended_price"]
        if action == OperatorAction.approve:
            review["status"] = "settled"
        elif action == OperatorAction.adjust:
            review["status"] = "settled"
            if adjusted_price is not None:
                review["adjusted_price"] = adjusted_price
                final_price = adjusted_price
        elif action == OperatorAction.reject:
            review["status"] = "rejected"

        # Mirror the Supabase store: resolve is the decision moment.
        review["decided_at"] = now
        review["decision_hash"] = decision_hash(
            record_id=review_id,
            seller_id=review["seller_id"],
            ai_recommended_price=review["ai_recommended_price"],
            kwh=review["kwh_contributed"],
            decision=action.value,
            final_price=final_price,
            decided_at=now,
            model_version=review.get("model_version", "rules"),
        )

        return {
            "id": review_id,
            "seller_id": review["seller_id"],
            "operator_action": action,
            "operator_reason": reason,
            "adjusted_price": adjusted_price,
            "resolved_at": now,
        }


@pytest.fixture(autouse=True)
def use_dict_store():
    store = DictReviewStore()
    set_store(store)
    yield
    set_store(None)


@pytest.mark.asyncio
async def test_add_and_list_pending():
    id1 = await add(
        seller_id="seller-1", kwh_contributed=50.0,
        ai_recommended_price=0.12, recommended_absorption_kwh=50.0,
        deviation_reason="Price exceeds band",
    )
    id2 = await add(
        seller_id="seller-2", kwh_contributed=30.0,
        ai_recommended_price=0.10, recommended_absorption_kwh=30.0,
        deviation_reason="Absorption exceeds capacity",
    )
    assert id1 is not None
    assert id2 is not None

    pending = await list_pending()
    assert len(pending) == 2


@pytest.mark.asyncio
async def test_resolve_with_reason():
    review_id = await add(
        seller_id="seller-3", kwh_contributed=40.0,
        ai_recommended_price=0.12, recommended_absorption_kwh=40.0,
        deviation_reason="Price exceeds band",
    )

    resolved = await resolve(
        review_id=review_id,
        action=OperatorAction.approve,
        reason="Seasonal demand spike justifies the price",
    )
    assert resolved is not None
    assert resolved["operator_action"] == OperatorAction.approve
    assert resolved["operator_reason"] == "Seasonal demand spike justifies the price"
    assert resolved["resolved_at"] is not None

    pending = await list_pending()
    assert len(pending) == 0


@pytest.mark.asyncio
async def test_resolve_with_adjust():
    review_id = await add(
        seller_id="seller-4", kwh_contributed=60.0,
        ai_recommended_price=0.14, recommended_absorption_kwh=60.0,
        deviation_reason="Price exceeds band",
    )

    resolved = await resolve(
        review_id=review_id,
        action=OperatorAction.adjust,
        reason="Capping at upper band limit",
        adjusted_price=0.105,
    )
    assert resolved is not None
    assert resolved["operator_action"] == OperatorAction.adjust
    assert resolved["adjusted_price"] == 0.105


@pytest.mark.asyncio
async def test_resolve_reject():
    review_id = await add(
        seller_id="seller-5", kwh_contributed=20.0,
        ai_recommended_price=0.09, recommended_absorption_kwh=20.0,
        deviation_reason="Price below band",
    )

    resolved = await resolve(
        review_id=review_id,
        action=OperatorAction.reject,
        reason="Too low — would not incentivize contribution",
    )
    assert resolved is not None
    assert resolved["operator_action"] == OperatorAction.reject


@pytest.mark.asyncio
async def test_resolve_missing_reason_raises():
    review_id = await add(
        seller_id="seller-6", kwh_contributed=10.0,
        ai_recommended_price=0.10, recommended_absorption_kwh=10.0,
        deviation_reason="Test",
    )

    with pytest.raises(ValueError, match="reason is required"):
        await resolve(review_id=review_id, action=OperatorAction.reject, reason="")


@pytest.mark.asyncio
async def test_resolve_nonexistent_review_returns_none():
    result = await resolve(
        review_id="nonexistent",
        action=OperatorAction.approve,
        reason="no-op",
    )
    assert result is None
