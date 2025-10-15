#!/usr/bin/env python3
"""
Generate Admin Token for Laurin Build
This script generates a secure admin token for backdoor access
"""

import hashlib
import secrets
import os

def generate_admin_token():
    """Generate a secure admin token"""
    # Generate a random token
    token = secrets.token_urlsafe(32)
    
    # Create hash for verification
    secret_key = os.getenv('ADMIN_SECRET_KEY', 'laurin-build-admin-2024')
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expected_hash = hashlib.sha256(secret_key.encode()).hexdigest()
    
    print("🔐 Laurin Build - Admin Token Generator")
    print("=" * 50)
    print()
    print("📋 Admin Token Information:")
    print(f"   Token: {token}")
    print(f"   Secret Key: {secret_key}")
    print(f"   Token Hash: {token_hash}")
    print(f"   Expected Hash: {expected_hash}")
    print()
    print("🔑 How to use:")
    print("   1. Copy the token above")
    print("   2. Go to: http://localhost:5001/admin/login")
    print("   3. Enter the token to gain admin access")
    print()
    print("⚠️  Security Notes:")
    print("   • Keep this token secure")
    print("   • Don't share with unauthorized users")
    print("   • Change the secret key in production")
    print()
    print("🛡️  Environment Variables:")
    print(f"   ADMIN_SECRET_KEY={secret_key}")
    print()
    
    return token

if __name__ == "__main__":
    generate_admin_token()
