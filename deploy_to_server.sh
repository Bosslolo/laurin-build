#!/bin/bash

# Simple deployment script for server
echo "🚀 Deploying to Server"
echo "====================="

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Stop any existing containers
echo "🛑 Stopping existing containers..."
docker-compose -f docker-compose.laptop.yml down 2>/dev/null || true

# Start the system
echo "🚀 Starting system..."
./start_laptop.sh

# Wait for services to be ready
echo "⏳ Waiting for services to start..."
sleep 10

# Check if services are running
echo "🔍 Checking service status..."
docker-compose -f docker-compose.laptop.yml ps

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📡 Access URLs:"
echo "   Admin:  http://$(hostname -I | awk '{print $1}'):5001"
echo "   User:   http://$(hostname -I | awk '{print $1}'):5002"
echo "   DB:     http://$(hostname -I | awk '{print $1}'):8080"
echo ""
echo "🔧 Management:"
echo "   Stop:   ./stop_laptop.sh"
echo "   Logs:   docker-compose -f docker-compose.laptop.yml logs -f"
