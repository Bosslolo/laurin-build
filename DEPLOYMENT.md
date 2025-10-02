# Server Deployment Guide

## Quick Start

### 1. Pull from GitHub
```bash
git clone https://github.com/your-username/schuelerfirma_privat.git
cd schuelerfirma_privat
```

### 2. Start the System
```bash
# Start all services
./start_laptop.sh

# Or start individual services
docker-compose -f docker-compose.laptop.yml up -d
```

### 3. Access URLs
- **Admin View**: http://your-server-ip:5001
- **User View**: http://your-server-ip:5002  
- **Database**: http://your-server-ip:8080

## Server Configuration

### Port Configuration
- Admin: `5001:5000`
- User: `5002:5000`
- Database: `5432:5432`
- Adminer: `8080:8080`

### Environment Variables
- `FLASK_APP_MODE=admin` (for admin view)
- `FLASK_APP_MODE=user` (for user view)
- `DATABASE_URL=postgresql://user:password@db:5432/db`

## Database Setup

### Using Existing Database
The system will automatically connect to your existing PostgreSQL database.

### Import Real Data
```bash
# Copy your database backup to ./backups/database_backup.sql
./import_complete_data.sh
```

## Management Commands

### Start/Stop
```bash
./start_laptop.sh    # Start all services
./stop_laptop.sh     # Stop all services
```

### View Logs
```bash
docker-compose -f docker-compose.laptop.yml logs -f
```

### Restart Services
```bash
docker-compose -f docker-compose.laptop.yml restart
```

## Features

### Admin View (Port 5001)
- User management
- Beverage management
- Price setting
- Monthly reports
- Historical data access

### User View (Port 5002)
- Clean interface
- Current month consumption only
- PIN authentication
- Guest access

### Database Access (Port 8080)
- Server: `schuelerfirma_db`
- Username: `user`
- Password: `password`
- Database: `db`

## Troubleshooting

### Port Conflicts
If ports are in use, modify `docker-compose.laptop.yml`:
```yaml
ports:
  - "5003:5000"  # Change 5001 to 5003
```

### Database Issues
```bash
# Check database status
docker exec -i schuelerfirma_db psql -U user -d db -c "SELECT COUNT(*) FROM users;"

# Restart database
docker-compose -f docker-compose.laptop.yml restart db
```

### Character Encoding
```bash
# Fix German characters if needed
./fix_all_encoding.sh
```
