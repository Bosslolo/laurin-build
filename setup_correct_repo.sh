#!/bin/bash

echo "🔧 Setting up correct GitHub repository for Laurin Build"
echo "========================================================"
echo ""

# Remove any existing remotes
git remote remove origin 2>/dev/null || true
git remote remove upstream 2>/dev/null || true

echo "📋 Next steps:"
echo ""
echo "1️⃣ Create NEW repository on GitHub:"
echo "   • Go to: https://github.com/new"
echo "   • Repository name: laurin-build"
echo "   • Description: School Beverage Management System - Laurin's Build"
echo "   • Make it PUBLIC"
echo "   • Don't initialize with README"
echo "   • Click 'Create repository'"
echo ""
echo "2️⃣ After creating the repository, run:"
echo "   git remote add origin https://github.com/Bosslolo/laurin-build.git"
echo "   git push -u origin main"
echo ""
echo "3️⃣ For authentication, you'll need a Personal Access Token:"
echo "   • Go to: https://github.com/settings/tokens"
echo "   • Generate new token (classic)"
echo "   • Scopes: repo, workflow"
echo "   • Use token as password when prompted"
echo ""
echo "✅ This will create a completely separate repository for Laurin Build!"
