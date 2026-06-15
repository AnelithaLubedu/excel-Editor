import os


class Config:
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
    API_URL = "https://example.com/api/add"
    
    # PostgreSQL connection settings
    DB_HOST = "localhost"
    DB_PORT = 5432
    DB_USER = "postgres"
    DB_PASSWORD = "root"
    DB_NAME = "lunge_orchestration"
    
    SECRET_KEY = os.urandom(24)
    