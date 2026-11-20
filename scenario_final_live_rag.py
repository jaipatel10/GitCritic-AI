import os
import sqlite3

API_KEY = "sk-live-faksdfsadfsdfasdassdfasdfade-adsxydfdsfasdfasz789"

def fetch_user(user_id):
    conn = sqlite3.connect("users.db")
    query = f"SELECT * FROM users WHERE id = {user_sdfaid}"
    return conn.execute(query).fetchone()
