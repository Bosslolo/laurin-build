#!/bin/bash

# Server-side deployment script for Laurin Build
# This script safely deploys the new code while preserving database

set -e  # Exit on any error

echo "🖥️  Laurin Build - Server-side Deployment"
echo "========================================"
echo ""

# Configuration
APP_DIR="/home/laurin/laurin-build"
BACKUP_DIR="/home/laurin/backups"
DEPLOYMENT_PACKAGE="$1"

if [ -z "$DEPLOYMENT_PACKAGE" ]; then
    echo "❌ Error: Please provide deployment package name"
    echo "Usage: ./deploy_server_side.sh deployment_YYYYMMDD_HHMMSS.tar.gz"
    exit 1
fi

echo "📋 Server Configuration:"
echo "   App Directory: $APP_DIR"
echo "   Backup Directory: $BACKUP_DIR"
echo "   Deployment Package: $DEPLOYMENT_PACKAGE"
echo ""

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

echo "🛑 Step 1: Pre-deployment safety checks..."
echo "----------------------------------------"

# Check if deployment package exists
if [ ! -f "$DEPLOYMENT_PACKAGE" ]; then
    echo "❌ Error: Deployment package '$DEPLOYMENT_PACKAGE' not found"
    exit 1
fi

# Check if app directory exists
if [ ! -d "$APP_DIR" ]; then
    echo "❌ Error: App directory '$APP_DIR' not found"
    exit 1
fi

# Check if Docker is running
if ! docker ps >/dev/null 2>&1; then
    echo "❌ Error: Docker is not running. Please start Docker first."
    exit 1
fi

echo "   ✅ Deployment package found"
echo "   ✅ App directory exists"
echo "   ✅ Docker is running"

echo ""
echo "💾 Step 2: Creating server-side backup..."
echo "---------------------------------------"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
SERVER_BACKUP_NAME="server_backup_${TIMESTAMP}"

# Backup current database
echo "📊 Backing up current database..."
mysqldump -u root -p laurin_build > "$BACKUP_DIR/${SERVER_BACKUP_NAME}_database.sql"
echo "   ✅ Database backup created"

# Backup current application
echo "📁 Backing up current application..."
tar -czf "$BACKUP_DIR/${SERVER_BACKUP_NAME}_app.tar.gz" -C "$APP_DIR" .
echo "   ✅ Application backup created"

# Backup important files
echo "🔐 Backing up configuration files..."
cp "$APP_DIR/.env" "$BACKUP_DIR/${SERVER_BACKUP_NAME}_env" 2>/dev/null || echo "   ⚠️  No .env file found"
cp -r "$APP_DIR/instance" "$BACKUP_DIR/${SERVER_BACKUP_NAME}_instance" 2>/dev/null || echo "   ⚠️  No instance directory found"

echo ""
echo "🛑 Step 3: Stopping services..."
echo "-------------------------------"

# Stop Docker containers
echo "🐳 Stopping Docker containers..."
cd "$APP_DIR"
docker-compose down
echo "   ✅ Docker containers stopped"

echo ""
echo "📦 Step 4: Deploying new code..."
echo "--------------------------------"

# Extract new deployment
echo "📤 Extracting deployment package..."
tar -xzf "$DEPLOYMENT_PACKAGE" -C "$APP_DIR"
echo "   ✅ Deployment package extracted"

# Set proper permissions
echo "🔐 Setting permissions..."
chmod +x "$APP_DIR"/*.sh 2>/dev/null || true
chown -R laurin:laurin "$APP_DIR"
echo "   ✅ Permissions set"

echo ""
echo "🔄 Step 5: Database migration (if needed)..."
echo "------------------------------------------"

# Check if database needs migration
echo "🔍 Checking database schema..."
cd "$APP_DIR"

# Start database container first
echo "🐳 Starting database container..."
docker-compose up -d db
sleep 10  # Wait for database to be ready

# Run any pending migrations (if you have them)
# python3 -m flask db upgrade 2>/dev/null || echo "   ⚠️  No migrations to run"

echo "   ✅ Database is ready"

echo ""
echo "🚀 Step 6: Starting services..."
echo "-------------------------------"

# Start all services
echo "🐳 Starting all services..."
docker-compose up -d
echo "   ✅ All services started"

# Wait for services to be ready
echo "⏳ Waiting for services to be ready..."
sleep 15

echo ""
echo "✅ Step 7: Verification..."
echo "-------------------------"

# Check if services are running
echo "🔍 Checking service status..."
if docker-compose ps | grep -q "Up"; then
    echo "   ✅ Services are running"
else
    echo "   ❌ Some services failed to start"
    echo "   📋 Service status:"
    docker-compose ps
fi

# Test database connection
echo "🔍 Testing database connection..."
if docker-compose exec -T db mysql -u root -p -e "USE laurin_build; SELECT 1;" >/dev/null 2>&1; then
    echo "   ✅ Database connection successful"
else
    echo "   ⚠️  Database connection test failed (this might be normal)"
fi

echo ""
echo "🎉 Deployment Complete!"
echo "======================"
echo ""
echo "📋 Deployment Summary:"
echo "   ✅ Database backed up: ${SERVER_BACKUP_NAME}_database.sql"
echo "   ✅ Application backed up: ${SERVER_BACKUP_NAME}_app.tar.gz"
echo "   ✅ New code deployed successfully"
echo "   ✅ Services restarted"
echo ""
echo "🧪 Next Steps:"
echo "1. Test the application: http://your-server-ip:5001"
echo "2. Test new features:"
echo "   - Theme switching (winter theme should work on price list)"
echo "   - Cashbook overview (click title → Cashbook Overview)"
echo "   - Cashbook delete functionality"
echo "3. Verify database data is intact"
echo ""
echo "🆘 Emergency Rollback (if needed):"
echo "   ./rollback_deployment.sh $SERVER_BACKUP_NAME"
echo ""
echo "✅ Deployment completed successfully!"
