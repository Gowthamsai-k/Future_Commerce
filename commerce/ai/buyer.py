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


async def run_buyer(product_request: str, budget: float, customer_name: str, customer_email: str, shipping_address: str, quantity: int = 1, payment_method: str = "card", audit=None, audit_callback=None):
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

    def adapt_tool(tool_instance):
        @tool
        async def wrapped(**kwargs):
            """Invoke the connected store tool and return its result as a JSON string."""
            raw = await tool_instance.ainvoke(kwargs)
            return stringify_tool_result(raw)

        wrapped.__name__ = tool_instance.name
        return wrapped

    purchase_attempts = 0
    payment_attempts = 0
    committed_total = 0.0
    purchase_lock = asyncio.Lock()

    @tool
    async def create_budget_checked_order(product_id: int, requested_quantity: int, customer_id: int, buyer_payment_method: str):
        """Create an order only when its cumulative total fits the hard buyer budget."""
        nonlocal purchase_attempts, committed_total
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
            return json.dumps(result)

    @tool
    async def process_buyer_payment(order_id: int, payment_succeeded: bool, failure_reason: str = ""):
        """Process one payment attempt through the store MCP server."""
        nonlocal payment_attempts
        payment_attempts += 1
        if payment_attempts > PAYMENT_RETRY_ATTEMPTS:
            return json.dumps({"success": False, "error": "Payment retry limit reached"})
        record("payment_attempt", "Attempting payment", order_id=order_id, attempt=payment_attempts)
        return json.dumps(await call_with_retries(tools, "process_payment", {"order_id": order_id, "payment_succeeded": payment_succeeded, "failure_reason": failure_reason or None}))

    guarded = [adapt_tool(available_tool) for available_tool in mcp_tools if available_tool.name not in {"create_order", "process_payment"}]
    guarded.extend([create_budget_checked_order, process_buyer_payment])
    prompt = f"""You are a strict e-commerce AI buyer. Product request: {product_request}. Hard maximum budget: {budget:.2f}. Quantity: {quantity}. Customer: {customer_name}, {customer_email}. Address: {shipping_address}. Payment method: {payment_method}.
Follow this order: register_customer; search/list and inspect products; if no match reply exactly 'The required products do not exist here.'; use only create_budget_checked_order; never exceed the hard budget cumulatively; call payment only after an order exists; retry payment/tool failures at most {PAYMENT_RETRY_ATTEMPTS} times; never duplicate orders; report product, total, order ID, payment status, and order status."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is required. Add it to .env before running ai.py.")
    model = ChatGroq(model=GROQ_MODEL, api_key=GROQ_API_KEY, temperature=0, max_tokens=512)
    record("preferences", "Buyer preferences and budget supplied to agent")
    response = await create_agent(model, guarded, system_prompt=prompt).ainvoke({"messages": [{"role": "user", "content": "Complete the purchase protocol and report the result."}]})
    record("completed", "Buyer protocol completed")
    return {"message": response["messages"][-1].content, "audit": audit}