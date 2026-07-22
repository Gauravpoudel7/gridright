"""Seller onboarding — identity application state machine (spec §3.1, §5).

Covers: submit → approve (pool assigned, temp password emailed via the fake
emailer and never surfaced in the response/logs), submit → reject → resubmit →
back to submitted, and invalid transitions.

Uses an in-memory ApplicationStore + a fake Emailer, mirroring the
DictMeterStore / FakeBadgeMinter pattern.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth import set_verifier, TokenVerifier
from app.services import onboarding


class DictApplicationStore(onboarding.ApplicationStore):
    def __init__(self):
        self.apps: dict[str, dict] = {}
        self.profiles_pool: dict[str, str] = {}
        self._next_id = 1
        self._next_profile = 1

    async def insert_application(self, payload):
        app_id = f"app-{self._next_id}"
        self._next_id += 1
        row = {"id": app_id, "profile_id": None, "community_pool_id": None,
               "rejection_reason": None, **payload}
        self.apps[app_id] = row
        return dict(row)

    async def get_application(self, application_id):
        row = self.apps.get(application_id)
        return dict(row) if row else None

    async def update_application(self, application_id, updates):
        if application_id not in self.apps:
            return None
        self.apps[application_id].update(updates)
        return dict(self.apps[application_id])

    async def list_by_status(self, status):
        return [dict(a) for a in self.apps.values()
                if a["application_status"] == status]

    async def create_auth_seller(self, email, temp_password):
        pid = f"profile-{self._next_profile}"
        self._next_profile += 1
        return pid

    async def set_profile_pool(self, profile_id, community_pool_id):
        self.profiles_pool[profile_id] = community_pool_id


class FakeEmailer(onboarding.Emailer):
    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []

    async def send_temp_password(self, to_email, temp_password, login_url):
        self.sent.append((to_email, temp_password, login_url))


class _OperatorVerifier(TokenVerifier):
    def verify(self, token: str) -> dict:
        return {"sub": "op-1", "role": "operator",
                "app_metadata": {"role": "operator"}}


@pytest.fixture
def store():
    s = DictApplicationStore()
    onboarding.set_store(s)
    yield s
    onboarding.set_store(None)


# autouse: approve_application resolves the email transport before any side
# effect and fails loudly when none is configured, so every test in this
# module gets the fake transport unless it explicitly clears it.
@pytest.fixture(autouse=True)
def emailer():
    e = FakeEmailer()
    onboarding.set_emailer(e)
    yield e
    onboarding.set_emailer(None)


@pytest.fixture
def client():
    set_verifier(_OperatorVerifier())
    with TestClient(app) as c:
        yield c
    set_verifier(None)


VALID_APP = {
    "full_name": "Ada Lovelace",
    "dob": "1990-12-10",
    "ownership_doc_url": "https://docs.example/deed.pdf",
    "gmail": "ada@gmail.com",
    "location_text": "12 Analytical Ave",
}


def test_submit_returns_edit_token_and_submitted(client, store, emailer):
    resp = client.post("/api/v1/applications", json=VALID_APP)
    assert resp.status_code == 201
    body = resp.json()
    assert body["application_status"] == "submitted"
    assert body["edit_token"].startswith("gr_app_")
    # meter_id must NOT be set at submission time (spec §1)
    assert "meter_id" not in store.apps[body["id"]]


def test_submit_missing_field_rejected(client, store):
    bad = {**VALID_APP, "full_name": ""}
    resp = client.post("/api/v1/applications", json=bad)
    assert resp.status_code == 422


def test_approve_creates_user_assigns_pool_emails_password(client, store, emailer):
    app_id = client.post("/api/v1/applications", json=VALID_APP).json()["id"]

    resp = client.post(
        f"/api/v1/operator/applications/{app_id}/approve",
        json={"community_pool_id": "pool-1"},
        headers={"Authorization": "Bearer op"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["application_status"] == "identity_approved"
    assert body["community_pool_id"] == "pool-1"
    profile_id = body["profile_id"]

    # Pool assigned on the profile
    assert store.profiles_pool[profile_id] == "pool-1"
    # Temp password emailed exactly once, to the applicant's gmail
    assert len(emailer.sent) == 1
    to_email, temp_password, _ = emailer.sent[0]
    assert to_email == "ada@gmail.com"
    assert temp_password  # non-empty
    # SECURITY: the temp password must NEVER appear in the API response (spec §4)
    assert temp_password not in resp.text


def test_approve_requires_pool(client, store):
    app_id = client.post("/api/v1/applications", json=VALID_APP).json()["id"]
    resp = client.post(
        f"/api/v1/operator/applications/{app_id}/approve",
        json={"community_pool_id": ""},
        headers={"Authorization": "Bearer op"},
    )
    assert resp.status_code == 422


def test_reject_then_resubmit_returns_to_submitted(client, store):
    submit = client.post("/api/v1/applications", json=VALID_APP).json()
    app_id, edit_token = submit["id"], submit["edit_token"]

    reject = client.post(
        f"/api/v1/operator/applications/{app_id}/reject",
        json={"reason": "Ownership doc unreadable"},
        headers={"Authorization": "Bearer op"},
    )
    assert reject.status_code == 200
    assert reject.json()["application_status"] == "identity_rejected"

    # Applicant checks status (token-gated)
    status = client.get(
        f"/api/v1/applications/{app_id}/status",
        params={"edit_token": edit_token},
    )
    assert status.json()["application_status"] == "identity_rejected"
    assert status.json()["rejection_reason"] == "Ownership doc unreadable"

    # Resubmit with a corrected doc → back to submitted
    resub = client.put(
        f"/api/v1/applications/{app_id}",
        json={"edit_token": edit_token,
              "ownership_doc_url": "https://docs.example/deed-v2.pdf"},
    )
    assert resub.status_code == 200
    assert resub.json()["application_status"] == "submitted"
    assert store.apps[app_id]["rejection_reason"] is None


def test_reject_requires_reason(client, store):
    app_id = client.post("/api/v1/applications", json=VALID_APP).json()["id"]
    resp = client.post(
        f"/api/v1/operator/applications/{app_id}/reject",
        json={"reason": "   "},
        headers={"Authorization": "Bearer op"},
    )
    assert resp.status_code == 422


def test_cannot_approve_already_approved(client, store):
    app_id = client.post("/api/v1/applications", json=VALID_APP).json()["id"]
    client.post(
        f"/api/v1/operator/applications/{app_id}/approve",
        json={"community_pool_id": "pool-1"},
        headers={"Authorization": "Bearer op"},
    )
    # Second approve is an invalid transition
    resp = client.post(
        f"/api/v1/operator/applications/{app_id}/approve",
        json={"community_pool_id": "pool-2"},
        headers={"Authorization": "Bearer op"},
    )
    assert resp.status_code == 409


def test_cannot_resubmit_non_rejected(client, store):
    submit = client.post("/api/v1/applications", json=VALID_APP).json()
    # Still 'submitted' — resubmit not allowed
    resp = client.put(
        f"/api/v1/applications/{submit['id']}",
        json={"edit_token": submit["edit_token"], "full_name": "New Name"},
    )
    assert resp.status_code == 409


def test_wrong_edit_token_rejected(client, store):
    submit = client.post("/api/v1/applications", json=VALID_APP).json()
    resp = client.get(
        f"/api/v1/applications/{submit['id']}/status",
        params={"edit_token": "gr_app_wrong"},
    )
    assert resp.status_code == 403


def test_pending_list_shows_submitted(client, store):
    client.post("/api/v1/applications", json=VALID_APP)
    resp = client.get(
        "/api/v1/operator/applications",
        headers={"Authorization": "Bearer op"},
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["application_status"] == "submitted"


def test_list_operator_only(client, store):
    """Seller role cannot list applications."""
    class _SellerVerifier(TokenVerifier):
        def verify(self, token: str) -> dict:
            return {"sub": "s-1", "role": "seller",
                    "app_metadata": {"role": "seller"}}
    set_verifier(_SellerVerifier())
    resp = client.get(
        "/api/v1/operator/applications",
        headers={"Authorization": "Bearer s"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_approve_duplicate_email_maps_to_409(store):
    """auth-user creation failing with 'already registered' surfaces as a
    clear 409 conflict, and the application stays reviewable."""
    class DuplicateEmailStore(DictApplicationStore):
        async def create_auth_seller(self, email, temp_password):
            raise Exception("A user with this email address has already been registered")

    dup = DuplicateEmailStore()
    onboarding.set_store(dup)
    row = await onboarding.submit_application(
        full_name="Ada Lovelace", dob="1990-12-10",
        ownership_doc_url="https://docs.example/deed.pdf",
        gmail="taken@gmail.com", location_text="12 Analytical Ave",
    )
    with pytest.raises(onboarding.ApplicationError) as exc:
        await onboarding.approve_application(row["id"], "pool-1")
    assert exc.value.status_code == 409
    assert "already exists" in exc.value.detail
    assert dup.apps[row["id"]]["application_status"] == "submitted"


@pytest.mark.asyncio
async def test_approve_other_auth_failure_maps_to_502(store):
    class BrokenAuthStore(DictApplicationStore):
        async def create_auth_seller(self, email, temp_password):
            raise Exception("connection reset by peer")

    broken = BrokenAuthStore()
    onboarding.set_store(broken)
    row = await onboarding.submit_application(
        full_name="Ada Lovelace", dob="1990-12-10",
        ownership_doc_url="https://docs.example/deed.pdf",
        gmail="ada@gmail.com", location_text="12 Analytical Ave",
    )
    with pytest.raises(onboarding.ApplicationError) as exc:
        await onboarding.approve_application(row["id"], "pool-1")
    assert exc.value.status_code == 502
    assert broken.apps[row["id"]]["application_status"] == "submitted"


# --- Email transport selection + temp-password hygiene (spec §4) ------------

def test_emailer_factory_fails_loud_when_unconfigured(monkeypatch):
    """No SMTP_HOST and no explicit console opt-in → RuntimeError, never a
    silent fall-through to a no-op transport."""
    onboarding.set_emailer(None)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("GRIDRIGHT_ALLOW_CONSOLE_EMAIL", raising=False)
    with pytest.raises(RuntimeError, match="No email transport configured"):
        onboarding._get_emailer()


def test_emailer_factory_console_requires_explicit_opt_in(monkeypatch):
    onboarding.set_emailer(None)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setenv("GRIDRIGHT_ALLOW_CONSOLE_EMAIL", "1")
    try:
        assert isinstance(onboarding._get_emailer(), onboarding.ConsoleEmailer)
    finally:
        onboarding.set_emailer(None)


def test_emailer_factory_prefers_smtp_when_configured(monkeypatch):
    onboarding.set_emailer(None)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("GRIDRIGHT_ALLOW_CONSOLE_EMAIL", "1")  # SMTP still wins
    try:
        assert isinstance(onboarding._get_emailer(), onboarding.SMTPEmailer)
    finally:
        onboarding.set_emailer(None)


@pytest.mark.asyncio
async def test_console_emailer_never_logs_password(caplog):
    """The dev console transport must not write the plaintext temp password to
    any log line or stdout (spec §4)."""
    import logging
    secret = "SUPER-SECRET-TEMP-PASSWORD-XYZ"
    with caplog.at_level(logging.DEBUG, logger="app.services.onboarding"):
        await onboarding.ConsoleEmailer().send_temp_password(
            "ada@gmail.com", secret, "https://gridright.app/login"
        )
    assert secret not in caplog.text
    assert "ada@gmail.com" in caplog.text  # the notice itself IS logged


@pytest.mark.asyncio
async def test_approve_fails_loud_before_side_effects_when_email_unconfigured(
    store, monkeypatch,
):
    """A misconfigured deploy (no transport) rejects the approval BEFORE
    creating the auth user — credentials are never silently dropped."""
    onboarding.set_emailer(None)  # no injected transport
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("GRIDRIGHT_ALLOW_CONSOLE_EMAIL", raising=False)

    row = await onboarding.submit_application(
        full_name="Ada Lovelace", dob="1990-12-10",
        ownership_doc_url="https://docs.example/deed.pdf",
        gmail="ada@gmail.com", location_text="12 Analytical Ave",
    )
    with pytest.raises(onboarding.ApplicationError) as exc:
        await onboarding.approve_application(row["id"], "pool-1")
    assert exc.value.status_code == 500

    # No side effects: still submitted, no auth user, no pool assignment.
    assert store.apps[row["id"]]["application_status"] == "submitted"
    assert store.apps[row["id"]]["profile_id"] is None
    assert store.profiles_pool == {}


@pytest.mark.asyncio
async def test_smtp_emailer_send_never_logs_password(caplog, monkeypatch):
    """Exercise the real SMTPEmailer.send path against a stubbed smtplib and
    assert the password reaches ONLY the message body, never a log record."""
    import logging
    import smtplib

    secret = "SUPER-SECRET-TEMP-PASSWORD-ABC"
    sent_messages = []

    class _StubSMTP:
        def __init__(self, host, port, timeout=None):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def starttls(self):
            pass
        def login(self, user, password):
            pass
        def send_message(self, msg):
            sent_messages.append(msg)

    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setattr(smtplib, "SMTP", _StubSMTP)

    with caplog.at_level(logging.DEBUG):
        await onboarding.SMTPEmailer().send_temp_password(
            "ada@gmail.com", secret, "https://gridright.app/login"
        )

    assert len(sent_messages) == 1
    assert secret in sent_messages[0].get_content()  # delivered to the email
    assert secret not in caplog.text                 # never to a log line
