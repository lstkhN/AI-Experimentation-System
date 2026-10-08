"""Small, transactional audit-event writer."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditEvent


def record_audit_event(
    db: Session,
    *,
    project_id: int,
    event_type: str,
    entity_type: str,
    entity_id: int | None = None,
    payload: dict[str, Any] | None = None,
    actor: str | None = None,
) -> AuditEvent:
    """Add a JSON-safe audit event to the caller's short write transaction.

    The caller must commit (or roll back) this event together with the domain
    change.  Normalizing the payload here prevents database-specific JSON
    serialization failures after the business operation has been performed.
    """
    json_payload = None
    if payload is not None:
        json_payload = json.loads(json.dumps(payload, allow_nan=False, sort_keys=True, default=str))
    event = AuditEvent(
        project_id=project_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=actor,
        payload=json_payload,
    )
    db.add(event)
    return event
