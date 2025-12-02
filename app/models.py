from . import db
from datetime import datetime

class roles(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)

class beverage_prices(db.Model):
    __tablename__ = "beverage_prices"
    __table_args__ = (
        # Enforce one logical price row per (role, beverage). Historical prices handled via separate tables if needed.
        db.UniqueConstraint('role_id', 'beverage_id', name='uq_beverage_prices_role_beverage'),
    )
    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    beverage_id = db.Column(db.Integer, db.ForeignKey("beverages.id"), nullable=False)
    price_cents = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    role = db.relationship('roles', backref='beverage_prices')
    beverage = db.relationship('beverages', backref='beverage_prices')

class beverages(db.Model):
    __tablename__ = "beverages"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(50), nullable=False, default='drink')  # 'drink' or 'food'
    status = db.Column(db.Boolean, nullable=False, default=True)  # active, inactive
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class users(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    itsl_id = db.Column(db.Integer, unique=True, nullable=True)  # Unique but not primary key
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    first_name = db.Column(db.String(120), nullable=False)
    last_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    pin_hash = db.Column(db.LargeBinary(64), nullable=True)
    status = db.Column(db.Boolean, nullable=False, default=True)  # active, inactive
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    role = db.relationship('roles', backref='users')

class display_items(db.Model):
    __tablename__ = "display_items"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    price_cents = db.Column(db.Integer, nullable=False)
    category = db.Column(db.String(50), nullable=False, default='food')  # 'food', 'drink', 'snack'
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    display_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class consumptions(db.Model):
    __tablename__ = "consumptions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    beverage_id = db.Column(db.Integer, db.ForeignKey("beverages.id"), nullable=False)
    beverage_price_id = db.Column(db.Integer, db.ForeignKey("beverage_prices.id"), nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price_cents = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    user = db.relationship('users', backref='consumptions')
    beverage = db.relationship('beverages', backref='consumptions')
    beverage_price = db.relationship('beverage_prices', backref='consumptions')
    invoice = db.relationship('invoices', backref='consumptions')

class invoices(db.Model):
    __tablename__ = "invoices"
    __table_args__ = (
        db.UniqueConstraint('user_id', 'period', name='uq_invoices_user_period'),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    invoice_name = db.Column(db.String(120), unique=True, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="draft")  # draft, sent, paid, overdue, void
    period = db.Column(db.Date, default=lambda: datetime.utcnow().replace(day=1).date(), nullable=False)
    sent_at = db.Column(db.DateTime, nullable=True)
    due_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    user = db.relationship('users', backref='invoices')

class payments(db.Model):
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)
    payment_method = db.Column(db.String(20), nullable=False, default="other")  # paypal, mypos, bank_transfer, cash, terminal
    note = db.Column(db.String(255), nullable=True)
    raw_payload = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    invoice = db.relationship('invoices', backref='payments')

class cashbook_entries(db.Model):
    __tablename__ = "cashbook_entries"
    __table_args__ = (
        db.UniqueConstraint('company', 'beleg_nummer', name='uq_cashbook_company_beleg'),
    )
    id = db.Column(db.Integer, primary_key=True)
    company = db.Column(db.String(50), nullable=False)  # 'Schülerfirma' or 'Pausenverkauf'
    beleg_nummer = db.Column(db.Integer, nullable=False)  # auto-increment per company (managed in app code)
    entry_date = db.Column(db.Date, nullable=False)
    bemerkung = db.Column(db.String(255), nullable=True)
    posten = db.Column(db.String(120), nullable=False)
    einnahmen_bar_cents = db.Column(db.Integer, nullable=False, default=0)
    ausgaben_bar_cents = db.Column(db.Integer, nullable=False, default=0)
    kassenstand_bar_cents = db.Column(db.Integer, nullable=False)
    created_by = db.Column(db.String(50), nullable=True)  # Track who created the entry
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class settings(db.Model):
    __tablename__ = "settings"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.String(255), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    @staticmethod
    def get_value(key: str, default=None):
        row = settings.query.filter_by(key=key).first()
        return row.value if row else default

    @staticmethod
    def set_value(key: str, value: str):
        row = settings.query.filter_by(key=key).first()
        if not row:
            row = settings(key=key, value=value)
            db.session.add(row)
        else:
            row.value = value
        return row

class admin_access_logs(db.Model):
    __tablename__ = "admin_access_logs"
    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(45), nullable=False)  # IPv6 compatible
    user_agent = db.Column(db.Text, nullable=True)
    device_name = db.Column(db.String(255), nullable=True)
    username_attempted = db.Column(db.String(255), nullable=True)
    password_attempted = db.Column(db.String(255), nullable=True)
    success = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

class user_payments(db.Model):
    __tablename__ = "user_payments"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)
    payment_method = db.Column(db.String(20), nullable=False)  # 'paypal', 'cash', 'mypos_card'
    payment_status = db.Column(db.String(20), nullable=False, default='pending')  # 'pending', 'paid', 'cancelled'
    payment_reference = db.Column(db.String(120), nullable=True)  # PayPal transaction ID or cash receipt number
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    paid_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    user = db.relationship('users', backref='user_payments')

class payment_consumptions(db.Model):
    __tablename__ = "payment_consumptions"
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("user_payments.id"), nullable=False)
    consumption_id = db.Column(db.Integer, db.ForeignKey("consumptions.id"), nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)  # Amount of this consumption covered by this payment
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    payment = db.relationship('user_payments', backref='payment_consumptions')
    consumption = db.relationship('consumptions', backref='payment_consumptions')

class mypos_transactions(db.Model):
    __tablename__ = "mypos_transactions"
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("user_payments.id"), nullable=True)  # Nullable for standalone transactions
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)
    transaction_id = db.Column(db.String(120), nullable=True)  # myPOS transaction ID
    status = db.Column(db.String(20), nullable=False, default='pending')  # 'pending', 'completed', 'cancelled', 'failed'
    device_id = db.Column(db.String(120), nullable=True)  # myPOS device identifier
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    payment = db.relationship('user_payments', backref='mypos_transactions')
    user = db.relationship('users', backref='mypos_transactions')


class persistent_pins(db.Model):
    __tablename__ = "persistent_pins"
    id = db.Column(db.Integer, primary_key=True)
    user_identifier = db.Column(db.String(255), unique=True, nullable=False)
    pin_hash = db.Column(db.LargeBinary(64), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class cash_payment_requests(db.Model):
    __tablename__ = "cash_payment_requests"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending, collected, cancelled
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by = db.Column(db.String(50), nullable=True)
    note = db.Column(db.Text, nullable=True)

    user = db.relationship('users', backref='cash_payment_requests')