import os


class Config:
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
    API_URL = "https://example.com/api/add"
    
    DB_HOST = 'localhost'
    DB_USER = 'root'
    DB_PASSWORD = "WamApo99"
    DB_NAME = "excel_data"
    
    SECRET_KEY = os.urandom(24)
    