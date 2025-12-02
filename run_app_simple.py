#!/usr/bin/env python
"""
Run Flask application on a single port
Usage: python run_app_simple.py <port>
"""
import os
import sys

# Get the base directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, 'instance')
DB_PATH = os.path.join(INSTANCE_DIR, 'local.db')

# Ensure instance directory exists
os.makedirs(INSTANCE_DIR, exist_ok=True)

# Convert Windows path to SQLite format (use forward slashes)
DB_PATH_SQLITE = DB_PATH.replace('\\', '/')

# Set environment variables with absolute path
os.environ.setdefault('FLASK_ENV', 'development')
os.environ.setdefault('DATABASE_URL', f'sqlite:///{DB_PATH_SQLITE}')
os.environ.setdefault('SECRET_KEY', 'dev-key')
os.environ.setdefault('STRIPE_SUCCESS_BASE_URL', 'http://10.100.5.89:5004')
os.environ.setdefault('STRIPE_CANCEL_BASE_URL', 'http://10.100.5.89:5004')

# Get port from command line or use default
port = int(sys.argv[1]) if len(sys.argv) > 1 else 5003

from app import create_app

app = create_app()
print(f"Starting Flask app on 0.0.0.0:{port}...")
print(f"Access at: http://10.100.5.89:{port} or http://localhost:{port}")
app.run(host='0.0.0.0', port=port, debug=True)

