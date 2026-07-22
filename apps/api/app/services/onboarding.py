"""Seller onboarding — identity review state machine (spec §2, §3.1).

An applicant submits identity details (no auth user yet). An operator reviews;
on approve the flow creates the Supabase auth user, generates a temporary
password, emails it, assigns a community pool, and flips
`must_change_password = true`. On reject it records a reason; the applicant can
resubmit (back to `submitted`) using the one-time edit token issued at
submission.

Follows the repo's store-ABC + swappable-client pattern (see meter.py,
badge_service.py): a swappable `ApplicationStore` for the data layer and a
swappable `Emailer` for the side effect, so tests run fully in-memory and never
send real email or touch Supabase.

Security (spec §4):
  - The temp password is generated with `secrets` and is NEVER logged in
    plaintext — not in app logs, not in error tracking. Only the Emailer sees
    it, and the SMTP Emailer hands it straight to the transport.
  - The edit token is returned once at submission and stored only as a SHA-256
    hash, exactly like meter device tokens.
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

# Valid application states and the transitions the service permits. The DB
# CHECK constraint guards the value set; this map guards the edges.
_VALID_STATUSES = {"submitted", "identity_approved", "identity_rejected"}


class ApplicationError(Exception):
    """Raised for invalid onboarding operations (bad state, bad token).

    `status_code` mirrors the HTTP code the router should return.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def hash_edit_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_edit_token() -> str:
    """One-time token shown to the applicant once at submission."""
    return f"gr_app_{secrets.token_urlsafe(24)}"


def generate_temp_password() -> str:
    """Temporary password with sufficient entropy (spec §4).

    token_urlsafe(18) → 24 chars, ~144 bits. Never logged in plaintext.
    """
    return secrets.token_urlsafe(18)


# --- Email side effect -------------------------------------------------------

class Emailer(ABC):
    @abstractmethod
    async def send_temp_password(
        self, to_email: str, temp_password: str, login_url: str
    ) -> None:
        """Email the applicant their temporary password + login instructions."""


class ConsoleEmailer(Emailer):
    """Dev-only transport: logs that credentials were issued WITHOUT the
    password (spec §4 — the plaintext temp password must never reach a log
    line or stdout). Selected ONLY via the explicit
    GRIDRIGHT_ALLOW_CONSOLE_EMAIL=1 opt-in — a prod deploy that forgets to
    configure SMTP fails loudly instead of falling through to this."""

    async def send_temp_password(
        self, to_email: str, temp_password: str, login_url: str
    ) -> None:
        logger.info(
            "[console-emailer] Temp-password email suppressed for %s "
            "(dev mode — operator must relay credentials out-of-band)",
            to_email,
        )


class SMTPEmailer(Emailer):
    """Sends via SMTP using SMTP_* env vars. Requires SMTP_HOST — transport
    selection happens in _get_emailer(), which never routes here without it."""

    async def send_temp_password(
        self, to_email: str, temp_password: str, login_url: str
    ) -> None:
        host = os.getenv("SMTP_HOST")
        if not host:
            # Selection guarantees this doesn't happen; keep a loud guard so a
            # direct construction can't silently drop credentials.
            raise RuntimeError("SMTPEmailer requires SMTP_HOST")

        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = "Your GridRight seller account"
        msg["From"] = os.getenv("SMTP_FROM", "no-reply@gridright.app")
        msg["To"] = to_email
        msg.set_content(
            "Your GridRight seller application was approved.\n\n"
            f"Temporary password: {temp_password}\n\n"
            f"Sign in at {login_url} and you'll be asked to set a new "
            "password before you can continue.\n"
        )

        port = int(os.getenv("SMTP_PORT", "587"))
        user = os.getenv("SMTP_USER")
        password = os.getenv("SMTP_PASS")

        def _send() -> None:
            # Hard timeout: a wrong host/port must fail fast, not hang the
            # approve request until the platform kills it. Port 465 is
            # implicit-TLS (SMTP_SSL); 587 is STARTTLS.
            if port == 465:
                server_cls, use_starttls = smtplib.SMTP_SSL, False
            else:
                server_cls, use_starttls = smtplib.SMTP, True
            with server_cls(host, port, timeout=15) as server:
                if use_starttls:
                    server.starttls()
                if user and password:
                    server.login(user, password)
                server.send_message(msg)

        # smtplib is blocking; run it off the event loop.
        import asyncio

        await asyncio.get_event_loop().run_in_executor(None, _send)


# --- Data layer --------------------------------------------------------------

class ApplicationStore(ABC):
    @abstractmethod
    async def insert_application(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    @abstractmethod
    async def get_application(self, application_id: str) -> dict[str, Any] | None:
        ...

    @abstractmethod
    async def update_application(
        self, application_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        ...

    @abstractmethod
    async def list_by_status(self, status: str) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def create_auth_seller(
        self, email: str, temp_password: str
    ) -> str:
        """Create the Supabase auth user for an approved applicant and return
        its id. The created profile must carry must_change_password=true."""

    @abstractmethod
    async def set_profile_pool(self, profile_id: str, community_pool_id: str) -> None:
        ...


class SupabaseApplicationStore(ApplicationStore):
    def __init__(self) -> None:
        from supabase import create_client

        self._client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )

    async def insert_application(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = (
            self._client.table("seller_applications").insert(payload).execute()
        )
        return result.data[0]

    async def get_application(self, application_id: str) -> dict[str, Any] | None:
        result = (
            self._client.table("seller_applications")
            .select("*")
            .eq("id", application_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    async def update_application(
        self, application_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        result = (
            self._client.table("seller_applications")
            .update(updates)
            .eq("id", application_id)
            .execute()
        )
        return result.data[0] if result.data else None

    async def list_by_status(self, status: str) -> list[dict[str, Any]]:
        result = (
            self._client.table("seller_applications")
            .select("id, full_name, gmail, location_text, application_status, "
                    "community_pool_id, created_at")
            .eq("application_status", status)
            .order("created_at", desc=False)
            .execute()
        )
        return result.data or []

    async def create_auth_seller(self, email: str, temp_password: str) -> str:
        # Admin API: create a confirmed user carrying the must_change_password
        # flag in user metadata, which the handle_new_user trigger reads into
        # the profiles row.
        resp = self._client.auth.admin.create_user(
            {
                "email": email,
                "password": temp_password,
                "email_confirm": True,
                "user_metadata": {"must_change_password": True},
                # app_metadata lands in JWT claims — the API's per-route role
                # checks (get_seller_user etc.) read app_metadata.role.
                "app_metadata": {"role": "seller"},
            }
        )
        user = getattr(resp, "user", None) or resp
        return str(user.id)

    async def set_profile_pool(self, profile_id: str, community_pool_id: str) -> None:
        self._client.table("profiles").update(
            {"community_pool_id": community_pool_id}
        ).eq("id", profile_id).execute()


_store: ApplicationStore | None = None
_emailer: Emailer | None = None


def _get_store() -> ApplicationStore:
    global _store
    if _store is None:
        _store = SupabaseApplicationStore()
    return _store


def _get_emailer() -> Emailer:
    """Select the email transport, failing loudly on misconfiguration.

    Priority:
      1. A test-injected emailer (set_emailer) — used by the suite.
      2. SMTP when SMTP_HOST is set — the production path.
      3. ConsoleEmailer ONLY when GRIDRIGHT_ALLOW_CONSOLE_EMAIL=1 is set — an
         explicit dev opt-in.
      4. Otherwise raise. A production deploy that forgets SMTP config does NOT
         silently fall through to a no-op console emailer (spec §4 review):
         it fails loudly so the missing transport is caught at approval time.
    """
    global _emailer
    if _emailer is not None:
        return _emailer
    if os.getenv("SMTP_HOST"):
        _emailer = SMTPEmailer()
    elif os.getenv("GRIDRIGHT_ALLOW_CONSOLE_EMAIL") == "1":
        _emailer = ConsoleEmailer()
    else:
        raise RuntimeError(
            "No email transport configured: set SMTP_HOST for production, or "
            "GRIDRIGHT_ALLOW_CONSOLE_EMAIL=1 to explicitly opt into the "
            "dev console emailer. Refusing to silently drop seller credentials."
        )
    return _emailer


def set_store(store: ApplicationStore | None) -> None:
    global _store
    _store = store


def set_emailer(emailer: Emailer | None) -> None:
    global _emailer
    _emailer = emailer


# --- Operations --------------------------------------------------------------

async def submit_application(
    full_name: str,
    dob: str,
    ownership_doc_url: str,
    gmail: str,
    location_text: str,
) -> dict[str, Any]:
    """Create a new application in `submitted`. Returns the row plus the
    plaintext edit token (shown once — used for status checks / resubmit)."""
    for name, value in (
        ("full_name", full_name),
        ("dob", dob),
        ("ownership_doc_url", ownership_doc_url),
        ("gmail", gmail),
        ("location_text", location_text),
    ):
        if not value or not str(value).strip():
            raise ApplicationError(422, f"{name} is required")

    edit_token = generate_edit_token()
    row = await _get_store().insert_application(
        {
            "full_name": full_name,
            "dob": dob,
            "ownership_doc_url": ownership_doc_url,
            "gmail": gmail,
            "location_text": location_text,
            "application_status": "submitted",
            "edit_token_hash": hash_edit_token(edit_token),
        }
    )
    return {**row, "edit_token": edit_token}


def _check_edit_token(app: dict[str, Any], edit_token: str) -> None:
    stored = app.get("edit_token_hash") or ""
    if not secrets.compare_digest(stored, hash_edit_token(edit_token)):
        raise ApplicationError(403, "Invalid edit token")


async def get_status(application_id: str, edit_token: str) -> dict[str, Any]:
    app = await _get_store().get_application(application_id)
    if app is None:
        raise ApplicationError(404, "Application not found")
    _check_edit_token(app, edit_token)
    return {
        "id": app["id"],
        "application_status": app["application_status"],
        "rejection_reason": app.get("rejection_reason"),
    }


async def resubmit_application(
    application_id: str, edit_token: str, updates: dict[str, Any]
) -> dict[str, Any]:
    """Applicant edits a rejected application → back to `submitted` (spec §2)."""
    app = await _get_store().get_application(application_id)
    if app is None:
        raise ApplicationError(404, "Application not found")
    _check_edit_token(app, edit_token)
    if app["application_status"] != "identity_rejected":
        raise ApplicationError(
            409,
            "Only a rejected application can be resubmitted "
            f"(current status: {app['application_status']})",
        )

    allowed = {"full_name", "dob", "ownership_doc_url", "gmail", "location_text"}
    payload = {k: v for k, v in updates.items() if k in allowed and v is not None}
    payload["application_status"] = "submitted"
    payload["rejection_reason"] = None
    row = await _get_store().update_application(application_id, payload)
    return {"id": row["id"], "application_status": row["application_status"]}


async def list_pending_applications() -> list[dict[str, Any]]:
    return await _get_store().list_by_status("submitted")


async def approve_application(
    application_id: str, community_pool_id: str, login_url: str = "https://gridright.app/login"
) -> dict[str, Any]:
    """Operator approves: create auth user, temp password, email it, assign
    pool, flip must_change_password (via the trigger reading user metadata).

    The auth user is created BEFORE the status flip so a failure there leaves
    the application reviewable rather than half-approved with no login.
    """
    if not community_pool_id:
        raise ApplicationError(422, "community_pool_id is required to approve")

    # Resolve the email transport FIRST — a misconfigured deploy (no SMTP, no
    # explicit console opt-in) fails loudly here, before any side effect, so
    # we never create an account whose credentials silently go nowhere.
    try:
        emailer = _get_emailer()
    except RuntimeError as exc:
        raise ApplicationError(500, str(exc))

    store = _get_store()
    app = await store.get_application(application_id)
    if app is None:
        raise ApplicationError(404, "Application not found")
    if app["application_status"] != "submitted":
        raise ApplicationError(
            409,
            f"Only a submitted application can be approved "
            f"(current status: {app['application_status']})",
        )

    temp_password = generate_temp_password()
    try:
        profile_id = await store.create_auth_seller(app["gmail"], temp_password)
    except Exception as exc:
        # Most common real-world failure: the applicant's email is already a
        # registered auth user (e.g. they signed up directly before applying).
        # Surface it as a clear conflict instead of an opaque 500; the
        # application stays 'submitted' so the operator can reject with reason.
        msg = str(exc).lower()
        if "already" in msg and ("regist" in msg or "exist" in msg):
            raise ApplicationError(
                409,
                f"A user with email {app['gmail']} already exists. "
                "Reject this application or have the applicant use a "
                "different email.",
            )
        logger.exception(
            "Auth user creation failed for application %s", application_id
        )
        raise ApplicationError(
            502, "Could not create the seller account; try again or check "
                 "the auth service."
        )

    # Assign the pool on both the profile and the application record.
    await store.set_profile_pool(profile_id, community_pool_id)
    await store.update_application(
        application_id,
        {
            "application_status": "identity_approved",
            "profile_id": profile_id,
            "community_pool_id": community_pool_id,
            "rejection_reason": None,
        },
    )

    # Email last: the account exists and is approved regardless of transport
    # success. A TRANSIENT send failure is logged (without the password) but
    # must not unwind the approval — configuration failures were already
    # caught loudly above, before any side effect.
    try:
        await emailer.send_temp_password(app["gmail"], temp_password, login_url)
    except Exception:
        logger.exception(
            "Temp-password email failed for application %s", application_id
        )

    return {
        "id": application_id,
        "application_status": "identity_approved",
        "profile_id": profile_id,
        "community_pool_id": community_pool_id,
    }


async def reject_application(application_id: str, reason: str) -> dict[str, Any]:
    """Operator rejects with a reason; applicant may later resubmit (spec §2)."""
    if not reason or not reason.strip():
        raise ApplicationError(422, "A rejection reason is required")

    store = _get_store()
    app = await store.get_application(application_id)
    if app is None:
        raise ApplicationError(404, "Application not found")
    if app["application_status"] != "submitted":
        raise ApplicationError(
            409,
            f"Only a submitted application can be rejected "
            f"(current status: {app['application_status']})",
        )

    await store.update_application(
        application_id,
        {"application_status": "identity_rejected", "rejection_reason": reason},
    )
    return {"id": application_id, "application_status": "identity_rejected"}
