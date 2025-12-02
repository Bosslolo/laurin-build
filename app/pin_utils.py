from datetime import datetime

from . import db
from .models import users, persistent_pins


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lower()


def _compute_identifier(user) -> str | None:
    if getattr(user, "itsl_id", None) not in (None, "", 0):
        return f"itsl:{user.itsl_id}"
    first = _normalize(getattr(user, "first_name", ""))
    last = _normalize(getattr(user, "last_name", ""))
    if not first and not last:
        return None
    return f"name:{first}::{last}"


def store_persistent_pin(user, pin_hash: bytes):
    identifier = _compute_identifier(user)
    if not identifier or not pin_hash:
        return
    record = persistent_pins.query.filter_by(user_identifier=identifier).first()
    if not record:
        record = persistent_pins(user_identifier=identifier, pin_hash=pin_hash)
        db.session.add(record)
    else:
        record.pin_hash = pin_hash
        record.updated_at = datetime.utcnow()


def remove_persistent_pin(user):
    identifier = _compute_identifier(user)
    if not identifier:
        return
    record = persistent_pins.query.filter_by(user_identifier=identifier).first()
    if record:
        db.session.delete(record)


def restore_pin_for_user(user) -> bool:
    """
    Restore a user's PIN from the persistent archive if it was lost (e.g., after DB restore).
    Returns True if a PIN was restored and the caller should commit the session.
    """
    if not user or user.pin_hash:
        return False
    identifier = _compute_identifier(user)
    if not identifier:
        return False
    record = persistent_pins.query.filter_by(user_identifier=identifier).first()
    if not record:
        return False
    user.pin_hash = record.pin_hash
    user.updated_at = datetime.utcnow()
    return True


def backfill_persistent_pins():
    """
    Ensure every user with an existing PIN has a matching archive entry.
    Safe to run multiple times.
    """
    existing_identifiers = {
        entry.user_identifier for entry in persistent_pins.query.all()
    }
    added = 0
    for user in users.query.filter(users.pin_hash.isnot(None)).all():
        identifier = _compute_identifier(user)
        if not identifier or identifier in existing_identifiers:
            continue
        db.session.add(persistent_pins(user_identifier=identifier, pin_hash=user.pin_hash))
        existing_identifiers.add(identifier)
        added += 1
    if added:
        db.session.commit()

