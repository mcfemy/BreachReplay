"""Phase 2.5 CMMC Evidence Layer — Ed25519 signing key management
(build-order item 7).

Ed25519 over plain HMAC: small keys/signatures, deterministic (no
nonce-reuse footgun), and — the actual reason it wins — independently
verifiable offline by a third party holding our published public key
(see GET /cmmc/verify/public-keys), not just by calling our endpoint.
`cryptography` is already a dependency (pulled in transitively by pypdf)
and has native Ed25519 support.

Keys are loaded from CMMC_SIGNING_KEYS (never the repo): comma-separated
"key_id:base64_private_key" pairs. CMMC_ACTIVE_SIGNING_KEY_ID picks which
one signs NEWLY issued packs. Verification always looks up the key_id
stored with the specific pack being checked — never the active one —
which is what makes a rotation non-destructive to old signatures: retire
a key from "active" whenever, but keep it in CMMC_SIGNING_KEYS forever
(or at least as long as any pack signed with it might still need
verifying) and old signatures keep checking out.
"""
from __future__ import annotations

import base64
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from app.core.config import settings


class SigningNotConfigured(RuntimeError):
    """Raised when an operation needs a signing key and none is configured
    — e.g. local dev with CMMC_SIGNING_KEYS unset. Deliberately a distinct
    exception type so callers (the /issue route) can turn it into a clear
    5xx rather than a confusing KeyError/AttributeError."""


def _parse_keys(raw: Optional[str]) -> dict[str, Ed25519PrivateKey]:
    if not raw:
        return {}
    keys: dict[str, Ed25519PrivateKey] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        key_id, _, b64 = pair.partition(":")
        keys[key_id] = Ed25519PrivateKey.from_private_bytes(base64.b64decode(b64))
    return keys


def _private_keys() -> dict[str, Ed25519PrivateKey]:
    """Deliberately NOT cached: re-parses settings.CMMC_SIGNING_KEYS on
    every call. Sign/verify are low-frequency operations here (issuing a
    pack, checking one), so the cost is negligible — and caching a
    no-arg function that reads a mutable settings value would silently
    return stale keys the moment a test (or a hot-reload of config)
    changes CMMC_SIGNING_KEYS mid-process."""
    return _parse_keys(settings.CMMC_SIGNING_KEYS)


def sign(message: bytes) -> tuple[str, str]:
    """Signs `message` with the currently-active key. Returns
    (signature_base64, key_id) — both get stored with the issued pack."""
    keys = _private_keys()
    key_id = settings.CMMC_ACTIVE_SIGNING_KEY_ID
    if not key_id or key_id not in keys:
        raise SigningNotConfigured(
            "CMMC_ACTIVE_SIGNING_KEY_ID is not set, or not present in CMMC_SIGNING_KEYS"
        )
    signature = keys[key_id].sign(message)
    return base64.b64encode(signature).decode(), key_id


def verify(message: bytes, signature_b64: str, key_id: str) -> bool:
    """True iff `signature_b64` is a valid Ed25519 signature over `message`
    under the SPECIFIC key `key_id` — not necessarily the active one, so a
    retired key still verifies packs it actually signed."""
    keys = _private_keys()
    key = keys.get(key_id)
    if key is None:
        return False
    public_key = key.public_key()
    try:
        public_key.verify(base64.b64decode(signature_b64), message)
        return True
    except InvalidSignature:
        return False


def public_keys() -> list[dict]:
    """Every known key, not just the active one — published at
    GET /cmmc/verify/public-keys so a signature made before a rotation
    stays independently checkable offline, forever, by anyone holding
    this response, without ever calling our endpoint again."""
    return [
        {
            "key_id": key_id,
            "public_key_b64": base64.b64encode(
                key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
            ).decode(),
            "algorithm": "ed25519",
        }
        for key_id, key in _private_keys().items()
    ]


def generate_key_b64() -> str:
    """Convenience for provisioning a new key by hand (e.g. `python -c
    "from app.core.cmmc_signing import generate_key_b64; print(generate_key_b64())"`)
    — not called by any route. The real production key is generated and
    placed in .env.prod directly by whoever operates the box, never by
    this codebase automatically."""
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return base64.b64encode(raw).decode()
