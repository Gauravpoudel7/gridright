import os
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from app.services.decisions import decision_hash


class OperatorAction(str, Enum):
    approve = "approve"
    adjust = "adjust"
    reject = "reject"


class ReviewStore(ABC):
    @abstractmethod
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
        ...

    @abstractmethod
    async def add_auto_approved(
        self,
        seller_id: str,
        kwh_contributed: float,
        ai_recommended_price: float,
        direction: str = "local_pool",
        model_version: str = "rules",
    ) -> str:
        """Record an auto-approved decision (Phase 5): the policy check passed
        with no human step, so the decision moment IS the recommend moment —
        insert the contribution with its decision_hash immediately."""

    @abstractmethod
    async def list_pending_reviews(self) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def resolve_review(
        self,
        review_id: str,
        action: OperatorAction,
        reason: str,
        adjusted_price: float | None = None,
    ) -> dict[str, Any] | None:
        ...


class SupabaseReviewStore(ReviewStore):
    def __init__(self) -> None:
        from supabase import create_client

        self._client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )

    def _current_wallet(self, seller_id: str) -> str | None:
        """Snapshot the seller's wallet at decision/insert time.

        Onboarding spec §3.3: a wallet change applies from the NEXT settlement
        cycle only. Stamping payout_wallet on the row at creation means a later
        profile wallet change never affects a settlement already in flight.
        Best-effort — a lookup failure leaves the column null rather than
        failing the insert.
        """
        try:
            res = (
                self._client.table("profiles")
                .select("wallet_address")
                .eq("id", seller_id)
                .limit(1)
                .execute()
            )
            return res.data[0].get("wallet_address") if res.data else None
        except Exception:
            return None

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
        # The schema requires period_end > period_start. A review-pending
        # contribution covers the current (hourly) settlement window.
        start = datetime.now(timezone.utc)
        payload = {
            "seller_id": seller_id,
            "kwh_contributed": kwh_contributed,
            "period_start": start.isoformat(),
            "period_end": (start + timedelta(hours=1)).isoformat(),
            "ai_recommended_price": ai_recommended_price,
            "final_approved_price": ai_recommended_price,
            "approval_type": None,
            "approval_reason": None,
            "payout_amount": round(ai_recommended_price * kwh_contributed, 6),
            "status": "needs_review",
            "review_reason": deviation_reason,
            "direction": direction,
            # Stored now so the decision_hash computed at resolve time uses
            # the model that actually made the recommendation.
            "model_version": model_version,
            # Snapshot the payout wallet at creation (spec §3.3).
            "payout_wallet": self._current_wallet(seller_id),
        }
        result = self._client.table("contributions").insert(payload).execute()
        return result.data[0]["id"]

    async def add_auto_approved(
        self,
        seller_id: str,
        kwh_contributed: float,
        ai_recommended_price: float,
        direction: str = "local_pool",
        model_version: str = "rules",
    ) -> str:
        start = datetime.now(timezone.utc)
        decided_at = start.isoformat()
        # id generated client-side so the decision_hash (which includes the
        # record id) can be computed in the same insert.
        record_id = str(uuid.uuid4())
        payload = {
            "id": record_id,
            "seller_id": seller_id,
            "kwh_contributed": kwh_contributed,
            "period_start": start.isoformat(),
            "period_end": (start + timedelta(hours=1)).isoformat(),
            "ai_recommended_price": ai_recommended_price,
            "final_approved_price": ai_recommended_price,
            "approval_type": "auto",
            "approval_reason": None,
            "payout_amount": round(ai_recommended_price * kwh_contributed, 6),
            "status": "settled",
            "direction": direction,
            "model_version": model_version,
            "decided_at": decided_at,
            # Snapshot the payout wallet at the decision moment (spec §3.3).
            "payout_wallet": self._current_wallet(seller_id),
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
        self._client.table("contributions").insert(payload).execute()
        return record_id

    async def list_pending_reviews(self) -> list[dict[str, Any]]:
        result = (
            self._client.table("contributions")
            .select("id, seller_id, kwh_contributed, ai_recommended_price, "
                    "review_reason, created_at, direction")
            .eq("status", "needs_review")
            .execute()
        )
        return [
            {
                "id": row["id"],
                "kwh_contributed": float(row["kwh_contributed"]),
                "ai_recommended_price": float(row["ai_recommended_price"]),
                "recommended_absorption_kwh": float(row.get("kwh_contributed", 0)),
                "deviation_reason": row.get("review_reason", ""),
                "created_at": row["created_at"],
                "direction": row.get("direction", "local_pool"),
            }
            for row in result.data
        ]

    async def resolve_review(
        self,
        review_id: str,
        action: OperatorAction,
        reason: str,
        adjusted_price: float | None = None,
    ) -> dict[str, Any] | None:
        if not reason.strip():
            raise ValueError("Operator reason is required")

        fetch = (
            self._client.table("contributions")
            .select("id, seller_id, kwh_contributed, ai_recommended_price, model_version")
            .eq("id", review_id)
            .eq("status", "needs_review")
            .execute()
        )
        if not fetch.data:
            return None
        row = fetch.data[0]
        kwh_contributed = float(row["kwh_contributed"])
        seller_id = row["seller_id"]
        ai_price = float(row["ai_recommended_price"])
        model_version = row.get("model_version") or "rules"

        now = datetime.now(timezone.utc).isoformat()
        updates: dict[str, Any] = {
            "approval_type": "human",
            "approval_reason": reason,
            "reviewed_at": now,
        }

        final_price = ai_price
        if action == OperatorAction.approve:
            updates["status"] = "settled"
        elif action == OperatorAction.adjust:
            updates["status"] = "settled"
            if adjusted_price is not None:
                updates["adjusted_price"] = adjusted_price
                updates["final_approved_price"] = adjusted_price
                # payout_amount was seeded from the AI price at insert time;
                # re-derive it so every payout traces back to the final
                # approved price per the architecture doc's payout rule.
                updates["payout_amount"] = round(adjusted_price * kwh_contributed, 6)
                final_price = adjusted_price
        elif action == OperatorAction.reject:
            updates["status"] = "rejected"

        # Phase 5: this is the decision moment for a human-reviewed record —
        # hash it now so the daily commitment covers it.
        updates["decided_at"] = now
        updates["decision_hash"] = decision_hash(
            record_id=str(review_id),
            seller_id=str(seller_id),
            ai_recommended_price=ai_price,
            kwh=kwh_contributed,
            decision=action.value,
            final_price=final_price,
            decided_at=now,
            model_version=model_version,
        )

        self._client.table("contributions").update(updates).eq("id", review_id).execute()

        return {
            "id": review_id,
            "seller_id": seller_id,
            "operator_action": action,
            "operator_reason": reason,
            "adjusted_price": adjusted_price,
            "resolved_at": now,
        }


_store: ReviewStore | None = None


def _get_store() -> ReviewStore:
    global _store
    if _store is None:
        _store = SupabaseReviewStore()
    return _store


def set_store(store: ReviewStore) -> None:
    global _store
    _store = store


async def add(
    seller_id: str,
    kwh_contributed: float,
    ai_recommended_price: float,
    recommended_absorption_kwh: float,
    deviation_reason: str,
    direction: str = "local_pool",
    model_version: str = "rules",
) -> str:
    return await _get_store().add_pending_review(
        seller_id, kwh_contributed, ai_recommended_price,
        recommended_absorption_kwh, deviation_reason, direction,
        model_version,
    )


async def add_auto_approved(
    seller_id: str,
    kwh_contributed: float,
    ai_recommended_price: float,
    direction: str = "local_pool",
    model_version: str = "rules",
) -> str:
    return await _get_store().add_auto_approved(
        seller_id, kwh_contributed, ai_recommended_price, direction,
        model_version,
    )


async def list_pending() -> list[dict[str, Any]]:
    return await _get_store().list_pending_reviews()


async def resolve(
    review_id: str,
    action: OperatorAction,
    reason: str,
    adjusted_price: float | None = None,
) -> dict[str, Any] | None:
    return await _get_store().resolve_review(review_id, action, reason, adjusted_price)
