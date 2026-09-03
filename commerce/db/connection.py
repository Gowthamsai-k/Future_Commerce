import sqlite3

from commerce.config import DB_NAME


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_NAME, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection