"""
Stripe billing routes — checkout, webhook, subscription status, customer portal.
"""
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.organization import Organization
from app.models.user import User

router = APIRouter(prefix="/billing", tags=["billing"])
logger = get_logger(__name__)


@router.post("/create-checkout")
async def create_checkout(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe Checkout session for Enterprise tier upgrade."""
    if not settings.STRIPE_SECRET_KEY or not settings.STRIPE_PRICE_ID_ENTERPRISE:
        raise HTTPException(status_code=503, detail="Billing not configured")

    stripe.api_key = settings.STRIPE_SECRET_KEY

    org_id = current_user.organization_id
    stripe_customer_id = None

    if org_id:
        result = await db.execute(select(Organization).where(Organization.id == org_id))
        org = result.scalar_one_or_none()
        if org:
            stripe_customer_id = org.stripe_customer_id
            if org.tier == "enterprise":
                raise HTTPException(status_code=400, detail="Already on Enterprise tier")

    checkout_params: dict = {
        "mode": "subscription",
        "line_items": [{"price": settings.STRIPE_PRICE_ID_ENTERPRISE, "quantity": 1}],
        "success_url": f"{settings.FRONTEND_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{settings.FRONTEND_URL}/billing/cancel",
        "allow_promotion_codes": True,
        "billing_address_collection": "required",
        "metadata": {
            "user_id": current_user.id,
            "org_id": org_id or "",
        },
    }

    if stripe_customer_id:
        checkout_params["customer"] = stripe_customer_id
    elif current_user.email:
        checkout_params["customer_email"] = current_user.email

    session = stripe.checkout.Session.create(**checkout_params)
    return {"checkout_url": session.url, "session_id": session.id}


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Stripe webhook events — verify signature before processing."""
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Billing not configured")

    stripe.api_key = settings.STRIPE_SECRET_KEY
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(data, db)
    elif event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
        await _handle_subscription_change(data, db)
    elif event_type == "invoice.payment_failed":
        logger.warning("Payment failed for customer %s", data.get("customer"))

    return {"received": True}


async def _handle_checkout_completed(session_obj: dict, db: AsyncSession):
    org_id = session_obj.get("metadata", {}).get("org_id")
    stripe_customer_id = session_obj.get("customer")
    if not org_id:
        return

    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if org:
        org.stripe_customer_id = stripe_customer_id
        org.tier = "enterprise"
        await db.commit()
        logger.info("Org %s upgraded to enterprise, Stripe customer %s", org_id, stripe_customer_id)


async def _handle_subscription_change(subscription: dict, db: AsyncSession):
    stripe_customer_id = subscription.get("customer")
    sub_status = subscription.get("status")

    result = await db.execute(
        select(Organization).where(Organization.stripe_customer_id == stripe_customer_id)
    )
    org = result.scalar_one_or_none()
    if not org:
        return

    if sub_status in ("active", "trialing"):
        org.tier = "enterprise"
    elif sub_status in ("canceled", "unpaid", "past_due"):
        org.tier = "starter"
    await db.commit()
    logger.info("Org %s subscription status=%s → tier=%s", org.id, sub_status, org.tier)


@router.get("/subscription")
async def get_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return current subscription/tier info for the user's org."""
    if not current_user.organization_id:
        return {"tier": "free", "status": "active", "features": _free_features()}

    result = await db.execute(
        select(Organization).where(Organization.id == current_user.organization_id)
    )
    org = result.scalar_one_or_none()
    if not org:
        return {"tier": "free", "status": "active", "features": _free_features()}

    if not settings.STRIPE_SECRET_KEY or not org.stripe_customer_id:
        return {
            "tier": org.tier,
            "status": "active",
            "features": _tier_features(org.tier),
            "stripe_customer_id": None,
        }

    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        subs = stripe.Subscription.list(customer=org.stripe_customer_id, limit=1, status="all")
        sub = subs.data[0] if subs.data else None
    except Exception:
        sub = None

    return {
        "tier": org.tier,
        "status": sub.status if sub else "none",
        "current_period_end": sub.current_period_end if sub else None,
        "cancel_at_period_end": sub.cancel_at_period_end if sub else False,
        "features": _tier_features(org.tier),
        "stripe_customer_id": org.stripe_customer_id,
    }


@router.post("/portal")
async def create_portal_session(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe Customer Portal session for subscription management."""
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Billing not configured")

    if not current_user.organization_id:
        raise HTTPException(status_code=400, detail="No organization found")

    result = await db.execute(
        select(Organization).where(Organization.id == current_user.organization_id)
    )
    org = result.scalar_one_or_none()
    if not org or not org.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account found. Please subscribe first.")

    stripe.api_key = settings.STRIPE_SECRET_KEY
    portal = stripe.billing_portal.Session.create(
        customer=org.stripe_customer_id,
        return_url=f"{settings.FRONTEND_URL}/settings",
    )
    return {"portal_url": portal.url}


def _free_features() -> list[str]:
    return [
        "Solo play on all public scenarios",
        "Remote multiplayer (up to 4 players)",
        "Basic debrief report",
        "Community leaderboard",
    ]


def _tier_features(tier: str) -> list[str]:
    if tier in ("enterprise", "mssp"):
        return [
            "Everything in Free",
            "Team analytics dashboard",
            "Compliance export (NIST, HIPAA, SOC 2)",
            "Private scenario upload",
            "Completion certificates",
            "Multiplayer up to 8 players",
            "Priority support",
            "SSO / SAML",
            "White-label (MSSP only)" if tier == "mssp" else "",
        ]
    if tier == "team":
        return [
            "Everything in Free",
            "Team analytics",
            "Completion certificates",
            "Multiplayer up to 8 players",
        ]
    return _free_features()
