# 🚀 Laurin Build - Safe Deployment Guide

This guide will help you safely deploy your changes to the server while preserving all your existing database data.

## 📋 What We're Deploying

### New Features Added:
- ✅ **Theme System Fix**: Price list now correctly shows the selected theme (winter theme)
- ✅ **Cashbook Overview**: New comprehensive overview with statistics for both companies
- ✅ **Cashbook Delete**: Delete individual cashbook entries with confirmation
- ✅ **Admin Password Update**: Changed from "Champus15" to "Champus99"

## 🛡️ Safety Measures

### Multiple Backup Layers:
1. **Database Backup**: Complete MySQL dump of your current data
2. **Application Backup**: Full backup of current server files
3. **Configuration Backup**: Environment files and instance data
4. **Rollback Capability**: Emergency rollback script if anything goes wrong

## 🚀 Step-by-Step Deployment

### Step 1: Prepare on Your Mac
```bash
# Run the preparation script
./deploy_to_server_safe.sh
```

This will:
- Create a complete backup of your current database
- Create a deployment package with all your changes
- Provide you with exact commands to run

### Step 2: Upload to Server
```bash
# Upload the deployment package (replace with actual filename)
scp deployment_YYYYMMDD_HHMMSS.tar.gz laurin@your-server:/home/laurin/
```

### Step 3: Deploy on Server
```bash
# SSH into your server
ssh laurin@your-server

# Run the server-side deployment
cd /home/laurin
chmod +x deploy_server_side.sh
./deploy_server_side.sh deployment_YYYYMMDD_HHMMSS.tar.gz
```

## 🔍 What Happens During Deployment

### Server-side Process:
1. **Pre-deployment Backup**: Creates additional server-side backups
2. **Service Stop**: Safely stops all Docker containers
3. **Database Backup**: Backs up current database state
4. **Code Deployment**: Extracts new code while preserving database
5. **Service Restart**: Starts all services with new code
6. **Verification**: Checks that everything is working

### Data Preservation:
- ✅ **Database**: Your existing users, consumptions, cashbook entries are preserved
- ✅ **Configuration**: Environment settings and instance data maintained
- ✅ **File Structure**: Only application code is updated, data remains intact

## 🧪 Testing After Deployment

### 1. Basic Functionality
- [ ] Application loads at `http://your-server:5001`
- [ ] Admin login works with new password "Champus99"
- [ ] All existing users can still log in
- [ ] Database data is intact

### 2. New Features
- [ ] **Theme Switching**: 
  - Go to admin → Change Theme → Select "Winter"
  - Visit Price List page → Should show winter theme (blue colors)
- [ ] **Cashbook Overview**:
  - Click on title → "Cashbook Overview" → Should show statistics
- [ ] **Cashbook Delete**:
  - Go to cashbook management → Try deleting an entry → Should work with confirmation

## 🆘 Emergency Rollback

If something goes wrong, you can instantly rollback:

```bash
# On your server
./rollback_deployment.sh backup_name
```

This will:
- Restore your exact previous database state
- Restore your exact previous application code
- Restart services with the old version

## 📊 Backup Information

### Local Backups (on your Mac):
- `pre_deployment_YYYYMMDD_HHMMSS_database.sql` - Database backup
- `pre_deployment_YYYYMMDD_HHMMSS_app_files.tar.gz` - Application backup

### Server Backups (on your server):
- `server_backup_YYYYMMDD_HHMMSS_database.sql` - Server database backup
- `server_backup_YYYYMMDD_HHMMSS_app.tar.gz` - Server application backup

## 🔧 Troubleshooting

### If Services Don't Start:
```bash
# Check Docker status
docker-compose ps

# Check logs
docker-compose logs

# Restart services
docker-compose down && docker-compose up -d
```

### If Database Issues:
```bash
# Check database connection
docker-compose exec db mysql -u root -p -e "USE laurin_build; SHOW TABLES;"
```

### If Rollback Needed:
```bash
# List available backups
ls -la /home/laurin/backups/

# Rollback to specific backup
./rollback_deployment.sh backup_name
```

## ✅ Success Checklist

After deployment, verify:
- [ ] Application is accessible
- [ ] Admin login works with new password
- [ ] All existing data is present
- [ ] Theme switching works on price list
- [ ] Cashbook overview shows statistics
- [ ] Cashbook delete functionality works
- [ ] No error messages in browser console

## 📞 Support

If you encounter any issues:
1. Check the logs: `docker-compose logs`
2. Try rollback: `./rollback_deployment.sh backup_name`
3. The original data is always preserved in backups

---

**Remember**: Your data is always safe with multiple backup layers. The deployment process is designed to be completely reversible.
