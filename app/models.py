from . import db
from datetime import datetime

class roles(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)

class beverage_prices(db.Model):
    __tablename__ = "beverage_prices"
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