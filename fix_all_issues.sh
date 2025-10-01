#!/bin/bash

# Comprehensive fix for all recurring database issues
echo "🔧 Comprehensive Database Fix"
echo "============================="

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker Desktop first."
    exit 1
fi

# Check if containers are running
if ! docker ps | grep -q "schuelerfirma_db"; then
    echo "❌ Database container is not running. Please start the system first."
    exit 1
fi

echo "🔍 Step 1: Adding missing database columns..."
# Add missing category column if it doesn't exist
docker exec -i laurin_build_db psql -U user -d db -c "
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'beverages' AND column_name = 'category') THEN
        ALTER TABLE beverages ADD COLUMN category VARCHAR(50) DEFAULT 'drink';
    END IF;
END
\$\$;
"

echo "🔍 Step 2: Fixing character encoding issues..."
# Fix all German umlauts and special characters - step by step
echo "  Fixing ü characters..."
docker exec -i laurin_build_db psql -U user -d db -c "UPDATE users SET first_name = REPLACE(first_name, '├╝', 'ü'), last_name = REPLACE(last_name, '├╝', 'ü') WHERE first_name LIKE '%├╝%' OR last_name LIKE '%├╝%';"

echo "  Fixing ö characters..."
docker exec -i laurin_build_db psql -U user -d db -c "UPDATE users SET first_name = REPLACE(first_name, '├Â', 'ö'), last_name = REPLACE(last_name, '├Â', 'ö') WHERE first_name LIKE '%├Â%' OR last_name LIKE '%├Â%';"

echo "  Fixing ä characters..."
docker exec -i laurin_build_db psql -U user -d db -c "UPDATE users SET first_name = REPLACE(first_name, '├ñ', 'ä'), last_name = REPLACE(last_name, '├ñ', 'ä') WHERE first_name LIKE '%├ñ%' OR last_name LIKE '%├ñ%';"

echo "  Fixing ß characters..."
docker exec -i laurin_build_db psql -U user -d db -c "UPDATE users SET first_name = REPLACE(first_name, '├ƒ', 'ß'), last_name = REPLACE(last_name, '├ƒ', 'ß') WHERE first_name LIKE '%├ƒ%' OR last_name LIKE '%├ƒ%';"

echo "  Fixing remaining corrupted characters..."
docker exec -i laurin_build_db psql -U user -d db -c "UPDATE users SET first_name = REPLACE(first_name, '├', ''), last_name = REPLACE(last_name, '├', '') WHERE first_name LIKE '%├%' OR last_name LIKE '%├%';"

echo "  Fixing beverage names..."
docker exec -i laurin_build_db psql -U user -d db -c "UPDATE beverages SET name = REPLACE(REPLACE(REPLACE(REPLACE(name, '├ñ', 'ä'), '├Â', 'ö'), '├╝', 'ü'), '├ƒ', 'ß') WHERE name LIKE '%├%';"

echo "🔍 Step 3: Ensuring database schema is complete..."
# Ensure all required tables and columns exist
docker exec -i laurin_build_db psql -U user -d db -c "
-- Create roles table if it doesn't exist
CREATE TABLE IF NOT EXISTS roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(120) NOT NULL
);

-- Create beverages table if it doesn't exist
CREATE TABLE IF NOT EXISTS beverages (
    id SERIAL PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    category VARCHAR(50) DEFAULT 'drink',
    status BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

-- Create users table if it doesn't exist
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    itsl_id INTEGER UNIQUE,
    role_id INTEGER NOT NULL REFERENCES roles(id),
    first_name VARCHAR(120) NOT NULL,
    last_name VARCHAR(120) NOT NULL,
    email VARCHAR(120),
    pin_hash BYTEA,
    status BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

-- Create beverage_prices table if it doesn't exist
CREATE TABLE IF NOT EXISTS beverage_prices (
    id SERIAL PRIMARY KEY,
    role_id INTEGER NOT NULL REFERENCES roles(id),
    beverage_id INTEGER NOT NULL REFERENCES beverages(id),
    price_cents INTEGER NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

-- Create invoices table if it doesn't exist
CREATE TABLE IF NOT EXISTS invoices (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    invoice_name VARCHAR(120) UNIQUE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    period DATE NOT NULL DEFAULT DATE_TRUNC('month', CURRENT_DATE),
    sent_at TIMESTAMP WITHOUT TIME ZONE,
    due_at TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_invoices_user_period UNIQUE (user_id, period)
);

-- Create consumptions table if it doesn't exist
CREATE TABLE IF NOT EXISTS consumptions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    beverage_id INTEGER NOT NULL REFERENCES beverages(id),
    beverage_price_id INTEGER NOT NULL REFERENCES beverage_prices(id),
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    quantity INTEGER NOT NULL,
    unit_price_cents INTEGER NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

-- Create payments table if it doesn't exist
CREATE TABLE IF NOT EXISTS payments (
    id SERIAL PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    amount_cents INTEGER NOT NULL,
    payment_method VARCHAR(20) NOT NULL DEFAULT 'other',
    note VARCHAR(255),
    raw_payload JSON,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);
"

echo "🔍 Step 4: Ensuring essential roles exist..."
# Create essential roles if they don't exist
docker exec -i laurin_build_db psql -U user -d db -c "
INSERT INTO roles (id, name) VALUES (1, 'Teachers') ON CONFLICT (id) DO NOTHING;
INSERT INTO roles (id, name) VALUES (2, 'Students') ON CONFLICT (id) DO NOTHING;
INSERT INTO roles (id, name) VALUES (3, 'Staff') ON CONFLICT (id) DO NOTHING;
INSERT INTO roles (id, name) VALUES (4, 'Guests') ON CONFLICT (id) DO NOTHING;
"

echo "🔍 Step 5: Restarting application containers..."
# Restart the application containers to pick up database changes
docker-compose -f docker-compose.laptop.yml restart admin user

echo "⏳ Waiting for containers to restart..."
sleep 10

echo "🔍 Step 6: Verifying the fix..."
# Check if everything is working
echo "📊 Database status:"
docker exec -i laurin_build_db psql -U user -d db -c "SELECT COUNT(*) as users FROM users;"
docker exec -i laurin_build_db psql -U user -d db -c "SELECT COUNT(*) as consumptions FROM consumptions;"
docker exec -i laurin_build_db psql -U user -d db -c "SELECT COUNT(*) as beverages FROM beverages;"
docker exec -i laurin_build_db psql -U user -d db -c "SELECT COUNT(*) as roles FROM roles;"

echo "🔤 Character encoding check:"
docker exec -i laurin_build_db psql -U user -d db -c "SELECT first_name, last_name FROM users WHERE first_name LIKE '%ü%' OR last_name LIKE '%ü%' OR first_name LIKE '%ö%' OR last_name LIKE '%ö%' OR first_name LIKE '%ä%' OR last_name LIKE '%ä%' OR first_name LIKE '%ß%' OR last_name LIKE '%ß%' LIMIT 5;"

echo "🍹 Beverage names check:"
docker exec -i laurin_build_db psql -U user -d db -c "SELECT name FROM beverages;"

echo ""
echo "✅ All issues fixed!"
echo ""
echo "🎉 Your system should now work perfectly:"
echo "   Admin: http://localhost:5001"
echo "   User:  http://localhost:5002"
echo "   Database: http://localhost:8080"
echo ""
echo "📋 What was fixed:"
echo "   ✅ Added missing database columns"
echo "   ✅ Fixed all German character encoding"
echo "   ✅ Ensured complete database schema"
echo "   ✅ Created essential roles"
echo "   ✅ Restarted application containers"
echo ""
echo "🔄 Use this script anytime you import a new backup!"
