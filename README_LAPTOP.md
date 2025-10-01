# 🖥️ Laurin Build - Laptop Development Setup

This is Laurin's personalized beverage management system, optimized for local development on your laptop while keeping your server configuration intact.

## 🚀 Quick Start

### Prerequisites
- Docker Desktop installed and running
- Git (if cloning)

### Start Development Environment
```bash
./start_laptop.sh
```

### Stop Development Environment
```bash
./stop_laptop.sh
```

## 📡 Access URLs

- **Web App**: http://localhost:5000
- **Adminer (Database)**: http://localhost:8080
- **Redis**: localhost:6379

## 🔧 What's Included

### Services
- **Web App**: Flask application with hot reload
- **Database**: PostgreSQL for production-like testing
- **Adminer**: Database management interface
- **Redis**: For future caching/sessions

### Features
- ✅ **Hot Reload**: Code changes sync automatically
- ✅ **SQLite Development**: Fast local database
- ✅ **PostgreSQL Testing**: Production-like database
- ✅ **Volume Mounting**: All files synced
- ✅ **Development Tools**: Adminer, Redis, etc.

## 📁 File Structure

```
laurin-build/
├── docker-compose.yml          # Server setup (unchanged)
├── docker-compose.laptop.yml   # Laptop setup (new)
├── Dockerfile                  # Server Dockerfile (unchanged)
├── Dockerfile.laptop          # Laptop Dockerfile (new)
├── start_laptop.sh            # Laptop startup script
├── stop_laptop.sh             # Laptop stop script
├── laptop.env                 # Laptop environment variables
└── README_LAPTOP.md           # This file
```

## 🆚 Server vs Laptop

| Feature | Server | Laptop |
|---------|--------|--------|
| Database | PostgreSQL | SQLite + PostgreSQL |
| Environment | Production | Development |
| Hot Reload | No | Yes |
| Debug Mode | Off | On |
| Additional Services | Web + DB + Adminer | Web + DB + Adminer + Redis |

## 🛠️ Development Commands

### View Logs
```bash
docker-compose -f docker-compose.laptop.yml logs -f
```

### Restart Services
```bash
docker-compose -f docker-compose.laptop.yml restart
```

### Access Container Shell
```bash
docker exec -it schuelerfirma_web bash
```

### Reset Everything
```bash
docker-compose -f docker-compose.laptop.yml down -v
```

## 🔒 Server Setup Unchanged

Your original server setup remains completely unchanged:
- `docker-compose.yml` (server)
- `Dockerfile` (server)
- All existing scripts and configurations

## 🎯 Benefits

1. **Complete Isolation**: Laptop setup doesn't affect server
2. **Hot Reload**: Instant code changes
3. **Full Stack**: All services included
4. **Easy Management**: Simple start/stop scripts
5. **Production Parity**: Same services as server
