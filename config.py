import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Application configuration"""

    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'

    # Database
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URI', 'sqlite:///crm.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Turso auth token for cloud database
    TURSO_AUTH_TOKEN = os.getenv('TURSO_AUTH_TOKEN', '')

    # Pass auth token to libsql driver if using Turso
    SQLALCHEMY_ENGINE_OPTIONS = (
        {'connect_args': {'auth_token': os.getenv('TURSO_AUTH_TOKEN')}}
        if os.getenv('TURSO_AUTH_TOKEN')
        else {}
    )

    # Email Rate Limiting
    DEFAULT_MAX_EMAILS_PER_HOUR = int(os.getenv('MAX_EMAILS_PER_HOUR', '5'))
    DEFAULT_SENDING_HOURS_START = int(os.getenv('SENDING_HOURS_START', '9'))  # 9 AM
    DEFAULT_SENDING_HOURS_END = int(os.getenv('SENDING_HOURS_END', '17'))  # 5 PM

    # Scheduler
    RESPONSE_CHECK_INTERVAL_MINUTES = int(os.getenv('RESPONSE_CHECK_INTERVAL', '10'))
    SEND_CHECK_INTERVAL_MINUTES = int(os.getenv('SEND_CHECK_INTERVAL', '60'))

    # Security
    BASIC_AUTH_USERNAME = os.getenv('AUTH_USERNAME', 'admin')
    BASIC_AUTH_PASSWORD = os.getenv('AUTH_PASSWORD', 'changeme')

    # Application
    TIMEZONE = os.getenv('TIMEZONE', 'America/Mexico_City')

    # Deliverability Guardrails
    SPIKE_WINDOW_MINUTES = int(os.getenv('SPIKE_WINDOW_MINUTES', '60'))
    SPIKE_BOUNCE_RATE = float(os.getenv('SPIKE_BOUNCE_RATE', '5.0'))  # %
    SPIKE_FAILURE_RATE = float(os.getenv('SPIKE_FAILURE_RATE', '10.0'))  # %
