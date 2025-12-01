import os

db_path = "test.db"

if os.path.exists(db_path):
    os.remove(db_path)
    print("🔥 Deleted old test.db")
else:
    print("No old DB found")
