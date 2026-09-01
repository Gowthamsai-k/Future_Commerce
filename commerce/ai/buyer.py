import asyncio
import json
import re
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


def normalize_buyer_request(product_request: str | None, budget: float | int | str | None, customer_name: str | None = None, customer_email: str | None = None, shipping_address: str | None = None, quantity: int | str | None = None, payment_method: str | None = None):
    """Normalize request inputs without injecting defaults or hardcoded buyer details."""
    if product_request is None or not str(product_request).strip():
        raise ValueError("product_request is required")

    def clean_text(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    def clean_float(value: float | int | str | None) -> float | None:
        if value is None:
            return None
        coerced = float(value)
        if coerced <= 0:
            raise ValueError("budget must be greater than zero when provided")
        return coerced

    def clean_int(value: int | str | None) -> int | None:
        if value is None:
            return None
        coerced = int(value)
        if coerced <= 0:
            raise ValueError("quantity must be greater than zero when provided")
        return coerced

    normalized = {
        "product_request": str(product_request).strip(),
        "budget": clean_float(budget) if budget is not None else None,
        "customer_name": clean_text(customer_name),
        "customer_email": clean_text(customer_email),
        "shipping_address": clean_text(shipping_address),
        "quantity": clean_int(quantity) if quantity is not None else None,
        "payment_method": clean_text(payment_method),
    }
    return normalized


def build_follow_up_question(requested_product: str | None = None, alternative_product: str | None = None, current_budget: float | int | str | None = None, alternative_price: float | int | str | None = None, missing_fields: dict[str, str] | None = None) -> str:
    """Build a natural follow-up prompt when an alternate product or extra buyer detail is needed."""
    requested_label = requested_product or "the requested item"
    parts: list[str] = []

    if alternative_product:
        parts.append(f"I found a close alternative: {alternative_product}.")
    if alternative_price is not None and current_budget is not None:
        parts.append(f"Its price is ${float(alternative_price):.2f}, while your current budget is ${float(current_budget):.2f}.")
        parts.append("Would you like me to keep the same budget or adjust it slightly up or down to match this option?")
    elif current_budget is not None:
        parts.append(f"Your current budget is ${float(current_budget):.2f}.")
        parts.append("Should I look for a lower-cost option, or would you like to adjust your budget?")

    if missing_fields:
        missing = [label for field, label in missing_fields.items() if field]
        if missing:
            parts.append(f"I also need the following to continue: {', '.join(missing)}.")

    if not parts:
        return f"I need one more detail before I can complete the order for {requested_label}."

    return " ".join(parts)


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


async def run_buyer(product_request: str | None, budget: float | int | str | None, customer_name: str | None = None, customer_email: str | None = None, shipping_address: str | None = None, quantity: int | str | None = None, payment_method: str | None = None, conversation_history: list | None = None, audit=None, audit_callback=None):
    request = normalize_buyer_request(product_request, budget, customer_name, customer_email, shipping_address, quantity, payment_method)
    product_request = request["product_request"]
    budget = request["budget"]
    customer_name = request["customer_name"]
    customer_email = request["customer_email"]
    shipping_address = request["shipping_address"]
    quantity = request["quantity"]
    payment_method = request["payment_method"]
    audit = audit if audit is not None else []

    def record(event: str, detail: str, **data):
        entry = {"event": event, "detail": detail, "timestamp": datetime.now(timezone.utc).isoformat(), **data}
        audit.append(entry)
        if audit_callback:
            audit_callback(entry)

    record("started", "Buyer protocol started", request=product_request, budget=budget, quantity=quantity)
    
    # Configure MCP client with longer timeout for multi-iteration queries
    mcp_config = {
        "gaming_store": {
            "transport": "streamable_http",
            "url": MCP_URL,
            "timeout": 30.0,  # 30 second timeout for MCP requests
        }
    }
    
    # Retry logic for MCP connection
    client = None
    mcp_tools = None
    for attempt in range(3):
        try:
            client = MultiServerMCPClient(mcp_config)
            mcp_tools = await client.get_tools()
            record("connected", "Connected to the store MCP server", tool_count=len(mcp_tools))
            break
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(1.0)  # Wait before retrying
                continue
            else:
                record("error", f"Failed to connect to MCP server after 3 attempts: {str(e)}")
                raise BuyerProtocolError(f"MCP connection failed after retries: {str(e)}")
    
    if not mcp_tools:
        raise BuyerProtocolError("No MCP tools available")
    
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
        """Create an order only when its cumulative total fits the buyer's provided budget, if any."""
        nonlocal purchase_attempts, committed_total, summary
        purchase_attempts += 1
        if purchase_attempts > PAYMENT_RETRY_ATTEMPTS:
            return json.dumps({"success": False, "error": f"Purchase retry limit reached after {PAYMENT_RETRY_ATTEMPTS} attempts"})
        record("budget_check", "Checking product total against buyer budget", product_id=product_id, attempt=purchase_attempts)
        async with purchase_lock:
            product = await call_with_retries(tools, "get_product", {"product_id": product_id})
            if error := result_error(product):
                return json.dumps({"success": False, "error": error})
            total = float(product["price"]) * requested_quantity
            if budget is not None and committed_total + total > budget:
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
        """Attempt payment with graceful retry handling and only the provided failure reason."""
        nonlocal payment_attempts, summary
        final_result = None
        for attempt in range(1, PAYMENT_RETRY_ATTEMPTS + 1):
            payment_attempts += 1
            record("payment_attempt", "Attempting payment", order_id=order_id, attempt=payment_attempts)
            result = await call_with_retries(tools, "process_payment", {"order_id": order_id, "payment_succeeded": payment_succeeded, "failure_reason": failure_reason or None})
            final_result = result
            if isinstance(result, dict):
                summary["order_id"] = result.get("order_id", summary.get("order_id"))
                summary["status"] = result.get("status") or summary.get("status")
                summary["payment_status"] = result.get("payment_status") or ("paid" if payment_succeeded else "failed")
                if result.get("success") is True:
                    return json.dumps(result)
                if result.get("error"):
                    summary["error"] = result["error"]
                if attempt < PAYMENT_RETRY_ATTEMPTS:
                    record("payment_retry", "Payment failed; retrying with the same request data", order_id=order_id, attempt=attempt + 1, failure_reason=failure_reason or None)
                    await asyncio.sleep(0.25 * attempt)
                    continue
            return json.dumps({"success": False, "error": str(result.get("error") if isinstance(result, dict) else "Payment failed")})
        if isinstance(final_result, dict) and final_result.get("error"):
            return json.dumps({"success": False, "error": final_result["error"]})
        return json.dumps({"success": False, "error": "Payment failed after retries"})

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
    budget_text = f"{budget:.2f}" if budget is not None else "not provided"
    quantity_text = str(quantity) if quantity is not None else "not provided"
    customer_text = f"{customer_name}, {customer_email}" if customer_name or customer_email else "not provided"
    address_text = shipping_address if shipping_address else "not provided"
    payment_text = payment_method if payment_method else "razorpay"
    
    # Extract original product request from conversation history if current input is a follow-up
    original_product_request = product_request
    inferred_budget = budget
    
    if conversation_history and isinstance(conversation_history, list) and len(conversation_history) > 0:
        # Check if current request looks like a follow-up (just a number, yes/no, or single word)
        words = str(product_request).lower().strip().split()
        is_followup = len(words) <= 2 and (
            words[0] in ['yes', 'no', 'sure', 'ok', 'okay', 'increase', 'decrease', 'adjust'] or
            (len(words) == 1 and any(c.isdigit() for c in words[0]))  # Single word with digits
        )
        
        if is_followup and len(conversation_history) >= 2:
            # Try to find the original product request from history (search backwards for efficiency)
            for msg in reversed(conversation_history):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    prev_content = msg.get("content", "").strip().lower()
                    # Skip very short follow-up responses and duplicates
                    if len(prev_content.split()) > 3 and prev_content != product_request.lower():
                        original_product_request = prev_content
                        break
            
            # Try to extract numeric budget from current response
            numbers = re.findall(r'\d+', product_request)
            if numbers:
                try:
                    potential_budget = float(numbers[-1])  # Take the last number mentioned
                    if potential_budget > 0:
                        inferred_budget = potential_budget
                except (ValueError, IndexError):
                    pass
    
    # Build conversation context for memory
    conversation_context = ""
    if conversation_history and isinstance(conversation_history, list):
        recent_messages = conversation_history[-6:]  # Keep last 3 exchanges
        conversation_context = "\n\nConversation history:\n"
        for msg in recent_messages:
            if isinstance(msg, dict):
                role = msg.get("role", "unknown")
                content = msg.get("content", "").strip()
                if content:
                    conversation_context += f"{role.title()}: {content}\n"
    
    inferred_budget_text = f"{inferred_budget:.2f}" if inferred_budget is not None else budget_text
    
    prompt = f"""You are a natural shopping assistant for a gaming store. 
ORIGINAL REQUEST: {original_product_request}
Current input: {product_request}
Budget (hard max): {inferred_budget_text}. Quantity: {quantity_text}. Customer: {customer_text}. Address: {address_text}. Payment method: {payment_text} (use this as default).{conversation_context}

Your job is to follow the user's original request efficiently. If the user provides a budget adjustment or other follow-up, treat it as a modification to their original request, NOT a new request.

Core intent rules:
- MAINTAIN CONTEXT: Always remember the original product the user asked for. If they ask "can you increase budget to 10k?", you should immediately continue searching for the original product (e.g., headphones) with the new budget.
- FOLLOW-UP RESPONSES: When the user responds with a number, "yes", "no", or a budget adjustment, do NOT forget what they originally asked for. Use conversation history to find the original product request.
- First decide the user's intent: browse/search products, buy a product, query order history/status, or ask an irrelevant question.
- Only ask for information that is truly missing and required to complete the request.
- Do NOT re-ask for information already provided in the current or previous conversation. Use conversation history to avoid redundant questions.
- **CRITICAL: If you find a product within budget, ask for quantity and proceed. Do NOT ask to increase/decrease budget if the product already fits.**
- If the user clearly asks to buy and the product exists in stock at a price within budget, execute the purchase immediately without unnecessary follow-up questions. Just ask: "How many would you like to order?" and wait for a number response.
- If the request is unrelated to shopping, product discovery, or order management, politely explain that you can only help with shopping, product listings, and order-related purchases.
- Only use the values explicitly supplied in the user's request or request payload. Never invent customer names, addresses, emails, prices, quantities, or payment methods unless they were provided earlier.
- If the user is only browsing, searching, comparing, or asking about products without explicitly asking to buy, do not force a purchase. Use search_product or list_products and respond naturally with product names, prices, categories, and stock.
- If the user clearly asks to buy, then proceed with a purchase flow: register_customer only when the required customer details are provided, look up available products, choose the correct item, use create_budget_checked_order only, respect the hard budget only if one was provided, and do not exceed it cumulatively.
- If the requested product is unavailable or a matching item exceeds the provided budget by a small amount, do not fail immediately. Offer a close alternative product and ask the user whether they want to keep the same budget or adjust it slightly up or down. If the user changes the budget, loop and retry the purchase flow with the updated values.
- If the user asks to check orders, order status, history, or previous purchases, use list_orders, list_customer_orders, or get_order. Query by customer_email when available, or by customer_id if known. Provide a clear summary of order status, total, product, and payment state.
- If the user asks for their order history and has a customer email, do not treat that as a purchase request.
- If no product matches, respond naturally like: 'I could not find a matching product in the store right now.'
- Use the default payment method provided unless the user specifies otherwise.
- If a purchase is made, include product, total, order ID, payment status, and order status in the final response.
- Retry tool failures at most {PAYMENT_RETRY_ATTEMPTS} times.
- Never duplicate orders.
- Keep the tone natural, helpful, and conversational.
- Do not narrate internal tool mechanics unless the user explicitly asks for details.
- If the user only asks for product information or order information, do not create or pay for an order.
- Minimize questions and act decisively when you have enough information to proceed."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is required. Add it to .env before running ai.py.")
    model = ChatGroq(model=GROQ_MODEL, api_key=GROQ_API_KEY, temperature=0, max_tokens=512)
    record("preferences", "Buyer preferences and budget supplied to agent")
    
    # Build messages with conversation history
    messages = []
    if conversation_history and isinstance(conversation_history, list):
        for msg in conversation_history:
            if isinstance(msg, dict) and msg.get("content"):
                messages.append({"role": msg.get("role", "user"), "content": msg.get("content")})
    
    # Determine if this is a follow-up and add context
    words = str(product_request).lower().strip().split()
    is_followup = len(words) <= 2 and (
        words[0] in ['yes', 'no', 'sure', 'ok', 'okay', 'increase', 'decrease', 'adjust'] or
        (len(words) == 1 and any(c.isdigit() for c in words[0]))
    )
    
    # Add current request with context about whether it's a follow-up
    if not messages or messages[-1].get("content") != product_request:
        if is_followup and original_product_request != product_request:
            # Combine follow-up response with original request context
            context_msg = f"{product_request} [continuing search for: {original_product_request}]"
            messages.append({"role": "user", "content": context_msg})
        else:
            messages.append({"role": "user", "content": product_request or "Help me with shopping or order questions."})
    
    if not messages:
        messages = [{"role": "user", "content": product_request or "Help me with shopping or order questions."}]
    
    response = await create_agent(model, guarded, system_prompt=prompt).ainvoke({"messages": messages})
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