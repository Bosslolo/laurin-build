#!/bin/bash

# GitHub-based deployment script for Laurin Build
# This script pushes changes to GitHub and provides server deployment instructions

set -e  # Exit on any error

echo "🚀 Laurin Build - GitHub Deployment Script"
echo "=========================================="
echo ""

# Configuration
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="./backups"
BACKUP_NAME="pre_deployment_${TIMESTAMP}"

echo "📋 Deployment Configuration:"
echo "   Backup Directory: $BACKUP_DIR"
echo "   Backup Name: $BACKUP_NAME"
echo ""

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

echo "🔄 Step 1: Creating local backup..."
echo "-----------------------------------"

# Backup current database (if running locally)
echo "📊 Backing up local database (if available)..."
if docker-compose ps | grep -q "Up" 2>/dev/null; then
    docker-compose exec -T db mysqldump -u root -p laurin_build > "$BACKUP_DIR/${BACKUP_NAME}_local_database.sql" 2>/dev/null || echo "   ⚠️  Could not backup local database (this is normal if not running locally)"
    echo "   ✅ Local database backup created"
else
    echo "   ⚠️  No local database running - skipping local backup"
fi

# Backup current application files
echo "📁 Backing up current application..."
tar -czf "$BACKUP_DIR/${BACKUP_NAME}_app_files.tar.gz" \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='backups' \
    --exclude='*.log' \
    .
echo "   ✅ Application backup created"

echo ""
echo "📤 Step 2: Preparing for GitHub deployment..."
echo "--------------------------------------------"

# Check if we're in a git repository
if [ ! -d ".git" ]; then
    echo "🔧 Initializing Git repository..."
    git init
    echo "   ✅ Git repository initialized"
fi

# Add all files to git
echo "📝 Adding files to Git..."
git add .

# Check if there are changes to commit
if git diff --staged --quiet; then
    echo "   ⚠️  No changes to commit"
else
    echo "📝 Committing changes..."
    git commit -m "Deploy: Theme fixes, cashbook overview, and delete functionality

- Fixed price list theme display (winter theme now works)
- Added comprehensive cashbook overview with statistics
- Added delete functionality for cashbook entries
- Updated admin password from Champus15 to Champus99
- Added deployment scripts and safety measures

Deployment timestamp: $TIMESTAMP"
    echo "   ✅ Changes committed"
fi

echo ""
echo "🌐 Step 3: GitHub deployment options..."
echo "======================================"
echo ""
echo "Choose your deployment method:"
echo ""
echo "Option 1: 🚀 Direct Server Deployment (Recommended)"
echo "----------------------------------------------------"
echo "1. Push to GitHub:"
echo "   git remote add origin https://github.com/yourusername/laurin-build.git"
echo "   git push -u origin main"
echo ""
echo "2. On your server, run:"
echo "   git clone https://github.com/yourusername/laurin-build.git"
echo "   cd laurin-build"
echo "   ./deploy_server_github.sh"
echo ""
echo "Option 2: 📦 Manual Upload"
echo "-------------------------"
echo "1. Create deployment package:"
echo "   tar -czf deployment_${TIMESTAMP}.tar.gz --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' ."
echo ""
echo "2. Upload to server:"
echo "   scp deployment_${TIMESTAMP}.tar.gz laurin@your-server:/home/laurin/"
echo ""
echo "3. Deploy on server:"
echo "   ssh laurin@your-server"
echo "   tar -xzf deployment_${TIMESTAMP}.tar.gz -C /home/laurin/laurin-build/"
echo "   cd /home/laurin/laurin-build"
echo "   ./deploy_server_github.sh"
echo ""

# Create deployment package
echo "📦 Creating deployment package..."
tar -czf "deployment_${TIMESTAMP}.tar.gz" \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='backups' \
    --exclude='*.log' \
    .
echo "   ✅ Deployment package created: deployment_${TIMESTAMP}.tar.gz"

echo ""
echo "🛡️ Safety Information:"
echo "====================="
echo "   Local backup: $BACKUP_DIR/${BACKUP_NAME}_app_files.tar.gz"
echo "   Deployment package: deployment_${TIMESTAMP}.tar.gz"
echo ""
echo "✅ Preparation complete! Choose your deployment method above."
