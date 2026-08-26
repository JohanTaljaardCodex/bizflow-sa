import os
import sqlite3

DB_NAME = os.getenv("BIZFLOW_DB_PATH", "bizflow.db")


def get_connection():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000;")
    return conn


def add_column_if_missing(cursor, table, column, definition):
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    if column not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def create_database():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL;")
    except sqlite3.OperationalError:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'Pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    add_column_if_missing(cursor, "tasks", "priority", "TEXT DEFAULT 'Normal'")
    add_column_if_missing(cursor, "tasks", "due_date", "TEXT")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            phone TEXT,
            source TEXT,
            status TEXT DEFAULT 'New',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    add_column_if_missing(cursor, "leads", "followup_draft", "TEXT")
    add_column_if_missing(cursor, "leads", "followup_status", "TEXT DEFAULT 'Not Drafted'")
    add_column_if_missing(cursor, "leads", "pipeline_stage", "TEXT DEFAULT 'New Lead'")
    add_column_if_missing(cursor, "leads", "lead_value", "REAL DEFAULT 0")
    add_column_if_missing(cursor, "leads", "next_followup", "TEXT")
    add_column_if_missing(cursor, "leads", "notes", "TEXT")
    add_column_if_missing(cursor, "leads", "lead_score", "INTEGER DEFAULT 20")
    add_column_if_missing(cursor, "leads", "last_scored_at", "TEXT")
    add_column_if_missing(cursor, "leads", "last_followup_alert", "TEXT")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            phone TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT,
            details TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS content_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            content TEXT,
            status TEXT DEFAULT 'Pending Approval',
            platform TEXT DEFAULT 'Instagram',
            scheduled_for TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    add_column_if_missing(cursor, "content_queue", "platform", "TEXT DEFAULT 'Instagram'")
    add_column_if_missing(cursor, "content_queue", "scheduled_for", "TEXT")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS operator_status (
            id INTEGER PRIMARY KEY,
            status TEXT,
            last_heartbeat TEXT,
            last_cycle_started TEXT,
            last_cycle_completed TEXT,
            last_error TEXT
        )
    """)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    create_database()
    print("BizFlow database updated successfully.")
