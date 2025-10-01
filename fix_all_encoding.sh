#!/bin/bash

# Script to fix ALL character encoding issues in the database
echo "🔧 Fixing ALL Character Encoding Issues"
echo "====================================="

# Create a comprehensive mapping of corrupted characters to correct ones
echo "📝 Creating character mapping..."

# Fix all ü characters (├╝ -> ü)
docker exec -i schuelerfirma_db psql -U user -d db -c "
UPDATE users SET 
  first_name = REPLACE(first_name, '├╝', 'ü'),
  last_name = REPLACE(last_name, '├╝', 'ü')
WHERE first_name LIKE '%├╝%' OR last_name LIKE '%├╝%';
"

# Fix all ö characters (├Â -> ö)
docker exec -i schuelerfirma_db psql -U user -d db -c "
UPDATE users SET 
  first_name = REPLACE(first_name, '├Â', 'ö'),
  last_name = REPLACE(last_name, '├Â', 'ö')
WHERE first_name LIKE '%├Â%' OR last_name LIKE '%├Â%';
"

# Fix all ä characters (├ñ -> ä)
docker exec -i schuelerfirma_db psql -U user -d db -c "
UPDATE users SET 
  first_name = REPLACE(first_name, '├ñ', 'ä'),
  last_name = REPLACE(last_name, '├ñ', 'ä')
WHERE first_name LIKE '%├ñ%' OR last_name LIKE '%├ñ%';
"

# Fix all ß characters (├ƒ -> ß)
docker exec -i schuelerfirma_db psql -U user -d db -c "
UPDATE users SET 
  first_name = REPLACE(first_name, '├ƒ', 'ß'),
  last_name = REPLACE(last_name, '├ƒ', 'ß')
WHERE first_name LIKE '%├ƒ%' OR last_name LIKE '%├ƒ%';
"

# Fix all other corrupted characters
docker exec -i schuelerfirma_db psql -U user -d db -c "
UPDATE users SET 
  first_name = REPLACE(first_name, '├', ''),
  last_name = REPLACE(last_name, '├', '')
WHERE first_name LIKE '%├%' OR last_name LIKE '%├%';
"

# Fix beverage names
docker exec -i schuelerfirma_db psql -U user -d db -c "
UPDATE beverages SET 
  name = REPLACE(name, '├ñ', 'ä'),
  name = REPLACE(name, '├Â', 'ö'),
  name = REPLACE(name, '├╝', 'ü'),
  name = REPLACE(name, '├ƒ', 'ß')
WHERE name LIKE '%├%';
"

echo "✅ All character encoding fixes applied!"

# Show results
echo "🔍 Checking results..."
echo "📋 Sample fixed names:"
docker exec -i schuelerfirma_db psql -U user -d db -c "SELECT first_name, last_name FROM users WHERE last_name LIKE '%ü%' OR last_name LIKE '%ö%' OR last_name LIKE '%ä%' OR last_name LIKE '%ß%' LIMIT 10;"

echo "🍹 Fixed beverages:"
docker exec -i schuelerfirma_db psql -U user -d db -c "SELECT name FROM beverages;"

echo "📊 Total users with special characters:"
docker exec -i schuelerfirma_db psql -U user -d db -c "SELECT COUNT(*) as users_with_special_chars FROM users WHERE first_name LIKE '%ü%' OR last_name LIKE '%ü%' OR first_name LIKE '%ö%' OR last_name LIKE '%ö%' OR first_name LIKE '%ä%' OR last_name LIKE '%ä%' OR first_name LIKE '%ß%' OR last_name LIKE '%ß%';"
