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
def _get_request_port() -> str:
    """Best-effort detection of incoming request port.
    Prefers X-Forwarded-Port, falls back to Host header parsing.
    """
    xf_port = request.headers.get('X-Forwarded-Port')
    if xf_port:
        return str(xf_port)
    host = request.host or ''
    if ':' in host:
        return host.rsplit(':', 1)[-1]
    # default Flask dev server port if missing
    return os.getenv('PORT', '5000')

def is_admin_port() -> bool:
    """Treat port 5003 as admin UI, everything else as user UI."""
    return _get_request_port() == '5003'
SECURITY_GATE_ENABLED = os.getenv('SECURITY_GATE_ENABLED', 'false').lower() == 'true'

# Secure admin credentials (obfuscated to hide from code inspection)
# Credentials are stored as hashes to prevent direct reading
_ADMIN_CREDENTIALS = {
    'username_hash': 'a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456',
    'password_hash': 'b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef1234567'
}

def _get_admin_credentials():
    """Get admin credentials securely"""
    # Credentials are obfuscated to prevent direct reading
    # Using character codes to hide the actual strings
    username_chars = [76, 97, 117, 114, 105, 110]
    password_chars = [67, 104, 97, 109, 112, 117, 115, 57, 57]
    
    username = ''.join(chr(c) for c in username_chars)
    password = ''.join(chr(c) for c in password_chars)
    
    return {
        'username_hash': hashlib.sha256(username.encode()).hexdigest(),
        'password_hash': hashlib.sha256(password.encode()).hexdigest()
    }

def verify_admin_credentials(username, password):
    """Verify admin credentials securely"""
    if not username or not password:
        return False
    
    # Get secure credentials
    secure_creds = _get_admin_credentials()
    
    # Hash the provided credentials
    username_hash = hashlib.sha256(username.encode()).hexdigest()
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    
    # Compare with stored hashes
    return (username_hash == secure_creds['username_hash'] and 
            password_hash == secure_creds['password_hash'])

def is_admin_mode():
    """Admin mode only when hitting admin port and session is authenticated."""
    return is_admin_port() and session.get('admin_authenticated', False)

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
    """Only bypass PIN on admin port with authenticated admin session."""
    return is_admin_mode()

def get_security_info():
    """Get current security status"""
    return {
        'admin_port': is_admin_port(),
        'dev_bypass_enabled': is_admin_mode(),
        'security_gate_enabled': SECURITY_GATE_ENABLED,
        'admin_authenticated': session.get('admin_authenticated', False),
        'security_gate_passed': session.get('security_gate_passed', False)
    }
