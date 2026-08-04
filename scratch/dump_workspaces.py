import sqlite3
import os

db_path = "/Users/duhakeer/program/wiki/wiki-backend/anythingllm/storage/anythingllm.db"

if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    cursor.execute("SELECT id, name, slug FROM workspaces;")
    workspaces = cursor.fetchall()
    print("Workspaces:")
    for ws in workspaces:
        print(f"ID: {ws[0]}, Name: {ws[1]}, Slug: {ws[2]}")
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
