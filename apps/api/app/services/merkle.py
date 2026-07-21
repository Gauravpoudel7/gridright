"""Merkle tree over decision hashes (Phase 5).

Standard pairwise SHA-256 tree:
- Leaves are 32-byte decision hashes, sorted ascending by byte value before
  building — root must NOT depend on insertion order (spec requirement).
- Odd leaf count: duplicate the last leaf at that level.
- Proof = sibling path; verify by folding the leaf up to the root.

Pure functions, no I/O — proofs are regenerated on demand from stored hashes
(deterministic + cheap), never persisted.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass


def _h(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


@dataclass
class MerkleProof:
    leaf: bytes
    # (sibling_hash, sibling_is_left) pairs from leaf level up to the root.
    path: list[tuple[bytes, bool]]


def sort_leaves(leaves: list[bytes]) -> list[bytes]:
    """Deterministic leaf order: ascending by hash bytes."""
    return sorted(leaves)


def merkle_root(leaves: list[bytes]) -> bytes:
    """Root of the sorted leaf set. Raises on empty input — an empty day has
    nothing to commit (the job skips it)."""
    if not leaves:
        raise ValueError("Cannot build a Merkle root over zero leaves")
    level = sort_leaves(leaves)
    while len(level) > 1:
        if len(level) % 2 == 1:
            level = level + [level[-1]]  # duplicate last on odd count
        level = [_h(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def merkle_proof(leaves: list[bytes], leaf: bytes) -> MerkleProof:
    """Sibling path for `leaf` within the sorted leaf set."""
    level = sort_leaves(leaves)
    try:
        idx = level.index(leaf)
    except ValueError:
        raise ValueError("Leaf not present in the leaf set")

    path: list[tuple[bytes, bool]] = []
    while len(level) > 1:
        if len(level) % 2 == 1:
            level = level + [level[-1]]
        sibling_idx = idx - 1 if idx % 2 == 1 else idx + 1
        path.append((level[sibling_idx], sibling_idx < idx))
        level = [_h(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
        idx //= 2
    return MerkleProof(leaf=leaf, path=path)


def verify_proof(proof: MerkleProof, root: bytes) -> bool:
    node = proof.leaf
    for sibling, sibling_is_left in proof.path:
        node = _h(sibling + node) if sibling_is_left else _h(node + sibling)
    return node == root
