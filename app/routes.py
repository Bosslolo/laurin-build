from flask import Blueprint, jsonify, render_template, request, redirect, url_for, flash, abort, session
from .models import roles, beverages, users, consumptions, invoices, beverage_prices, daily_prices, display_items
from . import db
from datetime import datetime, date
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
import hashlib
import os
from .security import (
    require_admin_auth, require_security_gate, is_admin_mode, 
    bypass_pin_for_dev, get_security_info, verify_admin_token, SECURITY_GATE_ENABLED
)

bp = Blueprint("routes", __name__)

def check_invoice_exists(user_id):
    """Get or create an invoice for the user and current month."""
    current_month_year = date.today().replace(day=1)
    existing_invoice = invoices.query.filter_by(
        user_id=user_id,
        period=current_month_year
    ).first()
    
    if existing_invoice:
        return existing_invoice

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

def hash_pin(pin):
    """Hash a PIN using SHA-256"""
    return hashlib.sha256(pin.encode()).digest()

def verify_pin(user_id, pin):
    """Verify a PIN against the stored hash"""
    user = users.query.get(user_id)
    if not user or not user.pin_hash:
        return False
    return user.pin_hash == hash_pin(pin)

@bp.route("/")
def index():
    # Get current month start date
    current_month = date.today().replace(day=1)
    
    # Fetch all users with their roles and total consumption for current month
    users_with_consumption = db.session.query(
        users,
        roles,
        func.coalesce(func.sum(consumptions.quantity), 0).label('total_consumption')
    ).join(roles, users.role_id == roles.id)\
     .outerjoin(consumptions, 
                db.and_(consumptions.user_id == users.id,
                       consumptions.created_at >= current_month))\
     .group_by(users.id, roles.id)\
     .order_by(func.coalesce(func.sum(consumptions.quantity), 0).desc())\
     .all()
    
    # Extract just the user objects for template
    sorted_users = [user_role_consumption[0] for user_role_consumption in users_with_consumption]
    
    # Check if we're in admin mode (development mode OR explicitly set to admin)
    is_dev = (os.getenv('FLASK_ENV') == 'development' or 
              os.getenv('FLASK_APP_MODE') == 'admin')
    return render_template("index.html", users=sorted_users, is_dev=is_dev)


@bp.route("/dev/add_user", methods=["GET", "POST"])
def dev_add_user():
    """Development-only simple user creation form."""
    # Check if we're in admin mode
    if not (os.getenv('FLASK_ENV') == 'development' or os.getenv('FLASK_APP_MODE') == 'admin'):
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
    if not (os.getenv('FLASK_ENV') == 'development' or os.getenv('FLASK_APP_MODE') == 'admin'):
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
    """Development-only beverage management."""
    # Check if we're in admin mode
    if not (os.getenv('FLASK_ENV') == 'development' or os.getenv('FLASK_APP_MODE') == 'admin'):
        abort(404)
    
    if request.method == "POST":
        data = request.get_json()
        name = data.get("name", "").strip()
        category = data.get("category", "drink")
        
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
                "beverage": {"id": new_beverage.id, "name": new_beverage.name, "category": new_beverage.category}
            })
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "error": f"Failed to create beverage: {str(e)}"}), 500
    
    # GET request - return all beverages
    all_beverages = beverages.query.filter_by(status=True).all()
    return jsonify([{"id": bev.id, "name": bev.name, "category": bev.category} for bev in all_beverages])

@bp.route("/dev/prices", methods=["GET", "POST"])
def dev_prices():
    """Development-only role-specific price management."""
    # Check if we're in admin mode
    if not (os.getenv('FLASK_ENV') == 'development' or os.getenv('FLASK_APP_MODE') == 'admin'):
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
            
            # Remove existing prices for this role
            beverage_prices.query.filter_by(role_id=role_id).delete()
            
            # Add new prices for this role
            for price_data in prices:
                beverage_id = price_data.get("beverage_id")
                price_cents = price_data.get("price_cents")
                
                if beverage_id and price_cents is not None:
                    new_price = beverage_prices(
                        role_id=role_id,
                        beverage_id=beverage_id,
                        price_cents=int(price_cents)
                    )
                    db.session.add(new_price)
            
            db.session.commit()
            
            return jsonify({
                "success": True,
                "message": f"Prices updated successfully for role '{role.name}'"
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
    if not (os.getenv('FLASK_ENV') == 'development' or os.getenv('FLASK_APP_MODE') == 'admin'):
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
        
        # Update prices for ALL roles
        for role in all_roles:
            # Remove existing prices for this role
            beverage_prices.query.filter_by(role_id=role.id).delete()
            
            # Add new prices for this role
            for price_data in prices:
                beverage_id = price_data.get("beverage_id")
                price_cents = price_data.get("price_cents")
                
                if beverage_id and price_cents is not None:
                    new_price = beverage_prices(
                        role_id=role.id,
                        beverage_id=beverage_id,
                        price_cents=int(price_cents)
                    )
                    db.session.add(new_price)
        
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": f"Unified prices updated successfully for all {len(all_roles)} roles"
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": f"Failed to update prices: {str(e)}"}), 500

@bp.route("/dev/roles_manage", methods=["GET", "POST"])
def dev_roles_manage():
    """Development-only role management."""
    # Check if we're in admin mode
    if not (os.getenv('FLASK_ENV') == 'development' or os.getenv('FLASK_APP_MODE') == 'admin'):
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
    if not (os.getenv('FLASK_ENV') == 'development' or os.getenv('FLASK_APP_MODE') == 'admin'):
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
    if not (os.getenv('FLASK_ENV') == 'development' or os.getenv('FLASK_APP_MODE') == 'admin'):
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

@bp.route("/dev/users_manage", methods=["GET"])
def dev_users_manage():
    """Development-only user management - get all users."""
    # Check if we're in admin mode
    if not (os.getenv('FLASK_ENV') == 'development' or os.getenv('FLASK_APP_MODE') == 'admin'):
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
                "has_pin": user.pin_hash is not None
            })
        
        return jsonify(users_data)
        
    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to load users: {str(e)}"}), 500

@bp.route("/dev/delete_beverage/<int:beverage_id>", methods=["DELETE"])
def dev_delete_beverage(beverage_id):
    """Development-only individual beverage deletion."""
    # Check if we're in admin mode
    if not (os.getenv('FLASK_ENV') == 'development' or os.getenv('FLASK_APP_MODE') == 'admin'):
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
    if not (os.getenv('FLASK_ENV') == 'development' or os.getenv('FLASK_APP_MODE') == 'admin'):
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
    """Guest entry page - allows beverage selection without a specific user."""
    # Create a temporary guest user object for the template
    guest_user = type('GuestUser', (), {
        'id': 0,
        'first_name': 'Guest',
        'last_name': '',
        'email': '',
        'role': type('GuestRole', (), {
            'id': 1,  # Default to role ID 1 (should be "Guests" role)
            'name': 'Guests'
        })()
    })()
    
    # Fetch all active beverages
    all_beverages = beverages.query.filter_by(status=True).all()
    
    # Fetch beverage prices for the guest role (role_id = 1)
    beverage_prices_for_role = beverage_prices.query.filter_by(role_id=1).all()
    
    # Create a dictionary for easy price lookup
    price_lookup = {bp.beverage_id: bp for bp in beverage_prices_for_role}
    
    # Convert guest user to dictionary for JSON serialization
    user_dict = {
        'id': guest_user.id,
        'first_name': guest_user.first_name,
        'last_name': guest_user.last_name,
        'email': guest_user.email,
        'role': {
            'id': guest_user.role.id,
            'name': guest_user.role.name
        }
    }
    
    return render_template("entries.html", 
                         user=guest_user,
                         beverages=all_beverages,
                         price_lookup=price_lookup,
                         consumptions=[],
                         user_data=user_dict)

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
    
    # Check for admin bypass
    if session.get('admin_bypass', False) and session.get('bypass_user_id') == user_id:
        # Admin bypass - no PIN required
        pass
    # PIN verification is now handled by JavaScript on the frontend
    # No need to redirect back to index with require_pin parameter
    
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
    
    return render_template("entries.html", 
                         user=user, 
                         user_data=user_dict,
                         consumptions=user_consumptions,
                         beverages=all_beverages,
                         price_lookup=price_lookup)

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
            user_id = int(data.get('user_id'))
            beverage_id = int(data.get('beverage_id'))
            quantity = int(data.get('quantity', 1))
        except (ValueError, TypeError) as e:
            return jsonify({"error": f"Invalid data format: {str(e)}"}), 400
        
        if not user_id or not beverage_id:
            return jsonify({"error": "Missing required fields"}), 400
        
        # Validate user exists
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
        
        # Get or create monthly invoice
        invoice = check_invoice_exists(user_id)
        
        # Create consumption entry
        consumption = consumptions(
            user_id=user_id,
            beverage_id=beverage_id,
            beverage_price_id=beverage_price.id,
            invoice_id=invoice.id,
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

@bp.route("/admin_consumption_history")
def admin_consumption_history():
    """Admin-only route to view historical consumption data for a specific user."""
    # Check if we're in admin mode
    if not (os.getenv('FLASK_ENV') == 'development' or os.getenv('FLASK_APP_MODE') == 'admin'):
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
    """Monthly consumption report for all users."""
    # Check if we're in admin mode
    if not (os.getenv('FLASK_ENV') == 'development' or os.getenv('FLASK_APP_MODE') == 'admin'):
        abort(404)
    
    # Get month and year from query parameters (default to current month)
    year = request.args.get('year', date.today().year, type=int)
    month = request.args.get('month', date.today().month, type=int)
    
    # Create date for the first day of the selected month
    report_date = date(year, month, 1)
    
    # Get all consumptions for the selected month
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
         consumptions.created_at >= report_date,
         consumptions.created_at < date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)
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
         consumptions.created_at >= report_date,
         consumptions.created_at < date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)
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
         consumptions.created_at >= report_date,
         consumptions.created_at < date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)
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
    
    return render_template("monthly_report.html", 
                         consumptions=month_consumptions,
                         summary_stats=summary_stats,
                         user_summaries=user_summaries,
                         available_months=available_months,
                         current_year=year,
                         current_month=month,
                         report_date=report_date)

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
    token = request.form.get('admin_token', '').strip()
    
    if verify_admin_token(token):
        session['admin_authenticated'] = True
        session['security_gate_passed'] = True  # Admin bypasses security gate
        flash('🔐 Admin access granted! You now have full system access.', 'success')
        return redirect(url_for('routes.index'))
    else:
        flash('❌ Invalid admin token. Access denied.', 'error')
        return redirect(url_for('routes.admin_login'))

@bp.route("/admin/logout")
def admin_logout():
    """Logout admin"""
    session.pop('admin_authenticated', None)
    session.pop('security_gate_passed', None)
    flash('👋 Admin session ended.', 'info')
    return redirect(url_for('routes.index'))

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
        flash('✅ Access granted! Welcome to Laurin Build.', 'success')
        return redirect(url_for('routes.index'))
    else:
        flash('❌ Invalid access code. Please try again.', 'error')
        return redirect(url_for('routes.security_gate'))

@bp.route("/admin/backdoor")
@require_admin_auth
def admin_backdoor():
    """Admin backdoor - access any user without PIN"""
    user_id = request.args.get('user_id', type=int)
    
    if not user_id:
        # Show list of all users for backdoor access
        all_users = users.query.join(roles, users.role_id == roles.id).all()
        return render_template("admin_backdoor.html", users=all_users)
    
    # Direct access to user without PIN
    user = users.query.join(roles, users.role_id == roles.id).filter(users.id == user_id).first()
    
    if not user:
        flash('❌ User not found.', 'error')
        return redirect(url_for('routes.admin_backdoor'))
    
    # Set admin bypass flag
    session['admin_bypass'] = True
    session['bypass_user_id'] = user_id
    
    flash(f'🔓 Admin backdoor: Accessing {user.first_name} {user.last_name} without PIN', 'info')
    return redirect(url_for('routes.entries', user_id=user_id))

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
    
    return render_template("price_list.html", 
                         price_data=price_data)

@bp.route("/admin/daily-prices")
@require_admin_auth
def admin_daily_prices():
    """Admin interface for managing daily prices"""
    from datetime import date, timedelta
    
    # Get all active beverages
    all_beverages = beverages.query.filter_by(status=True).all()
    
    # Get today's date
    today = date.today()
    
    # Get daily prices for today
    today_prices = daily_prices.query.filter_by(date=today, is_active=True).all()
    
    # Create a dict for easy lookup
    price_dict = {price.beverage_id: price for price in today_prices}
    
    return render_template("admin_daily_prices.html", 
                         beverages=all_beverages,
                         today_prices=price_dict,
                         today=today)

@bp.route("/admin/daily-prices/set", methods=["POST"])
@require_admin_auth
def set_daily_price():
    """Set daily price for a beverage"""
    from datetime import date
    
    beverage_id = request.form.get('beverage_id', type=int)
    price_euros = request.form.get('price_euros', type=float)
    price_date = request.form.get('price_date', type=str)
    
    if not beverage_id or not price_euros:
        flash('❌ Missing required fields.', 'error')
        return redirect(url_for('routes.admin_daily_prices'))
    
    # Convert euros to cents
    price_cents = int(price_euros * 100)
    
    # Parse date
    if price_date:
        target_date = datetime.strptime(price_date, '%Y-%m-%d').date()
    else:
        target_date = date.today()
    
    # Check if price already exists for this date
    existing_price = daily_prices.query.filter_by(
        beverage_id=beverage_id, 
        date=target_date
    ).first()
    
    if existing_price:
        # Update existing price
        existing_price.price_cents = price_cents
        existing_price.is_active = True
        existing_price.updated_at = datetime.utcnow()
    else:
        # Create new price
        new_price = daily_prices(
            beverage_id=beverage_id,
            price_cents=price_cents,
            date=target_date,
            is_active=True
        )
        db.session.add(new_price)
    
    try:
        db.session.commit()
        flash(f'✅ Daily price updated successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Error updating price: {str(e)}', 'error')
    
    return redirect(url_for('routes.admin_daily_prices'))

@bp.route("/admin/display-items")
@require_admin_auth
def admin_display_items():
    """Admin interface for managing display items (like cakes)"""
    # Get all display items
    all_items = display_items.query.order_by(display_items.display_order, display_items.name).all()
    
    return render_template("admin_display_items.html", 
                         items=all_items)

@bp.route("/admin/display-items/add", methods=["POST"])
@require_admin_auth
def add_display_item():
    """Add a new display item"""
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    price_euros = request.form.get('price_euros', type=float)
    category = request.form.get('category', 'food')
    display_order = request.form.get('display_order', type=int) or 0
    
    if not name or not price_euros:
        flash('❌ Name and price are required.', 'error')
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
        flash(f'✅ Display item "{name}" added successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Error adding item: {str(e)}', 'error')
    
    return redirect(url_for('routes.admin_display_items'))

@bp.route("/admin/display-items/update", methods=["POST"])
@require_admin_auth
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
        flash('❌ Missing required fields.', 'error')
        return redirect(url_for('routes.admin_display_items'))
    
    # Get the item
    item = display_items.query.get(item_id)
    if not item:
        flash('❌ Item not found.', 'error')
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
        flash(f'✅ Display item "{name}" updated successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Error updating item: {str(e)}', 'error')
    
    return redirect(url_for('routes.admin_display_items'))

@bp.route("/admin/display-items/delete/<int:item_id>")
@require_admin_auth
def delete_display_item(item_id):
    """Delete a display item"""
    item = display_items.query.get(item_id)
    if not item:
        flash('❌ Item not found.', 'error')
        return redirect(url_for('routes.admin_display_items'))
    
    try:
        db.session.delete(item)
        db.session.commit()
        flash(f'✅ Display item "{item.name}" deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'❌ Error deleting item: {str(e)}', 'error')
    
    return redirect(url_for('routes.admin_display_items'))

@bp.route("/api/set-theme", methods=["POST"])
def set_theme():
    """API endpoint to set the current theme globally"""
    try:
        data = request.get_json()
        theme = data.get('theme', 'coffee')
        
        # Store theme in session for server-side tracking
        session['current_theme'] = theme
        
        return jsonify({
            'success': True,
            'theme': theme,
            'message': f'Theme set to {theme}'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400

@bp.route("/api/get-theme")
def get_theme():
    """API endpoint to get the current theme"""
    theme = session.get('current_theme', 'coffee')
    return jsonify({
        'success': True,
        'theme': theme
    })

@bp.route("/admin/security-status")
@require_admin_auth
def admin_security_status():
    """Show current security status"""
    security_info = get_security_info()
    return jsonify(security_info)
