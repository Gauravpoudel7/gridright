"""Auto-pay: settle small, non-escalated payout lines without a human click.

The 30-minute settlement run batches payouts; historically the operator paid
every line manually (one Phantom transfer + one click each). That's fine for
ten sellers and a full-time job for five hundred. Auto-pay handles the long
tail of small lines and leaves humans exactly the exceptions:

  A settlement item is auto-paid ONLY when ALL of these hold:
    * auto-pay is enabled (AUTOPAY_ENABLED=1 — default OFF)
    * the item is unpaid and has a payout wallet
    * the item is NOT escalated (escalated lines demand human attention
      by definition — auto-pay must never quietly clear a red flag)
    * total_amount is at or below AUTOPAY_MAX_USD (default 5.00)

  Everything else — big amounts, escalated lines — still appears on the
  operator dashboard for a manual Phantom payment, unchanged.

Payment execution follows the ScriptAnchorCommitClient pattern
(commitments.py): shell out to a TS script in programs/gridright that signs
with the server's local keypair (SOLANA_WALLET, default ~/.config/solana/
id.json — the same funded devnet wallet used for badges/commitments) and
prints one JSON line with the tx signature. AUTOPAY_PAYER=mock swaps in a
no-network payer for tests and local demos; its fake signatures are clearly
prefixed AUTOPAY-SIM- so they can never be mistaken for real transfers.

A failed payment is logged and skipped — the item simply stays unpaid and
rolls forward through the existing missed-cycle machinery, so auto-pay can
never lose a payout, only decline to make one. Recording goes through
settlement_cycle.record_item_paid (paid_method='auto'), which also completes
the batch when the last line is paid.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from abc import ABC, abstractmethod
from typing import Any

from app.services import settlement_cycle

logger = logging.getLogger(__name__)

DEFAULT_MAX_USD = 5.0


def _enabled() -> bool:
    return os.getenv("AUTOPAY_ENABLED") == "1"


def _max_usd() -> float:
    try:
        return float(os.getenv("AUTOPAY_MAX_USD", DEFAULT_MAX_USD))
    except ValueError:
        return DEFAULT_MAX_USD


class SettlementPayer(ABC):
    @abstractmethod
    async def pay(self, wallet: str, amount_usd: float) -> str:
        """Transfer amount_usd to wallet; return the tx signature.
        Raise on any failure — callers treat exceptions as 'not paid'."""


class MockSettlementPayer(SettlementPayer):
    """No-network payer for tests and local demos. Signatures are prefixed
    AUTOPAY-SIM- so a simulated payment can never pass for a real one."""

    def __init__(self) -> None:
        self.payments: list[dict[str, Any]] = []

    async def pay(self, wallet: str, amount_usd: float) -> str:
        sig = f"AUTOPAY-SIM-{uuid.uuid4().hex}"
        self.payments.append({"wallet": wallet, "amount_usd": amount_usd, "sig": sig})
        return sig


class ScriptSettlementPayer(SettlementPayer):
    """Shells out to programs/gridright/scripts/pay-settlement.ts (same
    Windows-safe npx pattern as ScriptAnchorCommitClient)."""

    def __init__(self) -> None:
        self._script_dir = os.environ.get(
            "AUTOPAY_SCRIPT_DIR",
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..",
                         "programs", "gridright"),
        )

    async def pay(self, wallet: str, amount_usd: float) -> str:
        npx = shutil.which("npx") or "npx"
        proc = await asyncio.create_subprocess_exec(
            npx, "tsx", "scripts/pay-settlement.ts",
            "--wallet", wallet,
            "--amount-cents", str(int(round(amount_usd * 100))),
            cwd=self._script_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"pay-settlement.ts failed (exit {proc.returncode}): "
                f"{stderr.decode(errors='replace')[-500:]}"
            )
        result = json.loads(stdout.decode().strip().splitlines()[-1])
        return str(result["signature"])


_payer: SettlementPayer | None = None


def _get_payer() -> SettlementPayer:
    global _payer
    if _payer is None:
        name = os.getenv("AUTOPAY_PAYER", "script")
        _payer = MockSettlementPayer() if name == "mock" else ScriptSettlementPayer()
    return _payer


def set_payer(payer: SettlementPayer | None) -> None:
    global _payer
    _payer = payer


async def run_autopay() -> dict[str, Any]:
    """Pay every eligible line in the current due batch. Returns a summary the
    settlement-run response surfaces so each cycle's auto activity is visible.
    Per-item failures are logged and skipped (the line rolls forward as if
    auto-pay didn't exist); this function itself never raises for one bad line.
    """
    if not _enabled():
        return {"enabled": False}

    threshold = _max_usd()
    due = await settlement_cycle.get_due_settlements()
    items = due.get("items") or []

    summary: dict[str, Any] = {
        "enabled": True,
        "threshold_usd": threshold,
        "paid": 0,
        "paid_usd": 0.0,
        "left_for_manual": 0,
        "failed": 0,
    }

    payer = _get_payer()
    for item in items:
        if item.get("paid"):
            continue
        amount = float(item["total_amount"])
        if item.get("escalated") or amount > threshold or not item.get("payout_wallet"):
            summary["left_for_manual"] += 1
            continue
        try:
            sig = await payer.pay(item["payout_wallet"], amount)
            await settlement_cycle.record_item_paid(item["id"], sig, paid_method="auto")
            summary["paid"] += 1
            summary["paid_usd"] = round(summary["paid_usd"] + amount, 6)
        except Exception:
            logger.exception(
                "Auto-pay failed for item %s ($%.2f to %s); left for manual",
                item["id"], amount, item.get("payout_wallet"),
            )
            summary["failed"] += 1
            summary["left_for_manual"] += 1

    return summary
