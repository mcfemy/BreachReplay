"""SAML 2.0 SP-initiated SSO — custom implementation using lxml + cryptography.

No python3-saml / xmlsec native dependency required.
Supports HTTP-Redirect AuthnRequest and HTTP-POST ACS (signed assertions).
"""
import base64
import hashlib
import urllib.parse
import uuid
import zlib
from copy import deepcopy
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from lxml import etree
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    require_admin,
)
from app.db.session import get_db
from app.models.saml_config import OrganizationSAMLConfig
from app.models.user import User
from app.schemas.saml import SAMLConfigRequest, SAMLConfigResponse

router = APIRouter(prefix="/auth/saml", tags=["saml"])

_NS_SAML  = "urn:oasis:names:tc:SAML:2.0:assertion"
_NS_SAMLP = "urn:oasis:names:tc:SAML:2.0:protocol"
_NS_DS    = "http://www.w3.org/2000/09/xmldsig#"
_NS_MD    = "urn:oasis:names:tc:SAML:2.0:metadata"


# ── SP URL helpers ────────────────────────────────────────────────────────────

def _sp_entity_id() -> str:
    return f"{settings.FRONTEND_URL}/api/v1/auth/saml/metadata"


def _acs_url() -> str:
    return f"{settings.FRONTEND_URL}/api/v1/auth/saml/acs"


# ── AuthnRequest builder ──────────────────────────────────────────────────────

def _build_authn_request_url(idp_sso_url: str, relay_state: str = "") -> str:
    """Return an HTTP-Redirect URL with a deflated + base64-encoded AuthnRequest."""
    req_id = "_" + uuid.uuid4().hex
    issue_instant = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    sp_entity = _sp_entity_id()
    acs = _acs_url()

    xml = (
        '<samlp:AuthnRequest'
        ' xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"'
        ' xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"'
        f' ID="{req_id}"'
        ' Version="2.0"'
        f' IssueInstant="{issue_instant}"'
        f' Destination="{idp_sso_url}"'
        f' AssertionConsumerServiceURL="{acs}"'
        ' ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">'
        f'<saml:Issuer>{sp_entity}</saml:Issuer>'
        '</samlp:AuthnRequest>'
    )
    # Raw DEFLATE (strip 2-byte zlib header + 4-byte checksum)
    raw_deflate = zlib.compress(xml.encode("utf-8"))[2:-4]
    saml_req = base64.b64encode(raw_deflate).decode("utf-8")

    params: list[tuple[str, str]] = [("SAMLRequest", saml_req)]
    if relay_state:
        params.append(("RelayState", relay_state))
    return f"{idp_sso_url}?{urllib.parse.urlencode(params)}"


# ── SAMLResponse verifier ─────────────────────────────────────────────────────

def _c14n(el: etree._Element, exclusive: bool = False) -> bytes:
    return etree.tostring(el, method="c14n", exclusive=exclusive, with_comments=False)


def _verify_xml_dsig(signed_el: etree._Element, sig_el: etree._Element, cert_b64: str) -> None:
    """Verify an enveloped XMLDSig signature using the IdP's DER-encoded certificate."""
    from cryptography.hazmat.primitives import hashes as _hashes
    from cryptography.hazmat.primitives.asymmetric import padding as _padding
    from cryptography.x509 import load_der_x509_certificate
    from cryptography.exceptions import InvalidSignature

    cert_der = base64.b64decode(cert_b64)
    pub_key = load_der_x509_certificate(cert_der).public_key()

    # ── Canonicalize SignedInfo ────────────────────────────────────────────────
    si = sig_el.find(f"{{{_NS_DS}}}SignedInfo")
    if si is None:
        raise ValueError("Signature missing SignedInfo")

    c14n_el = si.find(f"{{{_NS_DS}}}CanonicalizationMethod")
    c14n_alg = c14n_el.get("Algorithm", "") if c14n_el is not None else ""
    exclusive = "exc-c14n" in c14n_alg or "xml-exc-c14n" in c14n_alg.lower()
    si_c14n = _c14n(si, exclusive=exclusive)

    # ── Signature bytes ────────────────────────────────────────────────────────
    sv_el = sig_el.find(f"{{{_NS_DS}}}SignatureValue")
    if sv_el is None:
        raise ValueError("Signature missing SignatureValue")
    sig_bytes = base64.b64decode("".join((sv_el.text or "").split()))

    # ── Signature algorithm ────────────────────────────────────────────────────
    sm_el = si.find(f"{{{_NS_DS}}}SignatureMethod")
    alg = sm_el.get("Algorithm", "") if sm_el is not None else ""
    if "sha256" in alg:
        hash_alg: _hashes.HashAlgorithm = _hashes.SHA256()
    elif "sha384" in alg:
        hash_alg = _hashes.SHA384()
    elif "sha512" in alg:
        hash_alg = _hashes.SHA512()
    else:
        hash_alg = _hashes.SHA1()

    try:
        pub_key.verify(sig_bytes, si_c14n, _padding.PKCS1v15(), hash_alg)
    except InvalidSignature:
        raise ValueError("SAML RSA signature verification failed")

    # ── Verify Reference digests ───────────────────────────────────────────────
    for ref in si.findall(f"{{{_NS_DS}}}Reference"):
        _verify_reference(ref, signed_el, exclusive)


def _verify_reference(
    ref: etree._Element, signed_el: etree._Element, default_exclusive: bool = False
) -> None:
    uri = ref.get("URI", "")
    ref_id = uri.lstrip("#")

    # Locate the referenced element by ID attribute
    if ref_id:
        target: etree._Element | None = None
        for el in signed_el.iter():
            for id_attr in ("ID", "Id", "id"):
                if el.get(id_attr) == ref_id:
                    target = el
                    break
            if target is not None:
                break
        if target is None:
            return  # can't verify — skip
    else:
        target = signed_el

    # Apply transforms
    transforms = ref.findall(f"{{{_NS_DS}}}Transforms/{{{_NS_DS}}}Transform")
    exclusive_ref = default_exclusive
    target_copy = deepcopy(target)

    for t in transforms:
        t_alg = t.get("Algorithm", "")
        if "enveloped-signature" in t_alg:
            for child_sig in target_copy.findall(f"{{{_NS_DS}}}Signature"):
                target_copy.remove(child_sig)
        elif "exc-c14n" in t_alg or "xml-exc-c14n" in t_alg.lower():
            exclusive_ref = True

    target_c14n = _c14n(target_copy, exclusive=exclusive_ref)

    # Compute expected digest
    dv_el = ref.find(f"{{{_NS_DS}}}DigestValue")
    dm_el = ref.find(f"{{{_NS_DS}}}DigestMethod")
    if dv_el is None:
        return

    expected = base64.b64decode("".join((dv_el.text or "").split()))
    dm_alg = dm_el.get("Algorithm", "") if dm_el is not None else ""

    if "sha256" in dm_alg:
        actual = hashlib.sha256(target_c14n).digest()
    elif "sha384" in dm_alg:
        actual = hashlib.sha384(target_c14n).digest()
    elif "sha512" in dm_alg:
        actual = hashlib.sha512(target_c14n).digest()
    else:
        actual = hashlib.sha1(target_c14n).digest()

    if actual != expected:
        raise ValueError("SAML digest mismatch — assertion may have been tampered with")


def _parse_saml_response(saml_response_b64: str, idp_x509_cert_b64: str) -> dict:
    """
    Parse and verify a SAML 2.0 HTTP-POST Response.
    Returns {'name_id': str | None, 'attributes': dict[str, list[str]]}
    """
    xml_bytes = base64.b64decode(saml_response_b64)
    root = etree.fromstring(xml_bytes)

    # Status check
    status_code = root.find(f".//{{{_NS_SAMLP}}}StatusCode")
    if status_code is not None:
        val = status_code.get("Value", "")
        if "Success" not in val:
            raise ValueError(f"SAML authentication failed: {val}")

    # Locate unencrypted Assertion
    assertion = root.find(f"{{{_NS_SAML}}}Assertion")
    if assertion is None:
        raise ValueError("No Assertion element found (encrypted assertions not supported)")

    # Locate and verify digital signature
    sig = assertion.find(f"{{{_NS_DS}}}Signature")
    signed_el = assertion
    if sig is None:
        sig = root.find(f"{{{_NS_DS}}}Signature")
        signed_el = root
    if sig is None:
        raise ValueError("SAMLResponse is unsigned — rejected for security")

    _verify_xml_dsig(signed_el, sig, idp_x509_cert_b64)

    # NameID (email)
    name_id_el = assertion.find(f".//{{{_NS_SAML}}}NameID")
    name_id = (name_id_el.text or "").strip() if name_id_el is not None else None

    # Attributes
    attributes: dict[str, list[str]] = {}
    for attr in assertion.findall(f".//{{{_NS_SAML}}}Attribute"):
        attr_name = attr.get("Name", "")
        vals = [
            v.text.strip()
            for v in attr.findall(f"{{{_NS_SAML}}}AttributeValue")
            if v.text
        ]
        if vals:
            attributes[attr_name] = vals

    return {"name_id": name_id, "attributes": attributes}


# ── SP Metadata ───────────────────────────────────────────────────────────────

def _generate_metadata() -> str:
    sp_entity = _sp_entity_id()
    acs = _acs_url()
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<md:EntityDescriptor xmlns:md="{_NS_MD}" entityID="{sp_entity}">'
        "<md:SPSSODescriptor"
        ' AuthnRequestsSigned="false"'
        ' WantAssertionsSigned="true"'
        f' protocolSupportEnumeration="{_NS_SAMLP}">'
        "<md:NameIDFormat>"
        "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
        "</md:NameIDFormat>"
        '<md:AssertionConsumerService'
        f' Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"'
        f' Location="{acs}"'
        ' index="1"/>'
        "</md:SPSSODescriptor>"
        "</md:EntityDescriptor>"
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/metadata")
async def saml_metadata():
    """SP metadata XML — register this URL with your IdP as the SP Entity ID."""
    return Response(content=_generate_metadata(), media_type="text/xml")


@router.get("/init")
async def saml_init(domain: str, db: AsyncSession = Depends(get_db)):
    """Redirect the browser to the IdP SSO URL. Frontend passes the work-email domain."""
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

    redirect_url = _build_authn_request_url(config.idp_sso_url, relay_state=str(config.id))
    return RedirectResponse(redirect_url)


@router.post("/acs")
async def saml_acs(request: Request, db: AsyncSession = Depends(get_db)):
    """Assertion Consumer Service — IdP POSTs the SAMLResponse here after login."""
    form = await request.form()
    saml_response = form.get("SAMLResponse")
    relay_state = form.get("RelayState", "")

    if not saml_response:
        raise HTTPException(400, "Missing SAMLResponse in POST body")

    # relay_state carries the OrganizationSAMLConfig.id set during /init
    result = await db.execute(
        select(OrganizationSAMLConfig).where(
            OrganizationSAMLConfig.id == relay_state,
            OrganizationSAMLConfig.is_enabled.is_(True),
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(400, "Invalid or expired SAML relay state")

    try:
        parsed = _parse_saml_response(str(saml_response), config.idp_x509_cert)
    except ValueError as exc:
        raise HTTPException(401, str(exc))

    email = parsed["name_id"]
    attrs = parsed["attributes"]

    # Fallback email from attributes if NameID is not an email
    if not email or "@" not in email:
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

    if not email or "@" not in email:
        raise HTTPException(400, "Could not extract email from SAML assertion")

    # Resolve display name from attributes
    full_name: str | None = None
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

    # Find or create the user
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
    else:
        if user.organization_id is None:
            user.organization_id = config.organization_id
        if full_name and not user.full_name:
            user.full_name = full_name

    user.last_login = datetime.utcnow()
    access_token = create_access_token({"sub": user.id})
    refresh_token = await create_refresh_token(str(user.id))
    await db.commit()

    return RedirectResponse(
        f"{settings.FRONTEND_URL}/auth/callback"
        f"?access_token={access_token}&refresh_token={refresh_token}"
    )


# ── Admin: configure SAML for an organisation ────────────────────────────────

@router.post("/configure", response_model=SAMLConfigResponse)
async def configure_saml(
    payload: SAMLConfigRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create or update SAML config for the current admin's organisation."""
    if not current_user.organization_id:
        raise HTTPException(400, "Your account is not associated with an organisation")

    # Strip PEM headers if present
    cert = payload.idp_x509_cert.strip()
    for header in ("-----BEGIN CERTIFICATE-----", "-----END CERTIFICATE-----"):
        cert = cert.replace(header, "")
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
