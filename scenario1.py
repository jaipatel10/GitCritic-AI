import os

API_SECRET = "sk-live-fake-xyz789"

def fetch_user(user_id):
    query = f"SELECT * FROM users WHERE id = {user_id}"
    return db.execute(query)
