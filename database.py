import os
import sqlite3

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
SQLITE_DB = "bizflow.db"


class DatabaseCursor:
    def __init__(self, cursor, postgres=False):
        self.cursor = cursor
        self.postgres = postgres
        self._lastrowid = None

    def execute(self, sql, params=None):
        if params is None:
            params = ()

        if self.postgres:
            sql = sql.replace("?", "%s")

        result = self.cursor.execute(
            sql,
            params
        )

        try:
            self._lastrowid = self.cursor.lastrowid
        except Exception:
            self._lastrowid = None

        return result

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    @property
    def lastrowid(self):
        return self._lastrowid


class DatabaseConnection:
    def __init__(self, connection, postgres=False):
        self.connection = connection
        self.postgres = postgres

    def cursor(self):
        return DatabaseCursor(
            self.connection.cursor(),
            postgres=self.postgres
        )

    def execute(self, sql, params=None):
        cursor = self.cursor()
        cursor.execute(sql, params)
        return cursor

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


def is_postgres():
    return bool(DATABASE_URL)


def get_connection():
    if is_postgres():
        import psycopg

        connection = psycopg.connect(
            DATABASE_URL,
            connect_timeout=30
        )

        return DatabaseConnection(
            connection,
            postgres=True
        )

    connection = sqlite3.connect(
        SQLITE_DB,
        timeout=30
    )

    connection.execute(
        "PRAGMA busy_timeout=30000;"
    )

    return DatabaseConnection(
        connection,
        postgres=False
    )


def add_column_if_missing(
    cursor,
    table,
    column,
    sqlite_definition,
    postgres_definition=None
):
    if is_postgres():
        definition = (
            postgres_definition
            or sqlite_definition
        )

        cursor.execute(
            f"""
            ALTER TABLE {table}
            ADD COLUMN IF NOT EXISTS
            {column} {definition}
            """
        )

        return

    cursor.execute(
        f"PRAGMA table_info({table})"
    )

    columns = [
        row[1]
        for row in cursor.fetchall()
    ]

    if column not in columns:
        cursor.execute(
            f"""
            ALTER TABLE {table}
            ADD COLUMN {column}
            {sqlite_definition}
            """
        )


def create_database():
    conn = get_connection()
    cursor = conn.cursor()

    # =====================================================
    # TASKS
    # =====================================================

    if is_postgres():

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id BIGSERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'Pending',
                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            )
        """)

    else:

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'Pending',
                created_at DATETIME
                    DEFAULT CURRENT_TIMESTAMP
            )
        """)

    add_column_if_missing(
        cursor,
        "tasks",
        "priority",
        "TEXT DEFAULT 'Normal'"
    )

    add_column_if_missing(
        cursor,
        "tasks",
        "due_date",
        "TEXT"
    )

    # =====================================================
    # LEADS
    # =====================================================

    if is_postgres():

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id BIGSERIAL PRIMARY KEY,
                name TEXT,
                email TEXT,
                phone TEXT,
                source TEXT,
                status TEXT DEFAULT 'New',
                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            )
        """)

    else:

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT,
                phone TEXT,
                source TEXT,
                status TEXT DEFAULT 'New',
                created_at DATETIME
                    DEFAULT CURRENT_TIMESTAMP
            )
        """)

    add_column_if_missing(
        cursor,
        "leads",
        "followup_draft",
        "TEXT"
    )

    add_column_if_missing(
        cursor,
        "leads",
        "followup_status",
        "TEXT DEFAULT 'Not Drafted'"
    )

    add_column_if_missing(
        cursor,
        "leads",
        "pipeline_stage",
        "TEXT DEFAULT 'New Lead'"
    )

    add_column_if_missing(
        cursor,
        "leads",
        "lead_value",
        "REAL DEFAULT 0",
        "DOUBLE PRECISION DEFAULT 0"
    )

    add_column_if_missing(
        cursor,
        "leads",
        "next_followup",
        "TEXT"
    )

    add_column_if_missing(
        cursor,
        "leads",
        "notes",
        "TEXT"
    )

    add_column_if_missing(
        cursor,
        "leads",
        "lead_score",
        "INTEGER DEFAULT 20"
    )

    add_column_if_missing(
        cursor,
        "leads",
        "last_scored_at",
        "TEXT"
    )

    add_column_if_missing(
        cursor,
        "leads",
        "last_followup_alert",
        "TEXT"
    )

    # =====================================================
    # CUSTOMERS
    # =====================================================

    if is_postgres():

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id BIGSERIAL PRIMARY KEY,
                name TEXT,
                email TEXT,
                phone TEXT,
                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            )
        """)

    else:

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT,
                phone TEXT,
                created_at DATETIME
                    DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # =====================================================
    # ACTIVITY
    # =====================================================

    if is_postgres():

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS activity (
                id BIGSERIAL PRIMARY KEY,
                action TEXT,
                details TEXT,
                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            )
        """)

    else:

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT,
                details TEXT,
                created_at DATETIME
                    DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # =====================================================
    # CONTENT
    # =====================================================

    if is_postgres():

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS content_queue (
                id BIGSERIAL PRIMARY KEY,
                title TEXT,
                content TEXT,
                status TEXT
                    DEFAULT 'Pending Approval',
                platform TEXT
                    DEFAULT 'Instagram',
                scheduled_for TEXT,
                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            )
        """)

    else:

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS content_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                content TEXT,
                status TEXT
                    DEFAULT 'Pending Approval',
                platform TEXT
                    DEFAULT 'Instagram',
                scheduled_for TEXT,
                created_at DATETIME
                    DEFAULT CURRENT_TIMESTAMP
            )
        """)

    add_column_if_missing(
        cursor,
        "content_queue",
        "platform",
        "TEXT DEFAULT 'Instagram'"
    )

    add_column_if_missing(
        cursor,
        "content_queue",
        "scheduled_for",
        "TEXT"
    )

    # =====================================================
    # OPERATOR HEARTBEAT
    # =====================================================

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

    if is_postgres():
        print(
            "BizFlow PostgreSQL database "
            "updated successfully."
        )
    else:
        print(
            "BizFlow SQLite database "
            "updated successfully."
        )