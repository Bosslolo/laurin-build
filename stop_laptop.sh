#!/bin/bash

# Laptop Docker Development Stop Script
echo "🛑 Stopping Laptop Development Environment..."

# Stop and remove containers
docker-compose -f docker-compose.laptop.yml down

# Optional: Remove volumes (uncomment if you want to reset database)
# echo "🗑️  Removing volumes..."
# docker-compose -f docker-compose.laptop.yml down -v

echo "✅ Laptop Development Environment stopped."
echo ""
echo "📋 To start again: ./start_laptop.sh"
echo "📋 To reset everything: docker-compose -f docker-compose.laptop.yml down -v"
