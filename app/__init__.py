import threading
import time
from datetime import datetime, timedelta

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
    # Cache configuration - try Redis first, fallback to simple cache if Redis unavailable
    # Check if Redis is available, otherwise use SimpleCache
    import socket
    redis_available = False
    try:
        # Try to connect to Redis
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('localhost', 6379))
        sock.close()
        redis_available = (result == 0)
    except Exception:
        redis_available = False
    
    if redis_available:
        app.config.setdefault('CACHE_TYPE', 'RedisCache')
        app.config.setdefault('CACHE_REDIS_HOST', 'localhost')
        app.config.setdefault('CACHE_REDIS_PORT', 6379)
        app.config.setdefault('CACHE_DEFAULT_TIMEOUT', 60)
        try:
            cache.init_app(app)
            print("INFO: Redis cache initialized successfully")
        except Exception as e:
            print(f"WARNING: Redis cache initialization failed, falling back to simple cache: {e}")
            app.config.update({'CACHE_TYPE': 'SimpleCache'})
            cache.init_app(app)
    else:
        # Use SimpleCache (in-memory) when Redis is not available
        app.config.update({
            'CACHE_TYPE': 'SimpleCache',
            'CACHE_DEFAULT_TIMEOUT': 60
        })
        cache.init_app(app)
        print("INFO: Using SimpleCache (Redis not available)")

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

        # Ensure persistent PIN archive is populated
        try:
            from .pin_utils import backfill_persistent_pins
            backfill_persistent_pins()
        except Exception as e:
            db.session.rollback()
            print(f"WARNING: Could not backfill persistent PINs: {e}")

    print("Database startup checks complete")

    _start_paypal_background_worker(app)

    return app


def _start_paypal_background_worker(app: Flask) -> None:
    """Background thread that periodically tries to auto-confirm pending PayPal payments."""
    if not app.config.get("PAYPAL_BACKGROUND_POLL_ENABLED", True):
        app.logger.info("PayPal background polling disabled by configuration")
        return

    # Prevent duplicate threads when running with a reloader
    if app.config.get("_paypal_poller_started"):
        return
    app.config["_paypal_poller_started"] = True

    def _poller():
        from .models import user_payments, payment_consumptions, mypos_transactions
        from .paypal_api import refresh_paypal_payment_status, cancel_pending_payment

        interval = max(15, int(app.config.get("PAYPAL_BACKGROUND_POLL_SECONDS", 120)))
        expiry_hours = int(app.config.get("PAYPAL_PENDING_EXPIRATION_HOURS", 0))
        cancelled_cleanup_hours = int(app.config.get("CANCELLED_PAYMENT_RETENTION_HOURS", 48))
        app.logger.info(
            "Starting PayPal background poller (interval=%ss, expiry=%sh, cleanup=%sh)",
            interval,
            expiry_hours,
            cancelled_cleanup_hours
        )

        with app.app_context():
            while True:
                try:
                    if expiry_hours:
                        cutoff = datetime.utcnow() - timedelta(hours=expiry_hours)
                        stale = user_payments.query.filter(
                            user_payments.payment_method == 'paypal',
                            user_payments.payment_status == 'pending',
                            user_payments.created_at < cutoff
                        ).all()
                        for payment in stale:
                            cancel_pending_payment(
                                payment,
                                f"automatisch storniert (älter als {expiry_hours}h)"
                            )

                    pending = user_payments.query.filter_by(
                        payment_method='paypal',
                        payment_status='pending'
                    ).all()

                    if pending:
                        app.logger.debug("PayPal poller checking %d pending payments", len(pending))

                    for payment in pending:
                        try:
                            if refresh_paypal_payment_status(payment, created_by="PayPal Poller"):
                                app.logger.info("PayPal poller auto-confirmed payment %s (user %s)", payment.id, payment.user_id)
                        except Exception:
                            app.logger.error("PayPal poller failed for payment %s", payment.id, exc_info=True)

                    if cancelled_cleanup_hours:
                        cleanup_cutoff = datetime.utcnow() - timedelta(hours=cancelled_cleanup_hours)
                        stale_cancelled = user_payments.query.filter(
                            user_payments.payment_status == 'cancelled',
                            user_payments.updated_at < cleanup_cutoff
                        ).all()
                        if stale_cancelled:
                            app.logger.info(
                                "Cleaning up %d cancelled payments older than %sh",
                                len(stale_cancelled),
                                cancelled_cleanup_hours
                            )
                        if stale_cancelled:
                            try:
                                for payment in stale_cancelled:
                                    payment_id = payment.id
                                    payment_consumptions.query.filter_by(payment_id=payment_id).delete()
                                    mypos_transactions.query.filter_by(payment_id=payment_id).update(
                                        {mypos_transactions.payment_id: None}
                                    )
                                    db.session.delete(payment)
                                db.session.commit()
                            except Exception:
                                db.session.rollback()
                                app.logger.exception("Failed to clean up cancelled payments")
                except Exception:
                    app.logger.exception("PayPal background poller encountered an error")

                time.sleep(interval)

    thread = threading.Thread(target=_poller, name="paypal-background-poller", daemon=True)
    thread.start()
