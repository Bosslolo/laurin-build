from datetime import datetime

from flask import current_app

from . import db
from .models import cashbook_entries, users

def get_auto_cashbook_company() -> str:
    """
    Return the target company name for automatic payment postings.
    Falls back to 'Kaffeemaschine' when no config override exists.
    """
    default_company = "Kaffeemaschine"
    company = current_app.config.get("CASHBOOK_AUTO_COMPANY", default_company)
    return company or default_company


def get_next_beleg_nummer(company: str) -> int:
    """Return the next sequential receipt number for the given company."""
    last = (
        cashbook_entries.query.filter_by(company=company)
        .order_by(cashbook_entries.beleg_nummer.desc())
        .first()
    )
    return (last.beleg_nummer + 1) if last else 1


def get_current_kassenstand(company: str) -> int:
    """Return the latest cash balance in cents for the given company."""
    last = (
        cashbook_entries.query.filter_by(company=company)
        .order_by(cashbook_entries.entry_date.desc(), cashbook_entries.id.desc())
        .first()
    )
    return last.kassenstand_bar_cents if last else 0


def recalculate_kassenstand_from_entry(company: str, entry_id: int) -> None:
    """
    Recalculate kassenstand for an edited/deleted entry and all subsequent entries.
    
    This function ensures the balance chain remains correct when entries are modified.
    It handles:
    - Editing income/expense amounts
    - Changing entry dates (which may change chronological order)
    - Deletions
    
    Args:
        company: The company name for which to recalculate
        entry_id: The ID of the entry from which to start recalculation
    """
    # Get all entries for the company, ordered chronologically (oldest first)
    # This ensures we process entries in the correct order
    all_entries = (
        cashbook_entries.query.filter_by(company=company)
        .order_by(cashbook_entries.entry_date.asc(), cashbook_entries.id.asc())
        .all()
    )
    
    if not all_entries:
        return
    
    # Find the entry with the given ID
    edited_entry = next((e for e in all_entries if e.id == entry_id), None)
    
    if not edited_entry:
        # Entry not found - might have been deleted, so recalculate from the earliest entry
        # This handles the deletion case where we need to recalculate everything
        start_index = 0
        prev_balance = 0
    else:
        # Find the index of the edited entry
        edited_index = all_entries.index(edited_entry)
        
        # Find the entry before the edited one (if any)
        if edited_index > 0:
            prev_entry = all_entries[edited_index - 1]
            prev_balance = prev_entry.kassenstand_bar_cents
        else:
            # This is the first entry, start from zero
            prev_balance = 0
        
        start_index = edited_index
    
    # Recalculate from the start_index forward
    current_balance = prev_balance
    for entry in all_entries[start_index:]:
        current_balance = current_balance + entry.einnahmen_bar_cents - entry.ausgaben_bar_cents
        entry.kassenstand_bar_cents = current_balance
    
    # Flush changes to database (but don't commit - let the caller handle that)
    db.session.flush()


def recalculate_all_kassenstand(company: str) -> None:
    """
    Recalculate kassenstand for all entries of a company from scratch.
    Useful for fixing corrupted balance chains or after bulk operations.
    
    Args:
        company: The company name for which to recalculate all balances
    """
    all_entries = (
        cashbook_entries.query.filter_by(company=company)
        .order_by(cashbook_entries.entry_date.asc(), cashbook_entries.id.asc())
        .all()
    )
    
    current_balance = 0
    for entry in all_entries:
        current_balance = current_balance + entry.einnahmen_bar_cents - entry.ausgaben_bar_cents
        entry.kassenstand_bar_cents = current_balance
    
    db.session.flush()




def log_payment_to_cashbook(payment, created_by: str | None = None, company: str | None = None):
    """
    Create (if necessary) a cashbook entry for a paid user payment.
    Returns the cashbook entry instance or None if nothing was created.
    """
    if not payment or payment.payment_status != "paid":
        return None

    if payment.amount_cents <= 0:
        return None

    target_company = company or get_auto_cashbook_company()
    if not target_company:
        return None

    marker = f"payment_id:{payment.id}"
    existing = (
        cashbook_entries.query.filter_by(company=target_company, bemerkung=marker).first()
    )
    if existing:
        return existing

    # Get the correct previous balance based on chronological order
    # Find the entry that comes before this payment's date chronologically
    entry_date = (payment.paid_at or datetime.utcnow()).date()
    
    from sqlalchemy import or_, and_
    prev_entry = (
        cashbook_entries.query.filter_by(company=target_company)
        .filter(
            or_(
                cashbook_entries.entry_date < entry_date,
                and_(
                    cashbook_entries.entry_date == entry_date,
                    cashbook_entries.id.isnot(None)
                )
            )
        )
        .order_by(cashbook_entries.entry_date.desc(), cashbook_entries.id.desc())
        .first()
    )
    
    if prev_entry:
        balance_before = prev_entry.kassenstand_bar_cents
    else:
        # This is the first entry (or earliest entry)
        balance_before = 0
    
    entry = cashbook_entries(
        company=target_company,
        beleg_nummer=get_next_beleg_nummer(target_company),
        entry_date=entry_date,
        bemerkung=marker,
        posten=_describe_payment(payment),
        einnahmen_bar_cents=payment.amount_cents,
        ausgaben_bar_cents=0,
        kassenstand_bar_cents=balance_before + payment.amount_cents,
        created_by=(created_by or "System"),
    )
    db.session.add(entry)
    db.session.flush()
    
    # Recalculate ALL entries from scratch to ensure the balance chain is correct
    # This handles cases where the payment date might be in the past
    recalculate_all_kassenstand(target_company)
    
    return entry


def _describe_payment(payment) -> str:
    """Build a human-friendly description for the payment posting."""
    method_labels = {
        "paypal": "PayPal",
        "cash": "Bar",
        "mypos_card": "Karte",
        "revolut": "Revolut",
    }
    method = method_labels.get(payment.payment_method, payment.payment_method.title())

    user = getattr(payment, "user", None)
    if not user:
        user = users.query.get(payment.user_id)

    if user:
        user_name = f"{user.first_name} {user.last_name}".strip()
    else:
        user_name = f"User #{payment.user_id}"

    return f"{method}-Zahlung {user_name}"

