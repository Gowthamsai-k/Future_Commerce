from commerce.db.connection import get_connection

STATUSES = {"created", "processing", "shipped", "delivered", "cancelled"}


def search_products(query: str, max_price=None, category=None, min_price=None):
    connection = get_connection()
    sql = "SELECT * FROM products WHERE (name LIKE ? OR description LIKE ? OR category LIKE ? OR brand LIKE ?)"
    search = f"%{query}%"
    params = [search, search, search, search]
    if max_price is not None:
        sql += " AND price <= ?"; params.append(max_price)
    if min_price is not None:
        sql += " AND price >= ?"; params.append(min_price)
    if category is not None:
        sql += " AND category = ?"; params.append(category)
    rows = connection.execute(sql, params).fetchall(); connection.close()
    return [dict(row) for row in rows]


def list_products(category=None, include_out_of_stock=False, min_price=None, max_price=None):
    connection = get_connection(); filters = []; params = []
    if category is not None: filters.append("category = ?"); params.append(category)
    if not include_out_of_stock: filters.append("stock > 0")
    if min_price is not None: filters.append("price >= ?"); params.append(min_price)
    if max_price is not None: filters.append("price <= ?"); params.append(max_price)
    sql = "SELECT * FROM products" + (" WHERE " + " AND ".join(filters) if filters else "") + " ORDER BY name"
    rows = connection.execute(sql, params).fetchall(); connection.close()
    return [dict(row) for row in rows]


def get_product(product_id: int):
    connection = get_connection(); row = connection.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone(); connection.close()
    return dict(row) if row else {"error": "Product not found"}


def check_inventory(product_id: int):
    connection = get_connection(); row = connection.execute("SELECT id, name, stock FROM products WHERE id = ?", (product_id,)).fetchone(); connection.close()
    if not row: return {"available": False, "reason": "Product not found"}
    return {"product_id": row["id"], "product": row["name"], "stock": row["stock"], "available": row["stock"] > 0}


def register_customer(name: str, email: str, shipping_address=None):
    name, email = name.strip(), email.strip().lower()
    if not name or "@" not in email: return {"success": False, "error": "Name and a valid email are required"}
    connection = get_connection()
    connection.execute("""INSERT INTO customers (name, email, shipping_address) VALUES (?, ?, ?)
        ON CONFLICT(email) DO UPDATE SET name = excluded.name, shipping_address = excluded.shipping_address, updated_at = CURRENT_TIMESTAMP""", (name, email, shipping_address))
    connection.commit(); row = connection.execute("SELECT * FROM customers WHERE email = ?", (email,)).fetchone(); connection.close()
    return {"success": True, "customer": dict(row)}


def get_customer(customer_id: int):
    connection = get_connection(); row = connection.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone(); connection.close()
    return dict(row) if row else {"error": "Customer not found"}


def create_order(product_id: int, quantity: int, customer_name=None, customer_email=None, shipping_address=None, payment_method=None, customer_id=None):
    if quantity <= 0: return {"success": False, "error": "Quantity must be greater than zero"}
    if customer_email is not None and "@" not in customer_email: return {"success": False, "error": "A valid customer email is required"}
    connection = get_connection(); connection.execute("BEGIN IMMEDIATE")
    if customer_id is not None:
        customer = connection.execute("SELECT id, name, email, shipping_address FROM customers WHERE id = ?", (customer_id,)).fetchone()
        if not customer: connection.close(); return {"success": False, "error": "Customer not found"}
        customer_name, customer_email = customer["name"], customer["email"]
        shipping_address = shipping_address or customer["shipping_address"]
    product = connection.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not product: connection.close(); return {"success": False, "error": "Product not found"}
    if product["stock"] < quantity: connection.close(); return {"success": False, "error": "Not enough stock"}
    total = product["price"] * quantity
    cursor = connection.execute("""INSERT INTO orders (product_id, quantity, total, unit_price, status, customer_id, customer_name, customer_email, shipping_address, payment_method, payment_status)
        VALUES (?, ?, ?, ?, 'created', ?, ?, ?, ?, ?, 'pending')""", (product_id, quantity, total, product["price"], customer_id, customer_name, customer_email, shipping_address, payment_method))
    connection.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (quantity, product_id)); connection.commit(); connection.close()
    return {"success": True, "order_id": cursor.lastrowid, "product": product["name"], "quantity": quantity, "total": total, "status": "created"}


def process_payment(order_id: int, payment_succeeded: bool, failure_reason=None):
    connection = get_connection(); connection.execute("BEGIN IMMEDIATE")
    order = connection.execute("SELECT product_id, quantity, status, payment_status FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not order: connection.close(); return {"success": False, "error": "Order not found"}
    if order["payment_status"] == "paid": connection.close(); return {"success": True, "order_id": order_id, "payment_status": "paid", "already_processed": True}
    if order["status"] == "cancelled": connection.close(); return {"success": False, "error": "A cancelled order cannot be paid"}
    if payment_succeeded:
        connection.execute("UPDATE orders SET payment_status = 'paid', status = 'processing', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (order_id,)); connection.commit(); connection.close()
        return {"success": True, "order_id": order_id, "payment_status": "paid", "status": "processing"}
    reason = failure_reason or "Payment failed"
    connection.execute("UPDATE products SET stock = stock + ? WHERE id = ?", (order["quantity"], order["product_id"]))
    connection.execute("UPDATE orders SET payment_status = 'failed', payment_failure_reason = ?, status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (reason, order_id)); connection.commit(); connection.close()
    return {"success": False, "order_id": order_id, "payment_status": "failed", "status": "cancelled", "error": reason}


def find_alternative_products(product_id: int, max_price=None):
    connection = get_connection(); product = connection.execute("SELECT category, price FROM products WHERE id = ?", (product_id,)).fetchone()
    if not product: connection.close(); return {"error": "Product not found"}
    limit = max_price if max_price is not None else product["price"] * 1.25
    rows = connection.execute("SELECT * FROM products WHERE category = ? AND id != ? AND stock > 0 AND price <= ? ORDER BY ABS(price - ?), price", (product["category"], product_id, limit, product["price"])).fetchall(); connection.close()
    return [dict(row) for row in rows]


def _order_query():
    return """SELECT orders.id AS order_id, orders.product_id, products.name AS product, products.brand, orders.quantity, orders.unit_price, orders.total, orders.status, orders.customer_id, orders.customer_name, orders.customer_email, orders.shipping_address, orders.payment_method, orders.payment_status, orders.payment_failure_reason, orders.created_at, orders.updated_at FROM orders JOIN products ON products.id = orders.product_id"""


def list_orders(status=None, customer_id=None, customer_email=None):
    if status is not None and status not in STATUSES: return {"error": f"Status must be one of: {', '.join(sorted(STATUSES))}"}
    connection = get_connection(); filters = []; params = []
    for field, value in (("orders.status", status), ("orders.customer_id", customer_id), ("orders.customer_email", customer_email)):
        if value is not None: filters.append(f"{field} = ?"); params.append(value)
    sql = _order_query() + ((" WHERE " + " AND ".join(filters)) if filters else "") + " ORDER BY orders.created_at DESC, orders.id DESC"
    rows = connection.execute(sql, params).fetchall(); connection.close(); return [dict(row) for row in rows]


def get_order(order_id: int):
    connection = get_connection(); row = connection.execute(_order_query() + " WHERE orders.id = ?", (order_id,)).fetchone(); connection.close()
    return dict(row) if row else {"error": "Order not found"}


def cancel_order(order_id: int):
    connection = get_connection(); connection.execute("BEGIN IMMEDIATE"); order = connection.execute("SELECT product_id, quantity, status FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not order: connection.close(); return {"success": False, "error": "Order not found"}
    if order["status"] == "cancelled": connection.close(); return {"success": True, "order_id": order_id, "status": "cancelled", "already_cancelled": True}
    if order["status"] in {"shipped", "delivered"}: connection.close(); return {"success": False, "error": f"Order cannot be cancelled when {order['status']}"}
    connection.execute("UPDATE products SET stock = stock + ? WHERE id = ?", (order["quantity"], order["product_id"]))
    connection.execute("UPDATE orders SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (order_id,)); connection.commit(); connection.close()
    return {"success": True, "order_id": order_id, "status": "cancelled"}


def update_order_status(order_id: int, status: str):
    if status not in STATUSES: return {"success": False, "error": f"Status must be one of: {', '.join(sorted(STATUSES))}"}
    if status == "cancelled": return cancel_order(order_id)
    connection = get_connection(); order = connection.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not order: connection.close(); return {"success": False, "error": "Order not found"}
    if order["status"] == "cancelled" and status != "cancelled": connection.close(); return {"success": False, "error": "A cancelled order cannot be reopened"}
    if order["status"] == "delivered" and status != "delivered": connection.close(); return {"success": False, "error": "A delivered order cannot change status"}
    connection.execute("UPDATE orders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (status, order_id)); connection.commit(); connection.close()
    return {"success": True, "order_id": order_id, "status": status}


def list_customer_orders(customer_id: int):
    return list_orders(customer_id=customer_id)