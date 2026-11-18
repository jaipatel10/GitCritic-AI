"""Test file for CriticAI review — intentionally contains bugs."""
import os
import sqlite3

# Issue 1: hardcoded API key
API_KEY = "sk-live-fake-abc123def456ghi789"

# Issue 2: SQL injection
def get_user(user_id):
    conn = sqlite3.connect("users.db")
    query = f"SELECT * FROM users WHERE id = '{user_id}'"
    return conn.execute(query).fetchone()

# Issue 3: no error handling, broad except
def risky_operation(data):
    try:
        result = process(data)
        return result
    except:
        return None

# Issue 4: N+1 pattern
def get_users_with_orders():
    users = db.execute("SELECT * FROM users").fetchall()
    result = []
    for user in users:
        orders = db.execute(f"SELECT * FROM orders WHERE user_id = {user['id']}").fetchall()
        result.append({"user": user, "orders": orders})
    return result
