#!/bin/bash

# Laptop Docker Development Startup Script
echo "🖥️  Starting Laptop Development Environment..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker Desktop first."
    exit 1
fi

# Stop any existing containers
echo "🛑 Stopping existing containers..."
docker-compose -f docker-compose.laptop.yml down 2>/dev/null || true

# Build and start services
echo "🔨 Building and starting services..."
docker-compose -f docker-compose.laptop.yml up --build -d

# Wait for services to be ready
echo "⏳ Waiting for services to start..."
sleep 10

# Check if services are running
echo "🔍 Checking service status..."
docker-compose -f docker-compose.laptop.yml ps

echo ""
echo "🎉 Laptop Development Environment is ready!"
echo ""
echo "📡 Access URLs:"
echo "   🔧 Admin View:     http://localhost:5001 (with dev tools)"
echo "   👥 User View:      http://localhost:5002 (clean interface)"
echo "   🗄️  Adminer:       http://localhost:8080"
echo "   📊 Redis:          localhost:6379"
echo ""
echo "📋 Management Commands:"
echo "   Stop:              ./stop_laptop.sh"
echo "   View logs:         docker-compose -f docker-compose.laptop.yml logs -f"
echo "   Restart:           docker-compose -f docker-compose.laptop.yml restart"
echo ""
echo "🔧 Development Tips:"
echo "   - Files are synced automatically (hot reload)"
echo "   - Database: SQLite for development, PostgreSQL for testing"
echo "   - Use Adminer to manage databases"
echo ""
