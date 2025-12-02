import threading
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import requests
from flask import current_app

from . import db
from .models import payment_consumptions
from .cashbook_utils import log_payment_to_cashbook

_token_lock = threading.Lock()
_token_cache: Dict[str, Any] = {"token": None, "expires_at": datetime.utcnow()}
_last_status_checks: Dict[int, datetime] = {}


def refresh_paypal_payment_status(payment, created_by: str = "PayPal API") -> bool:
    """
    Attempt to refresh a pending PayPal payment by querying the PayPal Reporting API.
    Returns True if the payment was confirmed as paid and the DB row was updated.
    """
    cfg = current_app.config
    client_id = cfg.get("PAYPAL_CLIENT_ID")
    client_secret = cfg.get("PAYPAL_CLIENT_SECRET")
    if not client_id or not client_secret:
        return False

    cooldown = cfg.get("PAYPAL_POLL_INTERVAL_SECONDS", 60)
    now = datetime.utcnow()
    last_check = _last_status_checks.get(payment.id)
    if last_check and (now - last_check).total_seconds() < cooldown:
        return False

    _last_status_checks[payment.id] = now

    token = _get_access_token()
    if not token:
        return False

    transaction = _find_transaction_for_payment(payment, token)
    if not transaction:
        return False

    payment.payment_status = 'paid'
    payment.payment_reference = transaction.get('transaction_id') or payment.payment_reference
    payment.paid_at = datetime.utcnow()
    note_bits = ["PayPal API confirmed"]
    if transaction.get('transaction_id'):
        note_bits.append(f"Txn: {transaction['transaction_id']}")
    if transaction.get('payer_email'):
        note_bits.append(f"Payer: {transaction['payer_email']}")
    payment.notes = (payment.notes or '') + f" [{' - '.join(note_bits)}]"
    log_payment_to_cashbook(payment, created_by=created_by)
    db.session.commit()
    return True


def _get_access_token() -> Optional[str]:
    cfg = current_app.config
    client_id = cfg.get("PAYPAL_CLIENT_ID")
    client_secret = cfg.get("PAYPAL_CLIENT_SECRET")
    base_url = cfg.get("PAYPAL_API_BASE")
    if not client_id or not client_secret or not base_url:
        return None

    with _token_lock:
        now = datetime.utcnow()
        cached_token = _token_cache.get("token")
        expires_at = _token_cache.get("expires_at", now)
        if cached_token and expires_at > now + timedelta(seconds=15):
            return cached_token

        try:
            resp = requests.post(
                f"{base_url}/v1/oauth2/token",
                auth=(client_id, client_secret),
                data={"grant_type": "client_credentials"},
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            token = data.get("access_token")
            expires_in = int(data.get("expires_in", 300))
            if not token:
                current_app.logger.warning("PayPal API: access token missing in response")
                return None
            _token_cache["token"] = token
            _token_cache["expires_at"] = now + timedelta(seconds=max(30, expires_in - 30))
            return token
        except Exception as exc:
            current_app.logger.warning(f"PayPal API token request failed: {exc}")
            return None


def _find_transaction_for_payment(payment, token: str) -> Optional[Dict[str, Any]]:
    base_url = current_app.config.get("PAYPAL_API_BASE")
    lookback_minutes = current_app.config.get("PAYPAL_REPORTING_LOOKBACK_MINUTES", 240)
    invoice_id = f"payment_{payment.id}"

    end_time = datetime.utcnow().replace(tzinfo=timezone.utc)
    created_at = payment.created_at or datetime.utcnow()
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    else:
        created_at = created_at.astimezone(timezone.utc)

    start_time = min(created_at, end_time) - timedelta(minutes=lookback_minutes)

    params = {
        "start_date": _format_time(start_time),
        "end_date": _format_time(end_time + timedelta(minutes=5)),
        "fields": "all",
        "page_size": 100,
        "page": 1
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        resp = requests.get(
            f"{base_url}/v1/reporting/transactions",
            params=params,
            headers=headers,
            timeout=15
        )
        if resp.status_code == 422:
            current_app.logger.warning("PayPal API: invalid reporting window requested")
            return None
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        current_app.logger.warning(f"PayPal API transaction lookup failed: {exc}")
        return None

    for detail in data.get("transaction_details", []):
        transaction_info = detail.get("transaction_info", {})
        cart_info = detail.get("cart_info", {})
        payer_info = detail.get("payer_info", {})

        invoice_match = str(transaction_info.get("invoice_id") or "").strip() == invoice_id
        custom_field = (cart_info.get("custom_field") or "")
        custom_match = f"payment_id:{payment.id}" in custom_field

        if not (invoice_match or custom_match):
            continue

        status = (transaction_info.get("transaction_status") or "").upper()
        if status in {"S", "SUCCESS", "COMPLETED"}:
            return {
                "transaction_id": transaction_info.get("transaction_id"),
                "payer_email": payer_info.get("email_address"),
                "status": status
            }
        if status in {"P", "PENDING"}:
            return None

    return None


def _format_time(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def cancel_pending_payment(payment, reason: str = "") -> bool:
    """Mark a pending payment as cancelled and release any reserved consumptions."""
    if not payment or payment.payment_status != 'pending':
        return False

    try:
        for link in list(payment.payment_consumptions):
            db.session.delete(link)

        note_parts = [payment.notes] if payment.notes else []
        if reason:
            note_parts.append(f"[Auto] {reason}")
        payment.notes = "\n".join(filter(None, note_parts)) or None

        payment.payment_status = 'cancelled'
        payment.payment_reference = None
        payment.paid_at = None
        payment.updated_at = datetime.utcnow()

        db.session.commit()
        current_app.logger.info("Cancelled stale PayPal payment %s for user %s", payment.id, payment.user_id)
        return True
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning("Failed to cancel PayPal payment %s: %s", getattr(payment, 'id', '?'), exc)
        return False

