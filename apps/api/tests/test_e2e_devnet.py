"""Phase 9 — end-to-end regression scenarios, settled on devnet.

Each scenario drives the real API flow (recommend → policy check →
operator resolution) with in-memory stores, then settles the outcome
on devnet through the deployed Anchor program via
programs/gridright/scripts/settle-period.ts.

Scenarios (per phases.md Phase 9):
  1. a seller contributing
  2. an auto-approved settlement
  3. a flagged exception resolved by the operator
  4. an import scenario
  5. an export scenario
  6. a cNFT mint trigger

Devnet scenarios are marked `devnet` and skipped unless RUN_DEVNET_E2E=1
(they cost SOL and need a funded operator wallet + network access):

    RUN_DEVNET_E2E=1 pytest tests/test_e2e_devnet.py -v
"""
from __future__ import annotations

import json
import os
import subprocess
import time as time_mod
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import badge_service
from app.services.recommender import RecommendationResult

RUN_DEVNET = os.environ.get("RUN_DEVNET_E2E") == "1"
devnet = pytest.mark.skipif(
    not RUN_DEVNET, reason="devnet E2E disabled (set RUN_DEVNET_E2E=1)"
)

SCRIPT_DIR = Path(__file__).resolve().parents[3] / "programs" / "gridright"

client = TestClient(app)

_BODY = {
    "seller_id": "e2e-seller",
    "seller_surplus_kwh": 50.0,
    "time_of_day": "14:00:00",
    "pool_current_absorption_kwh": 1000,
    "pool_absorption_limit_kwh": 10000,
    "pool_current_consumption_kwh": 500,
}

# period_start must be unique per (seller, period) PDA — devnet state
# persists across runs, so derive it from wall-clock seconds and offset
# per scenario to avoid collisions within a run.
_RUN_BASE = int(time_mod.time())


def settle_on_devnet(
    kwh: int, price: int, payout: int, direction: str, record: dict, period_offset: int
) -> dict:
    """Submit a settle_period tx to devnet and return the parsed result."""
    proc = subprocess.run(
        [
            "npx", "tsx", "scripts/settle-period.ts",
            "--kwh", str(kwh),
            "--price", str(price),
            "--payout", str(payout),
            "--direction", direction,
            "--record", json.dumps(record),
            "--period-start", str(_RUN_BASE + period_offset),
        ],
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
        timeout=120,
        shell=(os.name == "nt"),
    )
    assert proc.returncode == 0, f"settle-period failed: {proc.stderr[-800:]}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _recommend(body: dict, mock_result: RecommendationResult | None = None) -> dict:
    """POST /recommend, optionally forcing the AI result via the rules mock."""
    if mock_result is None:
        resp = client.post("/api/v1/recommend", json=body)
    else:
        with patch("app.routers.recommend", return_value=mock_result):
            resp = client.post("/api/v1/recommend", json=body)
    assert resp.status_code == 200
    return resp.json()


def _resolve(review_id: str, action: str, reason: str, adjusted_price: float | None = None) -> dict:
    payload: dict = {"action": action, "reason": reason}
    if adjusted_price is not None:
        payload["adjusted_price"] = adjusted_price
    resp = client.post(
        f"/api/v1/reviews/{review_id}/resolve",
        json=payload,
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    return resp.json()


@devnet
class TestE2EDevnet:
    def test_1_seller_contributing(self):
        """A seller's surplus flows through recommend → policy check."""
        data = _recommend(
            _BODY,
            RecommendationResult(
                recommended_price=0.102, recommended_absorption_kwh=50.0,
                direction="local_pool", model_used="rules",
            ),
        )
        assert data["direction"] == "local_pool"
        assert data["recommended_price"] > 0
        assert data["policy_decision"] in ("auto-approved", "needs_review")

    def test_2_auto_approved_settlement(self):
        """In-band recommendation auto-approves and settles on devnet."""
        data = _recommend(
            _BODY,
            RecommendationResult(
                recommended_price=0.102, recommended_absorption_kwh=50.0,
                direction="local_pool", model_used="rules",
            ),
        )
        assert data["policy_decision"] == "auto-approved"
        assert data["review_id"] is None

        record = {
            "seller": "e2e-seller",
            "kwh_contributed": 50_000,  # watt-hours
            "ai_recommended_price": data["recommended_price"],
            "final_approved_price": data["recommended_price"],
            "approval_type": "auto",
            "approval_reason": None,
            "direction": "local_pool",
        }
        result = settle_on_devnet(
            kwh=50_000, price=10, payout=51_000,
            direction="local_pool", record=record, period_offset=0,
        )
        assert result["signature"]
        assert result["kwh"] == 50_000
        assert result["direction"] == "localPool"

    def test_3_flagged_exception_resolved_then_settled(self):
        """Out-of-band recommendation → exception queue → operator adjusts
        with a required reason → settles on devnet as human-approved."""
        # The unmocked rules estimator prices this out of band → needs_review
        data = _recommend({**_BODY, "seller_id": "e2e-flagged"})
        assert data["policy_decision"] == "needs_review"
        assert data["deviation_reason"] is not None
        assert data["review_id"] is not None

        resolved = _resolve(
            data["review_id"], "adjust",
            "E2E: adjusted to upper band limit", adjusted_price=0.105,
        )
        assert resolved["operator_action"] == "adjust"
        assert resolved["operator_reason"] == "E2E: adjusted to upper band limit"

        record = {
            "seller": "e2e-flagged",
            "kwh_contributed": 50_000,
            "ai_recommended_price": data["recommended_price"],
            "final_approved_price": 0.105,
            "approval_type": "human",
            "approval_reason": resolved["operator_reason"],
            "direction": "local_pool",
        }
        result = settle_on_devnet(
            kwh=50_000, price=11, payout=52_500,
            direction="local_pool", record=record, period_offset=1,
        )
        assert result["signature"]
        assert result["price"] == 11

    def test_4_import_scenario(self):
        """Pool shortfall → import recommendation → devnet settlement."""
        data = _recommend(
            {**_BODY, "pool_current_consumption_kwh": 2000},
            RecommendationResult(
                recommended_price=0.115, recommended_absorption_kwh=50.0,
                direction="import", model_used="rules",
            ),
        )
        assert data["direction"] == "import"

        record = {
            "direction": "import",
            "kwh": 20_000,
            "ai_recommended_price": data["recommended_price"],
        }
        result = settle_on_devnet(
            kwh=20_000, price=12, payout=24_000,
            direction="import", record=record, period_offset=2,
        )
        assert result["direction"] == "import"

    def test_5_export_scenario(self):
        """Surplus overflow → export recommendation → devnet settlement."""
        data = _recommend(
            {**_BODY, "seller_surplus_kwh": 5000, "pool_current_absorption_kwh": 8000},
            RecommendationResult(
                recommended_price=0.10, recommended_absorption_kwh=2000.0,
                direction="export", model_used="rules",
            ),
        )
        assert data["direction"] == "export"

        record = {
            "direction": "export",
            "kwh": 100_000,
            "ai_recommended_price": data["recommended_price"],
        }
        result = settle_on_devnet(
            kwh=100_000, price=10, payout=100_000,
            direction="export", record=record, period_offset=3,
        )
        assert result["direction"] == "export"

    def test_6_cnft_mint_trigger(self, request):
        """Operator approval settles a contribution that crosses the 100 kWh
        milestone → exactly one real Bubblegum cNFT minted on devnet."""
        tree = os.environ.get("BADGE_TREE_ADDRESS")
        if not tree:
            pytest.skip("BADGE_TREE_ADDRESS not set")

        # Real Bubblegum minter against the devnet tree; conftest resets
        # the fake minter after each test via its autouse fixture.
        os.environ.setdefault("BADGE_SCRIPT_DIR", str(SCRIPT_DIR))
        badge_service.set_minter(badge_service.BubblegumBadgeMinter())

        store = badge_service._get_store()  # DictBadgeStore from conftest
        # In-band → needs_review is irrelevant here; go through the queue so
        # the resolve endpoint (the real trigger) runs the badge check.
        data = _recommend({**_BODY, "seller_id": "e2e-badge", "seller_surplus_kwh": 150.0})
        assert data["review_id"] is not None

        # The settled contribution crosses the 100 kWh placeholder threshold
        store.contributions = [("e2e-badge", 150.0, "settled")]

        _resolve(data["review_id"], "approve", "E2E: badge trigger approval")

        badges = [b for b in store.badges.values() if b["seller_id"] == "e2e-badge"]
        assert len(badges) == 1, "exactly one badge minted"
        badge = badges[0]
        assert badge["threshold_kwh"] == 100
        assert badge["mint_status"] == "minted"
        assert badge["asset_id"], "real devnet asset id recorded"
        assert badge["tx_signature"], "real devnet tx signature recorded"

        # No re-mint on a further contribution below the next threshold
        store.contributions.append(("e2e-badge", 60.0, "settled"))
        data2 = _recommend({**_BODY, "seller_id": "e2e-badge", "seller_surplus_kwh": 60.0})
        if data2["review_id"]:
            _resolve(data2["review_id"], "approve", "E2E: second approval, no badge")
        badges_after = [b for b in store.badges.values() if b["seller_id"] == "e2e-badge"]
        assert len(badges_after) == 1, "no re-mint below next threshold"
