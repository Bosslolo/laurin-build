#!/bin/bash

echo "🔧 Fixing GitHub Repository Rule Violations"
echo "==========================================="
echo ""

echo "📋 Common causes and solutions:"
echo ""

echo "1️⃣ Branch Protection Rules:"
echo "   • Go to: https://github.com/Bosslolo/laurin-build/settings/branches"
echo "   • Delete any branch protection rules"
echo "   • Or disable 'Require pull request reviews'"
echo ""

echo "2️⃣ Content Policies:"
echo "   • Go to: https://github.com/Bosslolo/laurin-build/settings/rules"
echo "   • Delete any repository rules"
echo "   • Or disable content policies"
echo ""

echo "3️⃣ Force Push (if needed):"
echo "   git push --force-with-lease origin main"
echo ""

echo "4️⃣ Alternative: Push to different branch:"
echo "   git checkout -b laurin-build-main"
echo "   git push -u origin laurin-build-main"
echo ""

echo "5️⃣ Check repository settings:"
echo "   • Go to: https://github.com/Bosslolo/laurin-build/settings"
echo "   • Check 'Rules' section"
echo "   • Remove any blocking rules"
echo ""

echo "🔍 Let's check what's blocking the push..."
echo ""

# Check current branch and status
echo "Current branch:"
git branch

echo ""
echo "Git status:"
git status

echo ""
echo "Remote info:"
git remote -v
