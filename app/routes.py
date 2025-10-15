from flask import Blueprint, jsonify, render_template, request, redirect, url_for, flash, abort, session, Response
from .models import roles, beverages, users, consumptions, invoices, beverage_prices, display_items, settings, cashbook_entries
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
    """Decorator to enforce admin access on admin port and check session timeout."""
    def decorated_function(*args, **kwargs):
        # Must be on admin port and authenticated
        if not is_admin_mode():
            return redirect(url_for('routes.admin_login'))
        # Enforce inactivity timeout
        if check_session_timeout():
            return redirect(url_for('routes.admin_login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

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
        'coffee': '#222222',
        'spring': '#4CAF50',
        'summer': '#FF9800',
        'autumn': '#FF5722',
        'winter': '#2196F3'
    }
    theme_color = theme_colors.get(theme, '#222222')
    return render_template(
        'index.html',
        users=initial_subset,
        users_count=len(sorted_users),
        is_admin=is_admin,
        theme=theme,
        theme_version=theme_version,
        theme_color=theme_color
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
    
    theme_version = settings.get_value('theme_version', '1') or '1'
    cache_key = f"index:{theme_version}:{'admin' if is_admin_port() else 'user'}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    rv = _index_core()
    cache.set(cache_key, rv, timeout=30)
    return rv

@bp.route('/api/index-data')
@cache.cached(timeout=30)
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
        user.pin_hash = hash_pin(pin)
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
        
        if "consumptions" in delete_types:
            count = consumptions.query.count()
            consumptions.query.delete()
            deleted_items.append(f"{count} consumptions")
        
        if "prices" in delete_types:
            count = beverage_prices.query.count()
            beverage_prices.query.delete()
            deleted_items.append(f"{count} prices")
        
        if "beverages" in delete_types:
            count = beverages.query.count()
            beverages.query.delete()
            deleted_items.append(f"{count} beverages/food")
        
        if "users" in delete_types:
            count = users.query.count()
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
    
    return render_template("entries.html", 
                         user=guest_user,
                         beverages=all_beverages,
                         price_lookup=price_lookup,
                         consumptions=[],
                         user_data=user_dict,
                         theme=theme,
                         theme_color=theme_color)

@bp.route("/entries")
def entries():
    user_id = request.args.get('user_id', type=int)
    
    if not user_id:
        # Redirect to index if no user_id provided
        return redirect(url_for('routes.index'))
    
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
        user = users.query.get(user_id)
        if user and user.pin_hash:
            # User has PIN - check if PIN was verified
            if not session.get(f'pin_verified_{user_id}', False):
                # PIN not verified - redirect to index with PIN requirement
                return redirect(url_for('routes.index') + f'?user_id={user_id}&require_pin=true')
    
    # Fetch the specific user with their role
    user = users.query.join(roles, users.role_id == roles.id).filter(users.id == user_id).first()
    
    if not user:
        # Redirect to index if user not found
        return redirect(url_for('routes.index'))
    
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
    
    return render_template("entries.html", 
                         user=user, 
                         user_data=user_dict,
                         consumptions=user_consumptions,
                         beverages=all_beverages,
                         price_lookup=price_lookup,
                         theme=theme,
                         theme_color=theme_color)

@bp.route("/verify_pin", methods=["POST"])
def verify_pin_route():
    """Verify PIN for a specific user"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        pin = data.get('pin', '').strip()
        
        if not user_id or not pin:
            return jsonify({"error": "User ID and PIN are required"}), 400
        
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
        elif 'iPad' in user_agent:
            device_name = "iPad (Safari)"
        else:
            device_name = "Mac (Safari)"
    elif 'iPhone' in user_agent:
        device_name = "iPhone"
    elif 'iPad' in user_agent:
        device_name = "iPad"
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
@require_admin_session
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

# =============================================================================
# ADMIN: Cashbook for Schülerfirma and Pausenverkauf
# =============================================================================

COMPANY_OPTIONS = ["Schülerfirma", "Pausenverkauf"]

def _next_beleg_nummer(company: str) -> int:
    last = cashbook_entries.query.filter_by(company=company).order_by(cashbook_entries.beleg_nummer.desc()).first()
    return (last.beleg_nummer + 1) if last else 1

def _current_kassenstand(company: str) -> int:
    last = cashbook_entries.query.filter_by(company=company).order_by(cashbook_entries.entry_date.desc(), cashbook_entries.id.desc()).first()
    return last.kassenstand_bar_cents if last else 0

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
        current_balance = _current_kassenstand(company)
        
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
    
    return render_template('admin_cashbook.html',
                           theme=theme,
                           theme_color=theme_color,
                           company=company,
                           company_options=COMPANY_OPTIONS,
                           entries=entries,
                           next_beleg=_next_beleg_nummer(company),
                           current_kassenstand=_current_kassenstand(company) / 100.0,
                           current_user=current_user)

@bp.route('/admin/cashbook/add', methods=['POST'])
def admin_cashbook_add():
    # Check authentication - either admin or cashbook user
    if not (is_admin_mode() or session.get('cashbook_authenticated', False)):
        return redirect(url_for('routes.index'))
    try:
        company = request.form.get('company') or COMPANY_OPTIONS[0]
        if company not in COMPANY_OPTIONS:
            company = COMPANY_OPTIONS[0]
        beleg_nummer = _next_beleg_nummer(company)
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
        # compute new cash balance
        prev_kassenstand = _current_kassenstand(company)
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
        
        # Update entry fields
        entry.entry_date = datetime.strptime(request.form.get('entry_date'), '%Y-%m-%d').date()
        entry.posten = request.form.get('posten')
        entry.bemerkung = request.form.get('bemerkung', '')
        
        einnahmen_bar_eur = float(request.form.get('einnahmen_bar_eur', 0))
        ausgaben_bar_eur = float(request.form.get('ausgaben_bar_eur', 0))
        
        entry.einnahmen_bar_cents = int(einnahmen_bar_eur * 100)
        entry.ausgaben_bar_cents = int(ausgaben_bar_eur * 100)
        
        # Recalculate kassenstand for all entries after this one
        # This is a simplified approach - in production you might want more sophisticated recalculation
        entry.kassenstand_bar_cents = entry.kassenstand_bar_cents  # Keep current for now
        
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
        
        # Store company for redirect
        company = entry.company
        
        # Delete the entry
        db.session.delete(entry)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Entry deleted successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

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

# Admin: Find existing "Schülerfirma" user and return ID (no creation)
@bp.route('/admin/find_schuelerfirma', methods=['GET'])
def admin_find_schuelerfirma():
    if not (is_admin_port() and session.get('admin_authenticated', False)):
        abort(403)
    try:
        # Try several likely patterns: exact first name, startswith including trailing dot/spaces
        candidate = (
            users.query
                .filter(
                    (users.first_name.ilike('Schülerfirma%')) |
                    (users.last_name.ilike('Schülerfirma%'))
                )
                .order_by(users.id.asc())
                .first()
        )
        if not candidate:
            return jsonify({'success': False, 'error': 'No existing "Schülerfirma" user found'}), 404
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
@require_admin_session
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
