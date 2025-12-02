from flask import Blueprint, jsonify, render_template, request, redirect, url_for, flash, abort, session, Response, current_app, make_response
from .models import roles, beverages, users, consumptions, invoices, beverage_prices, display_items, settings, cashbook_entries, user_payments, payment_consumptions, mypos_transactions, cash_payment_requests
from . import db, cache
from datetime import datetime, date, timedelta
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
import hashlib
import os
import time
from .security import (
    require_admin_auth, require_security_gate, is_admin_mode,
    bypass_pin_for_dev, get_security_info, verify_admin_credentials, SECURITY_GATE_ENABLED, is_admin_port
)
from .paypal_api import cancel_pending_payment
from .paypal_api import refresh_paypal_payment_status
from .pin_utils import store_persistent_pin, remove_persistent_pin, restore_pin_for_user
from .cashbook_utils import (
    get_next_beleg_nummer,
    get_current_kassenstand,
    log_payment_to_cashbook,
    recalculate_kassenstand_from_entry,
    recalculate_all_kassenstand,
)

bp = Blueprint("routes", __name__)

def check_session_timeout():
    """Check if admin session has timed out (10 minutes)"""
    if os.getenv('FLASK_APP_MODE') == 'admin' and session.get('admin_authenticated'):
        last_activity = session.get('last_activity', 0)
        current_time = time.time()
        
        # 10 minutes = 600 seconds
        if current_time - last_activity > 600:
            # Session timed out
            session.clear()
            flash('🔒 Session expired. Please log in again.', 'warning')
            return True
        else:
            # Update last activity time
            session['last_activity'] = current_time
    return False

def require_admin_session(f):
    """Decorator to enforce admin access on admin port and check session timeout.
    Also allows access for cashbook-authenticated users (for user port access)."""
    def decorated_function(*args, **kwargs):
        # Allow access if admin mode OR cashbook authenticated
        is_admin = is_admin_mode()
        is_cashbook = session.get('cashbook_authenticated', False)
        
        if not (is_admin or is_cashbook):
            return redirect(url_for('routes.admin_login'))
        
        # Enforce inactivity timeout only for admin mode
        if is_admin and check_session_timeout():
            return redirect(url_for('routes.admin_login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def require_admin_only(f):
    """Decorator to enforce strict admin access (no cashbook bypass)."""
    def decorated_function(*args, **kwargs):
        if not is_admin_mode():
            return redirect(url_for('routes.admin_login'))
        if check_session_timeout():
            return redirect(url_for('routes.admin_login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def clear_pin_sessions(except_user_id=None):
    """Remove stored PIN verifications to avoid cross-user reuse."""
    keys_to_remove = [
        key for key in list(session.keys())
        if key.startswith('pin_verified_')
    ]
    for key in keys_to_remove:
        user_suffix = key.replace('pin_verified_', '')
        if except_user_id is not None and str(except_user_id) == user_suffix:
            continue
        session.pop(key, None)

def check_invoice_exists(user_id, period: date | None = None):
    """Get or create an invoice for the user and target month.
    If period is None, defaults to current month.
    """
    current_month_year = (period or date.today()).replace(day=1)
    existing_invoice = invoices.query.filter_by(
        user_id=user_id,
        period=current_month_year
    ).first()
    
    if existing_invoice:
        return existing_invoice

    # Handle guest users (user_id = 0)
    if user_id == 0:
        user = type('GuestUser', (), {
            'id': 0,
            'first_name': 'Guest',
            'last_name': ''
        })()
    else:
        user = users.query.get(user_id)
        if not user:
            raise ValueError(f"User with ID {user_id} not found")
    
    count = invoices.query.filter_by(period=current_month_year).count()
    invoice_name = f"INV-{current_month_year.strftime('%Y-%m')}_{count + 1}"

    new_invoice = invoices(
        user_id=user_id,
        invoice_name=invoice_name,
        status="draft",
        period=current_month_year
    )

    try:
        db.session.add(new_invoice)
        db.session.commit()
        return new_invoice
    except IntegrityError:
        # Another concurrent request likely created the invoice; rollback and fetch it
        db.session.rollback()
        existing_invoice = invoices.query.filter_by(
            user_id=user_id,
            period=current_month_year
        ).first()
        if existing_invoice:
            return existing_invoice
        # If still not found, rethrow a generic error to surface the issue
        raise
    except Exception as e:
        db.session.rollback()
        raise Exception(f"Failed to create invoice: {str(e)}")

def get_or_create_guest_user():
    """Return a persistent synthetic 'Guests' user under role 'Guests' (id 4 if present).
    Identified by sentinel itsl_id = -1 to avoid colliding with real users.
    """
    # Resolve Guests role id (prefer id 4, fallback to name lookup)
    guests_role_id = 4
    role_obj = roles.query.get(guests_role_id)
    if not role_obj:
        role_obj = roles.query.filter(roles.name.ilike('guests')).first()
        if role_obj:
            guests_role_id = role_obj.id

    # Try by sentinel itsl_id
    guest_user = users.query.filter_by(itsl_id=-1).first()
    if guest_user:
        return guest_user

    # Fallback try by role/name combo to prevent duplicates if existed before
    guest_user = users.query.filter_by(role_id=guests_role_id, first_name='Guests', last_name='').first()
    if guest_user:
        # ensure sentinel set for future lookups
        if guest_user.itsl_id is None:
            guest_user.itsl_id = -1
            db.session.commit()
        return guest_user

    # Create
    guest_user = users(
        itsl_id=-1,
        role_id=guests_role_id,
        first_name='Guests',
        last_name='',
        email=None,
        status=True
    )
    db.session.add(guest_user)
    db.session.commit()
    return guest_user

def hash_pin(pin):
    """Hash a PIN using SHA-256"""
    return hashlib.sha256(pin.encode()).digest()

def verify_pin(user_id, pin):
    """Verify a PIN against the stored hash"""
    user = users.query.get(user_id)
    if not user or not user.pin_hash:
        return False
    return user.pin_hash == hash_pin(pin)

def _index_core():
    current_month = date.today().replace(day=1)
    base_query = db.session.query(
        users,
        roles,
        func.coalesce(func.sum(consumptions.quantity), 0).label('total_consumption')
    ).join(roles, users.role_id == roles.id) \
     .outerjoin(consumptions, db.and_(consumptions.user_id == users.id, consumptions.created_at >= current_month)) \
     .group_by(users.id, roles.id) \
     .order_by(func.coalesce(func.sum(consumptions.quantity), 0).desc())

    # Only hide inactive users on the user port; admin port sees all
    if not is_admin_port():
        base_query = base_query.filter(users.status == True)

    users_with_consumption = base_query.all()
    sorted_users = [u[0] for u in users_with_consumption]
    # Only expose admin tools on admin port AND when admin session is authenticated
    is_admin = is_admin_mode()
    initial_subset = sorted_users[:12]
    theme = settings.get_value('theme', 'coffee') or 'coffee'
    theme_version = settings.get_value('theme_version', '1') or '1'
    theme_colors = {
        'coffee': '#B65D24',
        'spring': '#4CAF50',
        'summer': '#FF9800',
        'autumn': '#FF5722',
        'winter': '#2196F3'
    }
    theme_color = theme_colors.get(theme, '#222222')
    # Check if in development mode
    is_dev = os.getenv('FLASK_ENV', 'production') == 'development'
    
    return render_template(
        'index.html',
        users=initial_subset,
        users_count=len(sorted_users),
        is_admin=is_admin,
        theme=theme,
        theme_version=theme_version,
        theme_color=theme_color,
        is_dev=is_dev
    )

@bp.route("/")
def index():
    # Check session timeout for admin users
    if check_session_timeout():
        return redirect(url_for('routes.admin_login'))
    
    # Check if this is admin port and user is not authenticated
    # Enforce login on admin port
    if is_admin_port() and not session.get('admin_authenticated', False):
        return redirect(url_for('routes.admin_login'))
    
    # For user mode, ensure no admin session is active (security)
    if (not is_admin_port()) and session.get('admin_authenticated', False):
        # Clear any admin session on user port for security
        session.pop('admin_authenticated', None)
        session.pop('admin_username', None)
        session.pop('last_activity', None)

    # Clear any lingering PIN verifications unless we're explicitly prompting for one
    if request.args.get('require_pin', 'false').lower() != 'true':
        clear_pin_sessions()
    
    theme_version = settings.get_value('theme_version', '1') or '1'
    cache_key = f"index:{theme_version}:{'admin' if is_admin_port() else 'user'}"
    try:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
    except Exception as e:
        # If cache fails, just continue without caching
        print(f"WARNING: Cache get failed, continuing without cache: {e}")
    rv = _index_core()
    try:
        cache.set(cache_key, rv, timeout=30)
    except Exception as e:
        # If cache set fails, just continue without caching
        print(f"WARNING: Cache set failed, continuing without cache: {e}")
    return rv

@bp.route('/api/index-data')
def api_index_data():
    """Lightweight API to allow progressive loading of the main page user list."""
    current_month = date.today().replace(day=1)
    base_query = db.session.query(
        users.id,
        users.first_name,
        users.last_name,
        roles.name.label('role_name'),
        func.coalesce(func.sum(consumptions.quantity), 0).label('total_consumption')
    ).join(roles, users.role_id == roles.id) \
     .outerjoin(consumptions, db.and_(consumptions.user_id == users.id, consumptions.created_at >= current_month)) \
     .group_by(users.id, roles.id) \
     .order_by(func.coalesce(func.sum(consumptions.quantity), 0).desc())

    # Only hide inactive users on the user port; admin port sees all
    if not is_admin_port():
        base_query = base_query.filter(users.status == True)

    users_with_consumption = base_query.all()

    data = [
        {
            'id': row.id,
            'first_name': row.first_name,
            'last_name': row.last_name,
            'role': row.role_name,
            'total_consumption': int(row.total_consumption or 0)
        } for row in users_with_consumption
    ]
    return jsonify({'users': data, 'count': len(data)})


@bp.route("/dev/add_user", methods=["GET", "POST"])
def dev_add_user():
    """Development-only simple user creation form."""
    # Check if we're in admin mode
    if not is_admin_mode():
        abort(404)

    # Ensure at least one role exists
    available_roles = roles.query.all()
    if not available_roles:
        # Create a default role for convenience
        default_role = roles(name="Default")
        db.session.add(default_role)
        db.session.commit()
        available_roles = [default_role]

    if request.method == "POST":
        # Handle both form data and JSON requests
        if request.is_json:
            data = request.get_json()
            first_name = data.get("first_name", "").strip()
            last_name = data.get("last_name", "").strip()
            email = data.get("email", "").strip() or None
            role_id = data.get("role_id")
        else:
            first_name = request.form.get("first_name", "").strip()
            last_name = request.form.get("last_name", "").strip()
            email = request.form.get("email", "").strip() or None
            role_id = request.form.get("role_id")

        if not first_name or not last_name or not role_id:
            if request.is_json:
                return jsonify({"success": False, "error": "First name, last name and role are required"}), 400
            flash("First name, last name and role are required", "danger")
            return render_template("dev_add_user.html", roles=available_roles)

        try:
            role_id = int(role_id)
        except ValueError:
            if request.is_json:
                return jsonify({"success": False, "error": "Invalid role selected"}), 400
            flash("Invalid role selected", "danger")
            return render_template("dev_add_user.html", roles=available_roles)

        try:
            new_user = users(first_name=first_name, last_name=last_name, email=email, role_id=role_id)
            db.session.add(new_user)
            db.session.commit()
            
            if request.is_json:
                return jsonify({
                    "success": True, 
                    "message": f"User {first_name} {last_name} created successfully",
                    "user": {
                        "id": new_user.id,
                        "first_name": new_user.first_name,
                        "last_name": new_user.last_name
                    }
                })
            
            flash(f"User {first_name} {last_name} created", "success")
            return redirect(url_for('routes.index'))
        except Exception as e:
            db.session.rollback()
            if request.is_json:
                return jsonify({"success": False, "error": f"Failed to create user: {str(e)}"}), 500
            flash(f"Failed to create user: {str(e)}", "danger")
            return render_template("dev_add_user.html", roles=available_roles)

    return render_template("dev_add_user.html", roles=available_roles)

@bp.route("/dev/roles", methods=["GET"])
def dev_get_roles():
    """Development-only endpoint to get available roles."""
    # Check if we're in admin mode
    if not is_admin_mode():
        abort(404)
    
    available_roles = roles.query.all()
    if not available_roles:
        # Create a default role for convenience
        default_role = roles(name="Default")
        db.session.add(default_role)
        db.session.commit()
        available_roles = [default_role]
    
    return jsonify([{"id": role.id, "name": role.name} for role in available_roles])

@bp.route("/dev/beverages", methods=["GET", "POST"])
def dev_beverages():
    """Development-only beverage management.
    GET: ?all=1 returns all beverages (active + inactive); default only active.
    POST: create new beverage.
    """
    if not is_admin_mode():
        abort(404)

    if request.method == "POST":
        data = request.get_json() or {}
        name = (data.get("name") or "").strip()
        category = data.get("category", "drink").strip()
        if not name:
            return jsonify({"success": False, "error": "Beverage name is required"}), 400
        if category not in ['drink', 'food']:
            return jsonify({"success": False, "error": "Category must be 'drink' or 'food'"}), 400
        try:
            new_beverage = beverages(name=name, category=category, status=True)
            db.session.add(new_beverage)
            db.session.commit()
            return jsonify({
                "success": True,
                "message": f"{category.title()} '{name}' created successfully",
                "beverage": {"id": new_beverage.id, "name": new_beverage.name, "category": new_beverage.category, "status": new_beverage.status}
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "error": f"Failed to create beverage: {str(e)}"}), 500

    include_all = request.args.get('all', type=int) == 1
    query = beverages.query
    if not include_all:
        query = query.filter_by(status=True)
    rows = query.order_by(beverages.id.asc()).all()
    return jsonify([
        {"id": r.id, "name": r.name, "category": r.category, "status": r.status} for r in rows
    ])

@bp.route("/dev/prices", methods=["GET", "POST"])
def dev_prices():
    """Development-only role-specific price management."""
    # Check if we're in admin mode
    if not is_admin_mode():
        abort(404)
    
    if request.method == "POST":
        data = request.get_json()
        role_id = data.get("role_id")
        prices = data.get("prices", [])  # Array of {beverage_id, price_cents}
        
        if not role_id:
            return jsonify({"success": False, "error": "Role ID is required"}), 400
        
        if not prices:
            return jsonify({"success": False, "error": "Prices are required"}), 400
        
        try:
            # Validate role exists
            role = roles.query.get(role_id)
            if not role:
                return jsonify({"success": False, "error": "Role not found"}), 404

            # Fetch existing prices for role (to update instead of deleting to preserve FK integrity)
            existing_rows = beverage_prices.query.filter_by(role_id=role_id).all()
            existing_map = {}
            duplicates = []
            for row in existing_rows:
                if row.beverage_id in existing_map:
                    duplicates.append(row)
                else:
                    existing_map[row.beverage_id] = row

            updated = 0
            created = 0

            for price_data in prices:
                beverage_id = price_data.get("beverage_id")
                price_cents = price_data.get("price_cents")
                if beverage_id is None or price_cents is None:
                    continue
                try:
                    price_cents = int(price_cents)
                except (TypeError, ValueError):
                    continue

                # Update existing or create new
                existing = existing_map.get(beverage_id)
                if existing:
                    if existing.price_cents != price_cents:
                        existing.price_cents = price_cents
                        updated += 1
                else:
                    new_price = beverage_prices(
                        role_id=role_id,
                        beverage_id=beverage_id,
                        price_cents=price_cents
                    )
                    db.session.add(new_price)
                    created += 1

            # Attempt to clean duplicate rows that are not referenced by any consumptions
            cleaned_duplicates = 0
            for dup in duplicates:
                if not dup.consumptions:  # safe to delete
                    db.session.delete(dup)
                    cleaned_duplicates += 1

            db.session.commit()
            msg = (f"Prices processed for role '{role.name}': {updated} updated, {created} created"
                   f"; {cleaned_duplicates} duplicate(s) cleaned" if cleaned_duplicates else
                   f"Prices processed for role '{role.name}': {updated} updated, {created} created")
            return jsonify({
                "success": True,
                "message": msg
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "error": f"Failed to update prices: {str(e)}"}), 500
    
    # GET request - return prices for a specific role or all roles
    try:
        role_id = request.args.get('role_id', type=int)
        
        if role_id:
            # Return prices for specific role
            role = roles.query.get(role_id)
            if not role:
                return jsonify({"success": False, "error": "Role not found"}), 404
            
            existing_prices = beverage_prices.query.filter_by(role_id=role_id).all()
            return jsonify([{
                "beverage_id": price.beverage_id,
                "price_cents": price.price_cents
            } for price in existing_prices])
        else:
            # Return all roles with their prices
            all_roles = roles.query.all()
            result = []
            
            for role in all_roles:
                role_prices = beverage_prices.query.filter_by(role_id=role.id).all()
                result.append({
                    "role_id": role.id,
                    "role_name": role.name,
                    "prices": [{
                        "beverage_id": price.beverage_id,
                        "price_cents": price.price_cents
                    } for price in role_prices]
                })
            
            return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to load prices: {str(e)}"}), 500

@bp.route("/dev/prices_unified", methods=["POST"])
def dev_prices_unified():
    """Development-only unified price management - set same prices for all roles."""
    # Check if we're in admin mode
    if not is_admin_mode():
        abort(404)
    
    data = request.get_json()
    prices = data.get("prices", [])  # Array of {beverage_id, price_cents}
    
    if not prices:
        return jsonify({"success": False, "error": "Prices are required"}), 400
    
    try:
        # Get all roles
        all_roles = roles.query.all()
        if not all_roles:
            return jsonify({"success": False, "error": "No roles found"}), 400

        total_updated = 0
        total_created = 0
        total_cleaned = 0

        for role in all_roles:
            existing_rows = beverage_prices.query.filter_by(role_id=role.id).all()
            existing_map = {}
            duplicates = []
            for row in existing_rows:
                if row.beverage_id in existing_map:
                    duplicates.append(row)
                else:
                    existing_map[row.beverage_id] = row

            updated = 0
            created = 0

            for price_data in prices:
                beverage_id = price_data.get("beverage_id")
                price_cents = price_data.get("price_cents")
                if beverage_id is None or price_cents is None:
                    continue
                try:
                    price_cents = int(price_cents)
                except (TypeError, ValueError):
                    continue

                existing = existing_map.get(beverage_id)
                if existing:
                    if existing.price_cents != price_cents:
                        existing.price_cents = price_cents
                        updated += 1
                else:
                    new_price = beverage_prices(
                        role_id=role.id,
                        beverage_id=beverage_id,
                        price_cents=price_cents
                    )
                    db.session.add(new_price)
                    created += 1

            cleaned_duplicates = 0
            for dup in duplicates:
                if not dup.consumptions:
                    db.session.delete(dup)
                    cleaned_duplicates += 1

            total_updated += updated
            total_created += created
            total_cleaned += cleaned_duplicates

        db.session.commit()
        msg = (f"Unified prices processed: {total_updated} updated, {total_created} created"
               f"; {total_cleaned} duplicate(s) cleaned" if total_cleaned else
               f"Unified prices processed: {total_updated} updated, {total_created} created")
        return jsonify({
            "success": True,
            "message": msg
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": f"Failed to update prices: {str(e)}"}), 500

@bp.route("/dev/roles_manage", methods=["GET", "POST"])
def dev_roles_manage():
    """Development-only role management."""
    # Check if we're in admin mode
    if not is_admin_mode():
        abort(404)
    
    if request.method == "POST":
        data = request.get_json()
        name = data.get("name", "").strip()
        
        if not name:
            return jsonify({"success": False, "error": "Role name is required"}), 400
        
        # Check if role with this name already exists
        existing_role = roles.query.filter_by(name=name).first()
        if existing_role:
            return jsonify({"success": False, "error": f"Role '{name}' already exists"}), 400
        
        try:
            new_role = roles(name=name)
            db.session.add(new_role)
            db.session.commit()
            
            return jsonify({
                "success": True,
                "message": f"Role '{name}' created successfully",
                "role": {"id": new_role.id, "name": new_role.name}
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "error": f"Failed to create role: {str(e)}"}), 500
    
    # GET request - return all roles
    all_roles = roles.query.all()
    return jsonify([{"id": role.id, "name": role.name} for role in all_roles])

@bp.route("/dev/delete_role/<int:role_id>", methods=["DELETE"])
def dev_delete_role(role_id):
    """Development-only individual role deletion."""
    # Check if we're in admin mode
    if not is_admin_mode():
        abort(404)
    
    try:
        role = roles.query.get(role_id)
        if not role:
            return jsonify({"success": False, "error": "Role not found"}), 404
        
        # Check if role has users
        user_count = users.query.filter_by(role_id=role_id).count()
        if user_count > 0:
            return jsonify({
                "success": False, 
                "error": f"Cannot delete role '{role.name}' - it has {user_count} user(s) assigned. Delete users first."
            }), 400
        
        # Delete related beverage_prices first (foreign key constraint)
        beverage_prices_count = beverage_prices.query.filter_by(role_id=role_id).count()
        if beverage_prices_count > 0:
            beverage_prices.query.filter_by(role_id=role_id).delete()
        
        role_name = role.name
        roles.query.filter_by(id=role_id).delete()
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": f"Role '{role_name}' deleted successfully"
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": f"Failed to delete role: {str(e)}"}), 500

@bp.route("/dev/delete_user/<int:user_id>", methods=["DELETE"])
def dev_delete_user(user_id):
    """Development-only individual user deletion."""
    # Check if we're in admin mode
    if not is_admin_mode():
        abort(404)
    
    try:
        user = users.query.get(user_id)
        if not user:
            return jsonify({"success": False, "error": "User not found"}), 404
        
        user_name = f"{user.first_name} {user.last_name}"
        
        # Delete related data first
        consumptions.query.filter_by(user_id=user_id).delete()
        invoices.query.filter_by(user_id=user_id).delete()
        
        # Delete the user
        users.query.filter_by(id=user_id).delete()
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": f"User '{user_name}' and all related data deleted successfully"
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": f"Failed to delete user: {str(e)}"}), 500

@bp.route('/dev/delete_pin/<int:user_id>', methods=['POST'])
def dev_delete_pin(user_id):
    """Development-only: clear a user's PIN hash without deleting the user."""
    if not is_admin_mode():
        abort(404)
    try:
        user = users.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        if not user.pin_hash:
            return jsonify({'success': False, 'error': 'User has no PIN set'}), 400
        remove_persistent_pin(user)
        user.pin_hash = None
        db.session.commit()
        return jsonify({'success': True, 'message': f"PIN deleted for {user.first_name} {user.last_name}"})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Failed to delete PIN: {str(e)}'}), 500

@bp.route('/dev/set_pin/<int:user_id>', methods=['POST'])
def dev_set_pin(user_id):
    """Development-only: set or replace a user's PIN."""
    if not is_admin_mode():
        abort(404)
    try:
        data = request.get_json() or {}
        pin = (data.get('pin') or '').strip()
        if not pin or not pin.isdigit() or len(pin) != 4:
            return jsonify({'success': False, 'error': 'PIN must be exactly 4 digits'}), 400
        user = users.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        pin_hash = hash_pin(pin)
        user.pin_hash = pin_hash
        store_persistent_pin(user, pin_hash)
        db.session.commit()
        return jsonify({'success': True, 'message': f"PIN set for {user.first_name} {user.last_name}"})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Failed to set PIN: {str(e)}'}), 500

@bp.route('/dev/update_user/<int:user_id>', methods=['POST'])
def dev_update_user(user_id):
    """Development-only: update user's first/last name and role."""
    if not is_admin_mode():
        abort(404)
    try:
        data = request.get_json() or {}
        first_name = (data.get('first_name') or '').strip()
        last_name = (data.get('last_name') or '').strip()
        role_id = data.get('role_id')
        if not first_name or not last_name or role_id is None:
            return jsonify({'success': False, 'error': 'first_name, last_name and role_id are required'}), 400
        try:
            role_id = int(role_id)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Invalid role_id'}), 400
        user = users.query.get(user_id)
        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404
        role = roles.query.get(role_id)
        if not role:
            return jsonify({'success': False, 'error': 'Role not found'}), 404
        user.first_name = first_name
        user.last_name = last_name
        user.role_id = role_id
        db.session.commit()
        return jsonify({'success': True, 'message': 'User updated successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Failed to update user: {str(e)}'}), 500

@bp.route("/dev/users_manage", methods=["GET"])
def dev_users_manage():
    """Development-only user management - get all users."""
    # Check if we're in admin mode
    if not is_admin_mode():
        abort(404)
    
    try:
        all_users = db.session.query(users, roles).join(roles, users.role_id == roles.id).all()
        users_data = []
        
        for user, role in all_users:
            users_data.append({
                "id": user.id,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "role_name": role.name,
                "role_id": user.role_id,
                "has_pin": user.pin_hash is not None,
                "status": user.status
            })
        
        return jsonify(users_data)
        
    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to load users: {str(e)}"}), 500

@bp.route("/dev/toggle_user_status/<int:user_id>", methods=["POST"])
def dev_toggle_user_status(user_id):
    """Development-only toggle user status (hide/show)."""
    # Check if we're in admin mode
    if not is_admin_mode():
        abort(404)
    
    try:
        user = db.session.query(users).filter(users.id == user_id).first()
        if not user:
            return jsonify({"success": False, "error": "User not found"}), 404
        
        # Toggle status
        user.status = not user.status
        db.session.commit()
        
        return jsonify({
            "success": True, 
            "status": user.status,
            "message": f"User {'hidden' if not user.status else 'shown'}"
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": f"Failed to toggle user status: {str(e)}"}), 500

@bp.route("/dev/delete_beverage/<int:beverage_id>", methods=["DELETE"])
def dev_delete_beverage(beverage_id):
    """Development-only individual beverage deletion."""
    # Check if we're in admin mode
    if not is_admin_mode():
        abort(404)
    
    try:
        beverage = beverages.query.get(beverage_id)
        if not beverage:
            return jsonify({"success": False, "error": "Beverage not found"}), 404
        
        # Check if beverage has prices or consumptions
        price_count = beverage_prices.query.filter_by(beverage_id=beverage_id).count()
        consumption_count = consumptions.query.filter_by(beverage_id=beverage_id).count()
        
        # Get the force_delete parameter from request
        force_delete = False
        try:
            if request.is_json:
                data = request.get_json() or {}
                force_delete = data.get('force_delete', False)
        except Exception:
            # If JSON parsing fails, default to False
            force_delete = False
        
        if (price_count > 0 or consumption_count > 0) and not force_delete:
            return jsonify({
                "success": False, 
                "error": f"Cannot delete '{beverage.name}' - it has {price_count} price(s) and {consumption_count} consumption(s).",
                "has_related_data": True,
                "price_count": price_count,
                "consumption_count": consumption_count,
                "beverage_name": beverage.name
            }), 400
        
        beverage_name = beverage.name
        beverage_category = beverage.category
        
        # If force_delete is True, delete all related data first
        if force_delete:
            # Delete all consumptions for this beverage
            if consumption_count > 0:
                consumptions.query.filter_by(beverage_id=beverage_id).delete()
            
            # Delete all prices for this beverage
            if price_count > 0:
                beverage_prices.query.filter_by(beverage_id=beverage_id).delete()
        
        # Delete the beverage itself
        beverages.query.filter_by(id=beverage_id).delete()
        db.session.commit()
        
        message = f"{beverage_category.title()} '{beverage_name}' deleted successfully"
        if force_delete and (price_count > 0 or consumption_count > 0):
            message += f" (including {consumption_count} consumption(s) and {price_count} price(s))"
        
        return jsonify({
            "success": True,
            "message": message
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": f"Failed to delete beverage: {str(e)}"}), 500

@bp.route("/dev/delete_data", methods=["POST"])
def dev_delete_data():
    """Development-only data deletion."""
    # Check if we're in admin mode
    if not is_admin_mode():
        abort(404)
    
    data = request.get_json()
    delete_types = data.get("delete_types", [])
    
    if not delete_types:
        return jsonify({"success": False, "error": "No data types selected for deletion"}), 400
    
    try:
        deleted_items = []
        
        # Delete in correct order to handle foreign key constraints
        # Order: payment_consumptions -> consumptions -> beverage_prices -> beverages -> invoices -> users -> roles
        
        if "consumptions" in delete_types:
            count = consumptions.query.count()
            
            # Delete payment_consumptions first (foreign key constraint)
            payment_consumptions_count = payment_consumptions.query.count()
            if payment_consumptions_count > 0:
                payment_consumptions.query.delete()
                deleted_items.append(f"{payment_consumptions_count} payment_consumption links")
            
            # Now delete consumptions
            consumptions.query.delete()
            deleted_items.append(f"{count} consumptions")
        
        if "prices" in delete_types:
            count = beverage_prices.query.count()
            beverage_prices.query.delete()
            deleted_items.append(f"{count} prices")
        
        if "beverages" in delete_types:
            count = beverages.query.count()
            
            # Delete beverage_prices first (foreign key constraint)
            # Only if prices weren't already deleted
            if "prices" not in delete_types:
                beverage_prices_count = beverage_prices.query.count()
                if beverage_prices_count > 0:
                    beverage_prices.query.delete()
                    deleted_items.append(f"{beverage_prices_count} beverage prices")
            
            # Now delete beverages
            beverages.query.delete()
            deleted_items.append(f"{count} beverages/food")
        
        if "users" in delete_types:
            count = users.query.count()
            
            # Delete related data first (foreign key constraints)
            # Order: payment_consumptions -> mypos_transactions -> user_payments -> consumptions -> invoices -> users
            
            # Delete payment_consumptions first (references user_payments and consumptions)
            # Must delete ALL payment_consumptions, not just those linked to consumptions
            payment_consumptions_count = payment_consumptions.query.count()
            if payment_consumptions_count > 0:
                payment_consumptions.query.delete()
                deleted_items.append(f"{payment_consumptions_count} payment_consumption links")
            
            # Delete mypos_transactions (references user_payments and users)
            mypos_transactions_count = mypos_transactions.query.count()
            if mypos_transactions_count > 0:
                mypos_transactions.query.delete()
                deleted_items.append(f"{mypos_transactions_count} mypos transactions")
            
            # Delete user_payments (references users)
            user_payments_count = user_payments.query.count()
            if user_payments_count > 0:
                user_payments.query.delete()
                deleted_items.append(f"{user_payments_count} user payments")
            
            # Delete consumptions (only if not already deleted)
            if "consumptions" not in delete_types:
                consumptions.query.delete()
            
            # Delete invoices
            invoices.query.delete()
            
            # Now delete users
            users.query.delete()
            deleted_items.append(f"{count} users")
        
        if "roles" in delete_types:
            count = roles.query.count()
            roles.query.delete()
            deleted_items.append(f"{count} roles")
        
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": f"Successfully deleted: {', '.join(deleted_items)}"
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": f"Failed to delete data: {str(e)}"}), 500

@bp.route("/guests")
def guests():
    """Guest entry page - uses a persistent 'Guests' user (role Guests)."""
    guest_user = get_or_create_guest_user()
    
    # Fetch all active beverages
    all_beverages = beverages.query.filter_by(status=True).all()
    
    # Fetch beverage prices for the guest role
    beverage_prices_for_role = beverage_prices.query.filter_by(role_id=guest_user.role_id).all()
    
    # Create a dictionary for easy price lookup
    price_lookup = {bp.beverage_id: bp for bp in beverage_prices_for_role}
    
    # Convert guest user to dictionary for JSON serialization
    user_dict = {
        'id': guest_user.id,
        'first_name': guest_user.first_name,
        'last_name': guest_user.last_name,
        'email': guest_user.email,
        'role': {
            'id': guest_user.role_id,
            'name': 'Guests'
        }
    }
    
    # Get current theme, color and version (for cache-busting)
    theme = settings.get_value('theme', 'coffee') or 'coffee'
    theme_colors = {
        'coffee': '#222222',
        'spring': '#4CAF50',
        'summer': '#FF9800',
        'autumn': '#FF5722',
        'winter': '#2196F3'
    }
    theme_color = theme_colors.get(theme, '#222222')
    theme_version = settings.get_value('theme_version', '1') or '1'
    
    response = make_response(render_template("entries.html", 
                         user=guest_user,
                         beverages=all_beverages,
                         price_lookup=price_lookup,
                         consumptions=[],
                         user_data=user_dict,
                         theme=theme,
                         theme_color=theme_color,
                         theme_version=theme_version,
                         payment_button_hidden=False))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@bp.route("/entries")
def entries():
    user_id = request.args.get('user_id', type=int)
    
    if not user_id:
        # Redirect to index if no user_id provided
        return redirect(url_for('routes.index'))

    user_record = users.query.get(user_id)
    if not user_record:
        return redirect(url_for('routes.index'))

    # Attempt to restore lost PINs from persistent archive
    if restore_pin_for_user(user_record):
        db.session.commit()
    
    # Security gate is disabled by default for development
    # Only apply if explicitly enabled and not bypassed
    if (SECURITY_GATE_ENABLED and 
        not session.get('security_gate_passed', False) and 
        not bypass_pin_for_dev()):
        return redirect(url_for('routes.security_gate'))
    
    # Check for admin bypass (only on admin port with authenticated admin session)
    if (is_admin_port() and session.get('admin_authenticated', False)):
        # Admin bypass - no PIN required (only on admin port when authenticated)
        pass
    else:
        # PIN verification required for all users (backend security)
        if user_record.pin_hash:
            # User has PIN - check if PIN was verified
            if not session.get(f'pin_verified_{user_id}', False):
                # PIN not verified - redirect to index with PIN requirement
                return redirect(url_for('routes.index') + f'?user_id={user_id}&require_pin=true')
    
    user = user_record
    
    # Fetch user's beverage consumptions with counts per beverage (CURRENT MONTH ONLY)
    # Users should only see their current month consumption, not historical data
    current_month = date.today().replace(day=1)
    consumption_results = db.session.query(
        consumptions.beverage_id,
        func.count(consumptions.id).label('count'),
        func.sum(consumptions.quantity).label('total_quantity')
    ).filter_by(user_id=user_id)\
     .filter(consumptions.created_at >= current_month)\
     .group_by(consumptions.beverage_id).all()
    
    # Convert to list of dictionaries for JSON serialization
    user_consumptions = []
    for result in consumption_results:
        user_consumptions.append({
            'beverage_id': result.beverage_id,
            'count': result.count,
            'total_quantity': result.total_quantity
        })
    
    # Fetch all active beverages
    all_beverages = beverages.query.filter_by(status=True).all()
    
    # Fetch beverage prices for this user's role
    beverage_prices_for_role = beverage_prices.query.filter_by(role_id=user.role_id).all()
    
    # Create a dictionary for easy price lookup
    price_lookup = {bp.beverage_id: bp for bp in beverage_prices_for_role}
    
    # Calculate total amount owed for ALL time (not just current month)
    # Get ALL consumptions for the user (no date filter)
    all_consumption_results = db.session.query(
        consumptions.beverage_id,
        func.sum(consumptions.quantity).label('total_quantity')
    ).filter_by(user_id=user_id)\
     .group_by(consumptions.beverage_id).all()
    
    total_amount_cents = 0
    for result in all_consumption_results:
        # Get the price for this beverage and user's role
        price_info = price_lookup.get(result.beverage_id)
        if price_info:
            total_amount_cents += result.total_quantity * price_info.price_cents
    
    # Convert user to dictionary for JSON serialization
    user_dict = {
        'id': user.id,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'email': user.email,
        'role': {
            'id': user.role.id,
            'name': user.role.name
        } if user.role else None
    }
    
    # Get current theme, color, and version (for cache busting)
    theme = settings.get_value('theme', 'coffee') or 'coffee'
    theme_colors = {
        'coffee': '#222222',
        'spring': '#4CAF50',
        'summer': '#FF9800',
        'autumn': '#FF5722',
        'winter': '#2196F3'
    }
    theme_color = theme_colors.get(theme, '#222222')
    theme_version = settings.get_value('theme_version', '1') or '1'
    
    # Check if payment button should be hidden (always visible on admin port)
    payment_button_hidden = settings.get_value('payment_button_hidden', 'false').lower() == 'true'
    if is_admin_port():
        payment_button_hidden = False
    

    response = make_response(render_template("entries.html", 
                         user=user, 
                         user_data=user_dict,
                         consumptions=user_consumptions,
                         beverages=all_beverages,
                         price_lookup=price_lookup,
                         total_amount_cents=total_amount_cents,
                         theme=theme,
                         theme_color=theme_color,
                         theme_version=theme_version,
                         payment_button_hidden=payment_button_hidden))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@bp.route("/verify_pin", methods=["POST"])
def verify_pin_route():
    """Verify PIN for a specific user"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        pin = data.get('pin', '').strip()
        
        if not user_id or not pin:
            return jsonify({"error": "User ID and PIN are required"}), 400

        user = users.query.get(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        if restore_pin_for_user(user):
            db.session.commit()
        
        # Use existing verify_pin function
        if verify_pin(user_id, pin):
            # Set session flag to indicate PIN was verified
            session[f'pin_verified_{user_id}'] = True
            return jsonify({"success": True})
        else:
            return jsonify({"error": "Invalid PIN"}), 401
        
    except Exception as e:
        return jsonify({"error": f"Failed to verify PIN: {str(e)}"}), 500

@bp.route("/check_user_pin", methods=["POST"])
def check_user_pin():
    """Check if a user has a PIN set"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        
        if not user_id:
            return jsonify({"error": "User ID is required"}), 400
        
        user = users.query.get(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        return jsonify({
            "success": True,
            "has_pin": user.pin_hash is not None
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to check user PIN: {str(e)}"}), 500

@bp.route("/create_user_pin", methods=["POST"])
def create_user_pin():
    """Create PIN for a specific user"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
            
        user_id = data.get('user_id')
        pin = data.get('pin', '').strip()
        
        if not user_id:
            return jsonify({"error": "User ID is required"}), 400
            
        if not pin:
            return jsonify({"error": "PIN is required"}), 400
        
        # Get the specific user
        user = users.query.get(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        # Check if user already has a PIN set
        if user.pin_hash:
            return jsonify({"error": "User already has a PIN set"}), 400
        
        # Use existing hash_pin function to hash the PIN
        pin_hash = hash_pin(pin)
        user.pin_hash = pin_hash
        store_persistent_pin(user, pin_hash)
        
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "PIN created successfully",
            "user": {
                "id": user.id,
                "first_name": user.first_name,
                "last_name": user.last_name
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Failed to create PIN: {str(e)}"}), 500

@bp.route("/add_consumption", methods=["POST"])
def add_consumption():
    """
    Add a beverage consumption entry.
    Creates invoice if it doesn't exist for current month.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
            
        try:
            user_id_raw = data.get('user_id')
            beverage_id_raw = data.get('beverage_id')
            quantity_raw = data.get('quantity', 1)
            
            if user_id_raw is None or beverage_id_raw is None:
                return jsonify({"error": "Missing required fields: user_id and beverage_id are required"}), 400
                
            user_id = int(user_id_raw)
            beverage_id = int(beverage_id_raw)
            quantity = int(quantity_raw)
        except (ValueError, TypeError) as e:
            return jsonify({"error": f"Invalid data format: {str(e)}"}), 400
        
        # Validate required identifiers
        # Note: user_id can be 0 for guest users; do not treat 0 as missing
        if beverage_id is None:
            return jsonify({"error": "Missing required fields"}), 400
        if beverage_id <= 0:
            return jsonify({"error": "Invalid beverage_id"}), 400
        
        # Handle guest users (user_id = 0)
        if user_id == 0:
            # Create a temporary guest user object
            user = type('GuestUser', (), {
                'id': 0,
                'role_id': 1,  # Default to role ID 1 (Guests role)
                'first_name': 'Guest',
                'last_name': ''
            })()
        else:
            # Validate regular user exists
            user = users.query.get(user_id)
            if not user:
                return jsonify({"error": "User not found"}), 404
        
        # Validate beverage exists and is active
        beverage = beverages.query.filter_by(id=beverage_id, status=True).first()
        if not beverage:
            return jsonify({"error": "Beverage not found or inactive"}), 404
        
        # Get beverage price for user's role
        beverage_price = beverage_prices.query.filter_by(
            role_id=user.role_id,
            beverage_id=beverage_id
        ).first()
        
        if not beverage_price:
            return jsonify({"error": "No price found for this beverage and role"}), 404
        
        # Get or create monthly invoice (skip for guest users with id 0)
        invoice = None
        if user_id != 0:
            invoice = check_invoice_exists(user_id)
        
        # Create consumption entry
        consumption = consumptions(
            user_id=user_id,
            beverage_id=beverage_id,
            beverage_price_id=beverage_price.id,
            invoice_id=(invoice.id if invoice else None),
            quantity=quantity,
            unit_price_cents=beverage_price.price_cents
        )
        
        db.session.add(consumption)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "Consumption added successfully",
            "consumption_id": consumption.id,
            "invoice_id": invoice.id
        })
        
    except ValueError as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Failed to add consumption: {str(e)}"}), 500

@bp.route("/dev/consumptions_manage", methods=["GET", "POST"])
def dev_consumptions_manage():
    """Development-only consumption management."""
    if not is_admin_mode():
        abort(404)
    
    if request.method == "POST":
        data = request.get_json()
        user_id = data.get('user_id')
        action = data.get('action')
        year = data.get('year')
        month = data.get('month')
        
        if not user_id:
            return jsonify({"success": False, "error": "User ID is required"}), 400
        
        try:
            if action == 'clear_all':
                # Clear all consumptions for the user in selected month (or current month if not provided)
                if year and month:
                    target_start = date(int(year), int(month), 1)
                    target_end = date(int(year) + (1 if int(month) == 12 else 0), (1 if int(month) == 12 else int(month)+1), 1)
                else:
                    target_start = date.today().replace(day=1)
                    target_end = (target_start.replace(month=1, year=target_start.year+1) if target_start.month == 12 else target_start.replace(month=target_start.month+1))
                consumptions.query.filter(
                    consumptions.user_id == user_id,
                    consumptions.created_at >= target_start,
                    consumptions.created_at < target_end
                ).delete()
                db.session.commit()
                return jsonify({"success": True, "message": "All consumptions cleared for selected month"})
            elif action == 'clear_beverage':
                beverage_id = data.get('beverage_id')
                if not beverage_id:
                    return jsonify({"success": False, "error": "Beverage ID is required"}), 400
                
                # Clear all consumptions for specific beverage and user in selected month (or current)
                if year and month:
                    target_start = date(int(year), int(month), 1)
                    target_end = date(int(year) + (1 if int(month) == 12 else 0), (1 if int(month) == 12 else int(month)+1), 1)
                else:
                    target_start = date.today().replace(day=1)
                    target_end = (target_start.replace(month=1, year=target_start.year+1) if target_start.month == 12 else target_start.replace(month=target_start.month+1))
                consumptions.query.filter(
                    consumptions.user_id == user_id,
                    consumptions.beverage_id == beverage_id,
                    consumptions.created_at >= target_start,
                    consumptions.created_at < target_end
                ).delete()
                db.session.commit()
                return jsonify({"success": True, "message": f"All consumptions for beverage {beverage_id} cleared for selected month"})
            elif action == 'adjust_quantity':
                beverage_id = data.get('beverage_id')
                new_quantity = data.get('new_quantity')
                
                if not beverage_id or new_quantity is None:
                    return jsonify({"success": False, "error": "Beverage ID and new quantity are required"}), 400
                
                try:
                    new_quantity = int(new_quantity)
                    if new_quantity < 0:
                        return jsonify({"success": False, "error": "Quantity cannot be negative"}), 400
                except (ValueError, TypeError):
                    return jsonify({"success": False, "error": "Invalid quantity format"}), 400
                
                # Get current total quantity for the beverage within selected month
                if year and month:
                    target_start = date(int(year), int(month), 1)
                    target_end = date(int(year) + (1 if int(month) == 12 else 0), (1 if int(month) == 12 else int(month)+1), 1)
                else:
                    target_start = date.today().replace(day=1)
                    target_end = (target_start.replace(month=1, year=target_start.year+1) if target_start.month == 12 else target_start.replace(month=target_start.month+1))
                current_consumptions = consumptions.query.filter(
                    consumptions.user_id == user_id,
                    consumptions.beverage_id == beverage_id,
                    consumptions.created_at >= target_start,
                    consumptions.created_at < target_end
                ).all()
                
                current_total = sum(c.quantity for c in current_consumptions)
                
                if new_quantity == current_total:
                    return jsonify({"success": True, "message": "Quantity unchanged"})
                
                # Clear existing consumptions
                for cons in current_consumptions:
                    db.session.delete(cons)
                
                # Add new consumption with adjusted quantity
                if new_quantity > 0:
                    # Get beverage price for user's role
                    user = users.query.get(user_id)
                    beverage_price = beverage_prices.query.filter_by(
                        role_id=user.role_id,
                        beverage_id=beverage_id
                    ).first()
                    
                    if not beverage_price:
                        return jsonify({"success": False, "error": "No price found for this beverage and role"}), 404
                    
                    # Get or create invoice for the selected month
                    invoice = check_invoice_exists(user_id, period=target_start)
                    
                    # Create new consumption with adjusted quantity
                    new_consumption = consumptions(
                        user_id=user_id,
                        beverage_id=beverage_id,
                        beverage_price_id=beverage_price.id,
                        invoice_id=invoice.id,
                        quantity=new_quantity,
                        unit_price_cents=beverage_price.price_cents
                    )
                    db.session.add(new_consumption)
                
                db.session.commit()
                return jsonify({"success": True, "message": f"Quantity adjusted to {new_quantity}"})
            elif action == 'add_backdated':
                # Admin-only: add consumptions for a specific month
                beverage_id = data.get('beverage_id')
                quantity = data.get('quantity')
                year = data.get('year')
                month = data.get('month')

                if not all([beverage_id, quantity, year, month]):
                    return jsonify({"success": False, "error": "beverage_id, quantity, year and month are required"}), 400

                try:
                    beverage_id = int(beverage_id)
                    quantity = int(quantity)
                    year = int(year)
                    month = int(month)
                    if quantity <= 0:
                        return jsonify({"success": False, "error": "Quantity must be positive"}), 400
                    # Clamp to 1..12
                    if month < 1 or month > 12:
                        return jsonify({"success": False, "error": "Invalid month"}), 400
                except (TypeError, ValueError):
                    return jsonify({"success": False, "error": "Invalid numeric values"}), 400

                try:
                    # Validate user and beverage
                    user = users.query.get(user_id)
                    if not user:
                        return jsonify({"success": False, "error": "User not found"}), 404
                    beverage = beverages.query.filter_by(id=beverage_id, status=True).first()
                    if not beverage:
                        return jsonify({"success": False, "error": "Beverage not found or inactive"}), 404

                    # Price for user's role
                    price_row = beverage_prices.query.filter_by(role_id=user.role_id, beverage_id=beverage_id).first()
                    if not price_row:
                        return jsonify({"success": False, "error": "No price found for this beverage and role"}), 404

                    # Target period (first day of selected month)
                    target_period = date(year, month, 1)

                    # Get or create invoice for that month
                    invoice = check_invoice_exists(user_id, period=target_period)

                    # Choose a created_at inside that month (use first day at noon)
                    created_at_dt = datetime(year, month, 1, 12, 0, 0)

                    # Create consumption row with given quantity
                    new_cons = consumptions(
                        user_id=user_id,
                        beverage_id=beverage_id,
                        beverage_price_id=price_row.id,
                        invoice_id=invoice.id,
                        quantity=quantity,
                        unit_price_cents=price_row.price_cents,
                        created_at=created_at_dt
                    )
                    db.session.add(new_cons)
                    db.session.commit()
                    return jsonify({"success": True, "message": f"Added {quantity} consumption(s) to {target_period.strftime('%Y-%m')}"})
                except Exception as e:
                    db.session.rollback()
                    return jsonify({"success": False, "error": f"Failed to add backdated consumption: {str(e)}"}), 500
            elif action == 'delete_consumption':
                cons_id = data.get('consumption_id')
                if not cons_id:
                    return jsonify({"success": False, "error": "consumption_id is required"}), 400
                row = consumptions.query.filter_by(id=cons_id, user_id=user_id).first()
                if not row:
                    return jsonify({"success": False, "error": "Consumption not found"}), 404
                db.session.delete(row)
                db.session.commit()
                return jsonify({"success": True, "message": "Consumption deleted"})
            else:
                return jsonify({"success": False, "error": "Invalid action"}), 400
                
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "error": f"Failed to clear consumptions: {str(e)}"}), 500
    
    # GET: Return consumptions for a specific user (optionally for a given month)
    user_id = request.args.get('user_id', type=int)
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    if not user_id:
        return jsonify({"success": False, "error": "User ID is required"}), 400
    
    try:
        if year and month:
            target_start = date(year, month, 1)
            target_end = date(year + (1 if month == 12 else 0), (1 if month == 12 else month+1), 1)
        else:
            target_start = date.today().replace(day=1)
            target_end = (target_start.replace(month=1, year=target_start.year+1) if target_start.month == 12 else target_start.replace(month=target_start.month+1))
        user_consumptions = db.session.query(
            consumptions,
            beverages.name.label('beverage_name'),
            beverages.category
        ).join(beverages, consumptions.beverage_id == beverages.id) \
         .filter(
             consumptions.user_id == user_id,
             consumptions.created_at >= target_start,
             consumptions.created_at < target_end
         ).order_by(consumptions.created_at.desc()).all()
        
        # Group by beverage
        beverage_totals = {}
        for cons, beverage_name, category in user_consumptions:
            if beverage_name not in beverage_totals:
                beverage_totals[beverage_name] = {
                    'beverage_id': cons.beverage_id,
                    'beverage_name': beverage_name,
                    'category': category,
                    'total_quantity': 0,
                    'consumptions': []
                }
            beverage_totals[beverage_name]['total_quantity'] += cons.quantity
            beverage_totals[beverage_name]['consumptions'].append({
                'id': cons.id,
                'quantity': cons.quantity,
                'created_at': cons.created_at.isoformat()
            })
        
        return jsonify({
            "success": True,
            "consumptions": list(beverage_totals.values()),
            "period": {"year": (year or target_start.year), "month": (month or target_start.month)}
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to fetch consumptions: {str(e)}"}), 500

@bp.route("/admin_consumption_history")
def admin_consumption_history():
    """Admin-only route to view historical consumption data for a specific user."""
    # Check if we're in admin mode
    if not is_admin_mode():
        abort(404)
    
    user_id = request.args.get('user_id', type=int)
    if not user_id:
        return jsonify({"error": "User ID required"}), 400
    
    # Get all historical consumption for this user (no date filter)
    consumption_results = db.session.query(
        consumptions.beverage_id,
        func.count(consumptions.id).label('count'),
        func.sum(consumptions.quantity).label('total_quantity'),
        func.min(consumptions.created_at).label('first_consumption'),
        func.max(consumptions.created_at).label('last_consumption')
    ).filter_by(user_id=user_id).group_by(consumptions.beverage_id).all()
    
    # Convert to list of dictionaries for JSON serialization
    historical_consumptions = []
    for result in consumption_results:
        historical_consumptions.append({
            'beverage_id': result.beverage_id,
            'count': result.count,
            'total_quantity': result.total_quantity,
            'first_consumption': result.first_consumption.isoformat() if result.first_consumption else None,
            'last_consumption': result.last_consumption.isoformat() if result.last_consumption else None
        })
    
    return jsonify({
        "user_id": user_id,
        "historical_consumptions": historical_consumptions
    })

@bp.route("/monthly_report")
def monthly_report():
    """Monthly consumption report for all users with optional date range."""
    # Check if we're in admin mode
    if not is_admin_mode():
        abort(404)
    
    # Get date range parameters
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    # If date range is provided, use it; otherwise use month/year
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            report_date = start_date
            use_date_range = True
        except ValueError:
            # Fallback to month/year if date parsing fails
            year = request.args.get('year', date.today().year, type=int)
            month = request.args.get('month', date.today().month, type=int)
            report_date = date(year, month, 1)
            start_date = report_date
            end_date = date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)
            use_date_range = False
    else:
        # Use month/year selection
        year = request.args.get('year', date.today().year, type=int)
        month = request.args.get('month', date.today().month, type=int)
        report_date = date(year, month, 1)
        start_date = report_date
        end_date = date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)
        use_date_range = False
    
    # Get all consumptions for the selected period
    month_consumptions = db.session.query(
        users.first_name,
        users.last_name,
        users.email,
        roles.name.label('role_name'),
        beverages.name.label('beverage_name'),
        beverages.category,
        func.sum(consumptions.quantity).label('total_quantity'),
        func.count(consumptions.id).label('consumption_count'),
        func.sum(consumptions.quantity * consumptions.unit_price_cents).label('total_cost_cents'),
        func.avg(consumptions.unit_price_cents).label('avg_price_cents')
    ).join(roles, users.role_id == roles.id)\
     .join(consumptions, users.id == consumptions.user_id)\
     .join(beverages, consumptions.beverage_id == beverages.id)\
     .filter(
         consumptions.created_at >= start_date,
         consumptions.created_at < end_date
     )\
     .group_by(users.id, users.first_name, users.last_name, users.email, roles.name, beverages.id, beverages.name, beverages.category)\
     .order_by(users.last_name, users.first_name, beverages.name)\
     .all()
    
    # Get summary statistics
    summary_stats = db.session.query(
        func.count(func.distinct(users.id)).label('total_users'),
        func.count(consumptions.id).label('total_consumptions'),
        func.sum(consumptions.quantity).label('total_quantity'),
        func.sum(consumptions.quantity * consumptions.unit_price_cents).label('total_revenue_cents')
    ).join(consumptions, users.id == consumptions.user_id)\
     .filter(
         consumptions.created_at >= start_date,
         consumptions.created_at < end_date
     )\
     .first()
    
    # Get user summaries (total per user)
    user_summaries = db.session.query(
        users.id,
        users.first_name,
        users.last_name,
        users.email,
        roles.name.label('role_name'),
        func.sum(consumptions.quantity).label('total_quantity'),
        func.count(consumptions.id).label('total_consumptions'),
        func.sum(consumptions.quantity * consumptions.unit_price_cents).label('total_cost_cents')
    ).join(roles, users.role_id == roles.id)\
     .join(consumptions, users.id == consumptions.user_id)\
     .filter(
         consumptions.created_at >= start_date,
         consumptions.created_at < end_date
     )\
     .group_by(users.id, users.first_name, users.last_name, users.email, roles.name)\
     .order_by(func.sum(consumptions.quantity * consumptions.unit_price_cents).desc())\
     .all()
    
    # Get available months for navigation
    available_months = db.session.query(
        func.extract('year', consumptions.created_at).label('year'),
        func.extract('month', consumptions.created_at).label('month')
    ).distinct()\
     .order_by(func.extract('year', consumptions.created_at).desc(), func.extract('month', consumptions.created_at).desc())\
     .all()
    
    # Get daily statistics if using date range
    daily_stats = []
    if use_date_range:
        daily_stats = db.session.query(
            func.date(consumptions.created_at).label('date'),
            func.count(consumptions.id).label('daily_consumptions'),
            func.sum(consumptions.quantity).label('daily_quantity'),
            func.sum(consumptions.quantity * consumptions.unit_price_cents).label('daily_revenue_cents')
        ).filter(
            consumptions.created_at >= start_date,
            consumptions.created_at < end_date
        ).group_by(func.date(consumptions.created_at))\
         .order_by(func.date(consumptions.created_at))\
         .all()
    
    # Get current theme and theme color
    theme = settings.get_value('theme', 'coffee') or 'coffee'
    theme_colors = {
        'coffee': '#222222',
        'spring': '#4CAF50',
        'summer': '#FF9800',
        'autumn': '#FF5722',
        'winter': '#2196F3'
    }
    theme_color = theme_colors.get(theme, '#222222')
    
    return render_template("monthly_report.html", 
                         consumptions=month_consumptions,
                         summary_stats=summary_stats,
                         user_summaries=user_summaries,
                         available_months=available_months,
                         current_year=year if not use_date_range else start_date.year,
                         current_month=month if not use_date_range else start_date.month,
                         report_date=report_date,
                         start_date=start_date,
                         end_date=end_date,
                         use_date_range=use_date_range,
                         daily_stats=daily_stats,
                         theme=theme,
                         theme_color=theme_color)

# =============================================================================
# CSV EXPORT AND BACKUP ROUTES
# =============================================================================

def _get_project_root():
    """Get the project root directory reliably"""
    from pathlib import Path
    import os
    
    # Try multiple methods to find project root
    # Method 1: Use __file__ from routes.py
    try:
        routes_file = Path(__file__).resolve()
        base_dir = routes_file.parent.parent
        if (base_dir / "CSV For each month").exists():
            return base_dir
    except:
        pass
    
    # Method 2: Use current working directory
    cwd = Path(os.getcwd())
    if (cwd / "CSV For each month").exists():
        return cwd
    
    # Method 3: Try going up from current directory
    current = Path.cwd()
    for parent in [current, current.parent, current.parent.parent]:
        if (parent / "CSV For each month").exists():
            return parent
    
    # Fallback: use current working directory
    return cwd

def _normalize_name_for_matching(name):
    """Normalize a name for fuzzy matching, handling encoding issues.
    Generates variants in both directions: corrupted->correct and correct->corrupted.
    This handles cases like 'M├╝ller' <-> 'Müller'."""
    if not name:
        return []
    
    name = name.strip()
    variants = [name]  # Start with original
    
    # Common encoding fixes for German umlauts and other special characters (corrupted -> correct)
    encoding_fixes = {
        '├╝': 'ü', '├ñ': 'ä', '├Â': 'ö', '├ƒ': 'ß',
        'Ã¼': 'ü', 'Ã¤': 'ä', 'Ã¶': 'ö', 'ÃŸ': 'ß',
        'Ãœ': 'Ü', 'Ã„': 'Ä', 'Ã–': 'Ö',
        '??': 'ü',  # Sometimes shows as ??
        # Norwegian/Danish characters
        '├©': 'ø', '├Ñ': 'å', 'Ã¸': 'ø', 'Ã¥': 'å',
    }
    
    # Reverse mapping (correct -> corrupted) for matching CSV names against corrupted DB names
    reverse_fixes = {
        'ü': ['├╝', 'Ã¼', 'ue'],
        'ä': ['├ñ', 'Ã¤', 'ae'],
        'ö': ['├Â', 'Ã¶', 'oe'],
        'ß': ['├ƒ', 'ÃŸ', 'ss'],
        'Ü': ['Ãœ', 'UE'],
        'Ä': ['Ã„', 'AE'],
        'Ö': ['Ã–', 'OE'],
        # Norwegian/Danish characters
        'ø': ['├©', 'Ã¸', 'o'],
        'å': ['├Ñ', 'Ã¥', 'aa'],
        'Ø': ['Ã˜', 'OE'],
        'Å': ['Ã…', 'AA'],
    }
    
    # Generate variants with encoding fixes (corrupted -> correct)
    for corrupted, correct in encoding_fixes.items():
        if corrupted in name:
            variant = name.replace(corrupted, correct)
            variants.append(variant)
    
    # Generate variants with reverse fixes (correct -> corrupted) for matching
    for correct, corrupted_list in reverse_fixes.items():
        if correct in name:
            for corrupted in corrupted_list:
                variant = name.replace(correct, corrupted)
                variants.append(variant)
    
    # Also try without accents (for cases where both exist)
    import unicodedata
    no_accents = ''.join(
        c for c in unicodedata.normalize('NFD', name)
        if unicodedata.category(c) != 'Mn'
    )
    if no_accents != name:
        variants.append(no_accents)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_variants = []
    for v in variants:
        v_lower = v.lower()
        if v_lower not in seen:
            seen.add(v_lower)
            unique_variants.append(v)
    
    return unique_variants

def _fuzzy_match_user(user_name, all_users_dict):
    """Try to match a user name using fuzzy matching with encoding normalization."""
    # Try exact match first
    if user_name in all_users_dict:
        return all_users_dict[user_name], 'exact'
    
    # Normalize the input name and get variants
    variants = _normalize_name_for_matching(user_name)
    user_name_lower = user_name.lower()
    
    # Try normalized variants exact match
    for variant in variants:
        if variant in all_users_dict:
            return all_users_dict[variant], f'fuzzy (encoding fix: {user_name} -> {variant})'
    
    # Try case-insensitive match on original
    for db_name, user_obj in all_users_dict.items():
        if db_name.lower() == user_name_lower:
            return user_obj, f'fuzzy (case-insensitive: {user_name} -> {db_name})'
    
    # Try with normalized variants case-insensitive
    for variant in variants:
        variant_lower = variant.lower()
        for db_name, user_obj in all_users_dict.items():
            if db_name.lower() == variant_lower:
                return user_obj, f'fuzzy (encoding+case: {user_name} -> {db_name})'
    
    # Last resort: try partial matching (if name contains the search term)
    # This handles cases where there might be extra spaces or minor differences
    user_words = user_name_lower.split()
    if len(user_words) >= 2:
        for db_name, user_obj in all_users_dict.items():
            db_words = db_name.lower().split()
            if len(db_words) >= 2:
                # Check if first and last name words match
                if (user_words[0] == db_words[0] and 
                    user_words[-1] == db_words[-1] and
                    len(user_words) == len(db_words)):
                    return user_obj, f'fuzzy (partial match: {user_name} -> {db_name})'
    
    return None, None

@bp.route("/admin/export/detailed_backup")
@require_admin_only
def export_detailed_backup():
    """Export detailed backup CSV with individual consumption records for restoration.
    This includes all fields needed to restore data from backup."""
    import csv
    import io
    
    # Get date range parameters
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    # Determine date range
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({"error": "Invalid date format"}), 400
    elif year and month:
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1)
        else:
            end_date = date(year, month + 1, 1)
    else:
        # Default to previous month
        today = date.today()
        if today.month == 1:
            start_date = date(today.year - 1, 12, 1)
            end_date = date(today.year, 1, 1)
        else:
            start_date = date(today.year, today.month - 1, 1)
            end_date = date(today.year, today.month, 1)
    
    # Get all individual consumption records with full details
    consumption_records = db.session.query(
        consumptions.id,
        consumptions.user_id,
        users.first_name,
        users.last_name,
        users.email,
        users.itsl_id,
        roles.name.label('role_name'),
        consumptions.beverage_id,
        beverages.name.label('beverage_name'),
        beverages.category,
        consumptions.quantity,
        consumptions.unit_price_cents,
        consumptions.invoice_id,
        consumptions.beverage_price_id,
        consumptions.created_at
    ).join(users, consumptions.user_id == users.id)\
     .join(roles, users.role_id == roles.id)\
     .join(beverages, consumptions.beverage_id == beverages.id)\
     .filter(
         consumptions.created_at >= start_date,
         consumptions.created_at < end_date
     )\
     .order_by(consumptions.created_at, consumptions.id)\
     .all()
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header with metadata
    writer.writerow(['# BACKUP FILE - Detailed Consumption Records'])
    writer.writerow(['# Generated:', datetime.now().isoformat()])
    writer.writerow(['# Period:', f"{start_date} to {end_date}"])
    writer.writerow(['# Total Records:', len(consumption_records)])
    writer.writerow([])
    
    # Write column headers
    writer.writerow([
        'CONSUMPTION_ID',
        'USER_ID',
        'USER_FIRST_NAME',
        'USER_LAST_NAME',
        'USER_EMAIL',
        'USER_ITSL_ID',
        'USER_ROLE',
        'BEVERAGE_ID',
        'BEVERAGE_NAME',
        'BEVERAGE_CATEGORY',
        'QUANTITY',
        'UNIT_PRICE_CENTS',
        'TOTAL_COST_CENTS',
        'INVOICE_ID',
        'BEVERAGE_PRICE_ID',
        'CREATED_AT'
    ])
    
    # Write data rows
    for record in consumption_records:
        total_cost_cents = record.quantity * record.unit_price_cents
        writer.writerow([
            record.id,
            record.user_id,
            record.first_name,
            record.last_name,
            record.email or '',
            record.itsl_id or '',
            record.role_name,
            record.beverage_id,
            record.beverage_name,
            record.category,
            record.quantity,
            record.unit_price_cents,
            total_cost_cents,
            record.invoice_id,
            record.beverage_price_id,
            record.created_at.isoformat()
        ])
    
    # Prepare response
    output.seek(0)
    filename = f"consumption_backup_{start_date.strftime('%Y_%m')}.csv"
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Type': 'text/csv; charset=utf-8'
        }
    )

@bp.route("/admin/export/aggregated_report")
@require_admin_only
def export_aggregated_report():
    """Export aggregated report CSV (for reporting/analysis).
    This is similar to the current CSV but with improved format."""
    import csv
    import io
    
    # Get date range parameters
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    # Determine date range
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            report_date = start_date
        except ValueError:
            return jsonify({"error": "Invalid date format"}), 400
    elif year and month:
        report_date = date(year, month, 1)
        start_date = report_date
        if month == 12:
            end_date = date(year + 1, 1, 1)
        else:
            end_date = date(year, month + 1, 1)
    else:
        # Default to previous month
        today = date.today()
        if today.month == 1:
            report_date = date(today.year - 1, 12, 1)
            start_date = report_date
            end_date = date(today.year, 1, 1)
        else:
            report_date = date(today.year, today.month - 1, 1)
            start_date = report_date
            end_date = date(today.year, today.month, 1)
    
    # Get aggregated consumption data (same as monthly_report)
    month_consumptions = db.session.query(
        users.first_name,
        users.last_name,
        users.email,
        roles.name.label('role_name'),
        beverages.name.label('beverage_name'),
        beverages.category,
        func.sum(consumptions.quantity).label('total_quantity'),
        func.count(consumptions.id).label('consumption_count'),
        func.sum(consumptions.quantity * consumptions.unit_price_cents).label('total_cost_cents'),
        func.avg(consumptions.unit_price_cents).label('avg_price_cents')
    ).join(roles, users.role_id == roles.id)\
     .join(consumptions, users.id == consumptions.user_id)\
     .join(beverages, consumptions.beverage_id == beverages.id)\
     .filter(
         consumptions.created_at >= start_date,
         consumptions.created_at < end_date
     )\
     .group_by(users.id, users.first_name, users.last_name, users.email, roles.name, beverages.id, beverages.name, beverages.category)\
     .order_by(users.last_name, users.first_name, beverages.name)\
     .all()
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header with metadata
    writer.writerow(['# MONTHLY CONSUMPTION REPORT - Aggregated Data'])
    writer.writerow(['# Generated:', datetime.now().isoformat()])
    writer.writerow(['# Period:', f"{start_date} to {end_date}"])
    writer.writerow(['# Report Date:', report_date.strftime('%Y-%m')])
    writer.writerow(['# Total Users:', len(set((c.first_name, c.last_name) for c in month_consumptions))])
    writer.writerow([])
    
    # Write column headers
    writer.writerow([
        'USER',
        'ROLE',
        'BEVERAGE',
        'CATEGORY',
        'QUANTITY',
        'ORDERS',
        'AVG PRICE',
        'TOTAL COST'
    ])
    
    # Write data rows
    for consumption in month_consumptions:
        user_name = f"{consumption.first_name} {consumption.last_name}"
        avg_price_euros = consumption.avg_price_cents / 100.0
        total_cost_euros = consumption.total_cost_cents / 100.0
        
        writer.writerow([
            user_name,
            consumption.role_name,
            consumption.beverage_name,
            consumption.category.title(),
            consumption.total_quantity,
            consumption.consumption_count,
            f"€{avg_price_euros:.2f}",
            f"€{total_cost_euros:.2f}"
        ])
    
    # Prepare response
    output.seek(0)
    filename = f"consumption_report_{report_date.strftime('%Y_%m')}.csv"
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Type': 'text/csv; charset=utf-8'
        }
    )

@bp.route("/admin/export/generate_monthly_backup", methods=["POST"])
@require_admin_only
def generate_monthly_backup():
    """Automatically generate monthly backup files (both detailed and aggregated).
    This endpoint can be called manually or scheduled via cron."""
    import os
    from pathlib import Path
    
    # Get target month (defaults to previous month)
    year = request.json.get('year') if request.is_json else request.form.get('year', type=int)
    month = request.json.get('month') if request.is_json else request.form.get('month', type=int)
    
    if not year or not month:
        # Default to previous month
        today = date.today()
        if today.month == 1:
            year = today.year - 1
            month = 12
        else:
            year = today.year
            month = today.month - 1
    
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)
    
    # Get project root directory
    base_dir = _get_project_root()
    backup_dir = base_dir / "CSV For each month"
    backup_dir.mkdir(exist_ok=True)
    
    # Generate detailed backup
    detailed_records = db.session.query(
        consumptions.id,
        consumptions.user_id,
        users.first_name,
        users.last_name,
        users.email,
        users.itsl_id,
        roles.name.label('role_name'),
        consumptions.beverage_id,
        beverages.name.label('beverage_name'),
        beverages.category,
        consumptions.quantity,
        consumptions.unit_price_cents,
        consumptions.invoice_id,
        consumptions.beverage_price_id,
        consumptions.created_at
    ).join(users, consumptions.user_id == users.id)\
     .join(roles, users.role_id == roles.id)\
     .join(beverages, consumptions.beverage_id == beverages.id)\
     .filter(
         consumptions.created_at >= start_date,
         consumptions.created_at < end_date
     )\
     .order_by(consumptions.created_at, consumptions.id)\
     .all()
    
    # Write detailed backup CSV
    detailed_filename = backup_dir / f"consumption_backup_{start_date.strftime('%Y_%m')}.csv"
    with open(detailed_filename, 'w', newline='', encoding='utf-8') as f:
        import csv
        writer = csv.writer(f)
        
        writer.writerow(['# BACKUP FILE - Detailed Consumption Records'])
        writer.writerow(['# Generated:', datetime.now().isoformat()])
        writer.writerow(['# Period:', f"{start_date} to {end_date}"])
        writer.writerow(['# Total Records:', len(detailed_records)])
        writer.writerow([])
        
        writer.writerow([
            'CONSUMPTION_ID', 'USER_ID', 'USER_FIRST_NAME', 'USER_LAST_NAME',
            'USER_EMAIL', 'USER_ITSL_ID', 'USER_ROLE', 'BEVERAGE_ID',
            'BEVERAGE_NAME', 'BEVERAGE_CATEGORY', 'QUANTITY', 'UNIT_PRICE_CENTS',
            'TOTAL_COST_CENTS', 'INVOICE_ID', 'BEVERAGE_PRICE_ID', 'CREATED_AT'
        ])
        
        for record in detailed_records:
            total_cost_cents = record.quantity * record.unit_price_cents
            writer.writerow([
                record.id, record.user_id, record.first_name, record.last_name,
                record.email or '', record.itsl_id or '', record.role_name,
                record.beverage_id, record.beverage_name, record.category,
                record.quantity, record.unit_price_cents, total_cost_cents,
                record.invoice_id, record.beverage_price_id,
                record.created_at.isoformat()
            ])
    
    # Generate aggregated report
    aggregated_data = db.session.query(
        users.first_name,
        users.last_name,
        users.email,
        roles.name.label('role_name'),
        beverages.name.label('beverage_name'),
        beverages.category,
        func.sum(consumptions.quantity).label('total_quantity'),
        func.count(consumptions.id).label('consumption_count'),
        func.sum(consumptions.quantity * consumptions.unit_price_cents).label('total_cost_cents'),
        func.avg(consumptions.unit_price_cents).label('avg_price_cents')
    ).join(roles, users.role_id == roles.id)\
     .join(consumptions, users.id == consumptions.user_id)\
     .join(beverages, consumptions.beverage_id == beverages.id)\
     .filter(
         consumptions.created_at >= start_date,
         consumptions.created_at < end_date
     )\
     .group_by(users.id, users.first_name, users.last_name, users.email, roles.name, beverages.id, beverages.name, beverages.category)\
     .order_by(users.last_name, users.first_name, beverages.name)\
     .all()
    
    # Write aggregated report CSV
    report_filename = backup_dir / f"consumption_report_{start_date.strftime('%Y_%m')}.csv"
    with open(report_filename, 'w', newline='', encoding='utf-8') as f:
        import csv
        writer = csv.writer(f)
        
        writer.writerow(['# MONTHLY CONSUMPTION REPORT - Aggregated Data'])
        writer.writerow(['# Generated:', datetime.now().isoformat()])
        writer.writerow(['# Period:', f"{start_date} to {end_date}"])
        writer.writerow(['# Report Date:', start_date.strftime('%Y-%m')])
        writer.writerow(['# Total Users:', len(set((c.first_name, c.last_name) for c in aggregated_data))])
        writer.writerow([])
        
        writer.writerow(['USER', 'BEVERAGE', 'CATEGORY', 'QUANTITY', 'ORDERS', 'AVG PRICE', 'TOTAL COST'])
        
        for consumption in aggregated_data:
            user_name = f"{consumption.first_name} {consumption.last_name}"
            avg_price_euros = consumption.avg_price_cents / 100.0
            total_cost_euros = consumption.total_cost_cents / 100.0
            
            writer.writerow([
                user_name,
                consumption.beverage_name,
                consumption.category.title(),
                consumption.total_quantity,
                consumption.consumption_count,
                f"€{avg_price_euros:.2f}",
                f"€{total_cost_euros:.2f}"
            ])
    
    return jsonify({
        "success": True,
        "message": f"Monthly backup generated for {start_date.strftime('%Y-%m')}",
        "files": {
            "detailed_backup": str(detailed_filename),
            "aggregated_report": str(report_filename)
        },
        "records": len(detailed_records),
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat()
        }
    })

@bp.route("/admin/restore/from_csv", methods=["POST"])
@require_admin_only
def restore_from_csv():
    """Restore consumptions from aggregated CSV report.
    Deletes consumptions from target month and imports from CSV file.
    Matches users by EXACT name only (case-insensitive). If no exact match is found, creates a new user."""
    import csv
    from pathlib import Path
    
    try:
        print("=== RESTORE FROM CSV STARTED ===")
        # Get filename from request (defaults to consumption_report_2025_09.csv)
        filename = request.json.get('filename') if request.is_json else request.form.get('filename')
        if not filename:
            filename = "consumption_report_2025_09.csv"
        
        # Extract year/month from filename (format: consumption_report_YYYY_MM.csv)
        import re
        match = re.search(r'(\d{4})_(\d{2})', filename)
        if match:
            year = int(match.group(1))
            month = int(match.group(2))
        else:
            # Try to get from request if filename doesn't match pattern
            year = request.json.get('year') if request.is_json else request.form.get('year', type=int)
            month = request.json.get('month') if request.is_json else request.form.get('month', type=int)
            
            if not year or not month:
                return jsonify({
                    "success": False,
                    "error": "Could not extract year/month from filename. Please specify year and month in the request."
                }), 400
        
        # Get project root directory
        base_dir = _get_project_root()
        csv_path = base_dir / "CSV For each month" / filename
        
        print(f"Base dir: {base_dir}")
        print(f"CSV path: {csv_path}")
        print(f"CSV exists: {csv_path.exists()}")
        
        if not csv_path.exists():
            return jsonify({
                "success": False,
                "error": f"CSV file not found: {csv_path}",
                "base_dir": str(base_dir),
                "filename": filename
            }), 404
        
        print(f"Starting restore from {csv_path} for {year}-{month:02d}")
        
        # Step 1: Delete consumptions from the target month only
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1)
        else:
            end_date = date(year, month + 1, 1)
        
        print(f"Deleting consumptions from {start_date} to {end_date}...")
        
        # First, get the consumption IDs that will be deleted
        consumption_ids_to_delete = db.session.query(consumptions.id).filter(
            consumptions.created_at >= start_date,
            consumptions.created_at < end_date
        ).all()
        consumption_ids_to_delete = [c[0] for c in consumption_ids_to_delete]
        
        # Delete payment_consumptions records that reference these consumptions
        if consumption_ids_to_delete:
            payment_consumptions_deleted = payment_consumptions.query.filter(
                payment_consumptions.consumption_id.in_(consumption_ids_to_delete)
            ).delete(synchronize_session=False)
            print(f"Deleted {payment_consumptions_deleted} payment_consumption links")
        
        # Now delete the consumptions
        deleted_count = consumptions.query.filter(
            consumptions.created_at >= start_date,
            consumptions.created_at < end_date
        ).delete(synchronize_session=False)
        db.session.commit()
        print(f"Deleted {deleted_count} existing consumptions for {year}-{month:02d}")
        
        # Step 2: Read and parse CSV
        print(f"Reading CSV file: {csv_path}")
        imported_count = 0
        errors = []
        warnings = []
        
        # Get all users for matching - EXACT MATCH ONLY
        # Build user lookup with exact names only (case-insensitive for matching)
        all_users = {}
        for u in users.query.all():
            user_full_name = f"{u.first_name} {u.last_name}".strip()
            # Store with exact name and case-insensitive version for matching
            all_users[user_full_name] = u
            all_users[user_full_name.lower()] = u  # For case-insensitive lookup
        
        print(f"Built user lookup with {len(users.query.all())} users (exact match only)")
        
        # Build beverage lookup with multiple name variants for fuzzy matching
        all_beverages = {}
        for b in beverages.query.all():
            # Add exact name
            all_beverages[b.name] = b
            # Add normalized variants (to handle encoding issues in database)
            variants = _normalize_name_for_matching(b.name)
            for variant in variants:
                if variant != b.name:  # Don't duplicate exact match
                    all_beverages[variant] = b
        
        # Get or create guest user
        guests_role = roles.query.filter_by(name="Guests").first()
        if not guests_role:
            guests_role = roles(name="Guests")
            db.session.add(guests_role)
            db.session.flush()
        
        guest_user = users.query.filter_by(first_name="Guest", last_name="").first()
        if not guest_user:
            guest_user = users(
                first_name="Guest",
                last_name="",
                role_id=guests_role.id,
                status=True
            )
            db.session.add(guest_user)
            db.session.flush()
        
        # Handle "Guests ㅤ" with special character - normalize it
        all_users["Guests ㅤ"] = guest_user  # Match the CSV format exactly
        all_users["Guests"] = guest_user  # Also match without special char
        # Try to match with various whitespace characters
        for variant in ["Guests ", "Guests  ", "Guests\u3164", "Guests\u00A0"]:
            all_users[variant] = guest_user
        
        # Target period (first day of the month)
        target_period = date(year, month, 1)
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                # Handle quoted values (CSV uses quotes)
                user_name = row.get('USER', '').strip().strip('"')
                role_name = row.get('ROLE', '').strip().strip('"')  # Optional: role from CSV
                beverage_name = row.get('BEVERAGE', '').strip().strip('"')
                quantity_str = row.get('QUANTITY', '').strip().strip('"')
                orders_str = row.get('ORDERS', '').strip().strip('"')
                avg_price_str = row.get('AVG PRICE', '').strip().strip('"')
                
                if not user_name or not beverage_name or not quantity_str:
                    continue
                
                # Normalize user name (handle special characters in "Guests ㅤ")
                user_name_normalized = user_name
                # Replace various whitespace/special chars with standard space
                user_name_normalized = re.sub(r'[\u3164\u00A0\u2000-\u200B]+', ' ', user_name_normalized).strip()
                
                # Parse quantity and orders
                try:
                    total_quantity = int(quantity_str)
                    num_orders = int(orders_str) if orders_str else 1
                except ValueError:
                    warnings.append(f"Invalid quantity/orders for {user_name} - {beverage_name}")
                    continue
                
                # Parse average price (remove € and convert to cents)
                try:
                    avg_price_clean = avg_price_str.replace('€', '').replace(',', '.').strip()
                    avg_price_euros = float(avg_price_clean)
                    unit_price_cents = int(avg_price_euros * 100)
                except (ValueError, AttributeError):
                    warnings.append(f"Invalid price for {user_name} - {beverage_name}: {avg_price_str}")
                    continue
                
                # Match user by name - EXACT MATCH ONLY (case-insensitive)
                # Try exact match first (case-insensitive)
                user = all_users.get(user_name) or all_users.get(user_name.lower())
                
                # If no exact match found, try with normalized whitespace
                if not user:
                    user = all_users.get(user_name_normalized) or all_users.get(user_name_normalized.lower())
                
                if not user:
                    # User doesn't exist - create a new user
                    user_words = user_name.split()
                    if len(user_words) >= 2:
                        first_name = user_words[0]
                        last_name = ' '.join(user_words[1:])
                        
                        # Get role from CSV if provided, otherwise use default
                        user_role = None
                        if role_name:
                            user_role = roles.query.filter_by(name=role_name).first()
                        
                        # If role not found from CSV, use default
                        if not user_role:
                            default_role = roles.query.filter_by(name="Students").first()
                            if not default_role:
                                default_role = roles.query.first()
                            user_role = default_role
                        
                        if not user_role:
                            errors.append(f"Cannot create user '{user_name}': No roles exist in database")
                            continue
                        
                        # Create new user
                        new_user = users(
                            first_name=first_name,
                            last_name=last_name,
                            role_id=user_role.id,
                            status=True
                        )
                        db.session.add(new_user)
                        db.session.flush()
                        
                        user = new_user
                        role_info = role_name if role_name and user_role.name == role_name else user_role.name
                        warnings.append(f"Created new user: {user_name} (assigned to role: {role_info})")
                        
                        # Add to lookup dictionary for subsequent rows
                        all_users[user_name] = user
                        all_users[user_name.lower()] = user
                    else:
                        # Can't create user without first and last name
                        errors.append(f"User not found and cannot create: {user_name} (invalid format - needs first and last name)")
                        continue
                
                # Match beverage by name using fuzzy matching
                beverage = all_beverages.get(beverage_name)
                if not beverage:
                    # Try fuzzy matching for beverages too
                    beverage_variants = _normalize_name_for_matching(beverage_name)
                    beverage = None
                    for variant in beverage_variants:
                        if variant in all_beverages:
                            beverage = all_beverages[variant]
                            warnings.append(f"Beverage match: fuzzy - {beverage_name} matched to {beverage.name}")
                            break
                    
                    # Try case-insensitive
                    if not beverage:
                        beverage_name_lower = beverage_name.lower()
                        for db_name, bev_obj in all_beverages.items():
                            if db_name.lower() == beverage_name_lower:
                                beverage = bev_obj
                                warnings.append(f"Beverage match: case-insensitive - {beverage_name} matched to {db_name}")
                                break
                
                # If beverage not found, create it
                if not beverage:
                    # Get category from CSV or default to 'drink'
                    category = row.get('CATEGORY', '').strip().strip('"').lower() or 'drink'
                    
                    # Create new beverage
                    new_beverage = beverages(
                        name=beverage_name,
                        category=category
                    )
                    db.session.add(new_beverage)
                    db.session.flush()
                    
                    beverage = new_beverage
                    warnings.append(f"Created new beverage: {beverage_name} (category: {category})")
                    
                    # Add to lookup dictionary for subsequent rows
                    all_beverages[beverage_name] = beverage
                    all_beverages[beverage_name.lower()] = beverage
                    all_beverages[beverage_name.upper()] = beverage
                
                # Get beverage price for user's role
                beverage_price = beverage_prices.query.filter_by(
                    role_id=user.role_id,
                    beverage_id=beverage.id
                ).first()
                
                if not beverage_price:
                    # Try to create a price entry if it doesn't exist
                    # Use the CSV price but round to nearest 10 cents
                    rounded_price = int(round(unit_price_cents / 10) * 10)
                    beverage_price = beverage_prices(
                        role_id=user.role_id,
                        beverage_id=beverage.id,
                        price_cents=rounded_price
                    )
                    db.session.add(beverage_price)
                    db.session.flush()
                    warnings.append(f"Created missing price for {user_name} - {beverage_name}: {rounded_price} cents")
                
                # IMPORTANT: Always use the database price from beverage_prices, not the CSV price
                # The CSV "AVG PRICE" might be an average or incorrect - we need the correct role-based price
                unit_price_cents = beverage_price.price_cents
                
                # Get or create invoice for the month
                invoice = check_invoice_exists(user.id, period=target_period)
                
                # Distribute consumptions across the month
                # If we have multiple orders, spread them out
                if num_orders > 1:
                    quantity_per_order = total_quantity // num_orders
                    remainder = total_quantity % num_orders
                    
                    for order_num in range(num_orders):
                        # Distribute across the month (roughly)
                        day_offset = (order_num * 30) // num_orders + 1
                        day = min(day_offset, 28)  # Cap at day 28 to avoid month boundary issues
                        
                        order_quantity = quantity_per_order + (1 if order_num < remainder else 0)
                        
                        if order_quantity > 0:
                            created_at_dt = datetime(year, month, day, 12, 0, 0)
                            
                            consumption = consumptions(
                                user_id=user.id,
                                beverage_id=beverage.id,
                                beverage_price_id=beverage_price.id,
                                invoice_id=invoice.id,
                                quantity=order_quantity,
                                unit_price_cents=unit_price_cents,
                                created_at=created_at_dt
                            )
                            db.session.add(consumption)
                            imported_count += 1
                else:
                    # Single order - place it in the middle of the month
                    created_at_dt = datetime(year, month, 15, 12, 0, 0)
                    
                    consumption = consumptions(
                        user_id=user.id,
                        beverage_id=beverage.id,
                        beverage_price_id=beverage_price.id,
                        invoice_id=invoice.id,
                        quantity=total_quantity,
                        unit_price_cents=unit_price_cents,
                        created_at=created_at_dt
                    )
                    db.session.add(consumption)
                    imported_count += 1
        
        # Commit all changes
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": f"Successfully restored consumptions from {filename}",
            "imported": imported_count,
            "deleted": deleted_count,
            "period": f"{year}-{month:02d}",
            "warnings": warnings[:20],  # Limit warnings
            "errors": errors[:20]  # Limit errors
        })
        
    except Exception as e:
        db.session.rollback()
        import traceback
        error_details = traceback.format_exc()
        print(f"Restore error: {error_details}")
        return jsonify({
            "success": False,
            "error": str(e),
            "details": error_details
        }), 500

@bp.route("/admin/csv-restore")
@require_admin_only
def admin_csv_restore():
    """CSV restore admin page"""
    theme = settings.get_value('theme', 'coffee') or 'coffee'
    theme_colors = {
        'coffee': '#222222',
        'spring': '#4CAF50',
        'summer': '#FF9800',
        'autumn': '#FF5722',
        'winter': '#2196F3'
    }
    theme_color = theme_colors.get(theme, '#222222')
    
    return render_template("admin_csv_restore.html", theme=theme, theme_color=theme_color)


@bp.route("/admin/csv-restore/files")
@require_admin_only
def list_csv_files():
    """List available CSV files in the backup directory"""
    from pathlib import Path
    
    try:
        base_dir = _get_project_root()
        backup_dir = base_dir / "CSV For each month"
        files = []
        
        if backup_dir.exists():
            # Look for both consumption_report_*.csv and consumption_backup_*.csv
            for pattern in ["consumption_report_*.csv", "consumption_backup_*.csv"]:
                for file_path in backup_dir.glob(pattern):
                    stat = file_path.stat()
                    files.append({
                        "name": file_path.name,
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                    })
            
            # Sort by name (which includes date)
            files.sort(key=lambda x: x["name"], reverse=True)
        
        return jsonify({
            "success": True,
            "files": files,
            "path": str(backup_dir),
            "exists": backup_dir.exists(),
            "base_dir": str(base_dir)
        })
    except Exception as e:
        import traceback
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500

@bp.route("/admin/csv-restore/upload", methods=["POST"])
@require_admin_only
def upload_csv_file():
    """Upload a CSV file and save it to the backup directory"""
    from pathlib import Path
    from werkzeug.utils import secure_filename
    
    if 'file' not in request.files:
        return jsonify({
            "success": False,
            "error": "No file provided"
        }), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({
            "success": False,
            "error": "No file selected"
        }), 400
    
    if not file.filename.lower().endswith('.csv'):
        return jsonify({
            "success": False,
            "error": "File must be a CSV file"
        }), 400
    
    try:
        # Get project root directory
        base_dir = _get_project_root()
        backup_dir = base_dir / "CSV For each month"
        backup_dir.mkdir(exist_ok=True)
        
        # Secure the filename
        filename = secure_filename(file.filename)
        
        # Save the file
        file_path = backup_dir / filename
        file.save(str(file_path))
        
        return jsonify({
            "success": True,
            "message": f"File uploaded successfully: {filename}",
            "filename": filename,
            "path": str(file_path)
        })
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Upload error: {error_details}")
        return jsonify({
            "success": False,
            "error": str(e),
            "details": error_details
        }), 500

# =============================================================================
# SECURITY ROUTES - Admin Backdoor and Security Gate
# =============================================================================

@bp.route("/admin/login")
def admin_login():
    """Admin login page for backdoor access"""
    return render_template("admin_login.html")

@bp.route("/admin/authenticate", methods=["POST"])
def admin_authenticate():
    """Authenticate admin access"""
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    
    # Get client information for logging
    ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.environ.get('REMOTE_ADDR', 'unknown'))
    user_agent = request.headers.get('User-Agent', 'unknown')
    
    # Enhanced device detection
    device_name = "Unknown Device"
    if 'Windows NT 10.0' in user_agent:
        device_name = "Windows 10/11 PC"
    elif 'Windows NT 6.3' in user_agent:
        device_name = "Windows 8.1 PC"
    elif 'Windows NT 6.1' in user_agent:
        device_name = "Windows 7 PC"
    elif 'Windows' in user_agent:
        device_name = "Windows PC"
    elif 'Macintosh' in user_agent:
        if 'iPhone' in user_agent:
            device_name = "iPhone (Safari)"
        else:
            device_name = "Mac (Safari)"
    elif 'iPhone' in user_agent:
        device_name = "iPhone"
    elif 'Android' in user_agent:
        if 'Mobile' in user_agent:
            device_name = "Android Phone"
        else:
            device_name = "Android Tablet"
    elif 'Linux' in user_agent:
        device_name = "Linux PC"
    elif 'Chrome' in user_agent:
        device_name = "Chrome Browser"
    elif 'Firefox' in user_agent:
        device_name = "Firefox Browser"
    elif 'Safari' in user_agent:
        device_name = "Safari Browser"
    elif 'Edge' in user_agent:
        device_name = "Edge Browser"
    
    # Verify credentials securely
    success = verify_admin_credentials(username, password)
    
    # Log the access attempt with smart password logging
    from .models import admin_access_logs
    password_to_log = "[HIDDEN]" if success else password  # Show wrong passwords, hide correct one
    access_log = admin_access_logs(
        ip_address=ip_address,
        user_agent=user_agent,
        device_name=device_name,
        username_attempted=username,
        password_attempted=password_to_log,
        success=success
    )
    db.session.add(access_log)
    db.session.commit()
    
    if success:
        session['admin_authenticated'] = True
        session['security_gate_passed'] = True  # Admin bypasses security gate
        session['admin_username'] = username
        session['last_activity'] = time.time()  # Set initial activity time
        flash('🔐 Admin access granted! Welcome, Laurin. You now have full system access.', 'success')
        return redirect(url_for('routes.index'))
    else:
        flash('🚫 ACCESS DENIED: Invalid credentials. Unauthorized access attempt logged.', 'error')
        return redirect(url_for('routes.admin_login'))

@bp.route("/admin/logout")
def admin_logout():
    """Logout admin"""
    session.pop('admin_authenticated', None)
    session.pop('security_gate_passed', None)
    flash('Admin session ended.', 'info')
    return redirect(url_for('routes.index'))

@bp.route("/admin/access-logs")
@require_admin_only
def admin_access_logs_view():
    """View admin access logs"""
    from .models import admin_access_logs
    from sqlalchemy import desc
    
    # Get all access logs, ordered by most recent first
    logs = admin_access_logs.query.order_by(desc(admin_access_logs.created_at)).limit(100).all()
    
    # Get current theme and theme color
    theme = settings.get_value('theme', 'coffee') or 'coffee'
    theme_colors = {
        'coffee': '#222222',
        'spring': '#4CAF50',
        'summer': '#FF9800',
        'autumn': '#FF5722',
        'winter': '#2196F3'
    }
    theme_color = theme_colors.get(theme, '#222222')
    
    return render_template("admin_access_logs.html", logs=logs, theme=theme, theme_color=theme_color)

@bp.route("/admin/payments")
@require_admin_session
def admin_payments_view():
    """Admin payments management page"""
    from .models import user_payments, users, consumptions, beverage_prices, payment_consumptions
    from sqlalchemy import desc, func
    
    # Get all users with their current payment status
    users_with_balances = []
    
    # Get all active users
    all_users = users.query.filter_by(status=True).all()
    
    for user in all_users:
        # Calculate unpaid amount for this user
        paid_consumption_ids = db.session.query(payment_consumptions.consumption_id).join(
            user_payments, payment_consumptions.payment_id == user_payments.id
        ).filter(
            user_payments.user_id == user.id,
            user_payments.payment_status == 'paid'
        ).all()
        
        paid_consumption_ids = [pc[0] for pc in paid_consumption_ids]
        
        # Get unpaid consumptions
        unpaid_consumptions = consumptions.query.filter_by(user_id=user.id)\
            .filter(~consumptions.id.in_(paid_consumption_ids))\
            .all()
        
        # Calculate total unpaid amount
        total_unpaid_cents = 0
        for consumption in unpaid_consumptions:
            total_unpaid_cents += consumption.quantity * consumption.unit_price_cents
        
        # Get recent payments for this user
        recent_payments = user_payments.query.filter_by(user_id=user.id)\
            .order_by(desc(user_payments.created_at)).limit(3).all()
        
        users_with_balances.append({
            'user': user,
            'unpaid_amount_cents': total_unpaid_cents,
            'unpaid_amount_euros': total_unpaid_cents / 100.0,
            'recent_payments': recent_payments,
            'has_balance': total_unpaid_cents > 0
        })
    
    # Sort by unpaid amount (highest first)
    users_with_balances.sort(key=lambda x: x['unpaid_amount_cents'], reverse=True)
    
    # Get all payments with user info, ordered by most recent first
    payments_data = db.session.query(user_payments, users).join(users, user_payments.user_id == users.id).order_by(desc(user_payments.created_at)).all()
    
    # Get current theme and theme color
    theme = settings.get_value('theme', 'coffee') or 'coffee'
    theme_colors = {
        'coffee': '#222222',
        'spring': '#4CAF50',
        'summer': '#FF9800',
        'autumn': '#FF5722',
        'winter': '#2196F3'
    }
    theme_color = theme_colors.get(theme, '#222222')
    
    return render_template("admin_payments.html", 
                         payments_data=payments_data, 
                         users_with_balances=users_with_balances,
                         theme=theme, 
                         theme_color=theme_color,
                         is_admin=is_admin_mode())

# =============================================================================
# ADMIN: Cashbook
# =============================================================================

COMPANY_OPTIONS = ["Schülerfirma", "Pausenverkauf", "Kaffeemaschine"]

@bp.route('/admin/cashbook/overview')
def admin_cashbook_overview():
    """Cashbook overview with summary statistics for both companies"""
    # Check authentication - either admin or cashbook user
    if not (is_admin_mode() or session.get('cashbook_authenticated', False)):
        return redirect(url_for('routes.index'))
    
    from sqlalchemy import func
    from datetime import datetime, timedelta
    
    # Get current theme
    theme = settings.get_value('theme', 'coffee') or 'coffee'
    theme_colors = {
        'coffee': '#222222',
        'spring': '#4CAF50',
        'summer': '#FF9800',
        'autumn': '#FF5722',
        'winter': '#2196F3'
    }
    theme_color = theme_colors.get(theme, '#222222')
    
    # Get current user for display
    current_user = session.get('cashbook_user', 'Admin')
    
    # Calculate date ranges
    today = datetime.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    
    # Get summary statistics for each company
    company_stats = {}
    for company in COMPANY_OPTIONS:
        # Total entries
        total_entries = cashbook_entries.query.filter_by(company=company).count()
        
        # Current cash balance
        current_balance = get_current_kassenstand(company)
        
        # This week's activity
        week_entries = cashbook_entries.query.filter(
            cashbook_entries.company == company,
            cashbook_entries.entry_date >= week_ago
        ).count()
        
        # This month's activity
        month_entries = cashbook_entries.query.filter(
            cashbook_entries.company == company,
            cashbook_entries.entry_date >= month_ago
        ).count()
        
        # Total income and expenses
        total_income = db.session.query(func.sum(cashbook_entries.einnahmen_bar_cents)).filter(
            cashbook_entries.company == company
        ).scalar() or 0
        
        total_expenses = db.session.query(func.sum(cashbook_entries.ausgaben_bar_cents)).filter(
            cashbook_entries.company == company
        ).scalar() or 0
        
        # Recent entries (last 10)
        recent_entries = cashbook_entries.query.filter_by(company=company)\
            .order_by(cashbook_entries.entry_date.desc(), cashbook_entries.id.desc())\
            .limit(10).all()
        
        company_stats[company] = {
            'total_entries': total_entries,
            'current_balance': current_balance / 100.0,
            'week_entries': week_entries,
            'month_entries': month_entries,
            'total_income': total_income / 100.0,
            'total_expenses': total_expenses / 100.0,
            'net_profit': (total_income - total_expenses) / 100.0,
            'recent_entries': recent_entries
        }
    
    return render_template('admin_cashbook_overview.html',
                           theme=theme,
                           theme_color=theme_color,
                           company_stats=company_stats,
                           company_options=COMPANY_OPTIONS,
                           current_user=current_user)

@bp.route('/admin/cashbook')
def admin_cashbook():
    # Check authentication - either admin or cashbook user
    if not (is_admin_mode() or session.get('cashbook_authenticated', False)):
        return redirect(url_for('routes.index'))
    
    company = request.args.get('company', COMPANY_OPTIONS[0])
    if company not in COMPANY_OPTIONS:
        company = COMPANY_OPTIONS[0]
    entries = cashbook_entries.query.filter_by(company=company).order_by(cashbook_entries.entry_date.desc(), cashbook_entries.id.desc()).limit(200).all()
    theme = settings.get_value('theme', 'coffee') or 'coffee'
    theme_colors = {
        'coffee': '#222222',
        'spring': '#4CAF50',
        'summer': '#FF9800',
        'autumn': '#FF5722',
        'winter': '#2196F3'
    }
    theme_color = theme_colors.get(theme, '#222222')
    
    # Get current user for display
    current_user = session.get('cashbook_user', 'Admin')
    pending_cash_requests = cash_payment_requests.query.filter_by(status='pending').order_by(cash_payment_requests.created_at.asc()).all()
    
    return render_template('admin_cashbook.html',
                           theme=theme,
                           theme_color=theme_color,
                           company=company,
                           company_options=COMPANY_OPTIONS,
                           entries=entries,
                           next_beleg=get_next_beleg_nummer(company),
                           current_kassenstand=get_current_kassenstand(company) / 100.0,
                           current_user=current_user,
                           pending_cash_requests=pending_cash_requests)


@bp.route('/admin/cashbook/cash-requests')
def admin_cashbook_cash_requests():
    # Check authentication - either admin or cashbook user
    if not (is_admin_mode() or session.get('cashbook_authenticated', False)):
        return redirect(url_for('routes.index'))

    theme = settings.get_value('theme', 'coffee') or 'coffee'
    theme_colors = {
        'coffee': '#222222',
        'spring': '#4CAF50',
        'summer': '#FF9800',
        'autumn': '#FF5722',
        'winter': '#2196F3'
    }
    theme_color = theme_colors.get(theme, '#222222')

    pending = cash_payment_requests.query.filter_by(status='pending').order_by(cash_payment_requests.created_at.asc()).all()
    recent = cash_payment_requests.query.filter(cash_payment_requests.status != 'pending').order_by(cash_payment_requests.updated_at.desc()).limit(20).all()

    return render_template(
        'admin_cash_requests.html',
        theme=theme,
        theme_color=theme_color,
        pending_requests=pending,
        recent_requests=recent
    )

@bp.route('/admin/cashbook/add', methods=['POST'])
def admin_cashbook_add():
    # Check authentication - either admin or cashbook user
    if not (is_admin_mode() or session.get('cashbook_authenticated', False)):
        return redirect(url_for('routes.index'))
    try:
        company = request.form.get('company') or COMPANY_OPTIONS[0]
        if company not in COMPANY_OPTIONS:
            company = COMPANY_OPTIONS[0]
        beleg_nummer = None
        custom_beleg = (request.form.get('beleg_nummer') or '').strip()
        if custom_beleg:
            try:
                custom_value = int(custom_beleg)
                if custom_value <= 0:
                    raise ValueError
                existing = cashbook_entries.query.filter_by(company=company, beleg_nummer=custom_value).first()
                if existing:
                    flash(f'Belegnummer {custom_value} ist in {company} bereits vergeben.', 'error')
                    return redirect(url_for('routes.admin_cashbook', company=company))
                beleg_nummer = custom_value
            except ValueError:
                flash('Belegnummer muss eine positive Zahl sein.', 'error')
                return redirect(url_for('routes.admin_cashbook', company=company))

        if beleg_nummer is None:
            beleg_nummer = get_next_beleg_nummer(company)
        # date handling: default today; optional custom
        date_str = request.form.get('entry_date')
        if date_str:
            entry_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            entry_date = date.today()
        bemerkung = (request.form.get('bemerkung') or '').strip()
        posten = (request.form.get('posten') or '').strip()
        einnahmen_bar_eur = request.form.get('einnahmen_bar') or '0'
        ausgaben_bar_eur = request.form.get('ausgaben_bar') or '0'
        try:
            einnahmen_bar_cents = int(round(float(einnahmen_bar_eur.replace(',', '.')) * 100))
        except ValueError:
            einnahmen_bar_cents = 0
        try:
            ausgaben_bar_cents = int(round(float(ausgaben_bar_eur.replace(',', '.')) * 100))
        except ValueError:
            ausgaben_bar_cents = 0
        if not posten:
            flash('Posten is required.', 'error')
            return redirect(url_for('routes.admin_cashbook', company=company))
        
        # Get the correct previous balance based on chronological order
        # Find the entry that comes before this one chronologically
        # We need entries with date < entry_date, or same date but lower ID
        from sqlalchemy import or_, and_
        prev_entry = (
            cashbook_entries.query.filter_by(company=company)
            .filter(
                or_(
                    cashbook_entries.entry_date < entry_date,
                    and_(
                        cashbook_entries.entry_date == entry_date,
                        cashbook_entries.id.isnot(None)  # Will be filtered by order
                    )
                )
            )
            .order_by(cashbook_entries.entry_date.desc(), cashbook_entries.id.desc())
            .first()
        )
        
        if prev_entry:
            prev_kassenstand = prev_entry.kassenstand_bar_cents
        else:
            # This is the first entry (or earliest entry)
            prev_kassenstand = 0
        
        # Compute new cash balance
        new_kassenstand = prev_kassenstand + einnahmen_bar_cents - ausgaben_bar_cents
        
        # Get current user for tracking
        current_user = session.get('cashbook_user', 'Admin')
        
        row = cashbook_entries(
            company=company,
            beleg_nummer=beleg_nummer,
            entry_date=entry_date,
            bemerkung=bemerkung or None,
            posten=posten,
            einnahmen_bar_cents=einnahmen_bar_cents,
            ausgaben_bar_cents=ausgaben_bar_cents,
            kassenstand_bar_cents=new_kassenstand,
            created_by=current_user,
        )
        db.session.add(row)
        db.session.flush()
        
        # Recalculate ALL entries from scratch to ensure the balance chain is correct
        # This is the safest approach and handles all edge cases:
        # - New entry inserted with past date
        # - Previous entries with incorrect balances
        # - Ensures consistency across all entries
        recalculate_all_kassenstand(company)
        
        db.session.commit()
        flash('Cashbook entry added.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding entry: {e}', 'error')
    return redirect(url_for('routes.admin_cashbook', company=company))

@bp.route('/admin/cashbook/get_entry/<int:entry_id>')
def admin_cashbook_get_entry(entry_id):
    # Check authentication - either admin or cashbook user
    if not (is_admin_mode() or session.get('cashbook_authenticated', False)):
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    try:
        entry = cashbook_entries.query.get_or_404(entry_id)
        
        return jsonify({
            'success': True,
            'entry': {
                'id': entry.id,
                'beleg_nummer': entry.beleg_nummer,
                'entry_date': entry.entry_date.strftime('%Y-%m-%d'),
                'posten': entry.posten,
                'bemerkung': entry.bemerkung,
                'einnahmen_bar_cents': entry.einnahmen_bar_cents,
                'ausgaben_bar_cents': entry.ausgaben_bar_cents,
                'kassenstand_bar_cents': entry.kassenstand_bar_cents,
                'created_by': entry.created_by
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/admin/cashbook/edit_entry/<int:entry_id>', methods=['POST'])
def admin_cashbook_edit_entry(entry_id):
    # Check authentication - either admin or cashbook user
    if not (is_admin_mode() or session.get('cashbook_authenticated', False)):
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    try:
        entry = cashbook_entries.query.get_or_404(entry_id)
        company = entry.company
        
        # Store old values to determine if recalculation is needed
        old_date = entry.entry_date
        old_einnahmen = entry.einnahmen_bar_cents
        old_ausgaben = entry.ausgaben_bar_cents
        
        # Update entry fields
        entry.entry_date = datetime.strptime(request.form.get('entry_date'), '%Y-%m-%d').date()
        entry.posten = request.form.get('posten')
        entry.bemerkung = request.form.get('bemerkung', '')
        
        einnahmen_bar_eur = float(request.form.get('einnahmen_bar_eur', 0))
        ausgaben_bar_eur = float(request.form.get('ausgaben_bar_eur', 0))
        
        entry.einnahmen_bar_cents = int(einnahmen_bar_eur * 100)
        entry.ausgaben_bar_cents = int(ausgaben_bar_eur * 100)
        
        # Recalculate kassenstand for this entry and all subsequent entries
        # This handles:
        # - Changes to income/expense amounts
        # - Changes to entry_date (which may change chronological order)
        recalculate_kassenstand_from_entry(company, entry_id)
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Entry updated successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/admin/cashbook/delete_entry/<int:entry_id>', methods=['POST'])
def admin_cashbook_delete_entry(entry_id):
    # Check authentication - either admin or cashbook user
    if not (is_admin_mode() or session.get('cashbook_authenticated', False)):
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    try:
        entry = cashbook_entries.query.get_or_404(entry_id)
        
        # Store company and find entry before deletion for recalculation
        company = entry.company
        
        # Get all entries ordered chronologically to find the entry before the one being deleted
        all_entries = (
            cashbook_entries.query.filter_by(company=company)
            .order_by(cashbook_entries.entry_date.asc(), cashbook_entries.id.asc())
            .all()
        )
        
        # Find the entry to delete
        entry_to_delete = next((e for e in all_entries if e.id == entry_id), None)
        recalculate_from_id = None
        
        if entry_to_delete:
            delete_index = all_entries.index(entry_to_delete)
            
            # Determine which entry to recalculate from after deletion
            if delete_index > 0:
                # There's an entry before the deleted one - recalculate from that point
                recalculate_from_id = all_entries[delete_index - 1].id
            
            # Delete the entry
            db.session.delete(entry)
            db.session.flush()  # Flush to ensure deletion is processed
            
            # Recalculate balances for all entries that came after the deleted entry
            if recalculate_from_id:
                # Recalculate from the entry that was before the deleted one
                recalculate_kassenstand_from_entry(company, recalculate_from_id)
            else:
                # Deleted the first entry (or only entry) - recalculate from the earliest remaining entry
                # The recalculation function handles this case by recalculating from start if entry not found
                remaining_entries = (
                    cashbook_entries.query.filter_by(company=company)
                    .order_by(cashbook_entries.entry_date.asc(), cashbook_entries.id.asc())
                    .all()
                )
                if remaining_entries:
                    # Recalculate from the new first entry
                    recalculate_kassenstand_from_entry(company, remaining_entries[0].id)
                # If no remaining entries, nothing to recalculate
        
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Entry deleted successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/admin/cashbook/fix-all-balances', methods=['POST'])
def admin_cashbook_fix_all_balances():
    """Fix all kassenstand balances by recalculating from scratch"""
    # Check authentication - either admin or cashbook user
    if not (is_admin_mode() or session.get('cashbook_authenticated', False)):
        return jsonify({'success': False, 'error': 'Access denied'}), 403
    
    try:
        company = request.form.get('company')
        
        if company:
            # Fix specific company
            if company not in COMPANY_OPTIONS:
                return jsonify({'success': False, 'error': 'Invalid company'}), 400
            recalculate_all_kassenstand(company)
            db.session.commit()
            return jsonify({
                'success': True,
                'message': f'Recalculated all balances for {company}'
            })
        else:
            # Fix all companies
            for comp in COMPANY_OPTIONS:
                recalculate_all_kassenstand(comp)
            db.session.commit()
            return jsonify({
                'success': True,
                'message': f'Recalculated balances for all companies: {", ".join(COMPANY_OPTIONS)}'
            })
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/admin/cash-request/<int:request_id>/resolve', methods=['POST'])
def admin_resolve_cash_request(request_id):
    if not (is_admin_mode() or session.get('cashbook_authenticated', False)):
        return redirect(url_for('routes.index'))
    action = request.form.get('action', 'collect')
    company = request.args.get('company', COMPANY_OPTIONS[0])
    req = cash_payment_requests.query.get_or_404(request_id)
    if req.status != 'pending':
        flash('Anfrage bereits erledigt.', 'warning')
        return redirect(url_for('routes.admin_cashbook', company=company))
    if action == 'cancel':
        req.status = 'cancelled'
    else:
        req.status = 'collected'
    req.resolved_at = datetime.utcnow()
    req.resolved_by = session.get('cashbook_user') or session.get('admin_username') or 'Admin'
    req.note = request.form.get('note') or req.note
    db.session.commit()
    flash('Barzahlungs-Anfrage aktualisiert.', 'success')
    return redirect(url_for('routes.admin_cashbook', company=company))
# Admin: Create quick-access user "Schülerfirma" (role_id=5)
@bp.route('/admin/create_schuelerfirma', methods=['POST'])
def admin_create_schuelerfirma():
    # Only on admin port with authenticated admin
    if not (is_admin_port() and session.get('admin_authenticated', False)):
        abort(403)
    try:
        # Prefer an existing role named 'Schülerfirma', else fall back to id 5
        role = roles.query.filter((roles.name == 'Schülerfirma') | (roles.id == 5)).first()
        role_id = role.id if role else 5
        # Check if user already exists
        existing = users.query.filter_by(first_name='Schülerfirma', last_name='Account', role_id=role_id).first()
        if existing:
            return jsonify({'success': True, 'user_id': existing.id, 'message': 'User already existed'}), 200
        # Create user
        new_user = users(
            role_id=role_id,
            first_name='Schülerfirma',
            last_name='Account',
            email=None,
            status=True
        )
        db.session.add(new_user)
        db.session.commit()
        return jsonify({'success': True, 'user_id': new_user.id}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'Failed to create user: {str(e)}'}), 500

# Admin: Find existing "Pausenverkauf" user and return ID (no creation)
@bp.route('/admin/find_schuelerfirma', methods=['GET'])
def admin_find_schuelerfirma():
    if not (is_admin_port() and session.get('admin_authenticated', False)):
        abort(403)
    try:
        # Search for "Pausenverkauf" user (updated from Schülerfirma)
        # Try several likely patterns: exact first name, startswith including trailing dot/spaces
        candidate = (
            users.query
                .filter(
                    (users.first_name.ilike('Pausenverkauf%')) |
                    (users.last_name.ilike('Pausenverkauf%')) |
                    (users.first_name.ilike('Schülerfirma%')) |  # Fallback for old name
                    (users.last_name.ilike('Schülerfirma%'))    # Fallback for old name
                )
                .order_by(users.id.asc())
                .first()
        )
        if not candidate:
            return jsonify({'success': False, 'error': 'No existing "Pausenverkauf" user found'}), 404
        return jsonify({'success': True, 'user_id': candidate.id})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Lookup failed: {str(e)}'}), 500

# Public: Find first user by role_id
@bp.route('/api/find_user_by_role/<int:role_id>', methods=['GET'])
def api_find_user_by_role(role_id: int):
    try:
        user = users.query.filter_by(role_id=role_id).order_by(users.id.asc()).first()
        if not user:
            return jsonify({'success': False, 'error': 'No user found for role'}), 404
        return jsonify({'success': True, 'user_id': user.id})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Lookup failed: {str(e)}'}), 500

# Cashbook login for coworkers
@bp.route('/api/cashbook_login', methods=['POST'])
def api_cashbook_login():
    """Login endpoint for cashbook access"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        # Hardcoded credentials
        valid_credentials = {
            'Laurin': 'Campus15',
            'Max': 'Money',
            'Lilian': 'Money',
            'Jasmin': 'Money',
            'Glenda': 'Money'
        }
        
        if username in valid_credentials and valid_credentials[username] == password:
            # Store in session
            session['cashbook_authenticated'] = True
            session['cashbook_user'] = username
            return jsonify({'success': True, 'username': username})
        else:
            return jsonify({'success': False, 'error': 'Invalid credentials'}), 401
            
    except Exception as e:
        return jsonify({'success': False, 'error': f'Login failed: {str(e)}'}), 500

@bp.route("/security-gate")
def security_gate():
    """Security gate for unauthorized access"""
    if session.get('security_gate_passed', False):
        return redirect(url_for('routes.index'))
    return render_template("security_gate.html")

@bp.route("/security-gate/verify", methods=["POST"])
def security_gate_verify():
    """Verify security gate access"""
    access_code = request.form.get('access_code', '').strip()
    
    # Simple access code (you can make this more complex)
    valid_codes = ['CSH2024', 'LAURIN', 'ADMIN', 'ACCESS']
    
    if access_code.upper() in valid_codes:
        session['security_gate_passed'] = True
        flash('Access granted! Welcome to Laurin Build.', 'success')
        return redirect(url_for('routes.index'))
    else:
        flash('Invalid access code. Please try again.', 'error')
        return redirect(url_for('routes.security_gate'))

# Admin backdoor removed - PIN bypass now automatic when admin is authenticated

@bp.route("/price-list")
def price_list():
    """Price list page showing display items (like cakes) for customers"""
    # Get all active display items (like cakes, snacks, etc.)
    display_items_list = display_items.query.filter_by(is_active=True).order_by(display_items.display_order, display_items.name).all()
    
    # Create price data for template
    price_data = []
    for item in display_items_list:
        price_data.append({
            'item': item,
            'price_euros': item.price_cents / 100,
            'category': item.category
        })
    
    # Get current theme and theme color
    theme = settings.get_value('theme', 'coffee') or 'coffee'
    theme_colors = {
        'coffee': '#222222',
        'spring': '#4CAF50',
        'summer': '#FF9800',
        'autumn': '#FF5722',
        'winter': '#2196F3'
    }
    theme_color = theme_colors.get(theme, '#222222')
    
    return render_template("price_list.html", 
                         price_data=price_data,
                         theme=theme,
                         theme_color=theme_color)


@bp.route("/admin/display-items")
@require_admin_only
def admin_display_items():
    """Admin interface for managing display items (like cakes)"""
    # Get all display items
    all_items = display_items.query.order_by(display_items.display_order, display_items.name).all()
    
    # Get current theme and theme color
    theme = settings.get_value('theme', 'coffee') or 'coffee'
    theme_colors = {
        'coffee': '#222222',
        'spring': '#4CAF50',
        'summer': '#FF9800',
        'autumn': '#FF5722',
        'winter': '#2196F3'
    }
    theme_color = theme_colors.get(theme, '#222222')
    
    return render_template("admin_display_items.html", 
                         items=all_items,
                         theme=theme,
                         theme_color=theme_color)

@bp.route("/admin/display-items/add", methods=["POST"])
@require_admin_only
def add_display_item():
    """Add a new display item"""
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    price_euros = request.form.get('price_euros', type=float)
    category = request.form.get('category', 'food')
    display_order = request.form.get('display_order', type=int) or 0
    
    if not name or not price_euros:
        flash('Name and price are required.', 'error')
        return redirect(url_for('routes.admin_display_items'))
    
    # Convert euros to cents
    price_cents = int(price_euros * 100)
    
    # Create new display item
    new_item = display_items(
        name=name,
        description=description,
        price_cents=price_cents,
        category=category,
        display_order=display_order,
        is_active=True
    )
    
    try:
        db.session.add(new_item)
        db.session.commit()
        flash(f'Display item "{name}" added successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding item: {str(e)}', 'error')
    
    return redirect(url_for('routes.admin_display_items'))

@bp.route("/admin/display-items/update", methods=["POST"])
@require_admin_only
def update_display_item():
    """Update a display item"""
    item_id = request.form.get('item_id', type=int)
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    price_euros = request.form.get('price_euros', type=float)
    category = request.form.get('category', 'food')
    display_order = request.form.get('display_order', type=int) or 0
    is_active = request.form.get('is_active') == 'on'
    
    if not item_id or not name or not price_euros:
        flash('Missing required fields.', 'error')
        return redirect(url_for('routes.admin_display_items'))
    
    # Get the item
    item = display_items.query.get(item_id)
    if not item:
        flash('Item not found.', 'error')
        return redirect(url_for('routes.admin_display_items'))
    
    # Update the item
    item.name = name
    item.description = description
    item.price_cents = int(price_euros * 100)
    item.category = category
    item.display_order = display_order
    item.is_active = is_active
    item.updated_at = datetime.utcnow()
    
    try:
        db.session.commit()
        flash(f'Display item "{name}" updated successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating item: {str(e)}', 'error')
    
    return redirect(url_for('routes.admin_display_items'))

@bp.route("/admin/display-items/delete/<int:item_id>")
@require_admin_only
def delete_display_item(item_id):
    """Delete a display item"""
    item = display_items.query.get(item_id)
    if not item:
        flash('❌ Item not found.', 'error')
        return redirect(url_for('routes.admin_display_items'))
    
    try:
        db.session.delete(item)
        db.session.commit()
        flash(f'Display item "{item.name}" deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting item: {str(e)}', 'error')
    
    return redirect(url_for('routes.admin_display_items'))

@bp.route("/api/set-theme", methods=["POST"])
def set_theme():
    """Set the global theme in settings and increment version so clients can detect and reload."""
    try:
        payload = request.get_json() or {}
        theme = payload.get('theme', 'coffee')
        allowed = { 'coffee','spring','summer','autumn','winter' }
        if theme not in allowed:
            return jsonify({'success': False, 'error': 'Invalid theme'}), 400

        current_version = settings.get_value('theme_version', '1') or '1'
        try:
            next_version = str(int(current_version) + 1)
        except ValueError:
            next_version = '1'

        settings.set_value('theme', theme)
        settings.set_value('theme_version', next_version)
        db.session.commit()

        # Invalidate cached pages that might embed theme-dependent markup
        try:
            cache.delete_memoized(index)
            cache.delete_memoized(api_index_data)
        except Exception:
            pass

        return jsonify({'success': True, 'theme': theme, 'version': next_version})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route("/api/get-theme")
def get_theme():
    """Return current theme and version so clients can auto-refresh on change."""
    theme = settings.get_value('theme', 'coffee')
    version = settings.get_value('theme_version', '1')
    return jsonify({'success': True, 'theme': theme, 'version': version})

@bp.route("/api/toggle-payment-button", methods=["POST"])
@require_admin_only
def api_toggle_payment_button():
    """Toggle payment button visibility on entries pages"""
    try:
        current_setting = settings.get_value('payment_button_hidden', 'false')
        new_value = 'true' if current_setting.lower() != 'true' else 'false'
        
        settings.set_value('payment_button_hidden', new_value)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "hidden": new_value == 'true',
            "message": "Payment button visibility updated"
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@bp.route("/api/get-payment-button-setting")
def api_get_payment_button_setting():
    """Get current payment button visibility setting"""
    try:
        hidden = settings.get_value('payment_button_hidden', 'false').lower() == 'true'
        return jsonify({"hidden": hidden})
    except Exception as e:
        return jsonify({"hidden": False, "error": str(e)}), 500

@bp.route("/api/payment/calculate", methods=["POST"])
def calculate_payment():
    """Calculate total payment amount for a user's ALL unpaid consumptions (any month)"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        if user_id is not None:
            user_id = int(user_id)
        
        if not user_id:
            return jsonify({"error": "User ID is required"}), 400
        
        # Get already paid consumption IDs
        paid_consumption_ids = db.session.query(payment_consumptions.consumption_id).join(
            user_payments, payment_consumptions.payment_id == user_payments.id
        ).filter(
            user_payments.user_id == user_id,
            user_payments.payment_status == 'paid'
        ).all()
        
        paid_consumption_ids = [pc[0] for pc in paid_consumption_ids]
        
        # Get ALL UNPAID consumptions for the user (no date filter) - return individual consumptions
        unpaid_consumptions = consumptions.query.filter_by(user_id=user_id)\
            .filter(~consumptions.id.in_(paid_consumption_ids))\
            .order_by(consumptions.created_at).all()
        
        # Calculate total amount and build individual consumption details
        total_amount_cents = 0
        consumption_details = []
        first_consumption = None
        last_consumption = None
        
        for consumption in unpaid_consumptions:
            # Calculate amount for this consumption (quantity * unit_price)
            consumption_amount_cents = consumption.quantity * consumption.unit_price_cents
            total_amount_cents += consumption_amount_cents
            
            # Track date range
            if not first_consumption or consumption.created_at < first_consumption:
                first_consumption = consumption.created_at
            if not last_consumption or consumption.created_at > last_consumption:
                last_consumption = consumption.created_at
            
            # Get beverage name
            beverage = beverages.query.get(consumption.beverage_id)
            consumption_details.append({
                'beverage_name': beverage.name if beverage else 'Unknown',
                'quantity': consumption.quantity,
                'unit_price_cents': consumption.unit_price_cents,
                'total_cents': consumption_amount_cents,
                'created_at': consumption.created_at.isoformat() if consumption.created_at else None
            })
        
        # Get date range for display
        if first_consumption and last_consumption:
            first_date = first_consumption.strftime('%Y-%m')
            last_date = last_consumption.strftime('%Y-%m')
            date_range = f"{first_date} to {last_date}" if first_date != last_date else first_date
        else:
            date_range = "No consumptions"
        
        return jsonify({
            'success': True,
            'total_amount_cents': total_amount_cents,
            'total_amount_euros': total_amount_cents / 100.0,
            'consumption_details': consumption_details,
            'date_range': date_range,
            'is_all_time': True
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to calculate payment: {str(e)}"}), 500


@bp.route("/api/payment/cash-request", methods=["POST"])
def request_cash_payment():
    """Create or update a cash collection request for the user."""
    try:
        data = request.get_json() or {}
        user_id = data.get('user_id')
        amount_cents = data.get('amount_cents')

        if not user_id:
            return jsonify({"success": False, "error": "User ID is required"}), 400
        user = users.query.get(int(user_id))
        if not user:
            return jsonify({"success": False, "error": "User not found"}), 404

        if amount_cents is None:
            return jsonify({"success": False, "error": "Amount is required"}), 400

        try:
            amount_cents = int(amount_cents)
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "Invalid amount"}), 400

        if amount_cents <= 0:
            return jsonify({"success": False, "error": "Amount must be greater than zero"}), 400

        existing = cash_payment_requests.query.filter_by(user_id=user.id, status='pending').first()
        if existing:
            existing.amount_cents = amount_cents
            existing.updated_at = datetime.utcnow()
            message = "Barzahlung aktualisiert."
        else:
            existing = cash_payment_requests(
                user_id=user.id,
                amount_cents=amount_cents,
                status='pending'
            )
            db.session.add(existing)
            message = "Barzahlung angefordert."

        db.session.commit()

        return jsonify({
            "success": True,
            "message": message,
            "request_id": existing.id
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": f"Failed to create cash request: {str(e)}"}), 500

@bp.route("/api/payment/paypal-qr", methods=["POST"])
def generate_paypal_qr():
    """Generate PayPal QR code for payment"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        amount_euros = data.get('amount_euros')
        
        if user_id is not None:
            user_id = int(user_id)
        if amount_euros is not None:
            amount_euros = float(amount_euros)
        
        if not user_id or not amount_euros:
            return jsonify({"error": "User ID and amount are required"}), 400
        
        # Get user info
        user = users.query.get(user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        # Cancel any existing pending PayPal payments for this user before creating a new one
        existing_pending = user_payments.query.filter_by(
            user_id=user_id,
            payment_method='paypal',
            payment_status='pending'
        ).all()
        for pending_payment in existing_pending:
            cancel_pending_payment(pending_payment, "neuer PayPal-QR generiert")
        
        # Create PayPal payment link
        # Try different email formats for the school account
        paypal_email = "schuelerfirma@cs-bodensee.de"  # Without special characters
        
        # Create payment description
        description = f"CSH Coffee - {user.first_name} {user.last_name} - {date.today().strftime('%Y-%m')}"
        
        # Create a pending payment record FIRST (before generating URLs)
        pending_payment = user_payments(
            user_id=user_id,
            amount_cents=int(amount_euros * 100),
            payment_method='paypal',
            payment_status='pending',
            notes=f'PayPal QR generated for {user.first_name} {user.last_name} - {description}'
        )
        db.session.add(pending_payment)
        db.session.flush()  # Get the payment ID
        
        # Create multiple payment URL options
        import urllib.parse
        encoded_email = urllib.parse.quote(paypal_email)
        encoded_user_name = urllib.parse.quote(f"{user.first_name} {user.last_name}")
        
        # Include payment_id in custom field for webhook matching
        custom_field = f"payment_id:{pending_payment.id}|user_id:{user_id}|user:{encoded_user_name}"
        encoded_custom = urllib.parse.quote(custom_field)
        
        # Use configured IPN URL (defaults to local network)
        paypal_ipn_url = current_app.config.get("PAYPAL_IPN_URL", "http://10.100.5.89:5004/api/payment/paypal-ipn")
        encoded_ipn_url = urllib.parse.quote(paypal_ipn_url)
        invoice_id = f"payment_{pending_payment.id}"
        encoded_invoice = urllib.parse.quote(invoice_id)
        
        # Option 1: PayPal.me (requires the recipient to have set up PayPal.me)
        paypal_me_url = f"https://www.paypal.me/csbodensee/{amount_euros:.2f}EUR"
        
        # Option 2: PayPal Standard Payment Link (most reliable for QR codes and IPN)
        # This format actually pre-fills the amount and recipient, and includes IPN notification URL
        paypal_standard_url = (
            "https://www.paypal.com/cgi-bin/webscr"
            f"?cmd=_xclick&business={encoded_email}"
            f"&amount={amount_euros:.2f}&currency_code=EUR"
            "&item_name=CSH+Coffee+Payment"
            f"&custom={encoded_custom}&notify_url={encoded_ipn_url}"
            f"&invoice={encoded_invoice}"
        )
        
        # Option 3: PayPal Send Money (alternative)
        paypal_send_url = f"https://www.paypal.com/sendmoney?amount={amount_euros:.2f}&currency=EUR&recipient={paypal_email}"
        
        # Option 4: PayPal Business (if you have a business account)
        paypal_business_url = f"https://www.paypal.com/paypalme/csbodensee/{amount_euros:.2f}EUR"
        
        # Use PayPal Standard Payment Link as it's most reliable for QR codes and IPN
        paypal_url = paypal_standard_url
        
        # Link to unpaid consumptions (oldest first)
        paid_consumption_ids = db.session.query(payment_consumptions.consumption_id).join(
            user_payments, payment_consumptions.payment_id == user_payments.id
        ).filter(
            user_payments.user_id == user_id,
            user_payments.payment_status == 'paid'
        ).all()
        paid_consumption_ids = [pc[0] for pc in paid_consumption_ids]
        unpaid_consumptions = consumptions.query.filter_by(user_id=user_id)\
            .filter(~consumptions.id.in_(paid_consumption_ids))\
            .order_by(consumptions.created_at).all()

        remaining_amount = int(amount_euros * 100)
        for consumption in unpaid_consumptions:
            if remaining_amount <= 0:
                break
            consumption_amount = consumption.quantity * consumption.unit_price_cents
            payment_amount = min(consumption_amount, remaining_amount)
            db.session.add(payment_consumptions(
                payment_id=pending_payment.id,
                consumption_id=consumption.id,
                amount_cents=payment_amount
            ))
            remaining_amount -= payment_amount
        
        db.session.commit()

        # Generate QR code data
        qr_data = {
            'paypal_url': paypal_url,
            'paypal_me_url': paypal_me_url,
            'paypal_send_url': paypal_send_url,
            'paypal_business_url': paypal_business_url,
            'amount_euros': amount_euros,
            'description': description,
            'user_name': f"{user.first_name} {user.last_name}",
            'month': date.today().strftime('%Y-%m'),
            'paypal_email': paypal_email,
            'payment_id': pending_payment.id,  # Include payment ID for tracking
            'invoice_id': invoice_id
        }
        
        return jsonify({
            'success': True,
            'qr_data': qr_data,
            'paypal_url': paypal_url,
            'payment_id': pending_payment.id
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to generate PayPal QR: {str(e)}"}), 500

@bp.route("/api/payment/paypal-ipn", methods=["POST", "GET"])
def paypal_ipn():
    """Handle PayPal IPN (Instant Payment Notification) webhooks"""
    try:
        # PayPal IPN sends data as form-encoded, not JSON
        if request.method == 'GET':
            # PayPal sometimes sends GET requests for verification
            return "OK", 200
        
        # Get raw POST data for verification
        raw_data = request.get_data(as_text=True)
        
        # Verify the IPN message with PayPal
        import urllib.parse
        verification_data = raw_data + "&cmd=_notify-validate"
        
        # Send verification request to PayPal
        import requests
        paypal_url = "https://www.paypal.com/cgi-bin/webscr"  # Use sandbox for testing: https://www.sandbox.paypal.com/cgi-bin/webscr
        verification_response = requests.post(paypal_url, data=verification_data, timeout=10)
        
        if verification_response.text != "VERIFIED":
            # IPN not verified - could be a fake request
            print(f"[PAYPAL IPN] Verification failed: {verification_response.text}")
            return "INVALID", 400
        
        # Parse the IPN data
        ipn_data = dict(urllib.parse.parse_qsl(raw_data))
        
        # Extract payment information
        payment_status = ipn_data.get('payment_status', '').upper()
        txn_id = ipn_data.get('txn_id', '')
        custom = ipn_data.get('custom', '')
        mc_gross = float(ipn_data.get('mc_gross', 0))
        mc_currency = ipn_data.get('mc_currency', 'EUR')
        payer_email = ipn_data.get('payer_email', '')
        receiver_email = ipn_data.get('receiver_email', '')
        
        # Parse custom field to get payment_id
        payment_id = None
        user_id = None
        if custom:
            for part in custom.split('|'):
                if part.startswith('payment_id:'):
                    payment_id = int(part.split(':', 1)[1])
                elif part.startswith('user_id:'):
                    user_id = int(part.split(':', 1)[1])
        
        # Handle different payment statuses
        if payment_status == 'COMPLETED':
            # Payment completed successfully
            if payment_id:
                payment = user_payments.query.get(payment_id)
                if payment and payment.payment_status == 'pending':
                    # Verify amount matches (within 1 cent tolerance)
                    payment_amount_euros = payment.amount_cents / 100.0
                    if abs(payment_amount_euros - mc_gross) < 0.01:
                        # Mark payment as paid
                        payment.payment_status = 'paid'
                        payment.payment_reference = txn_id
                        payment.paid_at = datetime.utcnow()
                        payment.notes = f"PayPal IPN confirmed - Payer: {payer_email} - Transaction: {txn_id}"
                        log_payment_to_cashbook(payment, created_by="PayPal IPN")
                        
                        db.session.commit()
                        
                        print(f"[PAYPAL IPN] Payment {payment_id} marked as paid for user {payment.user_id}")
                        return "OK", 200
                    else:
                        print(f"[PAYPAL IPN] Amount mismatch: expected {payment_amount_euros}, got {mc_gross}")
            else:
                # Try to match by amount and user_id if payment_id not found
                if user_id:
                    recent_payments = user_payments.query.filter_by(
                        user_id=user_id,
                        payment_method='paypal',
                        payment_status='pending'
                    ).order_by(user_payments.created_at.desc()).limit(5).all()
                    
                    for payment in recent_payments:
                        payment_amount_euros = payment.amount_cents / 100.0
                        if abs(payment_amount_euros - mc_gross) < 0.01:
                            payment.payment_status = 'paid'
                            payment.payment_reference = txn_id
                            payment.paid_at = datetime.utcnow()
                            payment.notes = f"PayPal IPN confirmed (matched by amount) - Payer: {payer_email} - Transaction: {txn_id}"
                            log_payment_to_cashbook(payment, created_by="PayPal IPN (amount match)")
                            db.session.commit()
                            print(f"[PAYPAL IPN] Payment {payment.id} matched and marked as paid")
                            return "OK", 200
        
        elif payment_status in ('DENIED', 'FAILED', 'VOIDED', 'REVERSED', 'REFUNDED'):
            # Payment was denied, failed, or refunded
            if payment_id:
                payment = user_payments.query.get(payment_id)
                if payment and payment.payment_status == 'pending':
                    payment.payment_status = 'cancelled'
                    payment.notes = (payment.notes or '') + f' [PayPal IPN: {payment_status}]'
                    db.session.commit()
                    print(f"[PAYPAL IPN] Payment {payment_id} marked as cancelled")
        
        elif payment_status == 'PENDING':
            # Payment is pending (e.g., eCheck)
            print(f"[PAYPAL IPN] Payment {payment_id} is pending")
        
        # Always return OK to PayPal (even if we couldn't process it)
        return "OK", 200
            
    except Exception as e:
        print(f"[PAYPAL IPN] Error processing IPN: {str(e)}")
        import traceback
        traceback.print_exc()
        # Still return OK to PayPal to prevent retries for our errors
        return "OK", 200

@bp.route("/api/payment/paypal-webhook", methods=["POST"])
def paypal_webhook():
    """Handle PayPal REST API webhooks (for PayPal REST API, not IPN)"""
    # This endpoint is kept for backward compatibility
    # But PayPal.me and standard payment links use IPN, not REST API
    try:
        data = request.get_json()
        event_type = data.get('event_type')
        resource = data.get('resource', {})
        
        if event_type == 'PAYMENT.CAPTURE.COMPLETED':
            amount = resource.get('amount', {})
            amount_value = float(amount.get('value', 0))
            transaction_id = resource.get('id', '')
            
            # Try to match by amount (less reliable)
            recent_payments = user_payments.query.filter_by(
                payment_method='paypal',
                payment_status='pending'
            ).order_by(user_payments.created_at.desc()).limit(10).all()
            
            for payment in recent_payments:
                payment_amount_euros = payment.amount_cents / 100.0
                if abs(payment_amount_euros - amount_value) < 0.01:
                    payment.payment_status = 'paid'
                    payment.payment_reference = transaction_id
                    payment.paid_at = datetime.utcnow()
                    log_payment_to_cashbook(payment, created_by="PayPal Webhook")
                    db.session.commit()
                    return jsonify({'success': True, 'message': 'Payment marked as paid'})
            
            return jsonify({'success': False, 'message': 'No matching payment found'})
        
        return jsonify({'success': True, 'message': f'Received {event_type} event'})
            
    except Exception as e:
        return jsonify({"error": f"Failed to process PayPal webhook: {str(e)}"}), 500

@bp.route("/api/payment/mark-paid/<int:payment_id>", methods=["POST"])
@require_admin_session
def mark_payment_paid(payment_id):
    """Manually mark a payment as paid (for admin use)"""
    try:
        payment = user_payments.query.get(payment_id)
        if not payment:
            return jsonify({"error": "Payment not found"}), 404
        
        creator = session.get('admin_username') or session.get('cashbook_user') or 'Admin'
        payment.payment_status = 'paid'
        payment.paid_at = datetime.utcnow()
        payment.notes = (payment.notes or '') + ' [Manually confirmed by admin]'
        log_payment_to_cashbook(payment, created_by=creator)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Payment marked as paid'
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to mark payment as paid: {str(e)}"}), 500


@bp.route("/api/payment/confirm-paypal", methods=["POST"])
@require_admin_session
def confirm_paypal_payment():
    """Manually confirm a PayPal payment when webhook doesn't work"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        amount_euros = data.get('amount_euros')
        transaction_id = data.get('transaction_id', 'Manual confirmation')
        payer_email = data.get('payer_email', 'Unknown')
        
        if not user_id or not amount_euros:
            return jsonify({"error": "User ID and amount are required"}), 400
        
        # Find the most recent pending PayPal payment for this user
        pending_payment = user_payments.query.filter_by(
            user_id=user_id,
            payment_method='paypal',
            payment_status='pending'
        ).order_by(user_payments.created_at.desc()).first()
        
        if not pending_payment:
            return jsonify({"error": "No pending PayPal payment found for this user"}), 404
        
        # Check if amount matches (within 1 cent tolerance)
        expected_amount = pending_payment.amount_cents / 100.0
        if abs(expected_amount - float(amount_euros)) > 0.01:
            return jsonify({"error": f"Amount mismatch. Expected €{expected_amount:.2f}, got €{amount_euros}"}), 400
        
        # Mark as paid
        pending_payment.payment_status = 'paid'
        pending_payment.payment_reference = transaction_id
        pending_payment.paid_at = datetime.utcnow()
        pending_payment.notes = f"PayPal payment manually confirmed - Payer: {payer_email} - Transaction: {transaction_id}"
        creator = session.get('admin_username') or session.get('cashbook_user') or 'Admin'
        log_payment_to_cashbook(pending_payment, created_by=creator)
        
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'Payment confirmed for user {user_id}',
            'payment_id': pending_payment.id
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to confirm payment: {str(e)}"}), 500

@bp.route("/api/payment/paypal-status/<int:payment_id>", methods=["GET"])
def get_paypal_payment_status(payment_id):
    """Return the latest status for a pending PayPal payment so clients can poll."""
    try:
        user_id = request.args.get('user_id', type=int)
        if not user_id:
            return jsonify({"success": False, "error": "User ID is required"}), 400

        payment = user_payments.query.get(payment_id)
        if not payment or payment.user_id != user_id:
            return jsonify({"success": False, "error": "Payment not found"}), 404

        if payment.payment_method != 'paypal':
            return jsonify({"success": False, "error": "Payment is not a PayPal payment"}), 400

        if payment.payment_status == 'pending':
            try:
                if refresh_paypal_payment_status(payment):
                    db.session.refresh(payment)
            except Exception as exc:
                current_app.logger.warning(f"PayPal status refresh failed for {payment_id}: {exc}")

        return jsonify({
            "success": True,
            "payment_status": payment.payment_status,
            "amount_euros": payment.amount_cents / 100.0,
            "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
            "payment_reference": payment.payment_reference or ""
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to fetch PayPal status: {str(e)}"}), 500


@bp.route("/api/payment/receipt/<int:payment_id>")
def generate_payment_receipt(payment_id):
    """Generate a payment receipt for airdrop sharing"""
    try:
        # Get payment details
        payment = user_payments.query.get(payment_id)
        if not payment:
            return jsonify({"error": "Payment not found"}), 404
        
        user = users.query.get(payment.user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        # Get consumption details for this payment
        consumption_details = db.session.query(
            consumptions, beverages
        ).join(
            beverages, consumptions.beverage_id == beverages.id
        ).join(
            payment_consumptions, payment_consumptions.consumption_id == consumptions.id
        ).filter(
            payment_consumptions.payment_id == payment_id
        ).all()
        
        # Generate receipt data
        receipt_data = {
            'payment_id': payment.id,
            'user_name': f"{user.first_name} {user.last_name}",
            'user_id': user.id,
            'amount_euros': payment.amount_cents / 100.0,
            'payment_method': payment.payment_method,
            'payment_date': payment.paid_at.strftime('%d.%m.%Y %H:%M') if payment.paid_at else payment.created_at.strftime('%d.%m.%Y %H:%M'),
            'transaction_id': payment.payment_reference or 'N/A',
            'items': [],
            'total': payment.amount_cents / 100.0
        }
        
        # Add consumption items
        for consumption, beverage in consumption_details:
            pc = payment_consumptions.query.filter_by(
                payment_id=payment_id,
                consumption_id=consumption.id
            ).first()
            
            if pc:
                receipt_data['items'].append({
                    'name': beverage.name,
                    'quantity': consumption.quantity,
                    'unit_price': consumption.unit_price_cents / 100.0,
                    'total_price': pc.amount_cents / 100.0,
                    'date': consumption.created_at.strftime('%d.%m.%Y')
                })
        
        return jsonify({
            'success': True,
            'receipt': receipt_data
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to generate receipt: {str(e)}"}), 500


@bp.route("/payment_receipt.html")
def payment_receipt_page():
    """Serve the payment receipt page"""
    return render_template("payment_receipt.html")


@bp.route("/api/payment/user-payments/<int:user_id>")
def get_user_payments(user_id):
    """Get all payments for a specific user"""
    try:
        payments = user_payments.query.filter_by(user_id=user_id).order_by(user_payments.created_at.desc()).all()
        
        payments_data = []
        for payment in payments:
            payments_data.append({
                'id': payment.id,
                'amount_cents': payment.amount_cents,
                'amount_euros': payment.amount_cents / 100.0,
                'payment_method': payment.payment_method,
                'payment_status': payment.payment_status,
                'payment_reference': payment.payment_reference,
                'created_at': payment.created_at.isoformat(),
                'paid_at': payment.paid_at.isoformat() if payment.paid_at else None,
                'notes': payment.notes
            })
        
        return jsonify({
            'success': True,
            'payments': payments_data
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to get user payments: {str(e)}"}), 500

@bp.route("/api/payments/create", methods=["POST"])
@require_admin_session
def create_payment():
    """Create a new payment record and link it to unpaid consumptions"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        amount_cents = data.get('amount_cents')
        payment_method = data.get('payment_method', 'cash')
        notes = data.get('notes', '')

        if not user_id or not amount_cents:
            return jsonify({"error": "User ID and amount are required"}), 400

        if payment_method not in ('cash', 'paypal'):
            return jsonify({"error": "Invalid payment method"}), 400

        # Get unpaid consumptions for this user
        paid_consumption_ids = db.session.query(payment_consumptions.consumption_id).join(
            user_payments, payment_consumptions.payment_id == user_payments.id
        ).filter(
            user_payments.user_id == user_id,
            user_payments.payment_status == 'paid'
        ).all()

        paid_consumption_ids = [pc[0] for pc in paid_consumption_ids]

        unpaid_consumptions = consumptions.query.filter_by(user_id=user_id)\
            .filter(~consumptions.id.in_(paid_consumption_ids))\
            .order_by(consumptions.created_at).all()

        if not unpaid_consumptions:
            return jsonify({"error": "No unpaid consumptions found for this user"}), 400

        # Create payment record
        payment = user_payments(
            user_id=user_id,
            amount_cents=amount_cents,
            payment_method=payment_method,
            payment_status='pending',
            notes=notes
        )

        db.session.add(payment)
        db.session.flush()  # Get the payment ID

        # Link payment to consumptions (oldest first)
        remaining_amount = amount_cents
        for consumption in unpaid_consumptions:
            if remaining_amount <= 0:
                break

            # Calculate amount for this consumption
            consumption_amount = consumption.quantity * consumption.unit_price_cents
            payment_amount = min(consumption_amount, remaining_amount)

            # Create payment_consumption link
            payment_consumption = payment_consumptions(
                payment_id=payment.id,
                consumption_id=consumption.id,
                amount_cents=payment_amount
            )

            db.session.add(payment_consumption)
            remaining_amount -= payment_amount

        db.session.commit()

        return jsonify({
            'success': True,
            'payment_id': payment.id,
            'message': 'Payment record created successfully'
        })

    except Exception as e:
        return jsonify({"error": f"Failed to create payment: {str(e)}"}), 500

@bp.route("/api/payments/<int:payment_id>/update", methods=["POST"])
@require_admin_session
def update_payment(payment_id):
    """Update payment status"""
    try:
        data = request.get_json()
        payment_status = data.get('payment_status')
        payment_reference = data.get('payment_reference', '')
        notes = data.get('notes', '')
        
        payment = user_payments.query.get(payment_id)
        if not payment:
            return jsonify({"error": "Payment not found"}), 404
        
        # Update payment
        previous_status = payment.payment_status
        payment.payment_status = payment_status
        payment.payment_reference = payment_reference
        payment.notes = notes
        
        if payment_status == 'paid':
            payment.paid_at = datetime.utcnow()
            if previous_status != 'paid':
                creator = session.get('admin_username') or session.get('cashbook_user') or 'Admin'
                log_payment_to_cashbook(payment, created_by=creator)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Payment updated successfully'
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to update payment: {str(e)}"}), 500

@bp.route("/api/payments/<int:payment_id>/delete", methods=["POST"])
@require_admin_session
def delete_payment(payment_id):
    """Delete a payment record"""
    try:
        payment = user_payments.query.get(payment_id)
        if not payment:
            return jsonify({"error": "Payment not found"}), 404
        
        # Delete payment_consumptions first (foreign key constraint)
        payment_consumptions.query.filter_by(payment_id=payment_id).delete()
        
        # Delete the payment
        db.session.delete(payment)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Payment deleted successfully'
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to delete payment: {str(e)}"}), 500


@bp.route("/api/payments/<int:payment_id>/revert", methods=["POST"])
@require_admin_session
def revert_payment(payment_id):
    """Revert a paid payment back to pending status"""
    try:
        payment = user_payments.query.get(payment_id)
        if not payment:
            return jsonify({"error": "Payment not found"}), 404

        if payment.payment_status != 'paid':
            return jsonify({"error": "Only paid payments can be reverted"}), 400

        # Revert payment status to pending
        payment.payment_status = 'pending'
        payment.paid_at = None
        payment.payment_reference = None
        payment.notes = (payment.notes or '') + ' [Reverted from paid to pending]'
        
        db.session.commit()

        return jsonify({'success': True, 'message': 'Payment reverted to pending status'})
    except Exception as e:
        return jsonify({"error": f"Failed to revert payment: {str(e)}"}), 500

@bp.route('/events')
def sse_events():
    """Server-Sent Events stream for real-time theme updates.
    Sends events of type 'theme' with JSON payload {theme, version}.
    Includes periodic heartbeat to keep connection alive.
    """
    def event_stream():
        import time
        last_version = None
        while True:
            try:
                current_theme = settings.get_value('theme', 'coffee')
                current_version = settings.get_value('theme_version', '1')
                if current_version != last_version:
                    last_version = current_version
                    yield f"event: theme\ndata: {{\"theme\":\"{current_theme}\",\"version\":\"{current_version}\"}}\n\n"
                # Heartbeat every 15s
                time.sleep(3)
            except GeneratorExit:
                break
            except Exception:
                # brief backoff on error
                time.sleep(5)
    headers = {
        'Cache-Control': 'no-cache',
        'Content-Type': 'text/event-stream',
        'Connection': 'keep-alive'
    }
    return Response(event_stream(), headers=headers)

@bp.route("/admin/security-status")
def admin_security_status():
    """Show current security status"""
    security_info = get_security_info()
    return jsonify(security_info)

# =============================================================================
# ADMIN: Encoding / Umlaut Repair UI
# =============================================================================

def _umlaut_guess(word: str) -> str:
    """Attempt a naive guess replacing '??' with likely German umlauts based on context.
    This is intentionally conservative; admin can override manually in the UI.
    Patterns (very rough):
      ue -> ü  (already proper style, so we don't touch)
      oe -> ö  (same)
      ae -> ä  (same)
      ss may become ß if double-s not at start and preceded by a vowel.
    For '??' we try to look at surrounding characters; if none match, leave as placeholder so admin edits.
    """
    if '??' not in word:
        return word
    # Provide a minimal set of character candidates
    candidates = ['ä','ö','ü','ß']
    # Replace sequentially – if multiple occurrences, keep placeholders for manual review after first replacement
    parts = word.split('??')
    rebuilt = parts[0]
    for tail in parts[1:]:
        # Heuristic: if preceding char is a/o/u and next char is consonant, try umlaut of that vowel
        replacement = 'ä'
        prev = rebuilt[-1:] if rebuilt else ''
        nextc = tail[:1]
        if prev.lower() == 'a':
            replacement = 'ä'
        elif prev.lower() == 'o':
            replacement = 'ö'
        elif prev.lower() == 'u':
            replacement = 'ü'
        elif prev.lower() in 'aeiou' and nextc.lower() == 's':
            replacement = 'ß'
        else:
            # fallback rotate choices to avoid uniform guess
            replacement = candidates[len(rebuilt) % len(candidates)]
        rebuilt += replacement + tail
    return rebuilt

ENCODING_FIXES_ENABLED = bool(os.getenv('ENABLE_ENCODING_FIXES'))

if ENCODING_FIXES_ENABLED:
    @bp.route('/admin/encoding-fixes')
    def admin_encoding_fixes():
        import re  # local import to avoid overhead when disabled
        suggestions = []
        suspicious = re.compile(r'\?\?|Ã|�')
        for u in users.query.limit(200).all():
            combined = f"{u.first_name} {u.last_name}"
            if suspicious.search(combined):
                suggestions.append({
                    'type': 'user',
                    'id': u.id,
                    'field': 'name',
                    'original': combined,
                    'guess': _umlaut_guess(combined)
                })
        flash(f'Found {len(suggestions)} potential issues (preview only).', 'info')
        return render_template('admin_encoding_fixes.html', data=suggestions)

    @bp.route('/admin/encoding-fixes/apply', methods=['POST'])
    def apply_encoding_fixes():
        import re
        updates = 0
        try:
            suspicious = re.compile(r'\?\?|Ã|�')
            for u in users.query.limit(200).all():
                combined = f"{u.first_name} {u.last_name}"
                if suspicious.search(combined):
                    guess = _umlaut_guess(combined)
                    parts = guess.split(' ', 1)
                    if len(parts) == 2:
                        u.first_name, u.last_name = parts[0], parts[1]
                        updates += 1
            if updates:
                db.session.commit()
                flash(f'Applied {updates} encoding corrections.', 'success')
            else:
                flash('No changes applied.', 'info')
        except Exception as e:
            db.session.rollback()
            flash(f'Error applying fixes: {e}', 'danger')
        return redirect(url_for('routes.admin_encoding_fixes'))

# MyPOS Integration Routes - REMOVED (device is locked)
