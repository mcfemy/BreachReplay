import pytest
from unittest.mock import patch, MagicMock
from io import BytesIO
from sqlalchemy import select

from app.models.user import User
from app.models.audit_log import AuditLog
from app.models.breach_document import BreachDocument
from app.core.security import hash_password

pytestmark = pytest.mark.asyncio


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ─── Admin User Management Tests ──────────────────────────────────────────────

async def test_list_users_as_admin(client, admin_user, test_user, db):
    """Admin can list all users in their own organization."""
    response = await client.get("/api/v1/admin/users", headers=auth_headers(admin_user["token"]))
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 2
    assert any(u["email"] == admin_user["user"].email for u in data)
    assert any(u["email"] == test_user["user"].email for u in data)


async def test_list_users_as_non_admin(client, test_user):
    """Standard user is blocked from listing users (403 Forbidden)."""
    response = await client.get("/api/v1/admin/users", headers=auth_headers(test_user["token"]))
    assert response.status_code == 403


async def test_list_users_unauthenticated(client):
    """Unauthenticated client is blocked from listing users (403 Forbidden)."""
    response = await client.get("/api/v1/admin/users")
    assert response.status_code == 403


# ─── Toggle User Active Status Tests ──────────────────────────────────────────

async def test_toggle_user_active_success(client, admin_user, test_user, db):
    """Admin can toggle the active status of another user, creating an audit log."""
    target_user = test_user["user"]
    initial_active_state = target_user.is_active

    response = await client.patch(
        f"/api/v1/admin/users/{target_user.id}/toggle-active",
        headers=auth_headers(admin_user["token"]),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["is_active"] == (not initial_active_state)

    # Verify database state was updated
    await db.refresh(target_user)
    assert target_user.is_active == (not initial_active_state)

    # Verify Audit log was created in the database
    result = await db.execute(
        select(AuditLog).where(
            AuditLog.action == ("user_deactivated" if initial_active_state else "user_activated")
        )
    )
    audit_log = result.scalar_one_or_none()
    assert audit_log is not None
    assert audit_log.user_id == admin_user["user"].id
    assert audit_log.details["target_user_id"] == target_user.id


async def test_toggle_user_active_self_fails(client, admin_user):
    """Admin is prevented from deactivating themselves."""
    response = await client.patch(
        f"/api/v1/admin/users/{admin_user['user'].id}/toggle-active",
        headers=auth_headers(admin_user["token"]),
    )
    assert response.status_code == 400
    assert "Admins cannot deactivate themselves" in response.json()["detail"]


async def test_toggle_user_active_wrong_org_fails(client, admin_user, db):
    """Admin cannot deactivate a user in a different organization."""
    from app.models.organization import Organization
    other_org = Organization(name="Other Org", slug="other-org-slug")
    db.add(other_org)
    await db.flush()

    other_user = User(
        email="other@example.com",
        hashed_password=hash_password("StrongPass1!"),
        full_name="Other User",
        role="analyst",
        organization_id=other_org.id,
    )
    db.add(other_user)
    await db.flush()

    response = await client.patch(
        f"/api/v1/admin/users/{other_user.id}/toggle-active",
        headers=auth_headers(admin_user["token"]),
    )
    assert response.status_code == 404
    assert "User not found in organization" in response.json()["detail"]


# ─── Role Update Tests ────────────────────────────────────────────────────────

async def test_update_user_role_success(client, admin_user, test_user, db):
    """Admin can change a user's role to a valid permission tier."""
    target_user = test_user["user"]
    assert target_user.role == "analyst"

    response = await client.patch(
        f"/api/v1/admin/users/{target_user.id}/role",
        headers=auth_headers(admin_user["token"]),
        json={"role": "ciso"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "ciso"

    # Verify DB updated
    await db.refresh(target_user)
    assert target_user.role == "owner"

    # Verify Audit log was logged
    result = await db.execute(
        select(AuditLog).where(AuditLog.action == "user_role_updated")
    )
    audit_log = result.scalar_one_or_none()
    assert audit_log is not None
    assert audit_log.user_id == admin_user["user"].id
    assert audit_log.details["new_role"] == "ciso"
    assert audit_log.details["old_role"] == "analyst"


async def test_update_user_role_invalid_role(client, admin_user, test_user):
    """Role updates must be validated against the allowed roles schema."""
    target_user = test_user["user"]
    response = await client.patch(
        f"/api/v1/admin/users/{target_user.id}/role",
        headers=auth_headers(admin_user["token"]),
        json={"role": "superuser"},
    )
    assert response.status_code == 400
    assert "Role must be one of" in response.json()["detail"]


# ─── Audit Log Retrieval Tests ────────────────────────────────────────────────

async def test_list_audit_logs_success(client, admin_user, db):
    """Admin can fetch paginated audit logs for their organization."""
    from app.services.audit import log_action
    await log_action(
        db,
        action="manual_test_action",
        user_id=admin_user["user"].id,
        organization_id=admin_user["user"].organization_id,
        details={"test": "data"},
    )

    response = await client.get(
        "/api/v1/admin/audit-logs",
        headers=auth_headers(admin_user["token"]),
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["action"] == "manual_test_action"
    assert data[0]["details"] == {"test": "data"}


# ─── Ingestion Upload Tests ───────────────────────────────────────────────────

async def test_upload_document_unsupported_format(client, admin_user):
    """Upload endpoint blocks non-pdf/txt formats."""
    file_content = b"fake executable content"
    files = {"file": ("malicious.exe", BytesIO(file_content), "application/octet-stream")}

    response = await client.post(
        "/api/v1/scenarios/upload-document",
        headers=auth_headers(admin_user["token"]),
        files=files,
    )
    assert response.status_code == 400
    assert "Only .pdf, .txt, and .docx file formats are supported" in response.json()["detail"]


async def test_upload_document_success(client, admin_user, db):
    """Upload endpoint stores files, registers db state and queues celery background extraction."""
    file_content = b"fake pdf content"
    files = {"file": ("test_breach.pdf", BytesIO(file_content), "application/pdf")}

    with patch("app.pipeline.tasks.process_uploaded_document_task.delay") as mock_delay:
        mock_delay.return_value = MagicMock(id="mock-task-id")

        response = await client.post(
            "/api/v1/scenarios/upload-document",
            headers=auth_headers(admin_user["token"]),
            files=files,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["filename"] == "test_breach.pdf"
        assert data["status"] == "processing"

        # Verify database record exists
        result = await db.execute(
            select(BreachDocument).where(BreachDocument.filename == "test_breach.pdf")
        )
        doc = result.scalar_one_or_none()
        assert doc is not None
        assert doc.status == "processing"

        # Verify background extraction task was queued with correct document UUID
        mock_delay.assert_called_once_with(doc.id)
