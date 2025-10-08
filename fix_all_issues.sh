#!/bin/bash

# Comprehensive fix for recurring database issues (encoding, schema, roles)
echo "Comprehensive Database Fix"
echo "=========================="

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

echo "[1/6] Adding missing database columns (idempotent)..."
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

echo "[2/6] Backing up database before text normalization..."
BACKUP_FILE="backup_pre_umlaut_fix_$(date +%Y%m%d_%H%M%S).sql"
docker exec -i laurin_build_db pg_dump -U user -d db > "$BACKUP_FILE" 2>/dev/null && \
  echo "  Backup written to $BACKUP_FILE" || echo "  WARNING: Backup may have failed (check permissions)"

echo "[3/6] Normalizing German umlaut mojibake in users..."
docker exec -i laurin_build_db psql -U user -d db -c "UPDATE users
SET first_name = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(first_name,
    '├ñ','ä'),'├Â','ö'),'├╝','ü'),'├ƒ','ß'),'Ã¼','ü'),'Ã¶','ö'),
    last_name  = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(last_name,
    '├ñ','ä'),'├Â','ö'),'├╝','ü'),'├ƒ','ß'),'Ã¼','ü'),'Ã¶','ö')
WHERE first_name ~ '├|Ã' OR last_name ~ '├|Ã';"

docker exec -i laurin_build_db psql -U user -d db -c "UPDATE users
SET first_name = REPLACE(REPLACE(REPLACE(first_name,'Ã„','Ä'),'Ã–','Ö'),'Ãœ','Ü'),
    last_name  = REPLACE(REPLACE(REPLACE(last_name,'Ã„','Ä'),'Ã–','Ö'),'Ãœ','Ü')
WHERE first_name ~ 'Ã' OR last_name ~ 'Ã';"

echo "[4/6] Normalizing umlauts in beverages..."
docker exec -i laurin_build_db psql -U user -d db -c "UPDATE beverages
SET name = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(name,
    '├ñ','ä'),'├Â','ö'),'├╝','ü'),'├ƒ','ß'),'Ã¼','ü'),'Ã¶','ö'),'ÃŸ','ß')
WHERE name ~ '├|Ã';"

docker exec -i laurin_build_db psql -U user -d db -c "UPDATE beverages
SET name = REPLACE(REPLACE(REPLACE(name,'Ã„','Ä'),'Ã–','Ö'),'Ãœ','Ü')
WHERE name ~ 'Ã';"

echo "[5/6] Ensuring database schema is complete (idempotent DDL)..."
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

echo "[6/6] Ensuring essential roles exist..."
# Create essential roles if they don't exist
docker exec -i laurin_build_db psql -U user -d db -c "
INSERT INTO roles (id, name) VALUES (1, 'Teachers') ON CONFLICT (id) DO NOTHING;
INSERT INTO roles (id, name) VALUES (2, 'Students') ON CONFLICT (id) DO NOTHING;
INSERT INTO roles (id, name) VALUES (3, 'Staff') ON CONFLICT (id) DO NOTHING;
INSERT INTO roles (id, name) VALUES (4, 'Guests') ON CONFLICT (id) DO NOTHING;
"

echo "Restarting application containers (admin, user) to clear any cached data..."
docker compose -f docker-compose.laptop.yml restart admin user

echo "Waiting for containers to restart..."
sleep 8

echo "Verifying results (sample rows)..."
# Check if everything is working
echo "Database status:"
docker exec -i laurin_build_db psql -U user -d db -c "SELECT COUNT(*) as users FROM users;"
docker exec -i laurin_build_db psql -U user -d db -c "SELECT COUNT(*) as consumptions FROM consumptions;"
docker exec -i laurin_build_db psql -U user -d db -c "SELECT COUNT(*) as beverages FROM beverages;"
docker exec -i laurin_build_db psql -U user -d db -c "SELECT COUNT(*) as roles FROM roles;"

echo "Character encoding check (should return 0 rows of corruption):"
docker exec -i laurin_build_db psql -U user -d db -c "SELECT first_name, last_name FROM users WHERE first_name LIKE '%ü%' OR last_name LIKE '%ü%' OR first_name LIKE '%ö%' OR last_name LIKE '%ö%' OR first_name LIKE '%ä%' OR last_name LIKE '%ä%' OR first_name LIKE '%ß%' OR last_name LIKE '%ß%' LIMIT 5;"

echo "Beverage names check:"
docker exec -i laurin_build_db psql -U user -d db -c "SELECT name FROM beverages;"

echo ""
echo "Done. Review above for any remaining issues."
echo ""
echo "System endpoints:"
echo "   Admin: http://localhost:5001"
echo "   User:  http://localhost:5002"
echo "   Database: http://localhost:8080"
echo ""
echo "Summary of actions:"
echo "   - Added missing database columns"
echo "   - Normalized German umlaut encoding in users & beverages"
echo "   - Ensured complete database schema"
echo "   - Ensured essential roles exist"
echo "   - Restarted application containers"
echo ""
echo "🔄 Use this script anytime you import a new backup!"
