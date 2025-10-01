#!/bin/bash

echo "🔐 Fixing GitHub Secret Detection"
echo "================================="
echo ""

echo "GitHub detected Azure Function Keys in your code."
echo "These are likely in your database backup files."
echo ""

echo "📋 Solutions:"
echo ""

echo "1️⃣ Remove secrets from Git history:"
echo "   git filter-branch --force --index-filter 'git rm --cached --ignore-unmatch *.sql' HEAD"
echo ""

echo "2️⃣ Create .gitignore to exclude sensitive files:"
echo "   echo '*.sql' >> .gitignore"
echo "   echo '*.db' >> .gitignore"
echo "   echo 'backups/' >> .gitignore"
echo ""

echo "3️⃣ Alternative: Push without sensitive files:"
echo "   git rm --cached *.sql"
echo "   git commit -m 'Remove sensitive files'"
echo "   git push origin main"
echo ""

echo "4️⃣ Allow the secrets (if they're safe):"
echo "   Visit: https://github.com/Bosslolo/laurin-build/security/secret-scanning"
echo "   Click 'Allow secret' for each detected secret"
echo ""

echo "🔍 Let's check what files contain secrets..."
echo ""

# Check for SQL files
if [ -f "*.sql" ]; then
    echo "Found SQL files that might contain secrets:"
    ls -la *.sql
else
    echo "No SQL files found in current directory"
fi

# Check for database files
if [ -f "*.db" ]; then
    echo "Found database files:"
    ls -la *.db
else
    echo "No database files found in current directory"
fi

echo ""
echo "💡 Recommendation: Remove sensitive files and use .gitignore"
