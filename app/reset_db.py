import os

db_path = "app/test.db"

if os.path.exists(db_path):
    os.remove(db_path)
    print("🔥 Deleted old SQLite DB:", db_path)
else:
    print("No DB found:", db_path)
