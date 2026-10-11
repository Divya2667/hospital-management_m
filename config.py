import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory of the project
BASE_DIR = Path(__file__).resolve().parent

# Load environment variables from .env file
load_dotenv(BASE_DIR / ".env")


class Config:
    """Base configuration class."""
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-fallback-key-hospital-mgmt-academic-2025")
    
    # MongoDB Connection Settings
    MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/hospital_management")
    MONGO_DB_NAME = os.environ.get("MONGO_DB_NAME", "hospital_management")

    # Clinic Scheduling Settings
    CLINIC_OPEN_TIME = os.environ.get("CLINIC_OPEN_TIME", "09:00")
    CLINIC_CLOSE_TIME = os.environ.get("CLINIC_CLOSE_TIME", "17:00")
    DEFAULT_APPOINTMENT_DURATION = int(os.environ.get("DEFAULT_APPOINTMENT_DURATION", 30))

    # Security & Session Settings
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None  # Academic convenience for forms


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    TESTING = False


class TestingConfig(Config):
    """Testing configuration with in-memory isolated test database."""
    DEBUG = False
    TESTING = True
    WTF_CSRF_ENABLED = False  # Simplify automated client testing
    MONGO_URI = "mongomock://localhost"
    MONGO_DB_NAME = "hospital_management_test"


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    TESTING = False


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
