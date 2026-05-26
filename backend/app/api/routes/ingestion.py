import asyncio
import os
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, ConfigDict
from typing import List, Optional

from app.db.session import get_db
from app.models.user import User
from app.models.breach_document import BreachDocument
from app.core.security import get_current_user
from app.pipeline.tasks import process_uploaded_document_task

router = APIRouter(prefix="/scenarios", tags=["ingestion"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


class BreachDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    filename: str
    status: str
    organization_id: str
    uploaded_by_user_id: str
    extracted_scenario_id: Optional[str]
    created_at: datetime


@router.post("/upload-document", response_model=BreachDocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a breach disclosure PDF or text file for automated Claude scenario extraction."""
    # Enforce organization membership
    if not current_user.organization_id:
        raise HTTPException(status_code=400, detail="User must belong to an organization to upload documents")

    # Enforce Subscription/Billing Quotas based on Organization Tier
    from app.models.organization import Organization
    org_result = await db.execute(
        select(Organization).where(Organization.id == current_user.organization_id)
    )
    org = org_result.scalar_one_or_none()
    if org and org.tier == "starter":
        count_result = await db.execute(
            select(func.count()).select_from(BreachDocument).where(
                BreachDocument.organization_id == org.id,
                BreachDocument.status != "failed",
            )
        )
        if count_result.scalar() >= 3:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Starter subscription upload limit reached (max 3 custom documents). Please upgrade your subscription tier."
            )

    # Validate file type
    filename = file.filename or "document.txt"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".pdf", ".txt", ".docx"):
        raise HTTPException(status_code=400, detail="Only .pdf, .txt, and .docx file formats are supported")

    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read uploaded file: {str(e)}")

    _MAX_BYTES = 20 * 1024 * 1024  # 20 MB
    if len(content) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 20 MB size limit")

    from app.core.config import settings

    doc_id = str(uuid.uuid4())
    save_filename = f"{doc_id}{ext}"
    s3_uploaded = False
    file_key = ""

    # Check if AWS settings are configured for S3 upload
    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY and settings.S3_BUCKET:
        try:
            import boto3
            s3_client = boto3.client(
                "s3",
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION
            )
            s3_key = f"uploads/{save_filename}"
            await asyncio.to_thread(
                s3_client.put_object,
                Bucket=settings.S3_BUCKET,
                Key=s3_key,
                Body=content,
                ContentType=file.content_type or "application/octet-stream",
            )
            file_key = f"s3://{settings.S3_BUCKET}/{s3_key}"
            s3_uploaded = True
        except Exception:
            # S3 failed, fall back to local
            s3_uploaded = False

    if not s3_uploaded:
        file_path = os.path.join(UPLOAD_DIR, save_filename)
        try:
            with open(file_path, "wb") as f:
                f.write(content)
            file_key = file_path
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to write file to local disk: {str(e)}")

    # Create BreachDocument DB record
    doc = BreachDocument(
        id=doc_id,
        filename=filename,
        file_key=file_key,
        status="processing",
        organization_id=current_user.organization_id,
        uploaded_by_user_id=current_user.id,
    )
    db.add(doc)
    await db.commit()

    # Trigger async Celery ingestion task
    process_uploaded_document_task.delay(doc.id)

    return BreachDocumentOut.model_validate(doc)


@router.get("/documents", response_model=List[BreachDocumentOut])
async def list_documents(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List breach disclosure documents uploaded by the user's organization."""
    if not current_user.organization_id:
        return []
    result = await db.execute(
        select(BreachDocument)
        .where(BreachDocument.organization_id == current_user.organization_id)
        .order_by(BreachDocument.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [BreachDocumentOut.model_validate(d) for d in result.scalars().all()]
