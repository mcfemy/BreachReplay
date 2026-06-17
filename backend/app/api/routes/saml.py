"""SAML 2.0 SSO routes — SP-initiated flow using python3-saml (OneLogin library)."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, get_current_user, hash_password, require_admin
from app.db.session import get_db
from app.models.saml_config import OrganizationSAMLConfig
from app.models.user import User
from app.schemas.saml import SAMLConfigRequest, SAMLConfigResponse

router = APIRouter(prefix="/auth/saml", tags=["saml"])


def _sp_entity_id() -> str:
    return f"{settings.FRONTEND_URL}/api/v1/auth/saml/metadata"


def _acs_url() -> str:
    return f"{settings.FRONTEND_URL}/api/v1/auth/saml/acs"


def _saml_settings(config: OrganizationSAMLConfig) -> dict:
    cert = config.idp_x509_cert.strip()
    # Strip PEM headers if present
    cert = cert.replace("-----BEGIN CERTIFICATE-----", "").replace("-----END CERTIFICATE-----", "")
    cert = "".join(cert.split())
    return {
        "strict": True,
        "debug": settings.DEBUG,
        "sp": {
            "entityId": _sp_entity_id(),
            "assertionConsumerService": {
                "url": _acs_url(),
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "nameIdFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
            "x509cert": "",
            "privateKey": "",
        },
        "idp": {
            "entityId": config.idp_entity_id,
            "singleSignOnService": {
                "url": config.idp_sso_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": cert,
        },
        "security": {
            "authnRequestsSigned": False,
            "wantAssertionsSigned": True,
            "wantMessagesSigned": False,
            "wantXMLValidation": True,
            "signatureAlgorithm": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
        },
    }


def _prepare_request(request: Request, form_data: dict | None = None) -> dict:
    host = request.url.hostname or "breachreplay.com"
    https = "on" if request.url.scheme == "https" else "off"
    port = request.url.port
    return {
        "https": https,
        "http_host": host,
        "server_port": str(port or (443 if https == "on" else 80)),
        "script_name": request.url.path,
        "get_data": dict(request.query_params),
        "post_data": form_data or {},
    }


@router.get("/metadata")
async def saml_metadata():
    """SP metadata XML — register this URL in your IdP as the SP Entity ID."""
    try:
        from onelogin.saml2.settings import OneLogin_Saml2_Settings
    except ImportError:
        raise HTTPException(503, "SAML library not available")

    sp_only_settings = {
        "strict": True,
        "debug": False,
        "sp": {
            "entityId": _sp_entity_id(),
            "assertionConsumerService": {
                "url": _acs_url(),
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "nameIdFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        },
        "idp": {},
    }
    try:
        settings_obj = OneLogin_Saml2_Settings(settings=sp_only_settings, sp_validation_only=True)
        metadata = settings_obj.get_sp_metadata()
        errors = settings_obj.validate_metadata(metadata)
        if errors:
            raise HTTPException(500, f"Metadata errors: {errors}")
        return Response(content=metadata, media_type="text/xml")
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/init")
async def saml_init(domain: str, db: AsyncSession = Depends(get_db)):
    """Redirect the user to their IdP SSO URL. Frontend passes the work email domain."""
    try:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth
    except ImportError:
        raise HTTPException(503, "SAML library not available")

    domain = domain.lower().strip()
    result = await db.execute(
        select(OrganizationSAMLConfig).where(
            OrganizationSAMLConfig.domain == domain,
            OrganizationSAMLConfig.is_enabled.is_(True),
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(404, f"No SAML SSO configured for domain: {domain}")

    from fastapi import Request as _Request

    class _FakeRequest:
        """Minimal shim so python3-saml can build the redirect without a real WSGI request."""
        url = type("U", (), {"hostname": "breachreplay.com", "scheme": "https",
                             "path": "/api/v1/auth/saml/init", "port": None,
                             "query_string": f"domain={domain}"})()
        query_params = {"domain": domain}

    req_dict = {
        "https": "on",
        "http_host": "breachreplay.com",
        "server_port": "443",
        "script_name": "/api/v1/auth/saml/init",
        "get_data": {"domain": domain},
        "post_data": {},
    }

    auth = OneLogin_Saml2_Auth(req_dict, old_settings=_saml_settings(config))
    redirect_url = auth.login(return_to=str(config.id))  # relay_state = config id
    return RedirectResponse(redirect_url)


@router.post("/acs")
async def saml_acs(request: Request, db: AsyncSession = Depends(get_db)):
    """Assertion Consumer Service — IdP POSTs the SAMLResponse here after authentication."""
    try:
        from onelogin.saml2.auth import OneLogin_Saml2_Auth
    except ImportError:
        raise HTTPException(503, "SAML library not available")

    form = await request.form()
    saml_response = form.get("SAMLResponse")
    relay_state = form.get("RelayState", "")

    if not saml_response:
        raise HTTPException(400, "Missing SAMLResponse")

    # relay_state carries the OrganizationSAMLConfig.id set during /init
    result = await db.execute(
        select(OrganizationSAMLConfig).where(
            OrganizationSAMLConfig.id == relay_state,
            OrganizationSAMLConfig.is_enabled.is_(True),
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(400, "Invalid or missing SAML relay state")

    req_dict = _prepare_request(request, {"SAMLResponse": saml_response, "RelayState": relay_state})
    auth = OneLogin_Saml2_Auth(req_dict, old_settings=_saml_settings(config))
    auth.process_response()

    errors = auth.get_errors()
    if errors:
        raise HTTPException(400, f"SAML error: {', '.join(errors)}")
    if not auth.is_authenticated():
        raise HTTPException(401, "SAML authentication failed")

    # Extract identity — NameID is typically the email
    email = auth.get_nameid()
    attrs = auth.get_attributes()

    # Fallback attribute names used by different IdPs
    if not email:
        for attr_name in (
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
            "urn:oid:0.9.2342.19200300.100.1.3",
            "email",
            "mail",
        ):
            vals = attrs.get(attr_name)
            if vals:
                email = vals[0]
                break

    if not email:
        raise HTTPException(400, "Could not extract email from SAML assertion")

    # Extract display name
    full_name = None
    for attr_name in (
        "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
        "urn:oid:2.5.4.3",
        "displayName",
        "cn",
    ):
        vals = attrs.get(attr_name)
        if vals:
            full_name = vals[0]
            break

    # Find or create user
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        user = User(
            email=email,
            hashed_password=hash_password(str(uuid.uuid4())),
            full_name=full_name,
            organization_id=config.organization_id,
        )
        db.add(user)
        await db.flush()
    elif user.organization_id is None:
        user.organization_id = config.organization_id

    if full_name and not user.full_name:
        user.full_name = full_name

    user.last_login = datetime.utcnow()
    access_token = create_access_token({"sub": user.id})
    refresh_token = await create_refresh_token(str(user.id))
    await db.commit()

    return RedirectResponse(
        f"{settings.FRONTEND_URL}/auth/callback?access_token={access_token}&refresh_token={refresh_token}"
    )


# ── Admin: configure SAML for an organisation ────────────────────────────────

@router.post("/configure", response_model=SAMLConfigResponse)
async def configure_saml(
    payload: SAMLConfigRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create or update the SAML configuration for the current admin's organisation."""
    if not current_user.organization_id:
        raise HTTPException(400, "Your account is not associated with an organisation")

    cert = payload.idp_x509_cert.strip()
    cert = cert.replace("-----BEGIN CERTIFICATE-----", "").replace("-----END CERTIFICATE-----", "")
    cert = "".join(cert.split())

    result = await db.execute(
        select(OrganizationSAMLConfig).where(
            OrganizationSAMLConfig.organization_id == current_user.organization_id
        )
    )
    config = result.scalar_one_or_none()

    if config:
        config.domain = payload.domain.lower().strip()
        config.idp_entity_id = payload.idp_entity_id
        config.idp_sso_url = payload.idp_sso_url
        config.idp_x509_cert = cert
        config.is_enabled = payload.is_enabled
        config.updated_at = datetime.utcnow()
    else:
        config = OrganizationSAMLConfig(
            organization_id=current_user.organization_id,
            domain=payload.domain.lower().strip(),
            idp_entity_id=payload.idp_entity_id,
            idp_sso_url=payload.idp_sso_url,
            idp_x509_cert=cert,
            is_enabled=payload.is_enabled,
        )
        db.add(config)

    await db.commit()
    await db.refresh(config)
    return config


@router.get("/config", response_model=SAMLConfigResponse)
async def get_saml_config(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.organization_id:
        raise HTTPException(400, "Your account is not associated with an organisation")

    result = await db.execute(
        select(OrganizationSAMLConfig).where(
            OrganizationSAMLConfig.organization_id == current_user.organization_id
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(404, "No SAML configuration found for your organisation")
    return config
