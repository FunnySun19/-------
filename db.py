import sqlite3
import os

# Если папка /app/data существует (Bothost), используем её для сохранения базы.
# Иначе (при локальном тестировании) база создастся рядом с файлом.
if os.path.exists("/app/data"):
    DB_PATH = "/app/data/stable.db"
else:
    DB_PATH = "stable.db"


def init_db():
    """Создает все необходимые таблицы при первом запуске."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Таблица расписания (хранит и прокаты, и поручения)
    c.execute("""
        CREATE TABLE IF NOT EXISTS schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_type TEXT NOT NULL,          -- 'rental' (прокат) или 'task' (поручение)
            date TEXT NOT NULL,                 -- Дата в формате YYYY-MM-DD
            time_slot TEXT DEFAULT '',          -- Время (только для проката)
            task_type TEXT NOT NULL,            -- Тип проката или описание задачи
            duration TEXT DEFAULT '',           -- Длительность (только для проката)
            horse_name TEXT DEFAULT '',         -- Кличка лошади (только для поручения)
            comment TEXT DEFAULT '',            -- Комментарий к записи
            required_instructors INTEGER DEFAULT 1, -- Сколько нужно инструкторов
            assigned_instructors TEXT DEFAULT '',   -- Кто взял (имена через запятую)
            created_by TEXT,                    -- TG ID создателя
            created_by_name TEXT,               -- Имя создателя
            updated_at TEXT,                    -- Время последнего изменения (МСК)
            updated_by TEXT,                    -- Кто изменил
            deleted_at TEXT DEFAULT NULL,       -- Мягкое удаление (если не NULL - запись в корзине)
            deleted_by TEXT DEFAULT NULL        -- Кто удалил
        )
    """)

    # Таблица журнала действий (кто что сделал)
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

    # Таблица сотрудников (связка TG ID и имени для напоминаний/отметок)
    c.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            tg_id INTEGER PRIMARY KEY,
            name TEXT UNIQUE
        )
    """)

    # Таблица авторизованных пользователей (тех, кто ввел пароль)
    c.execute("""
        CREATE TABLE IF NOT EXISTS auth_users (
            tg_id INTEGER PRIMARY KEY,
            name TEXT,
            authorized_at TEXT
        )
    """)

    conn.commit()
    conn.close()