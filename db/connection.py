import psycopg2
from config.config import Config


def get_connection():
    """
    Returns a new PostgreSQL connection using project configuration.
    """
    return psycopg2.connect(
        host=Config.DB_HOST,
        user=Config.DB_USER,
        password=Config.DB_PASSWORD,
        dbname=Config.DB_NAME,
        port=getattr(Config, "DB_PORT", 5432),
    )

