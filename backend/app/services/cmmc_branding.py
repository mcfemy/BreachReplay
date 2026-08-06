"""Phase 2.5 CMMC Evidence Layer — consultant branding (build-order
item 8).

Logo + text only, no accent colors — the plain, assessor-facing document
item 6/7 shipped stays exactly as-is; this only adds a logo image and an
optional tagline to the cover.

Storage reuses UPLOAD_DIR (the same volume the app/uploads/ durability
fix just made durable — `docker-compose.prod.yml`'s `uploads_data`),
namespaced under `cmmc_logos/{consulting_org_id}/` so it can never
collide with `app/api/routes/orgs.py`'s own upload convention under the
same root.

Real content-type validation, not extension: `orgs.py`'s existing upload
route only checks the file extension, exactly the weaker pattern this
item was told explicitly not to repeat. Pillow (already a dependency)
must genuinely decode the bytes as PNG or JPEG — a renamed .txt or a
truncated file fails here, not silently later. SVG is deliberately
excluded (can embed scripts — a real risk for a file base64-embedded
into a rendered document), and the accepted image is re-encoded via
Pillow before storing, not written verbatim, stripping any non-image
payload smuggled inside an otherwise-valid container.

The embed-at-issuance guarantee (an issued pack's bytes must never
change if the logo is later replaced) isn't special-cased anywhere — it
falls out of build_pack_payload's existing "called once per issuance,
never again" behavior (item 7). logo_data_uri() reads whatever's on disk
AT THE MOMENT IT'S CALLED; since that call only ever happens once per
issued pack, whatever it returns is frozen into that pack forever. See
app/services/cmmc_pdf.py's build_pack_payload.
"""
from __future__ import annotations

import base64
import io
import os
from typing import Optional

from PIL import Image, UnidentifiedImageError

from app.models.cmmc_org import ConsultingOrg

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/tmp/breachreplay_uploads")

_ALLOWED_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg"}
_MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2MB — logos don't need to be bigger, and this caps base64 payload growth


class InvalidLogoError(ValueError):
    """Plain, HTTP-agnostic — routes translate this to a 400, matching
    cmmc_after_action.AfterActionError's existing pattern in this layer."""


def _logo_dir(consulting_org_id: str) -> str:
    return os.path.join(UPLOAD_DIR, "cmmc_logos", consulting_org_id)


def validate_and_normalize_logo(content: bytes) -> tuple[bytes, str]:
    """Raises InvalidLogoError on anything that isn't a genuinely
    decodable PNG or JPEG, or is oversized. Returns (re-encoded bytes,
    content_type) on success — never the raw uploaded bytes."""
    if len(content) > _MAX_LOGO_BYTES:
        raise InvalidLogoError(f"Logo must be {_MAX_LOGO_BYTES // (1024 * 1024)}MB or smaller")

    try:
        probe = Image.open(io.BytesIO(content))
        probe.verify()
    except (UnidentifiedImageError, OSError):
        raise InvalidLogoError("File is not a valid image")

    if probe.format not in _ALLOWED_FORMATS:
        raise InvalidLogoError(f"Unsupported image format '{probe.format}' — only PNG and JPEG logos are allowed")

    content_type = _ALLOWED_FORMATS[probe.format]
    # verify() invalidates the Image instance for further use (Pillow's
    # own documented contract) — re-open fresh to actually re-encode it.
    image = Image.open(io.BytesIO(content))
    if probe.format == "JPEG" and image.mode != "RGB":
        image = image.convert("RGB")
    out = io.BytesIO()
    image.save(out, format=probe.format)
    return out.getvalue(), content_type


def save_logo(consulting_org: ConsultingOrg, content: bytes, content_type: str) -> str:
    ext = "png" if content_type == "image/png" else "jpg"
    logo_dir = _logo_dir(consulting_org.id)
    os.makedirs(logo_dir, exist_ok=True)
    logo_path = os.path.join(logo_dir, f"logo.{ext}")
    with open(logo_path, "wb") as f:
        f.write(content)

    consulting_org.branding = {**consulting_org.branding, "logo_path": logo_path, "logo_content_type": content_type}
    return logo_path


def remove_logo(consulting_org: ConsultingOrg) -> None:
    logo_path = (consulting_org.branding or {}).get("logo_path")
    if logo_path and os.path.exists(logo_path):
        os.remove(logo_path)
    branding = dict(consulting_org.branding or {})
    branding.pop("logo_path", None)
    branding.pop("logo_content_type", None)
    consulting_org.branding = branding


def update_tagline(consulting_org: ConsultingOrg, tagline: Optional[str]) -> None:
    branding = dict(consulting_org.branding or {})
    if tagline is None:
        branding.pop("tagline", None)
    else:
        branding["tagline"] = tagline
    consulting_org.branding = branding


def logo_data_uri(consulting_org: ConsultingOrg) -> Optional[str]:
    """Reads the CURRENT logo bytes from disk and returns a self-contained
    base64 data URI — see module docstring for why calling this from
    build_pack_payload is what makes "frozen at issuance" true without
    any special-casing."""
    branding = consulting_org.branding or {}
    logo_path = branding.get("logo_path")
    content_type = branding.get("logo_content_type")
    if not logo_path or not content_type or not os.path.exists(logo_path):
        return None
    with open(logo_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{content_type};base64,{b64}"
