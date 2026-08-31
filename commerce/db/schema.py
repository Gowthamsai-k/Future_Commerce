from commerce.db.connection import get_connection


def initialize_database() -> None:
    connection = get_connection()
    connection.execute("""CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price REAL NOT NULL,
        description TEXT NOT NULL,
        category TEXT NOT NULL,
        brand TEXT,
        stock INTEGER NOT NULL DEFAULT 0
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        shipping_address TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        total REAL NOT NULL,
        unit_price REAL,
        status TEXT NOT NULL,
        customer_id INTEGER,
        customer_name TEXT,
        customer_email TEXT,
        shipping_address TEXT,
        payment_method TEXT,
        payment_status TEXT NOT NULL DEFAULT 'pending',
        payment_failure_reason TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(product_id) REFERENCES products(id),
        FOREIGN KEY(customer_id) REFERENCES customers(id)
    )""")
    columns = {row[1] for row in connection.execute("PRAGMA table_info(orders)")}
    migrations = {
        "unit_price": "REAL", "customer_id": "INTEGER", "customer_name": "TEXT",
        "customer_email": "TEXT", "shipping_address": "TEXT", "payment_method": "TEXT",
        "payment_status": "TEXT NOT NULL DEFAULT 'pending'", "payment_failure_reason": "TEXT",
        "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
    }
    for column, definition in migrations.items():
        if column not in columns:
            connection.execute(f"ALTER TABLE orders ADD COLUMN {column} {definition}")
    connection.execute("UPDATE orders SET unit_price = total / quantity WHERE unit_price IS NULL AND quantity > 0")
    connection.commit()
    connection.close()