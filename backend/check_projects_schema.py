import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), "..", "novel_app.db")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("PRAGMA table_info(projects)")
columns = cursor.fetchall()

print("\n📋 projects 表结构:")
print("="*60)
for col in columns:
    print(f"{col[0]:3}. {col[1]:30} {col[2]:15} {'NOT NULL' if col[3] else ''}")

conn.close()
