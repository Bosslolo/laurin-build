# Laurin Build - GitHub Setup Guide

## 🚀 Complete GitHub Setup for Laurin Build

This guide will help you set up your personalized "Laurin Build" project on GitHub and deploy it to your server.

## 📋 Prerequisites

- GitHub account: [@Bosslolo](https://github.com/Bosslolo)
- Git installed on your laptop
- Access to your server (IP: 100.115.249.53)

## 🔧 Step 1: Initialize Git Repository

```bash
# Navigate to your project
cd "/Users/laurin.domenig/Library/CloudStorage/OneDrive-ChristlicheSchuleimHegau/Visual Studio/schuelerfirma_privat"

# Initialize Git repository
git init

# Add all files
git add .

# Create initial commit
git commit -m "Initial commit: Laurin Build - School Beverage Management System"
```

## 🌐 Step 2: Create GitHub Repository

1. **Go to GitHub**: Visit [github.com](https://github.com) and sign in as @Bosslolo
2. **Create New Repository**:
   - Click the "+" button → "New repository"
   - Repository name: `laurin-build`
   - Description: `School Beverage Management System - Laurin's Build`
   - Make it **Public** (so you can access it from your server)
   - **Don't** initialize with README (we already have files)
3. **Copy the repository URL** (you'll need it in the next step)

## 🔗 Step 3: Connect Local Repository to GitHub

```bash
# Add GitHub as remote origin (replace with your actual GitHub URL)
git remote add origin https://github.com/Bosslolo/laurin-build.git

# Push to GitHub
git push -u origin main
```

## 🖥️ Step 4: Deploy to Your Server

### Option A: Direct Server Setup (Recommended)

1. **SSH into your server**:
   ```bash
   ssh your-username@100.115.249.53
   ```

2. **Clone your repository**:
   ```bash
   # Navigate to your desired directory
   cd /path/to/your/projects
   
   # Clone your repository
   git clone https://github.com/Bosslolo/laurin-build.git
   cd laurin-build
   ```

3. **Set up the server environment**:
   ```bash
   # Make scripts executable
   chmod +x *.sh
   
   # Start the application
   ./start_laptop.sh
   ```

### Option B: Using USB Transfer

1. **On your laptop**:
   ```bash
   # Create a deployment package
   tar -czf laurin-build.tar.gz .
   ```

2. **Copy to USB and transfer to server**

3. **On your server**:
   ```bash
   # Extract the files
   tar -xzf laurin-build.tar.gz
   cd laurin-build
   
   # Start the application
   ./start_laptop.sh
   ```

## 🔄 Step 5: Future Updates

### Making Changes and Pushing to GitHub:

```bash
# Make your changes to the code
# ... edit files ...

# Add changes to Git
git add .

# Commit changes
git commit -m "Description of your changes"

# Push to GitHub
git push origin main
```

### Updating Your Server:

```bash
# SSH into your server
ssh your-username@100.115.249.53

# Navigate to your project
cd /path/to/laurin-build

# Pull latest changes
git pull origin main

# Restart the application
docker-compose -f docker-compose.laptop.yml down
docker-compose -f docker-compose.laptop.yml up -d
```

## 📱 Access URLs

Once deployed, your application will be available at:

- **Admin Interface**: `http://100.115.249.53:5001`
- **User Interface**: `http://100.115.249.53:5002`
- **Database Admin**: `http://100.115.249.53:8080`

## 🛠️ Development Workflow

### Local Development:
```bash
# Start development environment
./start_laptop.sh

# Access locally:
# Admin: http://localhost:5001
# User: http://localhost:5002
# Database: http://localhost:8080
```

### Making Changes:
1. Edit files on your laptop
2. Test locally using `./start_laptop.sh`
3. Commit and push to GitHub
4. Pull changes on server
5. Restart server application

## 🔧 Troubleshooting

### If GitHub push fails:
```bash
# Check remote URL
git remote -v

# If needed, update remote URL
git remote set-url origin https://github.com/Bosslolo/laurin-build.git
```

### If server deployment fails:
```bash
# Check Docker status
docker ps

# Check logs
docker-compose -f docker-compose.laptop.yml logs

# Restart everything
docker-compose -f docker-compose.laptop.yml down -v
docker-compose -f docker-compose.laptop.yml up -d
```

## 📚 Project Structure

```
laurin-build/
├── app/                    # Flask application
├── docker-compose.laptop.yml  # Docker configuration
├── Dockerfile.laptop       # Docker build file
├── start_laptop.sh         # Start script
├── stop_laptop.sh          # Stop script
├── fix_all_issues.sh       # Database fix script
└── README_LAPTOP.md        # Documentation
```

## 🎯 Key Features

- ✅ **Dual Interface**: Admin and User views
- ✅ **Database Management**: PostgreSQL with Adminer
- ✅ **Character Encoding**: Fixed German umlauts
- ✅ **Backup System**: Easy database import/export
- ✅ **Docker Deployment**: Containerized for easy deployment
- ✅ **GitHub Integration**: Version control and collaboration

## 🚀 Next Steps

1. **Set up the GitHub repository** following Step 2
2. **Push your code** using Step 3
3. **Deploy to your server** using Step 4
4. **Test everything** works correctly
5. **Start using your personalized Laurin Build!**

---

**Your personalized school beverage management system is ready to go!** 🎉
