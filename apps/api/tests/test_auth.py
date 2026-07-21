"""Tests for the operator-only auth layer.

Per Phase 5: seller hitting operator endpoint -> 403; operator -> success;
unauthenticated -> 401.
"""
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth import (
    AuthError,
    UserProfile,
    mint_test_token,
    set_verifier,
)
from app.main import app

client = TestClient(app)

TEST_SECRET = "test-secret-must-be-at-least-32-bytes-long"


class _ScriptedVerifier:
    """Returns a fixed claims dict regardless of token contents.

    Used to assert the dependency's role-checking behavior in isolation
    from the JWT decoding layer.
    """

    def __init__(self, claims: dict | None, error: Exception | None = None) -> None:
        self._claims = claims
        self._error = error

    def verify(self, token: str) -> dict:
        if self._error is not None:
            raise self._error
        return self._claims or {}


@pytest.fixture
def scripted_verifier():
    """Yield a controllable verifier; resets after the test."""
    holder: dict = {}

    class _Holder:
        verifier: _ScriptedVerifier | None = None

        def install(self, v: _ScriptedVerifier) -> None:
            _Holder.verifier = v
            set_verifier(v)

        def clear(self) -> None:
            _Holder.verifier = None
            set_verifier(None)

    h = _Holder()
    yield h
    h.clear()


def _recommend_request() -> dict:
    return {
        "seller_id": "seller-x",
        "seller_surplus_kwh": 50.0,
        "time_of_day": "14:00:00",
        "pool_current_absorption_kwh": 1000,
        "pool_absorption_limit_kwh": 10000,
        "pool_current_consumption_kwh": 500,
    }


# --- seller hitting operator endpoint -> 403 -------------------------------

def test_seller_get_pending_returns_403(scripted_verifier):
    scripted_verifier.install(
        _ScriptedVerifier({"sub": "u1", "role": "seller", "email": "u1@x"})
    )
    response = client.get(
        "/api/v1/reviews/pending",
        headers={"Authorization": "Bearer some-token"},
    )
    assert response.status_code == 403
    assert "Operator role required" in response.json()["detail"]


def test_seller_resolve_review_returns_403(scripted_verifier):
    scripted_verifier.install(
        _ScriptedVerifier({"sub": "u1", "role": "seller", "email": "u1@x"})
    )
    response = client.post(
        "/api/v1/reviews/some-id/resolve",
        json={"action": "approve", "reason": "test"},
        headers={"Authorization": "Bearer some-token"},
    )
    assert response.status_code == 403


# --- operator hitting operator endpoint -> 200 ------------------------------

def test_operator_get_pending_returns_200(scripted_verifier):
    scripted_verifier.install(
        _ScriptedVerifier({"sub": "op1", "role": "operator", "email": "op1@x"})
    )
    response = client.get(
        "/api/v1/reviews/pending",
        headers={"Authorization": "Bearer some-token"},
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_operator_resolve_nonexistent_returns_404(scripted_verifier):
    scripted_verifier.install(
        _ScriptedVerifier({"sub": "op1", "role": "operator", "email": "op1@x"})
    )
    response = client.post(
        "/api/v1/reviews/does-not-exist/resolve",
        json={"action": "approve", "reason": "no-op"},
        headers={"Authorization": "Bearer some-token"},
    )
    assert response.status_code == 404


# --- unauthenticated -> 401 -------------------------------------------------

def test_missing_authorization_header_returns_401(scripted_verifier):
    scripted_verifier.install(
        _ScriptedVerifier(
            {"sub": "u1", "role": "operator"},
            error=AuthError(401, "Missing Authorization header"),
        )
    )
    response = client.get("/api/v1/reviews/pending")
    assert response.status_code == 401


def test_malformed_authorization_header_returns_401(scripted_verifier):
    response = client.get(
        "/api/v1/reviews/pending",
        headers={"Authorization": "NotBearer abc"},
    )
    assert response.status_code == 401


# --- bad / expired tokens -> 401 (real JWT verifier) ------------------------

def test_expired_token_returns_401():
    now = datetime.now(timezone.utc)
    expired = jwt.encode(
        {
            "sub": "u1",
            "role": "operator",
            "iat": int((now - timedelta(hours=2)).timestamp()),
            "exp": int((now - timedelta(hours=1)).timestamp()),
        },
        TEST_SECRET,
        algorithm="HS256",
    )
    # Real verifier with signature check on, so exp errors propagate
    from app.auth import JWTTokenVerifier

    set_verifier(JWTTokenVerifier(secret=TEST_SECRET, testing=False))
    response = client.get(
        "/api/v1/reviews/pending",
        headers={"Authorization": f"Bearer {expired}"},
    )
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


def test_bad_signature_returns_401():
    # Sign with a different secret than the verifier expects.
    token = jwt.encode(
        {"sub": "u1", "role": "operator", "exp": 9999999999},
        "wrong-secret",
        algorithm="HS256",
    )
    from app.auth import JWTTokenVerifier

    set_verifier(JWTTokenVerifier(secret=TEST_SECRET, testing=False))
    response = client.get(
        "/api/v1/reviews/pending",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


def test_valid_token_with_operator_role_returns_200():
    token = mint_test_token(role="operator")
    from app.auth import JWTTokenVerifier

    set_verifier(JWTTokenVerifier(secret=TEST_SECRET, testing=False))
    response = client.get(
        "/api/v1/reviews/pending",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


def test_valid_token_with_seller_role_returns_403():
    token = mint_test_token(role="seller")
    from app.auth import JWTTokenVerifier

    set_verifier(JWTTokenVerifier(secret=TEST_SECRET, testing=False))
    response = client.get(
        "/api/v1/reviews/pending",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


# --- /recommend stays public (any caller, no auth required) ----------------

def test_recommend_endpoint_does_not_require_auth():
    """POST /api/v1/recommend is intentionally unauthenticated per Phase 5.

    Any caller (e.g. a smart meter) may submit a surplus signal. Operator
    gating is applied per-route to the review-queue endpoints, not here.
    """
    # Reset to the autouse permissive verifier (the previous tests may have
    # installed a stricter one).
    set_verifier(
        _ScriptedVerifier({"sub": "anyone", "role": "anyone"})
    )
    response = client.post("/api/v1/recommend", json=_recommend_request())
    assert response.status_code == 200
