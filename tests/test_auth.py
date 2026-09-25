"""Authentication tests -- docs/07_non_functional_requirements.md
(email + password, single role). Phase 10.

Password hashing tests need nothing external; the login/session tests
need Postgres, like tests/test_api.py, and skip without it.
"""

import os
from datetime import datetime, timedelta

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import users as users_cli
from app.auth import SESSION_COOKIE, hash_password, verify_password
from app.main import app
from app.models import User, UserSession

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://dpr_monitor:dpr_monitor@localhost:5432/dpr_monitor",
)

try:
    _engine = create_engine(DATABASE_URL)
    with _engine.connect():
        _DB_AVAILABLE = True
except Exception:
    _DB_AVAILABLE = False

needs_db = pytest.mark.skipif(
    not _DB_AVAILABLE,
    reason=f"no Postgres reachable at {DATABASE_URL} — start it with `docker compose up -d db`",
)

Session = sessionmaker(bind=_engine) if _DB_AVAILABLE else None

TEST_EMAIL = "phase10-auth-test@example.invalid"
TEST_PASSWORD = "correct horse battery"

# Routes reachable without logging in. Anything else under /api must 401.
PUBLIC_API_PATHS = {"/api/auth/login", "/api/auth/logout"}


# ---------------------------------------------------------------------------
# Password hashing (no DB)
# ---------------------------------------------------------------------------


def test_hash_roundtrip():
    stored = hash_password(TEST_PASSWORD)
    assert verify_password(TEST_PASSWORD, stored)
    assert not verify_password("wrong password", stored)


def test_hash_is_salted_and_not_plaintext():
    a, b = hash_password(TEST_PASSWORD), hash_password(TEST_PASSWORD)
    assert a != b
    assert TEST_PASSWORD not in a


def test_verify_rejects_malformed_hash():
    assert not verify_password(TEST_PASSWORD, "not-a-hash")
    assert not verify_password(TEST_PASSWORD, "bcrypt$1$2$3$4$5")


# ---------------------------------------------------------------------------
# Login / session / route protection (DB)
# ---------------------------------------------------------------------------


@pytest.fixture
def user():
    session = Session()
    user = User(email=TEST_EMAIL, password_hash=hash_password(TEST_PASSWORD))
    session.add(user)
    session.commit()
    try:
        yield user
    finally:
        session.query(UserSession).filter_by(user_id=user.id).delete()
        session.query(User).filter_by(id=user.id).delete()
        session.commit()
        session.close()


@pytest.fixture
def client():
    return TestClient(app)


def _login(client, email=TEST_EMAIL, password=TEST_PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


@needs_db
@pytest.mark.parametrize(
    "route",
    [r for r in app.routes if isinstance(r, APIRoute) and r.path.startswith("/api/")],
    ids=lambda r: f"{sorted(r.methods)[0]} {r.path}",
)
def test_every_api_route_requires_login(client, route):
    """Guards against a new endpoint being added without LOGIN_REQUIRED."""
    if route.path in PUBLIC_API_PATHS:
        pytest.skip("public by design")
    path = route.path.replace("{well_id}", "1").replace("{repair_id}", "1").replace(
        "{document_id}", "1"
    ).replace("{job_id}", "1")
    method = sorted(route.methods)[0]
    assert client.request(method, path).status_code == 401


def test_health_and_dashboard_shell_stay_public(client):
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200


@needs_db
def test_login_sets_httponly_cookie_and_grants_access(client, user):
    response = _login(client)
    assert response.status_code == 200
    assert response.json() == {"email": TEST_EMAIL}

    set_cookie = response.headers["set-cookie"]
    assert SESSION_COOKIE in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie

    assert client.get("/api/auth/me").json() == {"email": TEST_EMAIL}
    assert client.get("/api/wells").status_code == 200


@needs_db
def test_login_email_is_case_insensitive(client, user):
    assert _login(client, email="  Phase10-Auth-Test@Example.INVALID ").status_code == 200


@needs_db
def test_wrong_password_and_unknown_email_look_identical(client, user):
    wrong = _login(client, password="not the password")
    unknown = _login(client, email="nobody@example.invalid")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert SESSION_COOKIE not in client.cookies


@needs_db
def test_session_token_stored_only_as_hash(client, user):
    _login(client)
    token = client.cookies[SESSION_COOKIE]
    session = Session()
    try:
        stored = session.query(UserSession).filter_by(user_id=user.id).one()
        assert stored.token_hash != token
        assert token not in stored.token_hash
    finally:
        session.close()


@needs_db
def test_logout_invalidates_session_server_side(client, user):
    _login(client)
    token = client.cookies[SESSION_COOKIE]
    assert client.post("/api/auth/logout").status_code == 200

    # Replaying the old cookie must not work, even if a browser kept it.
    replay = TestClient(app, cookies={SESSION_COOKIE: token})
    assert replay.get("/api/wells").status_code == 401


@needs_db
def test_expired_session_rejected(client, user):
    _login(client)
    session = Session()
    try:
        session.query(UserSession).filter_by(user_id=user.id).update(
            {"expires_at": datetime.utcnow() - timedelta(minutes=1)}
        )
        session.commit()
    finally:
        session.close()
    assert client.get("/api/wells").status_code == 401


@needs_db
def test_deactivated_user_locked_out_immediately(client, user):
    _login(client)
    assert client.get("/api/wells").status_code == 200

    assert users_cli.main(["deactivate", TEST_EMAIL]) == 0
    assert client.get("/api/wells").status_code == 401
    assert _login(client).status_code == 401


@needs_db
def test_cli_set_password_changes_login(client, user, monkeypatch):
    monkeypatch.setattr(users_cli.getpass, "getpass", lambda prompt="": "a brand new passphrase")
    assert users_cli.main(["set-password", TEST_EMAIL]) == 0

    assert _login(client).status_code == 401
    assert _login(client, password="a brand new passphrase").status_code == 200


@needs_db
def test_cli_create_rejects_duplicate(user, monkeypatch):
    monkeypatch.setattr(users_cli.getpass, "getpass", lambda prompt="": "whatever-long-enough")
    assert users_cli.main(["create", TEST_EMAIL.upper()]) == 1
