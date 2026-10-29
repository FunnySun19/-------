import sqlite3
import os

# Bothost использует /app/data для постоянного хранения файлов.
# Если папка существует, используем её, иначе (локально) - текущую директорию.
if os.path.exists("/app/data"):
    DB_PATH = "/app/data/stable.db"
else:
    DB_PATH = "stable.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            time_slot TEXT NOT NULL,
            instructor TEXT NOT NULL,
            horse_name TEXT NOT NULL,
            task_type TEXT NOT NULL,
            created_by TEXT,
            created_by_name TEXT,
            updated_at TEXT,
            updated_by TEXT,
            deleted_at TEXT DEFAULT NULL,
            deleted_by TEXT DEFAULT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS horses (
            name TEXT PRIMARY KEY,
            status TEXT DEFAULT 'доступна',
            care_notes TEXT DEFAULT ''
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER,
            action TEXT,
            actor TEXT,
            details TEXT,
            timestamp TEXT DEFAULT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            tg_id INTEGER PRIMARY KEY,
            name TEXT UNIQUE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS auth_users (
            tg_id INTEGER PRIMARY KEY,
            name TEXT,
            authorized_at TEXT
        )
    """)

    conn.commit()
    conn.close()