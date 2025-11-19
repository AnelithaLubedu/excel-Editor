import requests
from config.config import Config


def send_to_api(row):
    """
    Sends a single row (dictionary) to an external API
    """
    try:
        response = requests.post(Config.API_URL, json=row)
        print(f"Sent row to API, status: {response.status_code}")
        return response.status_code
    except Exception as e:
        print("Error sending row to API:", e)
        return None



