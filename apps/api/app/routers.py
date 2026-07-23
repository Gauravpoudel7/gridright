import logging
from datetime import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth import (
    AuthError,
    UserProfile,
    get_current_user,
    get_operator_user,
    get_password_changed_seller,
    get_scheduler_or_operator_user,
    get_seller_user,
)
from app.services.seller_dashboard import (
    get_dashboard as seller_get_dashboard,
    get_history as seller_get_history,
)
from app.services.recommender import (
    PoolState,
    RecommendationInput,
    recommend,
)
from app.services.policy_checker import PolicyConfig, PriceRecommendation, check as policy_check
from app.services.exception_queue import (
    OperatorAction,
    add as queue_add,
    add_auto_approved as queue_add_auto_approved,
    list_pending as queue_list_pending,
    resolve as queue_resolve,
)
from app.services.operator_dashboard import (
    get_aggregate_stats as operator_get_stats,
    get_distribution as operator_get_distribution,
    get_feed as operator_get_feed,
    get_pool_status as operator_get_pool_status,
)
from app.services.badge_service import (
    check_and_mint as badges_check_and_mint,
    list_badges as badges_list,
)
from app.services.wallet import require_wallet, require_wallet_for_seller_id
from app.services.meter import (
    MeterAuthError,
    MeterValidationError,
    get_device_for_seller as meter_get_device,
    get_recent_readings as meter_get_recent_readings,
    ingest_reading as meter_ingest_reading,
    register_device as meter_register_device,
)
from app.services.forecast import (
    compute_accuracy as forecast_compute_accuracy,
    get_recent_forecasts as forecast_get_recent,
    run_forecast_job,
)
from app.services.recommender import FleetContext
from app.services.fleet import get_fleet_outlook, get_net_position_kwh
from app.services import onboarding as onboarding_service
from app.services import meter_binding as meter_binding_service
from app.services import wallet_activation as wallet_activation_service
from app.services import password_gate as password_gate_service
from app.services import settlement_cycle as settlement_cycle_service
from app.services import meter_aggregation as meter_aggregation_service
from app.services import autopay as autopay_service

router = APIRouter(prefix="/api/v1")

logger = logging.getLogger(__name__)


class RecommendRequest(BaseModel):
    seller_id: str
    seller_surplus_kwh: float
    time_of_day: str
    pool_current_absorption_kwh: float
    pool_absorption_limit_kwh: float
    pool_current_consumption_kwh: float


class RecommendResponse(BaseModel):
    recommended_price: float
    recommended_absorption_kwh: float
    direction: str
    model_used: str
    policy_decision: str
    deviation_reason: str | None = None
    review_id: str | None = None


class ResolveRequest(BaseModel):
    action: OperatorAction
    reason: str
    adjusted_price: float | None = None


class ResolveResponse(BaseModel):
    review_id: str
    operator_action: OperatorAction
    operator_reason: str
    adjusted_price: float | None = None
    resolved_at: str


@router.post("/recommend", response_model=RecommendResponse)
async def recommend_endpoint(req: RecommendRequest):
    # /recommend is intentionally public — any caller (e.g. a smart meter)
    # may submit a surplus signal. Operator-only gating is applied below to
    # the review-queue endpoints, which approve prices and move money.
    # Phase 9: the seller must have a registered wallet before surplus can
    # be listed/contributed — payouts go to that wallet.
    await require_wallet_for_seller_id(req.seller_id)
    pool = PoolState(
        current_absorption_kwh=req.pool_current_absorption_kwh,
        absorption_limit_kwh=req.pool_absorption_limit_kwh,
        current_consumption_kwh=req.pool_current_consumption_kwh,
    )

    # Fleet feed-in (Phase 4, decision b): pass the aggregated net position as
    # an explicit input. Defensive — any failure (no forecasts yet, store
    # unavailable, test mode without Supabase) degrades to None, which makes
    # the fleet nudge a no-op rather than an error.
    fleet = None
    try:
        net = await get_net_position_kwh()
        if net is not None:
            fleet = FleetContext(net_position_kwh=net)
    except Exception:
        fleet = None

    inp = RecommendationInput(
        seller_surplus_kwh=req.seller_surplus_kwh,
        time_of_day=time.fromisoformat(req.time_of_day),
        pool=pool,
        fleet=fleet,
    )

    recommendation = await recommend(inp)

    policy = PolicyConfig(
        band_width_percentage=5,
        pool_capacity_limit_kwh=10000,
        seller_uplift_percentage=15,
        operator_margin_percentage=5,
        feed_in_tariff_reference=0.10,
    )

    price_rec = PriceRecommendation(
        recommended_price=recommendation.recommended_price,
        recommended_absorption_kwh=recommendation.recommended_absorption_kwh,
        direction=recommendation.direction,
    )

    policy_result = policy_check(price_rec, policy)

    review_id = None
    if policy_result.decision == "needs_review":
        review_id = await queue_add(
            seller_id=req.seller_id,
            kwh_contributed=req.seller_surplus_kwh,
            ai_recommended_price=recommendation.recommended_price,
            recommended_absorption_kwh=recommendation.recommended_absorption_kwh,
            deviation_reason=policy_result.deviation_reason or "",
            direction=recommendation.direction,
            model_version=recommendation.model_used,
        )
    else:
        # Phase 5: an auto-approved recommendation IS the decision — persist
        # the contribution now with its decision_hash so the daily on-chain
        # commitment covers it. Defensive: a storage failure must not turn a
        # valid recommendation into an API error.
        try:
            await queue_add_auto_approved(
                seller_id=req.seller_id,
                kwh_contributed=req.seller_surplus_kwh,
                ai_recommended_price=recommendation.recommended_price,
                direction=recommendation.direction,
                model_version=recommendation.model_used,
            )
        except Exception:
            pass

    return RecommendResponse(
        recommended_price=recommendation.recommended_price,
        recommended_absorption_kwh=recommendation.recommended_absorption_kwh,
        direction=recommendation.direction,
        model_used=recommendation.model_used,
        policy_decision=policy_result.decision,
        deviation_reason=policy_result.deviation_reason,
        review_id=review_id,
    )


# --- Seller dashboard endpoints ---

class DashboardResponse(BaseModel):
    surplus_this_period: float
    cumulative_kwh: float
    total_earned: float
    period_start: str
    period_end: str


class HistoryItem(BaseModel):
    period_start: str
    period_end: str
    kwh_contributed: float
    amount_earned: float
    status: str


@router.get("/sellers/me/dashboard", response_model=DashboardResponse)
async def seller_dashboard(
    seller: UserProfile = Depends(get_seller_user),
):
    data = await seller_get_dashboard(seller.id)
    return DashboardResponse(
        surplus_this_period=data.surplus_this_period,
        cumulative_kwh=data.cumulative_kwh,
        total_earned=data.total_earned,
        period_start=data.period_start,
        period_end=data.period_end,
    )


@router.get("/sellers/me/history")
async def seller_history(
    seller: UserProfile = Depends(get_seller_user),
):
    items = await seller_get_history(seller.id)
    return [
        HistoryItem(
            period_start=item.period_start,
            period_end=item.period_end,
            kwh_contributed=item.kwh_contributed,
            amount_earned=item.amount_earned,
            status=item.status,
        )
        for item in items
    ]


@router.get("/sellers/me/history/export")
async def seller_history_export(
    seller: UserProfile = Depends(get_seller_user),
):
    import csv, io
    items = await seller_get_history(seller.id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["period_start", "period_end", "kwh_contributed", "amount_earned", "status"])
    for item in items:
        writer.writerow([item.period_start, item.period_end, item.kwh_contributed, item.amount_earned, item.status])
    return JSONResponse(
        content=buf.getvalue(),
        headers={"Content-Type": "text/csv", "Content-Disposition": "attachment; filename=seller_history.csv"},
    )


# --- cNFT contribution badges (Phase 8) ---

class BadgeResponse(BaseModel):
    threshold_kwh: float
    label: str
    kwh_at_mint: float
    asset_id: str | None = None
    tx_signature: str | None = None
    mint_status: str
    created_at: str | None = None


@router.get("/sellers/me/badges", response_model=list[BadgeResponse])
async def seller_badges(
    seller: UserProfile = Depends(get_seller_user),
):
    rows = await badges_list(seller.id)
    return [
        BadgeResponse(
            threshold_kwh=float(row["threshold_kwh"]),
            label=row["label"],
            kwh_at_mint=float(row["kwh_at_mint"]),
            asset_id=row.get("asset_id"),
            tx_signature=row.get("tx_signature"),
            mint_status=row["mint_status"],
            created_at=row.get("created_at"),
        )
        for row in rows
    ]


# --- Smart meter ingestion (Phase 2, advanced roadmap) ---

class MeterReadingRequest(BaseModel):
    meter_device_id: str
    reading_at: str  # ISO 8601 timestamp
    generation_kwh: float
    consumption_kwh: float
    grid_export_kwh: float


class MeterRegisterRequest(BaseModel):
    meter_device_id: str


@router.post("/meter-readings", status_code=201)
async def ingest_meter_reading(
    req: MeterReadingRequest,
    authorization: str | None = Header(default=None),
):
    """Device-token-authenticated ingestion — NOT a user-session endpoint.

    The device sends `Authorization: Bearer <device_token>`; the token is
    checked against the registered device's stored hash. surplus_kwh is
    computed by the DB, never accepted from the wire.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing device token")
    token = authorization.removeprefix("Bearer ")
    try:
        row = await meter_ingest_reading(
            meter_device_id=req.meter_device_id,
            device_token=token,
            reading_at=req.reading_at,
            generation_kwh=req.generation_kwh,
            consumption_kwh=req.consumption_kwh,
            grid_export_kwh=req.grid_export_kwh,
        )
    except MeterAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except MeterValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"id": row.get("id"), "seller_id": row.get("seller_id"), "status": "accepted"}


@router.post("/sellers/me/meter-device", status_code=201)
async def register_meter_device(
    req: MeterRegisterRequest,
    seller: UserProfile = Depends(get_seller_user),
):
    """Register (or replace) the caller's smart meter. Returns the plaintext
    device token exactly once — it is stored only as a hash."""
    result = await meter_register_device(seller.id, req.meter_device_id)
    return {
        "meter_device_id": result["meter_device_id"],
        "device_token": result["device_token"],
    }


@router.get("/sellers/me/meter")
async def seller_meter(
    seller: UserProfile = Depends(get_seller_user),
):
    """Device registration state + recent readings for the dashboard."""
    device = await meter_get_device(seller.id)
    readings = await meter_get_recent_readings(seller.id) if device else []
    return {
        "device": (
            {"meter_device_id": device["meter_device_id"]} if device else None
        ),
        "readings": readings,
    }


# --- Surplus forecasting (Phase 3, advanced roadmap) ---

@router.get("/sellers/me/forecasts")
async def seller_forecasts(
    seller: UserProfile = Depends(get_seller_user),
):
    """Recent surplus forecasts for the caller, factors and accuracy included."""
    return await forecast_get_recent(seller.id)


@router.post("/forecasts/run")
async def run_forecasts(
    _operator: UserProfile = Depends(get_scheduler_or_operator_user),
):
    """Run the forecast job + accuracy pass. Operator-triggered, or called by
    an external scheduler bearing the static SCHEDULER_TOKEN — the job itself
    is idempotent per run and cheap thanks to the region weather cache."""
    generated = await run_forecast_job()
    accuracy = await forecast_compute_accuracy()
    return {**generated, "accuracy": accuracy}


# Operator-only routes. Each one explicitly declares its auth requirement via
# the `get_operator_user` dependency — applied per-route, not globally, per
# the architecture doc's "Auth" section.
@router.get("/me")
async def whoami(
    user: UserProfile = Depends(get_current_user),
):
    """Return the authenticated caller's profile (no DB dependency)."""
    return {"id": user.id, "role": user.role, "email": user.email}


@router.get("/reviews/pending")
async def list_pending(
    _operator: UserProfile = Depends(get_operator_user),
):
    return await queue_list_pending()


@router.post("/reviews/{review_id}/resolve", response_model=ResolveResponse)
async def resolve_review(
    review_id: str,
    req: ResolveRequest,
    _operator: UserProfile = Depends(get_operator_user),
):
    await require_wallet(_operator)
    result = await queue_resolve(
        review_id=review_id,
        action=req.action,
        reason=req.reason,
        adjusted_price=req.adjusted_price,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Review not found or already resolved")

    # Phase 8: an approve/adjust settles the contribution, which may push the
    # seller's cumulative settled kWh across a badge threshold. The badge
    # service is idempotent, so calling it on every settlement is safe.
    # Best-effort: the review is already resolved at this point, so a minting
    # failure (unconfigured BADGE_TREE_ADDRESS, RPC outage, ...) must never
    # turn the operator's successful decision into an error response.
    if req.action in (OperatorAction.approve, OperatorAction.adjust) and result.get("seller_id"):
        try:
            await badges_check_and_mint(result["seller_id"])
        except Exception:
            logger.exception(
                "Badge check/mint failed after resolving review %s (seller %s)",
                review_id, result["seller_id"],
            )

    return ResolveResponse(
        review_id=result["id"],
        operator_action=result["operator_action"],
        operator_reason=result["operator_reason"],
        adjusted_price=result.get("adjusted_price"),
        resolved_at=result["resolved_at"],
    )


# --- Operator dashboard endpoints (Phase 7) ---
# Read-side aggregation; operator actions still go through /reviews/{id}/resolve.

class FeedItemResponse(BaseModel):
    id: str
    seller_id: str
    kwh_contributed: float
    ai_recommended_price: float
    final_approved_price: float
    approval_type: str | None = None
    approval_reason: str | None = None
    status: str
    direction: str
    deviation_reason: str | None = None
    created_at: str


class PoolStatusResponse(BaseModel):
    total_kwh_contributed: float
    current_absorption_kwh: float
    absorption_limit_kwh: float
    pending_import_export: list[dict]


class DistributionItemResponse(BaseModel):
    seller_id: str
    total_kwh: float
    contribution_count: int


class AggregateStatsResponse(BaseModel):
    total_kwh_settled: float
    total_payouts: float
    total_spread_captured: float
    average_uplift_percentage: float
    feed_in_tariff_reference: float
    settled_count: int


@router.get("/operator/feed", response_model=list[FeedItemResponse])
async def operator_feed(
    limit: int = 50,
    _operator: UserProfile = Depends(get_operator_user),
):
    items = await operator_get_feed(limit)
    return [FeedItemResponse(**vars(item)) for item in items]


@router.get("/operator/pool", response_model=PoolStatusResponse)
async def operator_pool(
    _operator: UserProfile = Depends(get_operator_user),
):
    pool = await operator_get_pool_status()
    return PoolStatusResponse(
        total_kwh_contributed=pool.total_kwh_contributed,
        current_absorption_kwh=pool.current_absorption_kwh,
        absorption_limit_kwh=pool.absorption_limit_kwh,
        pending_import_export=pool.pending_import_export,
    )


@router.get("/operator/distribution", response_model=list[DistributionItemResponse])
async def operator_distribution(
    _operator: UserProfile = Depends(get_operator_user),
):
    items = await operator_get_distribution()
    return [DistributionItemResponse(**vars(item)) for item in items]


@router.get("/operator/fleet")
async def operator_fleet(
    _operator: UserProfile = Depends(get_operator_user),
):
    """Fleet outlook: aggregated supply forecast + demand signal → net
    position, per-seller breakdown, drift flags, NL summary (Phase 4)."""
    outlook = await get_fleet_outlook()
    return {
        "horizon_hours": outlook.horizon_hours,
        "total_predicted_surplus_kwh": outlook.total_predicted_surplus_kwh,
        "total_expected_demand_kwh": outlook.total_expected_demand_kwh,
        "net_position_kwh": outlook.net_position_kwh,
        "summary": outlook.summary,
        "hourly": [vars(h) for h in outlook.hourly],
        "per_seller": [vars(s) for s in outlook.per_seller],
        "drift_flags": [vars(d) for d in outlook.drift_flags],
    }


@router.get("/operator/stats", response_model=AggregateStatsResponse)
async def operator_stats(
    _operator: UserProfile = Depends(get_operator_user),
):
    stats = await operator_get_stats()
    return AggregateStatsResponse(**vars(stats))


# --- Phase 5: daily on-chain decision commitment ---

class CommitmentRunResponse(BaseModel):
    day: str
    skipped: bool
    reason: str | None = None
    record_count: int | None = None
    merkle_root: str | None = None
    tx_signature: str | None = None
    pda: str | None = None


@router.post("/commitments/run", response_model=CommitmentRunResponse)
async def run_commitment(
    _operator: UserProfile = Depends(get_scheduler_or_operator_user),
):
    """Daily commit, operator-triggered or fired by the external scheduler via
    SCHEDULER_TOKEN. Idempotent: re-running the same day updates the mirror
    but the on-chain account is `init` (immutable)."""
    from app.services.commitments import run_daily_commitment
    from datetime import datetime, timezone
    result = await run_daily_commitment(datetime.now(timezone.utc).date())
    return CommitmentRunResponse(**result)


class VerifyResponse(BaseModel):
    ok: bool
    reason: str
    record_id: str
    merkle_root: str | None = None
    proof_len: int | None = None
    tx_signature: str | None = None
    pda: str | None = None
    explorer_url: str | None = None


@router.get("/contributions/{record_id}/verify", response_model=VerifyResponse)
async def verify_contribution_endpoint(
    record_id: str,
    _operator: UserProfile = Depends(get_operator_user),
):
    """Off-chain verification: regenerate the proof for the record and
    check it folds up to the committed root for the day it was decided.
    Returns the on-chain receipt (tx signature + explorer link) too."""
    from datetime import datetime, timezone
    from app.services.commitments import verify_contribution
    # Phase 5 keeps the record_id, day, and decision_hash side-by-side on the
    # contributions table — but for a one-call verify we look up the record,
    # then dispatch to the day's leaf set. A small Supabase fetch here keeps
    # the contract simple and the indexer external.
    from supabase import create_client
    import os
    client = create_client(
        os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"],
    )
    res = (
        client.table("contributions")
        .select("id, decision_hash, decided_at")
        .eq("id", record_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return VerifyResponse(ok=False, reason="record not found", record_id=record_id)
    row = res.data[0]
    hex_hash = row.get("decision_hash")
    if not hex_hash:
        return VerifyResponse(
            ok=False, reason="record has no decision_hash (pre-Phase 5?)",
            record_id=record_id,
        )
    decided_at = row.get("decided_at")
    if not decided_at:
        return VerifyResponse(
            ok=False, reason="record has no decided_at",
            record_id=record_id,
        )
    day = datetime.fromisoformat(decided_at.replace("Z", "+00:00")).date()
    result = await verify_contribution(record_id, hex_hash, day)
    return VerifyResponse(**result)


# --- Seller onboarding: identity application (spec §3.1) ---
# Public submit/status/resubmit (applicant has no auth user until approval);
# operator review endpoints are operator-gated.

class ApplicationSubmitRequest(BaseModel):
    full_name: str
    dob: str  # ISO date
    ownership_doc_url: str
    gmail: str
    location_text: str


class ApplicationResubmitRequest(BaseModel):
    edit_token: str
    full_name: str | None = None
    dob: str | None = None
    ownership_doc_url: str | None = None
    gmail: str | None = None
    location_text: str | None = None


class ApproveApplicationRequest(BaseModel):
    community_pool_id: str


class RejectApplicationRequest(BaseModel):
    reason: str


@router.post("/applications", status_code=201)
async def submit_application(req: ApplicationSubmitRequest):
    """Public: submit a seller identity application. Returns the one-time
    edit token — the applicant needs it to check status / resubmit."""
    try:
        row = await onboarding_service.submit_application(
            full_name=req.full_name,
            dob=req.dob,
            ownership_doc_url=req.ownership_doc_url,
            gmail=req.gmail,
            location_text=req.location_text,
        )
    except onboarding_service.ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return {
        "id": row["id"],
        "application_status": row["application_status"],
        "edit_token": row["edit_token"],
    }


@router.get("/applications/{application_id}/status")
async def application_status(application_id: str, edit_token: str):
    """Public (token-gated): applicant checks their application status."""
    try:
        return await onboarding_service.get_status(application_id, edit_token)
    except onboarding_service.ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.put("/applications/{application_id}")
async def resubmit_application(
    application_id: str, req: ApplicationResubmitRequest
):
    """Public (token-gated): resubmit a rejected application → submitted."""
    try:
        return await onboarding_service.resubmit_application(
            application_id,
            req.edit_token,
            req.model_dump(exclude={"edit_token"}, exclude_none=True),
        )
    except onboarding_service.ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/operator/applications")
async def operator_list_applications(
    _operator: UserProfile = Depends(get_operator_user),
):
    """Operator: pending (submitted) applications awaiting identity review."""
    return await onboarding_service.list_pending_applications()


@router.post("/operator/applications/{application_id}/approve")
async def operator_approve_application(
    application_id: str,
    req: ApproveApplicationRequest,
    _operator: UserProfile = Depends(get_operator_user),
):
    """Operator: approve identity, assign pool, create auth user + temp
    password (emailed), set must_change_password."""
    try:
        return await onboarding_service.approve_application(
            application_id, req.community_pool_id
        )
    except onboarding_service.ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/operator/applications/{application_id}/reject")
async def operator_reject_application(
    application_id: str,
    req: RejectApplicationRequest,
    _operator: UserProfile = Depends(get_operator_user),
):
    """Operator: reject with a reason; applicant may resubmit."""
    try:
        return await onboarding_service.reject_application(
            application_id, req.reason
        )
    except onboarding_service.ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


# --- Password-change gate (spec §4) ---
# Uses the plain seller dependency (NOT get_password_changed_seller) — this is
# the one seller route reachable while must_change_password is true.

class ChangePasswordRequest(BaseModel):
    new_password: str


@router.post("/sellers/me/change-password")
async def change_password(
    req: ChangePasswordRequest,
    seller: UserProfile = Depends(get_seller_user),
):
    try:
        await password_gate_service.change_password(seller.id, req.new_password)
    except password_gate_service.PasswordChangeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return {"status": "ok", "must_change_password": False}


# --- Meter binding (spec §3.2) --- gated behind the password change.

class MeterBindingRequest(BaseModel):
    pairing_code: str


@router.get("/sellers/me/meter-binding")
async def get_meter_binding(
    seller: UserProfile = Depends(get_password_changed_seller),
):
    try:
        return await meter_binding_service.get_binding(seller.id)
    except meter_binding_service.MeterBindingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/sellers/me/meter-binding")
async def submit_meter_binding(
    req: MeterBindingRequest,
    seller: UserProfile = Depends(get_password_changed_seller),
):
    """Submit a pairing code to bind the seller's meter (spec §3.2)."""
    try:
        return await meter_binding_service.submit_pairing_code(
            seller.id, req.pairing_code
        )
    except meter_binding_service.MeterBindingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


# --- Wallet activation via signed challenge (spec §3.3) --- gated.

class WalletVerifyRequest(BaseModel):
    address: str
    nonce: str
    signature: str


@router.post("/sellers/me/wallet/challenge")
async def wallet_challenge(
    seller: UserProfile = Depends(get_password_changed_seller),
):
    """Issue a single-use nonce for the wallet to sign."""
    try:
        return await wallet_activation_service.issue_challenge(seller.id)
    except wallet_activation_service.WalletActivationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/sellers/me/wallet/verify")
async def wallet_verify(
    req: WalletVerifyRequest,
    seller: UserProfile = Depends(get_password_changed_seller),
):
    """Verify a signed challenge and connect/update the wallet (spec §3.3)."""
    try:
        return await wallet_activation_service.verify_and_connect(
            seller.id, req.address, req.nonce, req.signature
        )
    except wallet_activation_service.WalletActivationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


# --- 30-minute settlement cycles ---
# Batches decision-settled, unpaid contributions into per-seller payouts every
# 30 minutes. Missed-deadline rule: unpaid payouts roll forward (+1 miss),
# escalating at 3 consecutive misses. See services/settlement_cycle.py.

class SettlementPaidRequest(BaseModel):
    tx_signature: str


@router.post("/settlements/run")
async def run_settlements(
    _operator: UserProfile = Depends(get_scheduler_or_operator_user),
):
    """Run one settlement cycle. Fired every 30 minutes by the external
    scheduler bearing SCHEDULER_TOKEN (same pattern as /forecasts/run), or
    manually by an operator. Idempotent-safe: an empty cycle creates nothing;
    re-running early just rolls the window forward.

    Sweeps unaggregated meter readings into contributions FIRST, so surplus
    pushed by meters since the last run is priced and included in this batch.
    """
    try:
        aggregation = await meter_aggregation_service.run_aggregation()
    except Exception:
        # The sweep failing must not block payouts of already-priced
        # contributions; unswept readings are retried next cycle.
        logger.exception("Meter aggregation sweep failed")
        aggregation = {"error": "aggregation_failed"}
    cycle = await settlement_cycle_service.run_settlement_cycle()

    # Auto-pay (opt-in via AUTOPAY_ENABLED): settle small, non-escalated lines
    # of the batch just created; big/escalated lines stay for manual payment.
    # Best-effort — an auto-pay failure must never fail the cycle itself.
    try:
        autopay = await autopay_service.run_autopay()
    except Exception:
        logger.exception("Auto-pay run failed")
        autopay = {"error": "autopay_failed"}

    return {**cycle, "meter_aggregation": aggregation, "autopay": autopay}


@router.get("/operator/settlements")
async def operator_settlements(
    _operator: UserProfile = Depends(get_operator_user),
):
    """Current due batch + per-seller payout lines for the dashboard."""
    return await settlement_cycle_service.get_due_settlements()


@router.post("/operator/settlements/items/{item_id}/paid")
async def settlement_item_paid(
    item_id: str,
    req: SettlementPaidRequest,
    _operator: UserProfile = Depends(get_operator_user),
):
    """Record the on-chain payment for one payout line. The operator pays via
    Phantom client-side; this endpoint records the resulting tx signature and
    completes the batch when the last line is paid."""
    try:
        return await settlement_cycle_service.record_item_paid(
            item_id, req.tx_signature
        )
    except settlement_cycle_service.SettlementCycleError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


async def auth_error_handler(request: Request, exc: AuthError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
