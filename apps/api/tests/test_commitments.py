"""Phase 5 verification tests — hash determinism, Merkle fixture, mocked
commit + verify (success + tampered failure). Pure-Python, no Supabase
or Anchor calls. The Anchor side is covered by the single on-chain test
in programs/gridright/tests/gridright.ts.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.commitments import (
    AnchorCommitClient,
    CommitmentStore,
    run_daily_commitment,
    verify_contribution,
)
from app.services.decisions import (
    DECISION_HASH_VERSION,
    canonical_decision_payload,
    decision_hash,
)
from app.services.merkle import (
    merkle_proof,
    merkle_root,
    sort_leaves,
    verify_proof,
)


# ---- canonical hash (1 test) ----

def test_decision_hash_is_deterministic_and_versioned():
    """Same inputs → same hash, different inputs → different hash, the
    version string is part of the payload so a hash can be re-derived
    against the right schema."""
    kwargs = dict(
        record_id="rec-1",
        seller_id="seller-A",
        ai_recommended_price=0.115,
        kwh=42.0,
        decision="auto",
        final_price=0.115,
        decided_at="2026-07-21T12:00:00+00:00",
        model_version="rules",
    )
    h1 = decision_hash(**kwargs)
    h2 = decision_hash(**kwargs)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex
    # Any field change → different hash
    assert h1 != decision_hash(**{**kwargs, "model_version": "groq"})
    assert h1 != decision_hash(**{**kwargs, "final_price": 0.12})
    # Version is in the payload
    assert DECISION_HASH_VERSION in canonical_decision_payload(**kwargs)["v"]


# ---- Merkle tree (3–5 leaf fixture hand-verified) ----

def test_merkle_root_hand_verified_three_leaves():
    """3 leaves — pairwise SHA-256, last duplicate on odd count.
    Hand-computed: pair (a,b) → h1; pair (h1, c) where c sorts last →
    final root. This is the fixture shipped with the spec."""
    a = bytes.fromhex("aa" * 32)
    b = bytes.fromhex("bb" * 32)
    c = bytes.fromhex("cc" * 32)
    leaves = sort_leaves([a, b, c])  # a, b, c already sorted by byte value
    # 3 leaves → duplicate last → 4 leaves for pairing: [a, b, c, c]
    # level 1: sha256(a+b), sha256(c+c)
    # root: sha256(level1[0] + level1[1])
    import hashlib
    expected_l1 = [
        hashlib.sha256(a + b).digest(),
        hashlib.sha256(c + c).digest(),
    ]
    expected_root = hashlib.sha256(expected_l1[0] + expected_l1[1]).digest()
    assert merkle_root([a, b, c]) == expected_root


def test_merkle_root_order_independent():
    """Root must NOT depend on insertion order — the same leaf set in any
    order must produce the same root. Spec requirement."""
    a = bytes.fromhex("11" * 32)
    b = bytes.fromhex("22" * 32)
    c = bytes.fromhex("33" * 32)
    d = bytes.fromhex("44" * 32)
    r1 = merkle_root([a, b, c, d])
    r2 = merkle_root([d, c, b, a])
    r3 = merkle_root([b, a, d, c])
    assert r1 == r2 == r3


def test_merkle_root_rejects_empty():
    """An empty day has nothing to commit — the job skips it before
    calling merkle_root, but the helper itself must guard."""
    with pytest.raises(ValueError):
        merkle_root([])


def test_merkle_proof_round_trip_five_leaves():
    """5 leaves — proof for the middle one folds back up to the same root."""
    leaves = [bytes.fromhex(f"{i:02x}" * 32) for i in range(1, 6)]
    root = merkle_root(leaves)
    target = leaves[2]
    proof = merkle_proof(leaves, target)
    assert verify_proof(proof, root)
    # Tamper the leaf: a leaf NOT in the set must NOT produce a valid proof.
    # We can build the path the same way (mimics a real attack) and verify
    # that the leaf bytes are folded into the root — the mismatch between
    # the tampered leaf and any real leaf's position produces a different
    # root, so verification fails.
    other_proof = merkle_proof(leaves, leaves[0])
    tampered = bytearray(leaves[0])
    tampered[0] ^= 0x01
    assert not verify_proof(
        SimpleNamespace(leaf=bytes(tampered), path=other_proof.path),
        root,
    )


def test_merkle_proof_missing_leaf_raises():
    leaves = [bytes.fromhex(f"{i:02x}" * 32) for i in range(1, 4)]
    with pytest.raises(ValueError):
        merkle_proof(leaves, bytes.fromhex("ff" * 32))


# ---- commit + verify, mocked (4 tests) ----

class _InMemoryStore(CommitmentStore):
    def __init__(self, leaves, mirror=None):
        self._leaves = leaves  # [(id, bytes)]
        self._mirror = mirror

    async def list_decided_hashes(self, day):
        return self._leaves

    async def get_commitment(self, day):
        return self._mirror

    async def record_commitment(self, day, authority, merkle_root, record_count, tx_signature, pda):
        self._mirror = {
            "commit_date": day.isoformat(),
            "authority": authority,
            "merkle_root": merkle_root,
            "record_count": record_count,
            "tx_signature": tx_signature,
            "pda": pda,
        }


class _FakeCommitter(AnchorCommitClient):
    def __init__(self, raise_on_call=False):
        self.calls = []
        self.raise_on_call = raise_on_call

    async def commit(self, day, merkle_root, record_count):
        self.calls.append((day, merkle_root, record_count))
        if self.raise_on_call:
            raise RuntimeError("on-chain tx failed")
        return {
            "signature": "5uFakeSig11111111111111111111111111111111111111",
            "pda": "FakePDA1111111111111111111111111111111111",
            "date": day.isoformat(),
            "merkle_root": merkle_root,
            "record_count": record_count,
        }


@pytest.fixture(autouse=True)
def _wire_mocks(monkeypatch):
    from app.services import commitments
    commitments.set_store(None)
    commitments.set_committer(None)
    yield
    commitments.set_store(None)
    commitments.set_committer(None)


@pytest.mark.asyncio
async def test_run_daily_commitment_end_to_end(monkeypatch):
    """Collect 3 leaves → root → on-chain tx → mirror row."""
    leaves = [
        ("rec-a", bytes.fromhex("aa" * 32)),
        ("rec-b", bytes.fromhex("bb" * 32)),
        ("rec-c", bytes.fromhex("cc" * 32)),
    ]
    store = _InMemoryStore(leaves)
    committer = _FakeCommitter()
    from app.services import commitments
    commitments.set_store(store)
    commitments.set_committer(committer)

    result = await run_daily_commitment(date(2026, 7, 21))
    assert result["skipped"] is False
    assert result["record_count"] == 3
    assert result["tx_signature"].startswith("5uFakeSig")
    # committer was called with the hex root + 3
    assert len(committer.calls) == 1
    day_arg, root_arg, count_arg = committer.calls[0]
    assert day_arg == date(2026, 7, 21)
    assert count_arg == 3
    assert len(root_arg) == 64
    # mirror row was written
    assert store._mirror is not None
    assert store._mirror["record_count"] == 3
    assert store._mirror["merkle_root"] == root_arg


@pytest.mark.asyncio
async def test_run_daily_commitment_skips_empty_day():
    """No decisions → no commit. Saves a pointless on-chain tx."""
    store = _InMemoryStore(leaves=[])
    committer = _FakeCommitter()
    from app.services import commitments
    commitments.set_store(store)
    commitments.set_committer(committer)

    result = await run_daily_commitment(date(2026, 7, 21))
    assert result["skipped"] is True
    assert committer.calls == []  # never called


@pytest.mark.asyncio
async def test_verify_contribution_success():
    """Regenerate proof for a known leaf → folds to committed root."""
    leaves = [
        ("rec-a", bytes.fromhex("aa" * 32)),
        ("rec-b", bytes.fromhex("bb" * 32)),
        ("rec-c", bytes.fromhex("cc" * 32)),
    ]
    root = merkle_root([h for _, h in leaves])
    mirror = {
        "commit_date": "2026-07-21",
        "authority": "Auth",
        "merkle_root": root.hex(),
        "record_count": 3,
        "tx_signature": "5uFakeSig",
        "pda": "FakePDA",
    }
    store = _InMemoryStore(leaves, mirror=mirror)
    from app.services import commitments
    commitments.set_store(store)

    result = await verify_contribution(
        "rec-b", leaves[1][1].hex(), date(2026, 7, 21),
    )
    assert result["ok"] is True
    assert result["reason"] == "ok"
    assert result["proof_len"] >= 1
    assert result["explorer_url"].startswith("https://explorer.solana.com/tx/5uFakeSig")


@pytest.mark.asyncio
async def test_verify_contribution_tampered_failure():
    """A leaf that doesn't belong in the day's set must NOT verify."""
    leaves = [
        ("rec-a", bytes.fromhex("aa" * 32)),
        ("rec-b", bytes.fromhex("bb" * 32)),
    ]
    root = merkle_root([h for _, h in leaves])
    mirror = {
        "commit_date": "2026-07-21",
        "authority": "Auth",
        "merkle_root": root.hex(),
        "record_count": 2,
        "tx_signature": "5uFakeSig",
        "pda": "FakePDA",
    }
    store = _InMemoryStore(leaves, mirror=mirror)
    from app.services import commitments
    commitments.set_store(store)

    result = await verify_contribution(
        "rec-evil", bytes.fromhex("ff" * 32).hex(), date(2026, 7, 21),
    )
    assert result["ok"] is False
    assert "not in" in result["reason"]
