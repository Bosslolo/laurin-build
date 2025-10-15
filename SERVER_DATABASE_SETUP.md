# 🗄️ Server Database Setup Guide

This guide will help you connect your local development environment to your server's database.

## 🔍 Current Situation

- **Local**: You have the new code with all the latest features
- **Server**: Has the database with all your users, consumptions, and cashbook data
- **Goal**: Connect your local code to the server's database

## 🚀 Option 1: Connect Local Code to Server Database (Recommended for Development)

### Step 1: Get Server Database Credentials
```bash
# SSH into your server
ssh laurin@your-server

# Check your current database configuration
cd /home/laurin/laurin-build
cat docker-compose.yml | grep -A 10 "db:"
```

### Step 2: Update Local Configuration
Create a `.env` file in your local project:

```bash
# Create .env file
cat > .env << 'EOF'
# Database Configuration (Server Database)
DB_HOST=your-server-ip
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your-database-password
DB_NAME=laurin_build

# Flask Configuration
FLASK_ENV=development
FLASK_APP=app/__init__.py
SECRET_KEY=your-secret-key-here

# Admin Configuration
ADMIN_SECRET_KEY=laurin-build-admin-2024
SECURITY_GATE_ENABLED=false
EOF
```

### Step 3: Update Local Docker Configuration
Modify your `docker-compose.laptop.yml`:

```yaml
version: '3.8'
services:
  web:
    build: .
    ports:
      - "5001:5001"
    environment:
      - DB_HOST=your-server-ip
      - DB_PORT=3306
      - DB_USER=root
      - DB_PASSWORD=your-database-password
      - DB_NAME=laurin_build
    depends_on:
      - redis
    volumes:
      - ./app:/app/app
    networks:
      - laurin-network

  redis:
    image: redis:alpine
    networks:
      - laurin-network

networks:
  laurin-network:
    driver: bridge
```

### Step 4: Test Connection
```bash
# Start your local services
docker-compose -f docker-compose.laptop.yml up -d

# Test database connection
docker-compose -f docker-compose.laptop.yml exec web python -c "
from app import create_app, db
app = create_app()
with app.app_context():
    from app.models import users
    print('Users count:', users.query.count())
    print('Connection successful!')
"
```

## 🚀 Option 2: Deploy to Server (Production Approach)

### Step 1: Push to GitHub
```bash
# Push your clean repository
git push origin main
```

### Step 2: Deploy on Server
```bash
# SSH into your server
ssh laurin@your-server

# Clone/update the repository
cd /home/laurin
git clone https://github.com/Bosslolo/laurin-build.git
# OR if already exists:
# cd laurin-build && git pull origin main

# Run the deployment script
cd laurin-build
chmod +x deploy_server_github.sh
./deploy_server_github.sh
```

## 🔧 Database Connection Troubleshooting

### Check Server Database Status
```bash
# On your server
docker-compose ps
docker-compose logs db
```

### Test Database Connection
```bash
# On your server
docker-compose exec db mysql -u root -p -e "USE laurin_build; SHOW TABLES;"
```

### Common Issues and Solutions

#### Issue 1: Connection Refused
```bash
# Check if database is running
docker-compose ps | grep db

# Start database if not running
docker-compose up -d db
```

#### Issue 2: Authentication Failed
```bash
# Check database password in docker-compose.yml
cat docker-compose.yml | grep MYSQL_ROOT_PASSWORD
```

#### Issue 3: Database Not Found
```bash
# Create database if it doesn't exist
docker-compose exec db mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS laurin_build;"
```

## 📊 Verify Your Data

### Check Database Contents
```bash
# On your server
docker-compose exec db mysql -u root -p laurin_build -e "
SELECT 'Users' as table_name, COUNT(*) as count FROM users
UNION ALL
SELECT 'Consumptions', COUNT(*) FROM consumptions
UNION ALL
SELECT 'Cashbook Entries', COUNT(*) FROM cashbook_entries;
"
```

### Test Application Features
1. **Admin Login**: Use password "Champus99"
2. **Theme Switching**: Test winter theme on price list
3. **Cashbook Overview**: Click title → Cashbook Overview
4. **Cashbook Delete**: Test delete functionality

## 🆘 Emergency Recovery

If something goes wrong:

```bash
# On your server
cd /home/laurin/laurin-build
./rollback_deployment.sh backup_name
```

## ✅ Success Checklist

- [ ] Database connection works
- [ ] All existing users are visible
- [ ] All consumptions data is intact
- [ ] All cashbook entries are preserved
- [ ] New features work (theme, overview, delete)
- [ ] Admin login works with new password

## 📞 Next Steps

1. **Choose your approach** (local connection vs server deployment)
2. **Test the connection** with the verification steps
3. **Deploy when ready** using the deployment scripts
4. **Verify all data** is intact and features work

Your data is safe - the deployment scripts include multiple backup layers!
