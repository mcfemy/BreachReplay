from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.routes.auth import get_current_user
from app.db.session import get_db
from app.models.team import Team, TeamMember
from app.models.user import User

router = APIRouter(prefix="/teams", tags=["teams"])


class TeamCreate(BaseModel):
    name: str


class InvitePayload(BaseModel):
    email: str


class MemberOut(BaseModel):
    user_id: str
    full_name: Optional[str]
    email: str
    role: str
    xp_total: int
    career_tier: str
    joined_at: str


class TeamOut(BaseModel):
    id: str
    name: str
    organization_id: str
    total_xp: int
    member_count: int
    created_at: str
    members: List[MemberOut] = []


class LeaderboardEntry(BaseModel):
    rank: int
    team_id: str
    team_name: str
    total_xp: int
    member_count: int


async def _get_org_id(user: User) -> str:
    if not user.organization_id:
        raise HTTPException(status_code=400, detail="You must belong to an organization to use teams. Upload a document first to auto-create one.")
    return user.organization_id


@router.post("/", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
async def create_team(
    payload: TeamCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = await _get_org_id(current_user)
    name = payload.name.strip()
    if not name or len(name) > 100:
        raise HTTPException(status_code=400, detail="Team name must be 1–100 characters")

    # Prevent duplicate names within org
    existing = await db.execute(
        select(Team).where(Team.organization_id == org_id, Team.name == name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"A team named '{name}' already exists in your org")

    team = Team(name=name, organization_id=org_id, created_by_user_id=current_user.id)
    db.add(team)
    await db.flush()

    member = TeamMember(team_id=team.id, user_id=current_user.id, role="captain")
    db.add(member)
    await db.commit()
    await db.refresh(team)

    return TeamOut(
        id=team.id,
        name=team.name,
        organization_id=team.organization_id,
        total_xp=team.total_xp,
        member_count=1,
        created_at=team.created_at.isoformat(),
        members=[
            MemberOut(
                user_id=current_user.id,
                full_name=current_user.full_name,
                email=current_user.email,
                role="captain",
                xp_total=current_user.xp_total,
                career_tier=current_user.career_tier,
                joined_at=member.joined_at.isoformat(),
            )
        ],
    )


@router.get("/", response_model=List[TeamOut])
async def list_org_teams(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.organization_id:
        return []
    org_id = current_user.organization_id
    result = await db.execute(
        select(Team)
        .options(selectinload(Team.members).selectinload(TeamMember.user))
        .where(Team.organization_id == org_id)
        .order_by(Team.total_xp.desc())
    )
    teams = result.scalars().all()
    out = []
    for t in teams:
        members = [
            MemberOut(
                user_id=m.user_id,
                full_name=m.user.full_name if m.user else None,
                email=m.user.email if m.user else "",
                role=m.role,
                xp_total=m.user.xp_total if m.user else 0,
                career_tier=m.user.career_tier if m.user else "recruit",
                joined_at=m.joined_at.isoformat(),
            )
            for m in t.members
        ]
        out.append(TeamOut(
            id=t.id,
            name=t.name,
            organization_id=t.organization_id,
            total_xp=t.total_xp,
            member_count=len(t.members),
            created_at=t.created_at.isoformat(),
            members=members,
        ))
    return out


@router.post("/{team_id}/join", status_code=status.HTTP_200_OK)
async def join_team(
    team_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = await _get_org_id(current_user)

    result = await db.execute(select(Team).where(Team.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if team.organization_id != org_id:
        raise HTTPException(status_code=403, detail="Team belongs to a different organization")

    existing = await db.execute(
        select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == current_user.id)
    )
    if existing.scalar_one_or_none():
        return {"message": "Already a member of this team"}

    member = TeamMember(team_id=team_id, user_id=current_user.id, role="member")
    db.add(member)
    await db.commit()
    return {"message": f"Joined team '{team.name}'"}


@router.post("/{team_id}/leave", status_code=status.HTTP_200_OK)
async def leave_team(
    team_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = await _get_org_id(current_user)

    # Confirm team belongs to user's org before allowing leave
    team_result = await db.execute(select(Team).where(Team.id == team_id))
    team = team_result.scalar_one_or_none()
    if not team or team.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Team not found")

    result = await db.execute(
        select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == current_user.id)
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="You are not a member of this team")
    await db.delete(member)
    await db.commit()
    return {"message": "Left the team"}


@router.get("/leaderboard", response_model=List[LeaderboardEntry])
async def team_leaderboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the top 20 teams in the user's org ranked by total XP."""
    if not current_user.organization_id:
        return []
    org_id = current_user.organization_id

    result = await db.execute(
        select(Team, func.count(TeamMember.id).label("mc"))
        .outerjoin(TeamMember, TeamMember.team_id == Team.id)
        .where(Team.organization_id == org_id)
        .group_by(Team.id)
        .order_by(Team.total_xp.desc())
        .limit(20)
    )
    rows = result.all()
    return [
        LeaderboardEntry(
            rank=i + 1,
            team_id=row.Team.id,
            team_name=row.Team.name,
            total_xp=row.Team.total_xp,
            member_count=row.mc,
        )
        for i, row in enumerate(rows)
    ]


@router.post("/{team_id}/invite")
async def invite_to_team(
    team_id: str,
    payload: InvitePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send an email invite to join this team. Caller must be a member."""
    org_id = current_user.organization_id
    if not org_id:
        raise HTTPException(status_code=400, detail="You must belong to an organization to invite others")

    team_result = await db.execute(select(Team).where(Team.id == team_id))
    team = team_result.scalar_one_or_none()
    if not team or team.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Team not found")

    member_result = await db.execute(
        select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == current_user.id)
    )
    if not member_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Only team members can send invites")

    from app.services.email_service import send_team_invite_email_v2
    inviter_name = current_user.full_name or current_user.email
    sent = send_team_invite_email_v2(
        to_email=payload.email,
        inviter_name=inviter_name,
        team_name=team.name,
        join_url="https://breachreplay.com/teams",
    )
    if sent:
        return {"message": f"Invite sent to {payload.email}"}
    return {"message": f"Email not configured — share this link: https://breachreplay.com/teams"}


@router.post("/{team_id}/sync-xp")
async def sync_team_xp(
    team_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Recalculate team XP from member XP totals. Any member can trigger this."""
    result = await db.execute(
        select(Team)
        .options(selectinload(Team.members).selectinload(TeamMember.user))
        .where(Team.id == team_id)
    )
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    member_ids = {m.user_id for m in team.members}
    if current_user.id not in member_ids:
        raise HTTPException(status_code=403, detail="Only team members can sync XP")

    team.total_xp = sum(m.user.xp_total for m in team.members if m.user)
    await db.commit()
    return {"team_id": team_id, "total_xp": team.total_xp}
