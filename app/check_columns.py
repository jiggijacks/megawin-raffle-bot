import sqlite3

# Connect to the SQLite database
conn = sqlite3.connect('raffle.db')
cursor = conn.cursor()

# Run PRAGMA statement to get table info
cursor.execute("PRAGMA table_info(entries);")
columns = cursor.fetchall()

# Print the columns
for column in columns:
    print(column)

conn.close()
