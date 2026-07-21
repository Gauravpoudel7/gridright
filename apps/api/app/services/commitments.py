"""Phase 5 — daily on-chain decision commitment.

Pipeline (operator-triggered or scheduled):
  1. Pull every contribution decided in one UTC day (decided_at window).
  2. Sort by decision_hash bytes ascending (Merkle sort independence).
  3. Compute Merkle root.
  4. Shell out to scripts/commit-daily-root.ts → on-chain DailyCommitment PDA.
  5. Mirror the commitment in Supabase (daily_commitments table) so the
     verify endpoint can answer without an RPC round-trip.

Two operators, two service classes, two thin module wrappers — same store-ABC
pattern as the rest of the codebase.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from abc import ABC, abstractmethod
from datetime import date as date_cls
from datetime import datetime, timezone

from app.services.decisions import decision_hash as _unused  # noqa: F401  (exported via verifier)
from app.services.merkle import merkle_proof, merkle_root, verify_proof


class CommitmentStore(ABC):
    @abstractmethod
    async def list_decided_hashes(
        self, day: date_cls
    ) -> list[tuple[str, bytes]]:
        """Return [(record_id, decision_hash_bytes), ...] for one UTC day,
        ordered by the API (callers MUST NOT rely on this order — they
        re-sort by hash bytes before building the tree)."""

    @abstractmethod
    async def get_commitment(self, day: date_cls) -> dict | None:
        """Return the mirror row for a day, or None if not yet committed."""

    @abstractmethod
    async def record_commitment(
        self,
        day: date_cls,
        authority: str,
        merkle_root: str,
        record_count: int,
        tx_signature: str,
        pda: str,
    ) -> None:
        ...


class SupabaseCommitmentStore(CommitmentStore):
    def __init__(self) -> None:
        from supabase import create_client

        self._client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )

    async def list_decided_hashes(
        self, day: date_cls
    ) -> list[tuple[str, bytes]]:
        start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        # half-open window: [start, start + 1 day)
        end = datetime.fromtimestamp(start.timestamp() + 86400, tz=timezone.utc)
        result = (
            self._client.table("contributions")
            .select("id, decision_hash")
            .gte("decided_at", start.isoformat())
            .lt("decided_at", end.isoformat())
            .execute()
        )
        out: list[tuple[str, bytes]] = []
        for row in result.data:
            hex_hash = row.get("decision_hash")
            if not hex_hash:
                # Phase 5 invariant: every decided record has a hash. A
                # missing one is a pre-Phase-5 record or a bug; skip rather
                # than crash the whole commit.
                continue
            out.append((str(row["id"]), bytes.fromhex(hex_hash)))
        return out

    async def get_commitment(self, day: date_cls) -> dict | None:
        result = (
            self._client.table("daily_commitments")
            .select("*")
            .eq("commit_date", day.isoformat())
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        return result.data[0]

    async def record_commitment(
        self,
        day: date_cls,
        authority: str,
        merkle_root: str,
        record_count: int,
        tx_signature: str,
        pda: str,
    ) -> None:
        # On conflict do nothing — the on-chain account is the source of
        # truth; the mirror is idempotent.
        self._client.table("daily_commitments").upsert(
            {
                "commit_date": day.isoformat(),
                "authority": authority,
                "merkle_root": merkle_root,
                "record_count": record_count,
                "tx_signature": tx_signature,
                "pda": pda,
            },
            on_conflict="commit_date,authority",
        ).execute()


class AnchorCommitClient(ABC):
    @abstractmethod
    async def commit(
        self, day: date_cls, merkle_root: str, record_count: int
    ) -> dict:
        """Return {signature, pda, date, merkle_root, record_count}."""


class ScriptAnchorCommitClient(AnchorCommitClient):
    """Shells out to programs/gridright/scripts/commit-daily-root.ts.

    Windows-safe: resolves npx to npx.cmd via shutil.which so subprocess
    doesn't try to exec the bare name.
    """

    def __init__(self) -> None:
        self._script_dir = os.environ.get(
            "COMMIT_SCRIPT_DIR",
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..",
                         "programs", "gridright"),
        )
        self._authority = os.environ.get(
            "COMMIT_AUTHORITY_PUBKEY",
            # devnet wallet pubkey — anchor can also use the wallet directly,
            # but storing it here makes the mirror table self-describing.
            "",
        )

    async def commit(
        self, day: date_cls, merkle_root: str, record_count: int
    ) -> dict:
        npx = shutil.which("npx") or "npx"
        proc = await asyncio.create_subprocess_exec(
            npx, "tsx", "scripts/commit-daily-root.ts",
            "--date", day.isoformat(),
            "--root", merkle_root,
            "--count", str(record_count),
            cwd=self._script_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"commit-daily-root.ts failed (exit {proc.returncode}): "
                f"{stderr.decode(errors='replace')[-500:]}"
            )
        # script prints one JSON line
        return json.loads(stdout.decode().strip().splitlines()[-1])


_store: CommitmentStore | None = None
_committer: AnchorCommitClient | None = None


def _get_store() -> CommitmentStore:
    global _store
    if _store is None:
        _store = SupabaseCommitmentStore()
    return _store


def _get_committer() -> AnchorCommitClient:
    global _committer
    if _committer is None:
        _committer = ScriptAnchorCommitClient()
    return _committer


def set_store(store: CommitmentStore | None) -> None:
    global _store
    _store = store


def set_committer(committer: AnchorCommitClient | None) -> None:
    global _committer
    _committer = committer


async def run_daily_commitment(
    day: date_cls | None = None,
) -> dict:
    """One-shot: collect hashes → root → on-chain tx → mirror row.

    Returns the mirror row plus the on-chain receipt so the caller can build
    an explorer link. Idempotent: re-running the same day is a no-op on-chain
    (init fails with account-in-use) and updates the mirror row.
    """
    if day is None:
        day = datetime.now(timezone.utc).date()
    leaves_with_ids = await _get_store().list_decided_hashes(day)
    if not leaves_with_ids:
        return {"day": day.isoformat(), "skipped": True, "reason": "no decisions"}
    leaves = [h for _, h in leaves_with_ids]
    root = merkle_root(leaves)
    receipt = await _get_committer().commit(day, root.hex(), len(leaves))
    await _get_store().record_commitment(
        day=day,
        authority=receipt.get("pda", ""),  # see comment in ScriptAnchorCommitClient
        merkle_root=receipt["merkle_root"],
        record_count=receipt["record_count"],
        tx_signature=receipt["signature"],
        pda=receipt["pda"],
    )
    return {
        "day": day.isoformat(),
        "skipped": False,
        "record_count": len(leaves),
        "merkle_root": receipt["merkle_root"],
        "tx_signature": receipt["signature"],
        "pda": receipt["pda"],
    }


async def verify_contribution(
    record_id: str, decision_hash_hex: str, day: date_cls
) -> dict:
    """Off-chain verification: regenerate the proof for a single record and
    check it folds up to the committed root for the day.

    Returns {ok, reason, merkle_root, proof_len, tx_signature, explorer_url}.
    The on-chain record (tx_signature + explorer link) is only included when
    a commitment exists for the day.
    """
    store = _get_store()
    mirror = await store.get_commitment(day)
    if mirror is None:
        return {
            "ok": False,
            "reason": "no commitment for day",
            "record_id": record_id,
        }
    leaves_with_ids = await store.list_decided_hashes(day)
    leaves = [h for _, h in leaves_with_ids]
    leaf = bytes.fromhex(decision_hash_hex)
    try:
        proof = merkle_proof(leaves, leaf)
    except ValueError as e:
        return {
            "ok": False,
            "reason": f"leaf not in day's leaf set: {e}",
            "record_id": record_id,
            "merkle_root": mirror["merkle_root"],
        }
    root_bytes = bytes.fromhex(mirror["merkle_root"])
    ok = verify_proof(proof, root_bytes)
    # devnet explorer is the only deployment target right now; if we ever
    # add mainnet, gate on a env var here.
    explorer_url = (
        f"https://explorer.solana.com/tx/{mirror['tx_signature']}?cluster=devnet"
        if mirror.get("tx_signature")
        else None
    )
    return {
        "ok": ok,
        "reason": "ok" if ok else "proof does not fold to committed root",
        "record_id": record_id,
        "merkle_root": mirror["merkle_root"],
        "proof_len": len(proof.path),
        "tx_signature": mirror.get("tx_signature"),
        "pda": mirror.get("pda"),
        "explorer_url": explorer_url,
    }


__all__ = [
    "CommitmentStore",
    "SupabaseCommitmentStore",
    "AnchorCommitClient",
    "ScriptAnchorCommitClient",
    "run_daily_commitment",
    "verify_contribution",
    "set_store",
    "set_committer",
]
