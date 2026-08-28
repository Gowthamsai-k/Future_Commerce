import os
import anyio
import uvicorn

from mcp.server.fastmcp import FastMCP as MCPServer
from database import get_connection

from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import PlainTextResponse

PORT = int(os.getenv("PORT", "8000"))
INSPECTOR_PORT = int(os.getenv("MCP_INSPECTOR_PORT", "6274"))
codespace_name = os.getenv("CODESPACE_NAME")
allowed_hosts = [
    f"localhost:{PORT}",
    f"127.0.0.1:{PORT}",
    f"0.0.0.0:{PORT}",
]
allowed_origins = [
    f"http://localhost:{PORT}",
    f"http://127.0.0.1:{PORT}",
    f"http://localhost:{INSPECTOR_PORT}",
    f"http://127.0.0.1:{INSPECTOR_PORT}",
]
if codespace_name:
    codespace_host = f"{codespace_name}-{PORT}.app.github.dev"
    allowed_hosts.append(codespace_host)
    allowed_origins.append(f"https://{codespace_host}")
    inspector_host = f"{codespace_name}-{INSPECTOR_PORT}.app.github.dev"
    allowed_origins.append(f"https://{inspector_host}")

security = TransportSecuritySettings(
    allowed_hosts=allowed_hosts,
    allowed_origins=allowed_origins,
)

mcp = MCPServer(
    "Gaming Store",
    host=os.getenv("HOST", "0.0.0.0"),
    port=PORT,
    streamable_http_path="/mcp",
    transport_security=security,
)

@mcp.tool()
def search_product(
    query : str ,
    max_price : float | None = None , 
    category : str | None = None ):

    """
    Search gaming products in the store.

    Use this when a buyer is looking for gaming
    products based on name, category, brand,
    description, or price.
    """
    conn = get_connection()
    sql = """Select * from products where (name Like ? OR description like ? OR category like  ?  OR brand like ?)"""
    search = f"%{query}%"
    params = [
        search,
        search,
        search,
        search
    ]

    if max_price is not None:

        sql += " AND price <= ?"

        params.append(max_price)

    if category is not None:

        sql += " AND category = ?"

        params.append(category)

    products = conn.execute(
        sql,
        params
    ).fetchall()

    conn.close()

    return [
        dict(product)
        for product in products
    ]

@mcp.tool()

def get_product(product_id: int):
    """
    Get complete information about a gaming product,
    including price, brand, category and stock.
    """

    conn = get_connection()

    product = conn.execute(
        """
        SELECT *
        FROM products
        WHERE id = ?
        """,
        (product_id,)
    ).fetchone()

    conn.close()

    if product is None:

        return {
            "error": "Product not found"
        }

    return dict(product) 

@mcp.tool()

def check_inventory(product_id: int):
    """
    Check whether a gaming product is currently
    available in stock.
    """

    conn = get_connection()

    product = conn.execute(
        """
        SELECT
            id,
            name,
            stock
        FROM products
        WHERE id = ?
        """,
        (product_id,)
    ).fetchone()

    conn.close()

    if product is None:

        return {
            "available": False,
            "reason": "Product not found"
        }

    return {
        "product_id": product["id"],
        "product": product["name"],
        "stock": product["stock"],
        "available": product["stock"] > 0
    }
@mcp.tool()

def create_order(
    product_id: int,
    quantity: int
):
    """
    Create an order for a gaming product.

    Only use this after the buyer has confirmed
    that they want to purchase the product.
    """

    if quantity <= 0:

        return {
            "success": False,
            "error": "Quantity must be greater than zero"
        }

    conn = get_connection()

    product = conn.execute(
        """
        SELECT *
        FROM products
        WHERE id = ?
        """,
        (product_id,)
    ).fetchone()

    if product is None:

        conn.close()

        return {
            "success": False,
            "error": "Product not found"
        }

    if product["stock"] < quantity:

        conn.close()

        return {
            "success": False,
            "error": "Not enough stock"
        }

    total = product["price"] * quantity

    cursor = conn.execute(
        """
        INSERT INTO orders
        (
            product_id,
            quantity,
            total,
            status
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            product_id,
            quantity,
            total,
            "created"
        )
    )

    order_id = cursor.lastrowid

    conn.execute(
        """
        UPDATE products
        SET stock = stock - ?
        WHERE id = ?
        """,
        (
            quantity,
            product_id
        )
    )

    conn.commit()
    conn.close()

    return {
        "success": True,
        "order_id": order_id,
        "product": product["name"],
        "quantity": quantity,
        "total": total,
        "status": "created"
    }


async def run_http_server():
    app = mcp.streamable_http_app()

    async def homepage(request):
        return PlainTextResponse("Gaming Store MCP server is running. MCP endpoint: /mcp")

    app.add_route("/", homepage, methods=["GET"])
    config = uvicorn.Config(
        app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=PORT,
        log_level="info",
    )
    await uvicorn.Server(config).serve()


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "streamable-http")
    if transport == "streamable-http":
        anyio.run(run_http_server)
    else:
        mcp.run(transport=transport)
