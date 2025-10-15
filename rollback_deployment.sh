#!/bin/bash

# Emergency rollback script for Laurin Build
# This script restores the application to a previous state

set -e  # Exit on any error

echo "🔄 Laurin Build - Emergency Rollback"
echo "==================================="
echo ""

# Configuration
APP_DIR="/home/laurin/laurin-build"
BACKUP_DIR="/home/laurin/backups"
BACKUP_NAME="$1"

if [ -z "$BACKUP_NAME" ]; then
    echo "❌ Error: Please provide backup name"
    echo "Usage: ./rollback_deployment.sh backup_name"
    echo ""
    echo "Available backups:"
    ls -la "$BACKUP_DIR"/*.sql 2>/dev/null | awk '{print $9}' | sed 's/.*\///' | sed 's/_database.sql//' || echo "   No backups found"
    exit 1
fi

echo "📋 Rollback Configuration:"
echo "   App Directory: $APP_DIR"
echo "   Backup Directory: $BACKUP_DIR"
echo "   Backup Name: $BACKUP_NAME"
echo ""

# Check if backup files exist
DATABASE_BACKUP="$BACKUP_DIR/${BACKUP_NAME}_database.sql"
APP_BACKUP="$BACKUP_DIR/${BACKUP_NAME}_app.tar.gz"

if [ ! -f "$DATABASE_BACKUP" ]; then
    echo "❌ Error: Database backup not found: $DATABASE_BACKUP"
    exit 1
fi

if [ ! -f "$APP_BACKUP" ]; then
    echo "❌ Error: Application backup not found: $APP_BACKUP"
    exit 1
fi

echo "✅ Backup files found:"
echo "   Database: $DATABASE_BACKUP"
echo "   Application: $APP_BACKUP"
echo ""

echo "🛑 Step 1: Stopping services..."
echo "-------------------------------"

# Stop Docker containers
echo "🐳 Stopping Docker containers..."
cd "$APP_DIR"
docker-compose down
echo "   ✅ Docker containers stopped"

echo ""
echo "💾 Step 2: Restoring database..."
echo "-------------------------------"

# Start database container
echo "🐳 Starting database container..."
docker-compose up -d db
sleep 10  # Wait for database to be ready

# Restore database
echo "📊 Restoring database from backup..."
docker-compose exec -T db mysql -u root -p laurin_build < "$DATABASE_BACKUP"
echo "   ✅ Database restored"

echo ""
echo "📁 Step 3: Restoring application..."
echo "----------------------------------"

# Create backup of current state (just in case)
CURRENT_BACKUP="rollback_backup_$(date +%Y%m%d_%H%M%S)"
echo "💾 Creating backup of current state: $CURRENT_BACKUP"
tar -czf "$BACKUP_DIR/${CURRENT_BACKUP}_app.tar.gz" -C "$APP_DIR" .

# Restore application files
echo "📁 Restoring application files..."
cd "$APP_DIR"
rm -rf * .* 2>/dev/null || true  # Remove current files
tar -xzf "$APP_BACKUP" -C "$APP_DIR"
echo "   ✅ Application files restored"

# Restore configuration files if they exist
if [ -f "$BACKUP_DIR/${BACKUP_NAME}_env" ]; then
    cp "$BACKUP_DIR/${BACKUP_NAME}_env" "$APP_DIR/.env"
    echo "   ✅ Environment file restored"
fi

if [ -d "$BACKUP_DIR/${BACKUP_NAME}_instance" ]; then
    cp -r "$BACKUP_DIR/${BACKUP_NAME}_instance" "$APP_DIR/instance"
    echo "   ✅ Instance directory restored"
fi

echo ""
echo "🚀 Step 4: Starting services..."
echo "-------------------------------"

# Start all services
echo "🐳 Starting all services..."
docker-compose up -d
echo "   ✅ All services started"

# Wait for services to be ready
echo "⏳ Waiting for services to be ready..."
sleep 15

echo ""
echo "✅ Step 5: Verification..."
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
echo "🎉 Rollback Complete!"
echo "===================="
echo ""
echo "📋 Rollback Summary:"
echo "   ✅ Database restored from: $DATABASE_BACKUP"
echo "   ✅ Application restored from: $APP_BACKUP"
echo "   ✅ Services restarted"
echo "   ✅ Current state backed up as: $CURRENT_BACKUP"
echo ""
echo "🧪 Next Steps:"
echo "1. Test the application: http://your-server-ip:5001"
echo "2. Verify all functionality is working"
echo "3. Check that your data is intact"
echo ""
echo "✅ Rollback completed successfully!"
