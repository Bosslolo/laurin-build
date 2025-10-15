# 🔐 Laurin Build - Security Guide

## 🛡️ **Complete Security System**

This guide explains the comprehensive security features implemented in Laurin Build.

## 🚪 **Security Features Overview**

### **1. Security Gate**
- **Purpose**: Prevents unauthorized access to the system
- **Access Codes**: `CSH2024`, `LAURIN`, `ADMIN`, `ACCESS`
- **URL**: `/security-gate`
- **Bypass**: Admin authentication automatically bypasses

### **2. Admin Backdoor**
- **Purpose**: Allows admin to access any user account without PIN
- **Authentication**: Requires admin token
- **URL**: `/admin/login` → `/admin/backdoor`
- **Features**: 
  - Access any user without PIN verification
  - Full system access
  - Session-based authentication

### **3. Development Bypass**
- **Purpose**: Skip PIN verification in development environment
- **Trigger**: `FLASK_ENV=development` OR `FLASK_APP_MODE=admin`
- **Scope**: All PIN-protected routes

## 🔑 **Admin Token System**

### **Generate Admin Token**
```bash
python3 generate_admin_token.py
```

### **Default Admin Token**
- **Secret Key**: `laurin-build-admin-2024`
- **Token**: Generated dynamically
- **Security**: SHA-256 hashed verification

### **Environment Variables**
```bash
# Admin authentication
ADMIN_SECRET_KEY=laurin-build-admin-2024

# Security gate
SECURITY_GATE_ENABLED=true

# Development bypass
FLASK_ENV=development
FLASK_APP_MODE=admin
```

## 🚀 **How to Use**

### **Step 1: Access Security Gate**
1. Visit: `http://localhost:5001`
2. Enter access code: `CSH2024`, `LAURIN`, `ADMIN`, or `ACCESS`
3. Click "Access System"

### **Step 2: Admin Backdoor Access**
1. Visit: `http://localhost:5001/admin/login`
2. Generate admin token: `python3 generate_admin_token.py`
3. Enter the generated token
4. Click "Authenticate"
5. Access "Admin Backdoor" from main interface
6. Select any user to access without PIN

### **Step 3: Development Bypass**
1. Set environment variables:
   ```bash
   export FLASK_ENV=development
   export FLASK_APP_MODE=admin
   ```
2. Start the application
3. PIN verification is automatically bypassed

## 🔒 **Security Levels**

### **Level 1: Public Access**
- **Security Gate**: Basic access code required
- **Access**: Main system interface
- **Restrictions**: Standard user functions only

### **Level 2: Admin Access**
- **Admin Token**: Secure token authentication
- **Access**: Full system control
- **Features**: 
  - Admin backdoor
  - User management
  - System configuration
  - PIN bypass for any user

### **Level 3: Development Access**
- **Environment**: Development mode
- **Access**: Complete system bypass
- **Features**: 
  - No PIN verification
  - Full admin privileges
  - Debug mode enabled

## 🛠️ **Implementation Details**

### **Security Decorators**
```python
@require_security_gate      # Requires security gate authentication
@require_admin_auth         # Requires admin authentication
@bypass_pin_for_dev()       # Checks if PIN should be bypassed
```

### **Session Management**
```python
session['security_gate_passed'] = True    # Security gate passed
session['admin_authenticated'] = True     # Admin authenticated
session['admin_bypass'] = True           # Admin bypass active
session['bypass_user_id'] = user_id      # User being bypassed
```

### **PIN Bypass Logic**
```python
if session.get('admin_bypass', False):
    # Admin bypass - no PIN required
    pass
elif not bypass_pin_for_dev():
    # Check if PIN is required
    if user.pin_hash:
        # Redirect to PIN verification
        return redirect(url_for('routes.index') + f'?user_id={user_id}&require_pin=true')
```

## 🔧 **Configuration**

### **Production Security**
```bash
# Disable development bypass
FLASK_ENV=production
FLASK_APP_MODE=user

# Enable security gate
SECURITY_GATE_ENABLED=true

# Set secure admin key
ADMIN_SECRET_KEY=your-secure-secret-key-here
```

### **Development Security**
```bash
# Enable development bypass
FLASK_ENV=development
FLASK_APP_MODE=admin

# Disable security gate (optional)
SECURITY_GATE_ENABLED=false
```

## 🚨 **Security Best Practices**

### **1. Token Management**
- ✅ Generate unique admin tokens
- ✅ Rotate tokens regularly
- ✅ Store tokens securely
- ❌ Don't hardcode tokens in code

### **2. Environment Security**
- ✅ Use environment variables for secrets
- ✅ Different keys for production/development
- ✅ Secure key storage
- ❌ Don't commit secrets to Git

### **3. Access Control**
- ✅ Limit admin access to authorized personnel
- ✅ Monitor admin activities
- ✅ Log security events
- ❌ Don't share admin credentials

## 🔍 **Troubleshooting**

### **Security Gate Not Working**
```bash
# Check environment variables
echo $SECURITY_GATE_ENABLED

# Check session status
# Visit: /admin/security-status
```

### **Admin Token Not Working**
```bash
# Generate new token
python3 generate_admin_token.py

# Check secret key
echo $ADMIN_SECRET_KEY
```

### **PIN Bypass Not Working**
```bash
# Check development mode
echo $FLASK_ENV
echo $FLASK_APP_MODE

# Check admin authentication
# Visit: /admin/security-status
```

## 📱 **Access URLs**

### **Main System**
- **Security Gate**: `http://localhost:5001/security-gate`
- **Main Interface**: `http://localhost:5001`

### **Admin Access**
- **Admin Login**: `http://localhost:5001/admin/login`
- **Admin Backdoor**: `http://localhost:5001/admin/backdoor`
- **Security Status**: `http://localhost:5001/admin/security-status`

### **User Interface**
- **User Interface**: `http://localhost:5002`
- **Database Admin**: `http://localhost:8080`

## 🎯 **Quick Start**

1. **Start the system**: `./start_laptop.sh`
2. **Access security gate**: Enter code `CSH2024`
3. **Generate admin token**: `python3 generate_admin_token.py`
4. **Admin access**: Use generated token at `/admin/login`
5. **Backdoor access**: Click "Admin Backdoor" in admin interface

**Your secure Laurin Build system is ready!** 🚀🔐
