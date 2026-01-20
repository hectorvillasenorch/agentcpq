import hashlib
import json
import logging

from cpq.models import DomainEvent

logger = logging.getLogger(__name__)


def _serialize_payload(payload):
    try:
        return json.dumps(payload or {}, sort_keys=True, default=str)
    except Exception:
        return json.dumps({"payload": str(payload)}, sort_keys=True)


def build_idempotency_key(event_type, payload=None, object_type=None, object_id=None, source=None):
    base = {
        "event_type": event_type,
        "object_type": object_type,
        "object_id": object_id,
        "source": source,
        "payload": payload or {},
    }
    raw = _serialize_payload(base)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def emit_domain_event(
    event_type,
    *,
    payload=None,
    object_type=None,
    object_id=None,
    source=None,
    idempotency_key=None,
):
    key = idempotency_key or build_idempotency_key(
        event_type,
        payload=payload,
        object_type=object_type,
        object_id=object_id,
        source=source,
    )
    full_key = f"{event_type}:{key}"
    if DomainEvent.objects.filter(idempotency_key=full_key).exists():
        return None

    try:
        return DomainEvent.objects.create(
            event_type=event_type,
            object_type=object_type,
            object_id=str(object_id) if object_id is not None else None,
            payload=payload or {},
            idempotency_key=full_key,
            source=source or "",
        )
    except Exception as exc:
        logger.warning("Failed to emit domain event %s: %s", event_type, exc)
        return None
