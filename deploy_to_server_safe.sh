#!/bin/bash

# Safe Deployment Script for Laurin Build
# This script safely deploys changes while preserving database data

set -e  # Exit on any error

echo "🚀 Laurin Build - Safe Deployment Script"
echo "========================================"
echo ""

# Configuration
BACKUP_DIR="./backups"
APP_DIR="."
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_NAME="pre_deployment_${TIMESTAMP}"

echo "📋 Deployment Configuration:"
echo "   Backup Directory: $BACKUP_DIR"
echo "   App Directory: $APP_DIR"
echo "   Backup Name: $BACKUP_NAME"
echo ""

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

echo "🔄 Step 1: Creating comprehensive backup..."
echo "--------------------------------------------"

# 1. Backup current database
echo "📊 Backing up database..."
mysqldump -u root -p laurin_build > "$BACKUP_DIR/${BACKUP_NAME}_database.sql"
echo "   ✅ Database backup created: ${BACKUP_NAME}_database.sql"

# 2. Backup current application files
echo "📁 Backing up current application..."
tar -czf "$BACKUP_DIR/${BACKUP_NAME}_app_files.tar.gz" -C "$APP_DIR" .
echo "   ✅ Application backup created: ${BACKUP_NAME}_app_files.tar.gz"

# 3. Backup specific important files
echo "🔐 Backing up configuration files..."
cp "$APP_DIR/.env" "$BACKUP_DIR/${BACKUP_NAME}_env" 2>/dev/null || echo "   ⚠️  No .env file found"
cp "$APP_DIR/instance" "$BACKUP_DIR/${BACKUP_NAME}_instance" 2>/dev/null || echo "   ⚠️  No instance directory found"

echo ""
echo "🛑 Step 2: Safety checks..."
echo "---------------------------"

# Check if we're in the right directory
if [ ! -f "app/__init__.py" ]; then
    echo "❌ Error: Not in the correct directory. Please run this from the laurin-build root directory."
    exit 1
fi

# Check if Docker is running
if ! docker ps >/dev/null 2>&1; then
    echo "❌ Error: Docker is not running. Please start Docker first."
    exit 1
fi

echo "   ✅ Directory check passed"
echo "   ✅ Docker is running"

echo ""
echo "📤 Step 3: Preparing files for deployment..."
echo "-------------------------------------------"

# Create deployment package
echo "📦 Creating deployment package..."
tar -czf "deployment_${TIMESTAMP}.tar.gz" \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.env' \
    --exclude='instance' \
    --exclude='backups' \
    --exclude='*.log' \
    .

echo "   ✅ Deployment package created: deployment_${TIMESTAMP}.tar.gz"

echo ""
echo "🚀 Step 4: Deployment instructions..."
echo "====================================="
echo ""
echo "To deploy to your server, follow these steps:"
echo ""
echo "1. 📤 Upload the deployment package to your server:"
echo "   scp deployment_${TIMESTAMP}.tar.gz laurin@your-server:/home/laurin/"
echo ""
echo "2. 🔐 SSH into your server:"
echo "   ssh laurin@your-server"
echo ""
echo "3. 🛡️  Run the server-side deployment script:"
echo "   cd /home/laurin"
echo "   chmod +x deploy_server_side.sh"
echo "   ./deploy_server_side.sh deployment_${TIMESTAMP}.tar.gz"
echo ""
echo "4. ✅ Verify deployment:"
echo "   - Check if the application is running"
echo "   - Test the new features (theme switching, cashbook overview, delete functionality)"
echo "   - Verify database data is intact"
echo ""
echo "🆘 Emergency Rollback (if needed):"
echo "================================"
echo "If something goes wrong, you can rollback using:"
echo "   ./rollback_deployment.sh $BACKUP_NAME"
echo ""
echo "📋 Backup Information:"
echo "======================"
echo "   Database backup: $BACKUP_DIR/${BACKUP_NAME}_database.sql"
echo "   App backup: $BACKUP_DIR/${BACKUP_NAME}_app_files.tar.gz"
echo "   Deployment package: deployment_${TIMESTAMP}.tar.gz"
echo ""
echo "✅ Local preparation complete! Ready for server deployment."
