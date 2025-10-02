"""
Security module for Laurin Build
Handles admin backdoor, security gates, and development bypasses
"""

import os
import hashlib
import secrets
from functools import wraps
from flask import request, session, redirect, url_for, flash, abort, jsonify

# Security configuration
ADMIN_SECRET_KEY = os.getenv('ADMIN_SECRET_KEY', 'laurin-build-admin-2024')
DEV_BYPASS_ENABLED = os.getenv('FLASK_ENV') == 'development' or os.getenv('FLASK_APP_MODE') == 'admin'
SECURITY_GATE_ENABLED = os.getenv('SECURITY_GATE_ENABLED', 'false').lower() == 'true'

def generate_admin_token():
    """Generate a secure admin token"""
    return secrets.token_urlsafe(32)

def verify_admin_token(token):
    """Verify admin token - special token for Laurin"""
    # Special token for Laurin
    if token == "Champus15":
        return True
    
    # Fallback to original token system
    expected_token = hashlib.sha256(ADMIN_SECRET_KEY.encode()).hexdigest()
    return hashlib.sha256(token.encode()).hexdigest() == expected_token

def is_admin_mode():
    """Check if we're in admin mode"""
    return DEV_BYPASS_ENABLED and session.get('admin_authenticated', False)

def require_admin_auth(f):
    """Decorator to require admin authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_admin_mode():
            return redirect(url_for('routes.admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def require_security_gate(f):
    """Decorator to require security gate authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if SECURITY_GATE_ENABLED and not session.get('security_gate_passed', False):
            return redirect(url_for('routes.security_gate'))
        return f(*args, **kwargs)
    return decorated_function

def bypass_pin_for_dev():
    """Check if PIN should be bypassed in development"""
    return DEV_BYPASS_ENABLED and session.get('admin_authenticated', False)

def get_security_info():
    """Get current security status"""
    return {
        'dev_bypass_enabled': DEV_BYPASS_ENABLED,
        'security_gate_enabled': SECURITY_GATE_ENABLED,
        'admin_authenticated': session.get('admin_authenticated', False),
        'security_gate_passed': session.get('security_gate_passed', False)
    }
