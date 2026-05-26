import pytest
from io import BytesIO
from unittest.mock import patch, MagicMock
from sqlalchemy import select

from app.models.organization import Organization
from app.models.breach_document import BreachDocument

pytestmark = pytest.mark.asyncio


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_s3_upload_document_success(client, test_user, db):
    """Test that setting AWS environment variables triggers an S3 upload using boto3."""
    file_content = b"mock pdf content for S3 upload"
    files = {"file": ("test_breach_s3.pdf", BytesIO(file_content), "application/pdf")}

    # Mock settings to simulate AWS S3 is active
    with patch("app.core.config.settings.AWS_ACCESS_KEY_ID", "test-aws-key"), \
         patch("app.core.config.settings.AWS_SECRET_ACCESS_KEY", "test-aws-secret"), \
         patch("app.core.config.settings.S3_BUCKET", "prod-breach-bucket"), \
         patch("app.pipeline.tasks.process_uploaded_document_task.delay") as mock_delay:

        # Mock boto3 S3 client
        mock_s3_client = MagicMock()
        with patch("boto3.client", return_value=mock_s3_client) as mock_boto:
            response = await client.post(
                "/api/v1/scenarios/upload-document",
                headers=auth_headers(test_user["token"]),
                files=files,
            )
            assert response.status_code == 201
            data = response.json()
            assert data["filename"] == "test_breach_s3.pdf"

            # Check that boto3 put_object was called with correct parameters
            mock_boto.assert_called_once_with(
                "s3",
                aws_access_key_id="test-aws-key",
                aws_secret_access_key="test-aws-secret",
                region_name="us-east-1"
            )
            mock_s3_client.put_object.assert_called_once()

            # Verify file_key in database starts with s3://
            result = await db.execute(
                select(BreachDocument).where(BreachDocument.id == data["id"])
            )
            doc = result.scalar_one()
            assert doc.file_key.startswith("s3://prod-breach-bucket/uploads/")


async def test_s3_upload_fails_falls_back_to_local(client, test_user, db):
    """Test that if S3 upload raises an error, it gracefully falls back to local storage."""
    file_content = b"mock pdf content for fallback"
    files = {"file": ("test_fallback.pdf", BytesIO(file_content), "application/pdf")}

    with patch("app.core.config.settings.AWS_ACCESS_KEY_ID", "test-aws-key"), \
         patch("app.core.config.settings.AWS_SECRET_ACCESS_KEY", "test-aws-secret"), \
         patch("app.core.config.settings.S3_BUCKET", "prod-breach-bucket"), \
         patch("app.pipeline.tasks.process_uploaded_document_task.delay"):

        # Mock boto3 S3 client to raise an exception
        with patch("boto3.client", side_effect=Exception("S3 Connection Timeout")):
            response = await client.post(
                "/api/v1/scenarios/upload-document",
                headers=auth_headers(test_user["token"]),
                files=files,
            )
            assert response.status_code == 201
            data = response.json()

            # Verify file_key is a local filepath rather than an s3:// link
            result = await db.execute(
                select(BreachDocument).where(BreachDocument.id == data["id"])
            )
            doc = result.scalar_one()
            assert not doc.file_key.startswith("s3://")
            assert "uploads" in doc.file_key


async def test_billing_quota_upload_limit_starter_tier(client, test_user, db):
    """Test that starter tier organizations are blocked with 402 if they exceed 3 custom uploads."""
    # Seed 3 existing uploads
    for i in range(3):
        doc = BreachDocument(
            id=f"mock-doc-{i}",
            filename=f"doc_{i}.pdf",
            file_key=f"uploads/doc_{i}.pdf",
            status="completed",
            organization_id=test_user["org"].id,
            uploaded_by_user_id=test_user["user"].id
        )
        db.add(doc)
    await db.commit()

    # Attempt 4th upload
    file_content = b"excessive pdf content"
    files = {"file": ("doc_excess.pdf", BytesIO(file_content), "application/pdf")}
    
    response = await client.post(
        "/api/v1/scenarios/upload-document",
        headers=auth_headers(test_user["token"]),
        files=files,
    )
    assert response.status_code == 402
    assert "Starter subscription upload limit reached" in response.json()["detail"]


async def test_tenant_onboard_as_owner_success(client, admin_user, db):
    """Test that a platform owner can successfully onboard a new tenant organization."""
    # Owner user role is needed (CISO role translates to Owner in DB)
    from app.core.security import create_access_token
    owner_user = admin_user["user"]
    owner_user.role = "owner"
    db.add(owner_user)
    await db.commit()
    
    owner_token = create_access_token({"sub": owner_user.id})

    payload = {
        "name": "Acme Corporation",
        "slug": "acme-slug",
        "tier": "enterprise"
    }

    response = await client.post(
        "/api/v1/admin/tenants/onboard",
        headers=auth_headers(owner_token),
        json=payload
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Acme Corporation"
    assert data["slug"] == "acme-slug"
    assert data["tier"] == "enterprise"

    # Verify organization exists in the database
    result = await db.execute(select(Organization).where(Organization.slug == "acme-slug"))
    org = result.scalar_one_or_none()
    assert org is not None
    assert org.tier == "enterprise"


async def test_tenant_onboard_non_owner_blocked(client, admin_user):
    """Test that administrative users (without Owner tier) are blocked from tenant onboarding."""
    # Standard admin (role="admin")
    payload = {
        "name": "Acme Corporation",
        "slug": "acme-slug",
        "tier": "enterprise"
    }
    response = await client.post(
        "/api/v1/admin/tenants/onboard",
        headers=auth_headers(admin_user["token"]),
        json=payload
    )
    assert response.status_code == 403
    assert "Platform onboarding requires OWNER/CISO authority" in response.json()["detail"]
