from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from .config import Config
from flask_caching import Cache

db = SQLAlchemy()
cache = Cache()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # Session timeout configuration (10 minutes for admin security)
    app.config['PERMANENT_SESSION_LIFETIME'] = 600  # 10 minutes in seconds

    db.init_app(app)
    # Cache configuration (Redis service from docker-compose); fallback to simple cache
    app.config.setdefault('CACHE_TYPE', 'RedisCache')
    app.config.setdefault('CACHE_REDIS_HOST', 'redis')
    app.config.setdefault('CACHE_REDIS_PORT', 6379)
    app.config.setdefault('CACHE_DEFAULT_TIMEOUT', 60)
    try:
        cache.init_app(app)
    except Exception as e:
        print(f"WARNING: Cache initialization failed, falling back to simple cache: {e}")
        app.config.update({'CACHE_TYPE': 'SimpleCache'})
        cache.init_app(app)

    # Register routes
    from .routes import bp as routes_bp
    app.register_blueprint(routes_bp)

    # Create tables on startup
    with app.app_context():
        # Create tables (no-op if they already exist after a restore)
        try:
            db.create_all()
        except Exception as e:
            print(f"WARNING: db.create_all() skipped/failed (likely restored schema present): {e}")

        # Performance indexes (idempotent CREATE INDEX IF NOT EXISTS for PostgreSQL)
        try:
            from sqlalchemy import text as _text
            db.session.execute(_text("CREATE INDEX IF NOT EXISTS ix_consumptions_created_user ON consumptions (created_at, user_id)"))
            db.session.execute(_text("CREATE INDEX IF NOT EXISTS ix_consumptions_user_created ON consumptions (user_id, created_at)"))
            db.session.execute(_text("CREATE INDEX IF NOT EXISTS ix_invoices_user_period ON invoices (user_id, period)"))
            db.session.commit()
            print("INFO: Ensured performance indexes exist")
        except Exception as e:
            db.session.rollback()
            print(f"WARNING: Could not create performance indexes: {e}")

        # Enforce unique (role_id, beverage_id) on beverage_prices with safe duplicate consolidation
        try:
            from sqlalchemy import text as _text2
            # Attempt to add the constraint if it does not exist (PostgreSQL specific check)
            constraint_check_sql = _text2("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint WHERE conname = 'uq_beverage_prices_role_beverage'
                    ) THEN
                        -- First, collapse duplicates keeping the oldest (lowest id) row referenced by consumptions if any
                        WITH ranked AS (
                            SELECT id, role_id, beverage_id,
                                   ROW_NUMBER() OVER (PARTITION BY role_id, beverage_id ORDER BY id ASC) AS rn
                            FROM beverage_prices
                        ), dups AS (
                            SELECT id FROM ranked WHERE rn > 1
                        )
                        -- For any consumptions referencing duplicate ids, repoint them to the kept (min id) row
                        UPDATE consumptions c SET beverage_price_id = sub.min_id
                        FROM (
                            SELECT bp.role_id, bp.beverage_id, MIN(bp.id) AS min_id, array_agg(bp.id) AS all_ids
                            FROM beverage_prices bp
                            GROUP BY bp.role_id, bp.beverage_id
                            HAVING COUNT(*) > 1
                        ) sub
                        WHERE c.beverage_price_id = ANY(sub.all_ids) AND c.beverage_price_id <> sub.min_id;

                        -- Delete the now unreferenced duplicate rows
                        DELETE FROM beverage_prices bp USING (
                            SELECT id FROM (
                                SELECT id, ROW_NUMBER() OVER (PARTITION BY role_id, beverage_id ORDER BY id ASC) AS rn
                                FROM beverage_prices
                            ) x WHERE x.rn > 1
                        ) d WHERE bp.id = d.id;

                        -- Finally, add the unique constraint
                        ALTER TABLE beverage_prices
                        ADD CONSTRAINT uq_beverage_prices_role_beverage UNIQUE (role_id, beverage_id);
                    END IF;
                END$$;
            """)
            db.session.execute(constraint_check_sql)
            db.session.commit()
            print("INFO: Ensured unique constraint uq_beverage_prices_role_beverage (with duplicate consolidation)")
        except Exception as e:
            db.session.rollback()
            print(f"WARNING: Could not enforce unique beverage price constraint: {e}")

        # Safely attempt category column addition only if a bind is present
        bind = db.session.get_bind()
        if bind is None:
            print("INFO: Database bind not ready yet; skipping category column check at startup")
        else:
            try:
                from sqlalchemy import text
                dialect = bind.dialect.name
                columns = []
                if dialect == 'sqlite':
                    result = db.session.execute(text("PRAGMA table_info(beverages)"))
                    columns = [row[1] for row in result.fetchall()]
                elif dialect == 'postgresql':
                    result = db.session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='beverages'"))
                    columns = [row[0] for row in result.fetchall()]
                else:
                    print(f"INFO: Unsupported dialect for column introspection: {dialect}")

                if 'category' not in columns:
                    print("Adding category column to beverages table...")
                    db.session.execute(text("ALTER TABLE beverages ADD COLUMN category VARCHAR(50) DEFAULT 'drink'"))
                    db.session.commit()
                    print("Category column added successfully")
                else:
                    print("Category column already exists")
            except Exception as e:
                print(f"WARNING: Could not ensure category column: {e}")
                db.session.rollback()

        # Ensure Guests role exists
        try:
            from .models import roles
            guests_role = roles.query.filter_by(name="Guests").first()
            if not guests_role:
                print("Creating Guests role...")
                guests_role = roles(name="Guests")
                db.session.add(guests_role)
                db.session.commit()
                print("Guests role created successfully")
            else:
                print("Guests role already exists")
        except Exception as e:
            print(f"WARNING: Could not create/verify Guests role: {e}")
            db.session.rollback()

        # Initialize theme settings if missing
        try:
            from .models import settings
            changed = False
            if settings.get_value('theme') is None:
                settings.set_value('theme', 'coffee')
                changed = True
            if settings.get_value('theme_version') is None:
                settings.set_value('theme_version', '1')
                changed = True
            if changed:
                db.session.commit()
                print("Initialized default theme settings")
        except Exception as e:
            db.session.rollback()
            print(f"WARNING: Could not initialize theme settings: {e}")

    print("Database startup checks complete")

    return app
