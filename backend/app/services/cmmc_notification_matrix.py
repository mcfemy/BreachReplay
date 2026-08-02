"""Phase 2.5 CMMC Evidence Layer — notification matrix CRUD (build-order
item 4).

Kept as a JSONB list on ClientOrg (item 1's original choice, reaffirmed
rather than revisited): rows are small, org-attested, and always read as
a full set — nothing today filters or joins on individual rows, which is
the only thing that would earn a real table its cost. Each entry carries
a server-generated `id` (a plain uuid4 string, not a DB primary key)
purely so a specific entry can be addressed for update/delete without one.

Field shape is the spec's own table (PHASE_2_5_CMMC_EVIDENCE_SPEC_FINAL.md
section 5): authority, basis, channel, window are required; last_validated
and validation_note are optional.

Mutations always reassign `client_org.notification_matrix` to a brand new
list — never append/remove on the existing Python list object in place.
SQLAlchemy's JSON/JSONB column type change-tracking is attribute-
assignment based; it does not detect in-place mutation of a list or dict
it already handed out.
"""
from __future__ import annotations

import uuid
from typing import Optional

from app.models.cmmc_org import ClientOrg


def list_notification_matrix(client_org: ClientOrg) -> list[dict]:
    return list(client_org.notification_matrix)


def add_notification_matrix_entry(client_org: ClientOrg, fields: dict) -> dict:
    entry = {"id": str(uuid.uuid4()), **fields}
    client_org.notification_matrix = [*client_org.notification_matrix, entry]
    return entry


def update_notification_matrix_entry(
    client_org: ClientOrg, entry_id: str, changes: dict,
) -> Optional[dict]:
    """None if no entry with this id exists (caller 404s); otherwise the
    updated entry, with `changes` merged in (only the fields the caller
    actually set — callers pass model_dump(exclude_unset=True), not a
    full replace, so omitted fields are left untouched)."""
    updated: Optional[dict] = None
    new_matrix = []
    for entry in client_org.notification_matrix:
        if entry["id"] == entry_id:
            entry = {**entry, **changes}
            updated = entry
        new_matrix.append(entry)
    if updated is not None:
        client_org.notification_matrix = new_matrix
    return updated


def remove_notification_matrix_entry(client_org: ClientOrg, entry_id: str) -> bool:
    original_length = len(client_org.notification_matrix)
    new_matrix = [e for e in client_org.notification_matrix if e["id"] != entry_id]
    if len(new_matrix) == original_length:
        return False
    client_org.notification_matrix = new_matrix
    return True
