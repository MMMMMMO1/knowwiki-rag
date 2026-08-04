import sqlite3
import os

db_path = "/Users/duhakeer/program/wiki/wiki-backend/anythingllm/storage/anythingllm.db"

if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    print("Tables in database:", [t[0] for t in tables])

    if ('embed_configs',) in tables or any('embed_configs' in t[0] for t in tables):
        cursor.execute("SELECT id, uuid, enabled, workspace_id FROM embed_configs;")
        embeds = cursor.fetchall()
        print("\nEmbed configs:")
        for embed in embeds:
            print(f"ID: {embed[0]}, UUID: {embed[1]}, Enabled: {embed[2]}, Workspace ID: {embed[3]}")
    else:
        print("\nembed_configs table not found!")
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
