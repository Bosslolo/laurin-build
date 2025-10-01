#!/bin/bash

# Laurin Build - GitHub Setup Script
echo "🚀 Setting up Laurin Build for GitHub..."

# Initialize Git repository
echo "📁 Initializing Git repository..."
git init

# Add all files
echo "📝 Adding all files to Git..."
git add .

# Create initial commit
echo "💾 Creating initial commit..."
git commit -m "Initial commit: Laurin Build - School Beverage Management System"

echo ""
echo "✅ Git repository initialized!"
echo ""
echo "🌐 Next steps:"
echo "1. Go to https://github.com/new"
echo "2. Create a new repository named 'laurin-build'"
echo "3. Make it PUBLIC"
echo "4. Don't initialize with README (we already have files)"
echo "5. Copy the repository URL"
echo ""
echo "🔗 Then run these commands:"
echo "git remote add origin https://github.com/Bosslolo/laurin-build.git"
echo "git push -u origin main"
echo ""
echo "📚 See GITHUB_SETUP_LAURIN.md for complete instructions!"
