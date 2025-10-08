#!/bin/bash

# Script to import complete real server data
echo "🎯 Importing Complete Real Server Data"
echo "======================================"

# Check if backup file exists
if [ ! -f "./backups/database_backup_complete.sql" ]; then
    echo "❌ Backup file not found at ./backups/database_backup_complete.sql"
    exit 1
fi

# Convert to UTF-8 if needed
echo "🔄 Converting backup to UTF-8..."
iconv -f UTF-16 -t UTF-8 ./backups/database_backup_complete.sql > ./backups/database_backup_complete_utf8.sql

# Stop and remove everything
echo "🛑 Stopping and removing all containers..."
docker-compose -f docker-compose.laptop.yml down -v

# Remove the database volume completely
echo "🗑️ Removing all database data..."
docker volume rm schuelerfirma_privat_pgdata 2>/dev/null || true

# Start fresh
echo "🚀 Starting completely fresh environment..."
./start_laptop.sh

# Wait for database to be ready
echo "⏳ Waiting for database to be ready..."
sleep 30

# Check if database container is running
if ! docker ps | grep -q "schuelerfirma_db"; then
    echo "❌ Database container is not running. Please check Docker setup."
    exit 1
fi

# Import the data
echo "📥 Importing complete real server data..."
docker exec -i schuelerfirma_db psql -U user -d db < ./backups/database_backup_complete_utf8.sql

if [ $? -eq 0 ]; then
    echo "✅ Complete real server data imported successfully!"
    
    # Check what was imported
    echo "🔍 Checking imported data..."
    echo "Users: $(docker exec -i schuelerfirma_db psql -U user -d db -t -c "SELECT COUNT(*) FROM users;")"
    echo "Consumptions: $(docker exec -i schuelerfirma_db psql -U user -d db -t -c "SELECT COUNT(*) FROM consumptions;")"
    echo "Beverages: $(docker exec -i schuelerfirma_db psql -U user -d db -t -c "SELECT COUNT(*) FROM beverages;")"
    echo "Roles: $(docker exec -i schuelerfirma_db psql -U user -d db -t -c "SELECT COUNT(*) FROM roles;")"
    echo "Beverage Prices: $(docker exec -i schuelerfirma_db psql -U user -d db -t -c "SELECT COUNT(*) FROM beverage_prices;")"
    
    echo ""
    echo "🎉 Test your system now:"
    echo "   Admin: http://localhost:5001"
    echo "   User:  http://localhost:5002"
    echo "   Database: http://localhost:8080"
    echo ""
    echo "📋 Test checklist:"
    echo "   ✅ Check if your 111+ users are there"
    echo "   ✅ Check if real consumption data is there"
    echo "   ✅ Test adding new consumption"
    echo "   ✅ Test monthly reports"
    echo ""
    echo "🔄 If everything works, you can deploy to server!"
else
    echo "❌ Import failed. Please check the backup file."
fi
