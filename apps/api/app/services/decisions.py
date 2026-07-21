"""Canonical decision hashing (Phase 5).

Every AI-recommendation-vs-final-decision gets a SHA-256 over a canonical,
fixed-field JSON — computed at the moment the decision is made (auto-approve
at recommend time, or operator resolve). The daily Merkle commitment anchors
these hashes on-chain; this module is the single place the canonical form is
defined so producer and verifier can never drift.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

# Bump when the canonical field set changes; part of the hashed payload so a
# hash can always be re-derived against the right schema.
DECISION_HASH_VERSION = "v1"


def canonical_decision_payload(
    *,
    record_id: str,
    seller_id: str,
    ai_recommended_price: float,
    kwh: float,
    decision: str,           # "auto" | "approve" | "adjust" | "reject"
    final_price: float,
    decided_at: str,         # ISO 8601 UTC
    model_version: str,      # e.g. "rules" | "groq"
) -> dict[str, Any]:
    """Fixed-field payload. Floats are stringified at fixed precision so the
    hash can't shift with float repr differences across runtimes."""
    return {
        "v": DECISION_HASH_VERSION,
        "record_id": record_id,
        "seller_id": seller_id,
        "ai_recommended_price": f"{ai_recommended_price:.6f}",
        "kwh": f"{kwh:.4f}",
        "decision": decision,
        "final_price": f"{final_price:.6f}",
        "decided_at": decided_at,
        "model_version": model_version,
    }


def decision_hash(**kwargs: Any) -> str:
    """Hex SHA-256 of the canonical JSON (sorted keys, compact separators)."""
    payload = canonical_decision_payload(**kwargs)
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()
