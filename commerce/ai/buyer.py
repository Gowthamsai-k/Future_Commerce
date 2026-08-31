import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langchain_mcp_adapters.client import MultiServerMCPClient

from commerce.config import GROQ_API_KEY, GROQ_MODEL, MCP_URL

MAX_TOOL_ATTEMPTS = 3
PAYMENT_RETRY_ATTEMPTS = 3


class BuyerProtocolError(RuntimeError):
    """Raised when the strict buyer protocol cannot complete safely."""


def normalize_tool_result(result: Any) -> Any:
    if isinstance(result, list) and len(result) == 1 and isinstance(result[0], dict):
        content = result[0]
        if content.get("type") == "text":
            try:
                return json.loads(content["text"])
            except (KeyError, TypeError, json.JSONDecodeError):
                return content.get("text", result)
    return result


def stringify_tool_result(result: Any) -> str:
    normalized = normalize_tool_result(result)
    if isinstance(normalized, str):
        return normalized
    if normalized is None:
        return "null"
    if isinstance(normalized, (int, float, bool)):
        return str(normalized)
    return json.dumps(normalized, ensure_ascii=False, default=str)


async def call_with_retries(tool_by_name, name: str, arguments: dict[str, Any]):
    last_error = None
    for attempt in range(1, MAX_TOOL_ATTEMPTS + 1):
        try:
            return normalize_tool_result(await tool_by_name[name].ainvoke(arguments))
        except Exception as error:
            last_error = error
            if attempt < MAX_TOOL_ATTEMPTS:
                await asyncio.sleep(0.25 * attempt)
    raise BuyerProtocolError(f"MCP tool {name!r} failed after {MAX_TOOL_ATTEMPTS} attempts: {last_error}")


def result_error(result: Any) -> str | None:
    if isinstance(result, dict) and result.get("error"):
        return str(result["error"])
    if isinstance(result, dict) and result.get("success") is False:
        return str(result.get("error", "The operation failed"))
    return None


def summarize_audit(audit: list[dict[str, Any]] | None) -> dict[str, Any]:
    if not audit:
        return {}
    summary: dict[str, Any] = {}
    for entry in audit:
        if not isinstance(entry, dict):
            continue
        event = entry.get("event")
        payload = entry.get("payload") or entry.get("data") or {}
        if event == "purchase":
            for key in ("product", "total", "order_id", "status", "payment_status", "customer_name", "customer_email", "shipping_address"):
                if key in payload and payload[key] is not None:
                    summary[key] = payload[key]
        elif event == "payment_attempt":
            if "payment_status" in payload:
                summary["payment_status"] = payload["payment_status"]
            if "status" in payload:
                summary["status"] = payload["status"]
        elif event == "completed":
            if summary and "status" not in summary:
                summary["status"] = "completed"
    return summary


async def run_buyer(product_request: str, budget: float, customer_name: str = "AI Buyer", customer_email: str = "ai-buyer@example.com", shipping_address: str = "Not provided", quantity: int = 1, payment_method: str = "card", audit=None, audit_callback=None):
    if budget <= 0 or quantity <= 0:
        raise ValueError("budget and quantity must be greater than zero")
    audit = audit if audit is not None else []

    def record(event: str, detail: str, **data):
        entry = {"event": event, "detail": detail, "timestamp": datetime.now(timezone.utc).isoformat(), **data}
        audit.append(entry)
        if audit_callback:
            audit_callback(entry)

    record("started", "Buyer protocol started", request=product_request, budget=budget, quantity=quantity)
    client = MultiServerMCPClient({"gaming_store": {"transport": "streamable_http", "url": MCP_URL}})
    mcp_tools = await client.get_tools()
    record("connected", "Connected to the store MCP server", tool_count=len(mcp_tools))
    tools = {available_tool.name: available_tool for available_tool in mcp_tools}
    required = {"get_product", "create_order", "process_payment", "register_customer"}
    missing = required - tools.keys()
    if missing:
        raise BuyerProtocolError(f"MCP server is missing required tools: {sorted(missing)}")

    async def invoke_mcp_tool(tool_name: str, **kwargs):
        """Call a raw MCP tool using its exact schema and return a JSON-safe string."""
        return stringify_tool_result(await call_with_retries(tools, tool_name, kwargs))

    @tool
    async def search_product(query: str, max_price: float | None = None, category: str | None = None, min_price: float | None = None):
        """Search products using buyer intent, category, or price filters."""
        return await invoke_mcp_tool("search_product", query=query, max_price=max_price, category=category, min_price=min_price)

    @tool
    async def list_products(category: str | None = None, include_out_of_stock: bool = False, min_price: float | None = None, max_price: float | None = None):
        """List products with optional filters."""
        return await invoke_mcp_tool("list_products", category=category, include_out_of_stock=include_out_of_stock, min_price=min_price, max_price=max_price)

    @tool
    async def get_product(product_id: int):
        """Read product details for a specific product ID."""
        return await invoke_mcp_tool("get_product", product_id=product_id)

    @tool
    async def check_inventory(product_id: int):
        """Check current stock for a specific product ID."""
        return await invoke_mcp_tool("check_inventory", product_id=product_id)

    @tool
    async def register_customer(name: str, email: str, shipping_address: str | None = None, address: str | None = None):
        """Create or update a buyer identity. Accepts either shipping_address or the natural address alias."""
        safe_address = shipping_address or address
        return await invoke_mcp_tool("register_customer", name=name, email=email, shipping_address=safe_address)

    @tool
    async def get_customer(customer_id: int):
        """Get the buyer profile for a customer ID."""
        return await invoke_mcp_tool("get_customer", customer_id=customer_id)

    @tool
    async def find_alternative_products(product_id: int, max_price: float | None = None):
        """Find alternative products in the same category within the buyer's price range."""
        return await invoke_mcp_tool("find_alternative_products", product_id=product_id, max_price=max_price)

    @tool
    async def list_orders(status: str | None = None, customer_id: int | None = None, customer_email: str | None = None):
        """List orders with optional filters for customer and status."""
        return await invoke_mcp_tool("list_orders", status=status, customer_id=customer_id, customer_email=customer_email)

    @tool
    async def get_order(order_id: int):
        """Get the detailed order record for a given order ID."""
        return await invoke_mcp_tool("get_order", order_id=order_id)

    @tool
    async def list_customer_orders(customer_id: int):
        """List all orders for a customer ID."""
        return await invoke_mcp_tool("list_customer_orders", customer_id=customer_id)

    @tool
    async def cancel_order(order_id: int):
        """Cancel an existing order and restore stock."""
        return await invoke_mcp_tool("cancel_order", order_id=order_id)

    @tool
    async def update_order_status(order_id: int, status: str):
        """Update the order status to a valid shipping lifecycle stage."""
        return await invoke_mcp_tool("update_order_status", order_id=order_id, status=status)

    purchase_attempts = 0
    payment_attempts = 0
    committed_total = 0.0
    purchase_lock = asyncio.Lock()
    summary: dict[str, Any] = {}

    @tool
    async def create_budget_checked_order(product_id: int, requested_quantity: int, customer_id: int, buyer_payment_method: str):
        """Create an order only when its cumulative total fits the hard buyer budget."""
        nonlocal purchase_attempts, committed_total, summary
        purchase_attempts += 1
        if purchase_attempts > PAYMENT_RETRY_ATTEMPTS:
            return json.dumps({"success": False, "error": "Purchase retry limit reached"})
        record("budget_check", "Checking product total against hard budget", product_id=product_id, attempt=purchase_attempts)
        async with purchase_lock:
            product = await call_with_retries(tools, "get_product", {"product_id": product_id})
            if error := result_error(product):
                return json.dumps({"success": False, "error": error})
            total = float(product["price"]) * requested_quantity
            if committed_total + total > budget:
                return json.dumps({"success": False, "error": f"Purchase blocked: running total {committed_total + total:.2f} exceeds budget {budget:.2f}"})
            record("purchase", "Budget approved; creating order", total=total, running_total=committed_total + total)
            result = await call_with_retries(tools, "create_order", {"product_id": product_id, "quantity": requested_quantity, "customer_id": customer_id, "payment_method": buyer_payment_method})
            if isinstance(result, dict) and result.get("success"):
                committed_total += total
                summary = {
                    "product": result.get("product") or product.get("name"),
                    "quantity": requested_quantity,
                    "total": float(result.get("total", total)),
                    "order_id": result.get("order_id"),
                    "status": result.get("status"),
                    "customer_name": customer_name,
                    "customer_email": customer_email,
                    "shipping_address": shipping_address,
                    "payment_status": "pending",
                }
            return json.dumps(result)

    @tool
    async def process_buyer_payment(order_id: int, payment_succeeded: bool, failure_reason: str = ""):
        """Process one payment attempt through the store MCP server."""
        nonlocal payment_attempts, summary
        payment_attempts += 1
        if payment_attempts > PAYMENT_RETRY_ATTEMPTS:
            return json.dumps({"success": False, "error": "Payment retry limit reached"})
        record("payment_attempt", "Attempting payment", order_id=order_id, attempt=payment_attempts)
        result = await call_with_retries(tools, "process_payment", {"order_id": order_id, "payment_succeeded": payment_succeeded, "failure_reason": failure_reason or None})
        if isinstance(result, dict):
            summary["order_id"] = result.get("order_id", summary.get("order_id"))
            summary["status"] = result.get("status") or summary.get("status")
            summary["payment_status"] = result.get("payment_status") or ("paid" if payment_succeeded else "failed")
            if result.get("success") is False and result.get("error"):
                summary["error"] = result["error"]
        return json.dumps(result)

    guarded = [
        search_product,
        list_products,
        get_product,
        check_inventory,
        register_customer,
        get_customer,
        find_alternative_products,
        list_orders,
        get_order,
        list_customer_orders,
        cancel_order,
        update_order_status,
        create_budget_checked_order,
        process_buyer_payment,
    ]
    prompt = f"""You are a natural shopping assistant for a gaming store. The user's actual request is: {product_request}. Hard maximum budget: {budget:.2f}. Quantity: {quantity}. Customer: {customer_name}, {customer_email}. Address: {shipping_address}. Payment method: {payment_method}.
Your job is to follow the user request, not to force a purchase.

Core intent rules:
- First decide the user's intent: browse/search products, buy a product, or query order history/status.
- If the user is only browsing, searching, comparing, or asking about products without explicitly asking to buy, do not force a purchase. Use search_product or list_products and respond naturally with product names, prices, categories, and stock.
- If the user clearly asks to buy, then proceed with a purchase flow: register_customer, look up available products, choose the correct item, use create_budget_checked_order only, respect the hard budget, and do not exceed it cumulatively.
- If the user asks to check orders, order status, history, or previous purchases, use list_orders, list_customer_orders, or get_order. Query by customer_email when available, or by customer_id if known. Provide a clear summary of order status, total, product, and payment state.
- If the user asks for their order history and has a customer email, do not treat that as a purchase request.
- If no product matches, respond naturally like: 'I could not find a matching product in the store right now.'
- If a purchase is made, include product, total, order ID, payment status, and order status in the final response.
- Retry tool failures at most {PAYMENT_RETRY_ATTEMPTS} times.
- Never duplicate orders.
- Keep the tone natural, helpful, and conversational.
- Do not narrate internal tool mechanics unless the user explicitly asks for details.
- If the user only asks for product information or order information, do not create or pay for an order."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is required. Add it to .env before running ai.py.")
    model = ChatGroq(model=GROQ_MODEL, api_key=GROQ_API_KEY, temperature=0, max_tokens=512)
    record("preferences", "Buyer preferences and budget supplied to agent")
    user_message = product_request or "Help me with shopping or order questions."
    response = await create_agent(model, guarded, system_prompt=prompt).ainvoke({"messages": [{"role": "user", "content": user_message}]})
    final_message = response["messages"][-1].content if response["messages"] else ""
    compiled_summary = summary or summarize_audit(audit)
    if compiled_summary:
        fallback_message = f"Purchased {compiled_summary.get('product') or 'the requested item'} for ${float(compiled_summary.get('total', 0) or 0):.2f}. Order #{compiled_summary.get('order_id') or 'n/a'} is {compiled_summary.get('status') or 'processing'} with payment status {compiled_summary.get('payment_status') or 'pending'}."
        if not final_message or final_message.strip() == "The buyer protocol completed without a final message.":
            final_message = fallback_message
    elif not final_message:
        final_message = "The buyer protocol completed without a final message."
    record("completed", "Buyer protocol completed")
    return {"message": final_message, "summary": compiled_summary, "audit": audit}