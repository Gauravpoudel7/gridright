"""Auth helpers for GridRight API.

Verifies a Supabase access token from the `Authorization: Bearer ...` header,
extracts the caller's role from a custom JWT claim, and exposes a FastAPI
dependency that gates operator-only endpoints.

Per the architecture doc's "Auth" section, this check is applied per-route via
FastAPI's `Depends` — NOT as a single global check — so each route's contract
documents its own auth requirement.

Two operating modes:
- Production: verifies ES256 signature via Supabase's JWKS endpoint
  (`SUPABASE_URL/auth/v1/.well-known/jwks.json`). Role is read from the
  `role` custom claim.
- Test: SUPABASE_AUTH_TESTING=1 disables signature verification so the test
  suite can mint unsigned tokens with arbitrary roles. The verifier is also
  swappable via `set_verifier` for in-memory test injection.

  Tests that need real signature validation (expired/bad-signature tests)
  construct JWTTokenVerifier(secret=TEST_SECRET, testing=False) which uses
  the legacy HS256 path. This is intentionally kept as a testing-only
  compat layer.
"""
from __future__ import annotations

import os
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Header, status
from jwt import PyJWKClient

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
TESTING = os.getenv("SUPABASE_AUTH_TESTING") == "1"


class AuthError(Exception):
    """Raised when authentication or authorization fails.

    `status_code` is 401 for missing/invalid/expired tokens, 403 for valid
    tokens belonging to non-operator callers.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class UserProfile:
    id: str
    role: str
    email: str | None = None


class TokenVerifier(ABC):
    @abstractmethod
    def verify(self, token: str) -> dict[str, Any]:
        """Verify the token and return its claims.

        Raise AuthError(401) on any failure (missing, expired, bad signature,
        malformed). The returned dict must include a `role` key and a `sub` key
        identifying the user.
        """


class JWTTokenVerifier(TokenVerifier):
    """Verifies Supabase JWTs.

    Production: fetches JWKS keys from the Supabase endpoint and verifies ES256
    signatures. The JWKS URL is derived from SUPABASE_URL.

    Test mode (testing=True): disables signature verification entirely per the
    SUPABASE_AUTH_TESTING convention.

    Test mode (secret provided, testing=False): verifies HS256 with the given
    secret — used by test_auth.py's expired/bad-signature scenarios which need
    real signature verification against a test HS256 key.
    """

    def __init__(
        self,
        secret: str = "",
        testing: bool = False,
        url: str = "",
    ) -> None:
        self._testing = testing
        self._secret = secret

        if not testing and not secret:
            # Production path: JWKS from Supabase URL
            jwks_url = f"{url or SUPABASE_URL}/auth/v1/.well-known/jwks.json"
            self._jwks_client = PyJWKClient(jwks_url, cache_keys=True)
        else:
            self._jwks_client = None

    def verify(self, token: str) -> dict[str, Any]:
        if not token:
            raise AuthError(status.HTTP_401_UNAUTHORIZED, "Missing token")

        try:
            if self._testing:
                options = {"verify_signature": False}
                claims = jwt.decode(
                    token,
                    self._secret or "test-secret-must-be-at-least-32-bytes-long",
                    algorithms=["HS256"],
                    options=options,
                )
            elif self._jwks_client:
                signing_key = self._jwks_client.get_signing_key_from_jwt(token)
                claims = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["ES256"],
                    options={
                        "verify_exp": True,
                        "verify_iat": False,
                        "verify_nbf": False,
                        "verify_aud": False,
                    },
                    leeway=30,
                )
            else:
                # HS256 path (used by tests with secret + testing=False)
                claims = jwt.decode(
                    token,
                    self._secret,
                    algorithms=["HS256"],
                    options={"verify_exp": True},
                )
        except jwt.ExpiredSignatureError as e:
            raise AuthError(status.HTTP_401_UNAUTHORIZED, "Token expired") from e
        except jwt.InvalidTokenError as e:
            raise AuthError(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}") from e

        if "sub" not in claims:
            raise AuthError(status.HTTP_401_UNAUTHORIZED, "Token missing sub claim")
        if "role" not in claims:
            raise AuthError(
                status.HTTP_401_UNAUTHORIZED, "Token missing role claim"
            )

        return claims


_verifier: TokenVerifier | None = None


def get_verifier() -> TokenVerifier:
    global _verifier
    if _verifier is None:
        _verifier = JWTTokenVerifier(testing=TESTING, url=SUPABASE_URL)
    return _verifier


def set_verifier(verifier: TokenVerifier | None) -> None:
    """Inject a custom verifier (used by the test suite)."""
    global _verifier
    _verifier = verifier


def _extract_bearer(authorization: str | None) -> str:
    if not authorization:
        raise AuthError(status.HTTP_401_UNAUTHORIZED, "Missing Authorization header")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthError(
            status.HTTP_401_UNAUTHORIZED,
            "Authorization header must be 'Bearer <token>'",
        )
    return parts[1]


def get_user_from_token(token: str) -> UserProfile:
    """Verify a bearer token and return the caller's profile.

    Role is read from (in priority order):
      1. app_metadata.role  (set by operator via admin API)
      2. user_metadata.role (set by signup or profile update)
      3. The legacy `role` claim (Supabase's built-in role —
         typically "authenticated" or "anon", not app-specific)
    """
    claims = get_verifier().verify(token)
    app_meta = claims.get("app_metadata") or {}
    user_meta = claims.get("user_metadata") or {}
    role = str(
        app_meta.get("role")
        or user_meta.get("role")
        or claims.get("role", "")
    )
    return UserProfile(
        id=str(claims["sub"]),
        role=role,
        email=claims.get("email"),
    )


async def get_current_user(
    authorization: str | None = Header(default=None),
) -> UserProfile:
    """FastAPI dependency: any authenticated caller."""
    token = _extract_bearer(authorization)
    return get_user_from_token(token)


async def get_operator_user(
    authorization: str | None = Header(default=None),
) -> UserProfile:
    """FastAPI dependency: caller must be authenticated AND role='operator'.

    Apply this per-route to operator-only endpoints (reviews queue, etc.).
    Raises AuthError(401) for unauthenticated, AuthError(403) for non-operator.
    """
    user = await get_current_user(authorization)
    if user.role != "operator":
        raise AuthError(
            status.HTTP_403_FORBIDDEN,
            "Operator role required",
        )
    return user


async def get_scheduler_or_operator_user(
    authorization: str | None = Header(default=None),
) -> UserProfile:
    """FastAPI dependency: accepts the static SCHEDULER_TOKEN or an operator JWT.

    Intended ONLY for the scheduled-job endpoints (/forecasts/run,
    /commitments/run): an external scheduler (cron-job.org) can't hold a live
    Supabase session, and a user JWT would expire and silently break the cron
    job. The token comes from the SCHEDULER_TOKEN env var; comparison is
    constant-time, and the token value is never logged.

    If SCHEDULER_TOKEN is unset or empty, the static path is disabled entirely
    and the check falls through to the normal operator-JWT dependency.
    """
    scheduler_token = os.getenv("SCHEDULER_TOKEN", "")
    if scheduler_token:
        token = _extract_bearer(authorization)
        if secrets.compare_digest(token, scheduler_token):
            return UserProfile(id="external-scheduler", role="scheduler")
    return await get_operator_user(authorization)


async def get_seller_user(
    authorization: str | None = Header(default=None),
) -> UserProfile:
    """FastAPI dependency: caller must be authenticated AND role='seller'."""
    user = await get_current_user(authorization)
    if user.role != "seller":
        raise AuthError(
            status.HTTP_403_FORBIDDEN,
            "Seller role required",
        )
    return user


async def get_password_changed_seller(
    authorization: str | None = Header(default=None),
) -> UserProfile:
    """FastAPI dependency: an authenticated seller who has changed their
    temporary password.

    This is the server-side enforcement of the password-change gate (spec §4):
    a seller with `must_change_password = true` is blocked from EVERY seller
    route except the password-change endpoint itself (which uses the plain
    `get_seller_user` dependency). A direct API call while the flag is set gets
    403 — the client-side redirect in proxy.ts is a convenience, not the
    authority.

    Delegates to the password_gate service, whose store is swappable: in test
    mode with no injected store the gate is open (matching the testing
    convention); the dedicated gate tests inject an in-memory store to
    exercise the real check.
    """
    user = await get_seller_user(authorization)
    from app.services.password_gate import must_change_password

    if await must_change_password(user.id):
        raise AuthError(
            status.HTTP_403_FORBIDDEN,
            "You must change your temporary password before continuing.",
        )
    return user


# --- helpers used by tests --------------------------------------------------

def mint_test_token(
    sub: str = "user-id",
    role: str = "seller",
    email: str | None = None,
    expires_in: int = 3600,
    secret: str = "test-secret-must-be-at-least-32-bytes-long",
) -> str:
    """Mint a HS256 JWT for the test suite.

    Mirrors the shape of a real Supabase access token (sub + role + exp).
    """
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": sub,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    if email is not None:
        payload["email"] = email
    return jwt.encode(payload, secret, algorithm="HS256")
