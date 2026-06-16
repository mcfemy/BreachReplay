import os
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.db.session import get_db
from app.models.breach_document import BreachDocument
from app.models.organization import Organization
from app.models.scenario import Scenario
from app.models.user import User

router = APIRouter(prefix="/orgs", tags=["orgs"])

ALLOWED_TYPES = {"application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text/plain"}
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

UPLOAD_ROOT = os.environ.get("UPLOAD_DIR", "/tmp/breachreplay_uploads")


class DocumentOut(BaseModel):
    id: str
    filename: str
    status: str
    created_at: str
    extracted_scenario_id: Optional[str] = None


class PrivateScenarioOut(BaseModel):
    id: str
    title: str
    difficulty: Optional[str]
    industry_vertical: Optional[str]
    extraction_confidence: Optional[float]
    status: str
    created_at: str


async def _ensure_org(user: User, db: AsyncSession) -> Organization:
    """Return user's org or auto-create a personal org so solo users can upload."""
    if user.organization_id:
        result = await db.execute(select(Organization).where(Organization.id == user.organization_id))
        org = result.scalar_one_or_none()
        if org:
            return org

    # Auto-create personal org
    domain = user.email.split("@")[-1].split(".")[0]
    name = user.full_name or domain
    slug = f"{name.lower().replace(' ', '-')}-{user.id[:8]}"
    org = Organization(name=name, slug=slug, tier="starter")
    db.add(org)
    await db.flush()
    user.organization_id = org.id
    await db.commit()
    await db.refresh(user)
    return org


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_breach_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a post-mortem PDF/DOCX/TXT — Claude extracts a private simulation scenario scoped to your org."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{ext}'. Allowed: pdf, docx, txt")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large — maximum 10 MB")
    if len(content) < 200:
        raise HTTPException(status_code=400, detail="File is too small to extract a scenario from")

    org = await _ensure_org(current_user, db)

    # Persist file to local upload dir
    org_dir = os.path.join(UPLOAD_ROOT, org.id)
    os.makedirs(org_dir, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(org_dir, safe_name)
    with open(file_path, "wb") as f:
        f.write(content)

    doc = BreachDocument(
        filename=file.filename or safe_name,
        file_key=file_path,
        organization_id=org.id,
        uploaded_by_user_id=current_user.id,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    from app.pipeline.tasks import process_uploaded_document_task
    process_uploaded_document_task.delay(doc.id)

    return {
        "document_id": doc.id,
        "filename": doc.filename,
        "status": "processing",
        "message": "Document received — Claude is generating your private scenario. Check status in 60-90 seconds.",
    }


@router.get("/documents", response_model=List[DocumentOut])
async def list_documents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all documents uploaded by this user's org and their processing status."""
    if not current_user.organization_id:
        return []
    result = await db.execute(
        select(BreachDocument)
        .where(BreachDocument.organization_id == current_user.organization_id)
        .order_by(BreachDocument.created_at.desc())
        .limit(50)
    )
    docs = result.scalars().all()
    return [
        DocumentOut(
            id=d.id,
            filename=d.filename,
            status=d.status,
            created_at=d.created_at.isoformat(),
            extracted_scenario_id=d.extracted_scenario_id,
        )
        for d in docs
    ]


@router.get("/private-scenarios", response_model=List[PrivateScenarioOut])
async def list_private_scenarios(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all private scenarios owned by this user's organization."""
    if not current_user.organization_id:
        return []
    result = await db.execute(
        select(Scenario)
        .where(
            Scenario.is_private == True,  # noqa: E712
            Scenario.owner_org_id == current_user.organization_id,
        )
        .order_by(Scenario.created_at.desc())
        .limit(100)
    )
    scenarios = result.scalars().all()
    return [
        PrivateScenarioOut(
            id=s.id,
            title=s.title,
            difficulty=s.difficulty,
            industry_vertical=s.industry_vertical,
            extraction_confidence=s.extraction_confidence,
            status=s.status,
            created_at=s.created_at.isoformat(),
        )
        for s in scenarios
    ]
