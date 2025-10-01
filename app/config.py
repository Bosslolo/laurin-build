import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-key")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///local.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
