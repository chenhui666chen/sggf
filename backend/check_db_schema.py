"""检查数据库表结构"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "novel_app.db")

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

print("📋 setting_items 表结构:")
print("="*60)
cursor.execute("PRAGMA table_info(setting_items)")
columns = cursor.fetchall()

for col in columns:
    cid, name, dtype, notnull, default, pk = col
    print(f"  {cid}. {name:20} {dtype:15} {'NOT NULL' if notnull else ''} {'PRIMARY KEY' if pk else ''}")

conn.close()
