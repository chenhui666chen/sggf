import requests
import json

url = "https://sggf.net/api/v1/auth/login"
headers = {"Content-Type": "application/json"}
data = {"username": "admin", "password": "admin123"}

response = requests.post(url, headers=headers, json=data, verify=False)
print(f"Status Code: {response.status_code}")
print(f"Response: {response.text}")
