import sqlite3

DB_NAME = "gaming_store.db"

def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def initilize_database():
    conn = get_connection()
    conn.execute("""CREATE TABLE IF NOT EXISTS products (
    id Integer Primary Key AUTOINCREMENT , 
    name Text Not Null , 
    price real not null , 
    description real not null , 
    category real not null, 
    brand text , 
    stock Integer not null default 0
    )""")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            total REAL NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY(product_id)
                REFERENCES products(id)
        )
    """)
    conn.commit()
    conn.close()

initilize_database()