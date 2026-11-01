import sqlite3
import os

# В Amvera постоянное хранилище находится в /data
# Локально (для тестов) база будет создаваться рядом с файлом
if os.path.exists("/data"):
    DB_PATH = "/data/stable.db"
else:
    DB_PATH = "stable.db"

def init_db():
    """Создает таблицы при первом запуске."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Таблица расписания (прокаты и поручения)
    c.execute("""
        CREATE TABLE IF NOT EXISTS schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_type TEXT NOT NULL,
            date TEXT NOT NULL,
            time_slot TEXT DEFAULT '',
            task_type TEXT NOT NULL,
            duration TEXT DEFAULT '',
            horse_name TEXT DEFAULT '',
            comment TEXT DEFAULT '',
            required_instructors INTEGER DEFAULT 1,
            assigned_instructors TEXT DEFAULT '',
            created_by TEXT,
            created_by_name TEXT,
            updated_at TEXT,
            updated_by TEXT,
            deleted_at TEXT DEFAULT NULL,
            deleted_by TEXT DEFAULT NULL
        )
    """)

    # Журнал действий
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

    # Связка ID и имени сотрудника
    c.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            tg_id INTEGER PRIMARY KEY,
            name TEXT UNIQUE
        )
    """)

    # Авторизованные пользователи
    c.execute("""
        CREATE TABLE IF NOT EXISTS auth_users (
            tg_id INTEGER PRIMARY KEY,
            name TEXT,
            authorized_at TEXT
        )
    """)

    conn.commit()
    conn.close()