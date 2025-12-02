import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-key")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///local.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # myPOS Device Configuration
    MYPOS_DEVICE_URL = os.getenv("MYPOS_DEVICE_URL", "http://192.168.1.100:8080")
    MYPOS_DEVICE_CONFIGURED = os.getenv("MYPOS_DEVICE_CONFIGURED", "false").lower() == "true"

    # PayPal API / Polling
    PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "")
    PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "")
    _paypal_env = os.getenv("PAYPAL_ENV", "live").lower()
    PAYPAL_API_BASE = "https://api-m.sandbox.paypal.com" if _paypal_env == "sandbox" else "https://api-m.paypal.com"
    PAYPAL_IPN_URL = os.getenv("PAYPAL_IPN_URL", "http://10.100.5.89:5004/api/payment/paypal-ipn")
    PAYPAL_POLL_INTERVAL_SECONDS = int(os.getenv("PAYPAL_POLL_INTERVAL_SECONDS", "15"))
    PAYPAL_REPORTING_LOOKBACK_MINUTES = int(os.getenv("PAYPAL_REPORTING_LOOKBACK_MINUTES", "240"))
    PAYPAL_BACKGROUND_POLL_SECONDS = int(os.getenv("PAYPAL_BACKGROUND_POLL_SECONDS", "120"))
    PAYPAL_BACKGROUND_POLL_ENABLED = os.getenv("PAYPAL_BACKGROUND_POLL_ENABLED", "true").lower() == "true"
    PAYPAL_PENDING_EXPIRATION_HOURS = int(os.getenv("PAYPAL_PENDING_EXPIRATION_HOURS", "72"))
    CANCELLED_PAYMENT_RETENTION_HOURS = int(os.getenv("CANCELLED_PAYMENT_RETENTION_HOURS", "48"))
    
    # Cashbook automation
    CASHBOOK_AUTO_COMPANY = os.getenv("CASHBOOK_AUTO_COMPANY", "Kaffeemaschine")
    CASHBOOK_SUMMARY_COMPANY = os.getenv("CASHBOOK_SUMMARY_COMPANY", "Schülerfirma")
