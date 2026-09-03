import anyio
import uvicorn
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import PlainTextResponse

from commerce.config import MCP_HOST, MCP_PORT
from commerce.db.schema import initialize_database
from commerce.db.seed import seed_products
from commerce.store import service

load_dotenv()
initialize_database()
seed_products()

allowed_hosts = [f"localhost:{MCP_PORT}", f"127.0.0.1:{MCP_PORT}", f"0.0.0.0:{MCP_PORT}"]
security = TransportSecuritySettings(allowed_hosts=allowed_hosts, allowed_origins=[f"http://localhost:{MCP_PORT}", f"http://127.0.0.1:{MCP_PORT}"])
mcp = FastMCP("Gaming Store", host=MCP_HOST, port=MCP_PORT, streamable_http_path="/mcp", transport_security=security)


@mcp.tool()
def search_product(query: str, max_price: float | None = None, category: str | None = None, min_price: float | None = None):
    """Search products by buyer need, price range, or category."""
    return service.search_products(query, max_price, category, min_price)


@mcp.tool()
def list_products(category: str | None = None, include_out_of_stock: bool = False, min_price: float | None = None, max_price: float | None = None):
    """List products available in the store."""
    rows = service.list_products(category, include_out_of_stock, min_price, max_price)
    if isinstance(rows, list) and len(rows) > 0:
        by_cat = {}
        for r in rows:
            cat = (r.get("category") or "General").capitalize()
            by_cat.setdefault(cat, []).append(f" - **{r.get('name')}** (ID #{r.get('id')}): ₹{r.get('price'):,.2f} [Stock: {r.get('stock')}]")
        lines = ["Here is our complete catalog of available products:\n"]
        for cat, items in sorted(by_cat.items()):
            lines.append(f"### {cat}")
            lines.extend(items)
            lines.append("")
        return "\n".join(lines)
    return rows


@mcp.tool()
def get_product(product_id: int):
    """Get complete product details."""
    return service.get_product(product_id)


@mcp.tool()
def check_inventory(product_id: int):
    """Check current stock for a product."""
    return service.check_inventory(product_id)


@mcp.tool()
def register_customer(name: str, email: str, shipping_address: str | None = None):
    """Create or update a buyer identity."""
    return service.register_customer(name, email, shipping_address)


@mcp.tool()
def get_customer(customer_id: int):
    """Retrieve a buyer identity."""
    return service.get_customer(customer_id)


@mcp.tool()
def create_order(product_id: int, quantity: int, customer_name: str | None = None, customer_email: str | None = None, shipping_address: str | None = None, payment_method: str | None = None, customer_id: int | None = None):
    """Reserve inventory and create a single-product order."""
    return service.create_order(product_id, quantity, customer_name, customer_email, shipping_address, payment_method, customer_id)


@mcp.tool()
def process_payment(order_id: int, payment_succeeded: bool = True, failure_reason: str | None = None, razorpay_payment_id: str | None = None, razorpay_signature: str | None = None, otp: str | None = None):
    """Record payment, verify OTP (default test OTP: 1111), and authorize order."""
    return service.process_payment(order_id, payment_succeeded, failure_reason, razorpay_payment_id, razorpay_signature, otp)


@mcp.tool()
def find_alternative_products(product_id: int, max_price: float | None = None):
    """Find similar in-stock products within a price limit."""
    return service.find_alternative_products(product_id, max_price)


@mcp.tool()
def list_orders(status: str | None = None, customer_id: int | None = None, customer_email: str | None = None):
    """List orders with optional buyer or status filters."""
    return service.list_orders(status, customer_id, customer_email)


@mcp.tool()
def get_order(order_id: int):
    """Get full order details."""
    return service.get_order(order_id)


@mcp.tool()
def list_customer_orders(customer_id: int):
    """List all orders for a buyer."""
    return service.list_customer_orders(customer_id)


@mcp.tool()
def cancel_order(order_id: int):
    """Cancel an order and restore reserved inventory."""
    return service.cancel_order(order_id)


@mcp.tool()
def update_order_status(order_id: int, status: str):
    """Update fulfillment status."""
    return service.update_order_status(order_id, status)


async def run_http_server():
    app = mcp.sse_app()

    async def homepage(request):
        return PlainTextResponse("Gaming Store MCP server is running. MCP SSE endpoint: /sse")

    app.add_route("/", homepage, methods=["GET"])
    await uvicorn.Server(uvicorn.Config(app, host=MCP_HOST, port=MCP_PORT, log_level="info")).serve()


def main():
    if __import__("os").getenv("MCP_TRANSPORT", "streamable-http") == "streamable-http":
        anyio.run(run_http_server)
    else:
        mcp.run(transport=__import__("os").getenv("MCP_TRANSPORT"))