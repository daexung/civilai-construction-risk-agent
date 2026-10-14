from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.api import admin
from backend.api.main import app


ADMIN_ID = "2e50c76d-b3d0-4cc1-9bf9-918b0eb4b102"
MEMBER_ID = "9e2818ea-1451-465b-98e0-0011fd23fa50"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADMIN_USER_IDS", ADMIN_ID)

    def identity(authorization):
        if authorization == "Bearer admin-token":
            return ADMIN_ID
        if authorization == "Bearer member-token":
            return MEMBER_ID
        raise HTTPException(401, "invalid test token")

    monkeypatch.setattr(admin.chat_storage, "identity", identity)
    return TestClient(app)


@pytest.mark.parametrize("path", [
    "/api/admin/summary", "/api/admin/answer-feedback", "/api/admin/feedback", "/api/admin/runs",
    "/api/admin/answer-feedback/2e50c76d-b3d0-4cc1-9bf9-918b0eb4b102",
    "/api/admin/feedback/2e50c76d-b3d0-4cc1-9bf9-918b0eb4b102",
    "/api/admin/runs/2e50c76d-b3d0-4cc1-9bf9-918b0eb4b102",
])
def test_admin_endpoints_require_verified_allowlisted_user(client, path):
    anonymous = client.get(path, headers={"X-User-ID": ADMIN_ID, "X-Role": "admin"})
    assert anonymous.status_code == 401
    assert anonymous.headers["cache-control"] == "private, no-store"
    assert anonymous.headers["x-robots-tag"] == "noindex, nofollow, noarchive"

    non_admin = client.get(path, headers={"Authorization": "Bearer member-token", "X-User-ID": ADMIN_ID})
    assert non_admin.status_code == 403


def test_admin_allowlist_is_fail_closed(monkeypatch):
    monkeypatch.setattr(admin.chat_storage, "identity", lambda _authorization: ADMIN_ID)
    monkeypatch.delenv("ADMIN_USER_IDS", raising=False)
    with pytest.raises(HTTPException) as unset:
        admin._admin_user("Bearer test")
    assert unset.value.status_code == 403

    monkeypatch.setenv("ADMIN_USER_IDS", "not-a-uuid")
    with pytest.raises(HTTPException) as malformed:
        admin._admin_user("Bearer test")
    assert malformed.value.status_code == 503

    monkeypatch.setenv("ADMIN_USER_IDS", f"{ADMIN_ID},")
    with pytest.raises(HTTPException) as empty_entry:
        admin._admin_user("Bearer test")
    assert empty_entry.value.status_code == 503

    monkeypatch.setenv("ADMIN_USER_IDS", f"{ADMIN_ID},{MEMBER_ID}")
    assert admin._admin_user("Bearer test") == ADMIN_ID
    assert UUID(admin._admin_user("Bearer test"))


def test_admin_query_inputs_are_bounded(client):
    bad_period = client.get("/api/admin/summary?period=all", headers={"Authorization": "Bearer admin-token"})
    assert bad_period.status_code == 422
    bad_page = client.get("/api/admin/runs?page=10001", headers={"Authorization": "Bearer admin-token"})
    assert bad_page.status_code == 422
