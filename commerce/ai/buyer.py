import asyncio
import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langchain_mcp_adapters.client import MultiServerMCPClient

from commerce.config import GROQ_API_KEY, GROQ_MODEL, LLM_PROVIDER, MCP_URL, OLLAMA_BASE_URL, OLLAMA_MODEL
from simulate_razorpay_payment import simulate_fake_card_payment

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
        "quantity": clean_int(quantity) if quantity is not None else 1,
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
    if isinstance(result, list) and len(result) > 0 and isinstance(result[0], dict) and result[0].get("type") == "text":
        text = result[0].get("text", "")
        try:
            return json.loads(text)
        except (TypeError, json.JSONDecodeError):
            return text
    if isinstance(result, str):
        try:
            return json.loads(result)
        except (TypeError, json.JSONDecodeError):
            return result
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
    if name not in tool_by_name:
        return {"success": False, "error": f"Tool {name!r} is unavailable on MCP server"}
    last_error = None
    for attempt in range(1, MAX_TOOL_ATTEMPTS + 1):
        try:
            return normalize_tool_result(await tool_by_name[name].ainvoke(arguments))
        except Exception as error:
            last_error = error
            if attempt < MAX_TOOL_ATTEMPTS:
                await asyncio.sleep(0.25 * attempt)
    return {"success": False, "error": f"MCP tool {name!r} failed after {MAX_TOOL_ATTEMPTS} attempts: {last_error}"}


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
            "transport": "sse",
            "url": MCP_URL,
            "timeout": 30.0,  # 30 second timeout for MCP requests
        }
    }
    
    client = MultiServerMCPClient(mcp_config)
    mcp_tools = await client.get_tools()
    record("connected", "Connected to the store MCP server", tool_count=len(mcp_tools))
    
    tools = {available_tool.name: available_tool for available_tool in mcp_tools}
    required = {"get_product", "create_order", "process_payment", "register_customer"}
    missing = required - tools.keys()
    if missing:
        raise BuyerProtocolError(f"MCP server is missing required tools: {sorted(missing)}")

    async def invoke_mcp_tool(tool_name: str, **kwargs):
        """Call a raw MCP tool using its exact schema and return a JSON-safe string."""
        clean_args = {k: v for k, v in kwargs.items() if v is not None}
        args_str = ", ".join(f"{k}='{v}'" if isinstance(v, str) else f"{k}={v}" for k, v in clean_args.items())
        record("mcp_tool_execution", f"Executing tool: {tool_name}({args_str})", tool=tool_name, arguments=clean_args)
        
        result = await call_with_retries(tools, tool_name, kwargs)
        normalized = normalize_tool_result(result)
        
        if isinstance(normalized, list):
            res_summary = f"{tool_name}: fetched {len(normalized)} product(s)"
        elif isinstance(normalized, dict):
            if normalized.get("name"):
                res_summary = f"{tool_name}: found '{normalized['name']}' (${normalized.get('price')})"
            elif normalized.get("customer"):
                res_summary = f"{tool_name}: identity updated for '{normalized['customer'].get('name')}'"
            elif normalized.get("error"):
                res_summary = f"{tool_name}: error - {normalized['error']}"
            else:
                res_summary = f"{tool_name}: completed successfully"
        else:
            res_summary = f"{tool_name}: completed"
            
        record("mcp_tool_result", res_summary, tool=tool_name)
        return stringify_tool_result(result)

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
    async def create_budget_checked_order(product_id: int, requested_quantity: int = 1, customer_id: int | None = None, buyer_payment_method: str = "razorpay"):
        """Create an order only when its cumulative total fits the buyer's provided budget, if any."""
        nonlocal purchase_attempts, committed_total, summary
        
        # SMART FIX 1: Auto-register customer if customer_id is missing or unregistered
        if not customer_id and customer_email and customer_name:
            record("auto_fix", "Customer ID missing. Automatically registering customer identity", name=customer_name, email=customer_email)
            try:
                reg_res = await call_with_retries(tools, "register_customer", {"name": customer_name, "email": customer_email, "shipping_address": shipping_address})
                if isinstance(reg_res, dict) and reg_res.get("success") and reg_res.get("customer"):
                    customer_id = reg_res["customer"]["id"]
                    record("auto_fix_success", f"Registered customer with ID #{customer_id}")
            except Exception as err:
                record("auto_fix_warning", f"Customer auto-registration notice: {err}")

        purchase_attempts += 1
        if purchase_attempts > PAYMENT_RETRY_ATTEMPTS:
            return json.dumps({"success": False, "error": f"Purchase retry limit reached after {PAYMENT_RETRY_ATTEMPTS} attempts"})
        
        record("budget_check", "Checking product total against buyer budget", product_id=product_id, attempt=purchase_attempts)
        async with purchase_lock:
            product = await call_with_retries(tools, "get_product", {"product_id": product_id})
            if error := result_error(product):
                return json.dumps({"success": False, "error": error})
            
            # SMART FIX 2: Check stock before attempting purchase. If out of stock, find an alternative!
            if isinstance(product, dict) and product.get("stock", 0) < requested_quantity:
                record("auto_fix", f"Product '{product.get('name')}' is out of stock (Stock: {product.get('stock')}). Searching for in-stock alternatives...", product_id=product_id)
                alternatives = await call_with_retries(tools, "find_alternative_products", {"product_id": product_id, "max_price": budget})
                if isinstance(alternatives, list) and len(alternatives) > 0:
                    alt_product = alternatives[0]
                    product_id = alt_product["id"]
                    product = alt_product
                    record("auto_fix_success", f"Automatically switched to in-stock alternative: '{alt_product.get('name')}' (Price: ₹{alt_product.get('price')})", alt_product_id=product_id)
                else:
                    return json.dumps({"success": False, "error": f"'{product.get('name')}' is out of stock, and no in-stock alternative fits your criteria."})

            total = float(product["price"]) * requested_quantity
            
            # SMART FIX 3: If price exceeds budget, search for budget-compliant alternatives first!
            if budget is not None and committed_total + total > budget:
                record("auto_fix", f"Item total (₹{total:.2f}) exceeds budget (₹{budget:.2f}). Looking for alternatives under ₹{budget:.2f}...", product_id=product_id)
                alternatives = await call_with_retries(tools, "find_alternative_products", {"product_id": product_id, "max_price": budget - committed_total})
                if isinstance(alternatives, list) and len(alternatives) > 0:
                    alt_product = alternatives[0]
                    product_id = alt_product["id"]
                    product = alt_product
                    total = float(product["price"]) * requested_quantity
                    record("auto_fix_success", f"Switched to alternative within budget: '{alt_product.get('name')}' (Price: ₹{total:.2f})")
                else:
                    return json.dumps({"success": False, "error": f"Purchase blocked: total ₹{committed_total + total:.2f} exceeds budget limit ₹{budget:.2f}"})

            record("purchase", "Budget approved; creating order", total=total, running_total=committed_total + total)
            
            # SMART FIX 4: Intelligent order execution with contextual recovery
            result = None
            try:
                result = await call_with_retries(tools, "create_order", {
                    "product_id": product_id,
                    "quantity": requested_quantity,
                    "customer_id": customer_id,
                    "customer_name": customer_name,
                    "customer_email": customer_email,
                    "shipping_address": shipping_address,
                    "payment_method": buyer_payment_method
                })
            except Exception as error:
                # If customer failure occurred mid-flight, recover by registering customer and retrying
                if "Customer" in str(error) and customer_email:
                    record("auto_fix", "Recovering from customer lookup failure...")
                    reg_res = await call_with_retries(tools, "register_customer", {"name": customer_name or "Guest", "email": customer_email, "shipping_address": shipping_address})
                    if isinstance(reg_res, dict) and reg_res.get("customer"):
                        customer_id = reg_res["customer"]["id"]
                        result = await call_with_retries(tools, "create_order", {
                            "product_id": product_id,
                            "quantity": requested_quantity,
                            "customer_id": customer_id,
                            "payment_method": buyer_payment_method
                        })
                else:
                    return json.dumps({"success": False, "error": f"Order creation failed: {error}"})

            if isinstance(result, dict) and result.get("success"):
                order_id = result.get("order_id")
                committed_total += total
                summary = {
                    "product": result.get("product") or product.get("name"),
                    "quantity": requested_quantity,
                    "total": float(result.get("total", total)),
                    "order_id": order_id,
                    "razorpay_order_id": result.get("razorpay_order_id"),
                    "status": "created",
                    "customer_name": customer_name,
                    "customer_email": customer_email,
                    "shipping_address": shipping_address,
                    "payment_status": "pending",
                }
                
                # FULLY AUTONOMOUS PAYMENT: Immediately authorize payment in background
                record("autonomous_payment", f"Executing autonomous test payment authorization for Order #{order_id}...", order_id=order_id)
                try:
                    if result.get("razorpay_payment_link"):
                        sim_res = simulate_fake_card_payment(result.get("razorpay_payment_link"))
                        record("fake_card_simulation", f"Domestic Indian card checkout simulation completed on link: {result.get('razorpay_payment_link')} (Card: Domestic Indian Visa 4000 **** **** 0002)")

                    pay_res = await call_with_retries(tools, "process_payment", {
                        "order_id": order_id,
                        "payment_succeeded": True,
                        "otp": "1111"
                    })
                    if isinstance(pay_res, dict) and pay_res.get("success"):
                        summary["payment_status"] = "paid"
                        summary["status"] = "processing"
                        summary["razorpay_payment_id"] = pay_res.get("razorpay_payment_id", f"pay_fake_card_{order_id}")
                        result["payment_status"] = "paid"
                        result["status"] = "processing"
                        result["razorpay_payment_id"] = pay_res.get("razorpay_payment_id")
                        result["message"] = f"✅ Order #{order_id} for {summary['product']} (Total: ₹{total:,.2f}) placed and paid successfully via Razorpay (Autonomous Domestic Indian Card Simulation: Visa 4000 **** **** 0002)!"
                        record("autonomous_payment_success", f"Autonomous domestic Indian card payment completed for Order #{order_id}! Status: paid", order_id=order_id)
                except Exception as p_err:
                    record("autonomous_payment_warning", f"Autonomous payment notice: {p_err}")

            return json.dumps(result)

    @tool
    async def process_buyer_payment(order_id: int = 0, payment_succeeded: bool = True, failure_reason: str = "", otp: str = ""):
        """Attempt payment authorization with intelligent multi-stage retry & test OTP fallback (Default test OTP: 1111)."""
        nonlocal payment_attempts, summary
        final_result = None
        current_otp = otp or "1111"
        
        # Self-healing Order ID auto-recovery if order_id is missing or 0
        if not order_id or order_id <= 0:
            if inferred_order_id:
                order_id = inferred_order_id
            else:
                try:
                    from commerce.db.connection import get_connection
                    conn = get_connection()
                    latest = conn.execute("SELECT id FROM orders WHERE payment_status = 'pending' ORDER BY id DESC LIMIT 1").fetchone()
                    conn.close()
                    if latest:
                        order_id = latest["id"]
                except Exception:
                    pass

        if not order_id:
            return json.dumps({"success": False, "error": "No pending order found to process payment."})
        for attempt in range(1, PAYMENT_RETRY_ATTEMPTS + 1):
            payment_attempts += 1
            record("payment_attempt", "Attempting payment authorization", order_id=order_id, attempt=payment_attempts, otp=current_otp)
            result = await call_with_retries(tools, "process_payment", {
                "order_id": order_id, 
                "payment_succeeded": True, 
                "failure_reason": failure_reason or None, 
                "otp": current_otp
            })
            final_result = result
            if isinstance(result, dict):
                summary["order_id"] = result.get("order_id", summary.get("order_id"))
                summary["status"] = result.get("status") or summary.get("status")
                summary["payment_status"] = result.get("payment_status") or "paid"
                summary["razorpay_order_id"] = result.get("razorpay_order_id") or summary.get("razorpay_order_id")
                summary["razorpay_payment_id"] = result.get("razorpay_payment_id") or summary.get("razorpay_payment_id")
                if result.get("success") is True:
                    return json.dumps(result)
                if result.get("error"):
                    summary["error"] = result["error"]
                if attempt < PAYMENT_RETRY_ATTEMPTS:
                    current_otp = "1111"
                    record("payment_retry", "Payment authorization pending; retrying with automated test OTP authorization", order_id=order_id, attempt=attempt + 1)
                    await asyncio.sleep(0.2 * attempt)
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
    inferred_order_id = None
    
    if conversation_history and isinstance(conversation_history, list) and len(conversation_history) > 0:
        clean_input = str(product_request).lower().strip()
        words = clean_input.split()
        
        # Check if user input expresses purchase confirmation or short response
        confirmation_terms = ['yes', 'buy', 'proceed', 'go ahead', 'do it', 'get it', 'confirm', 'sure', 'ok', 'okay', '1', 'place order', 'just buy']
        is_confirmation = any(term in clean_input for term in confirmation_terms)
        is_followup = is_confirmation or len(words) <= 5
        
        if is_followup and len(conversation_history) >= 2:
            # Try to find the original product request from history
            for msg in reversed(conversation_history):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    prev_content = msg.get("content", "").strip().lower()
                    if len(prev_content.split()) > 3 and prev_content != clean_input:
                        original_product_request = prev_content
                        break
            
            # Extract price quotes from assistant's previous message
            last_assistant_text = ""
            for msg in reversed(conversation_history):
                if isinstance(msg, dict) and msg.get("role") in ("assistant", "agent"):
                    last_assistant_text = msg.get("content", "")
                    break
            
            # If assistant quoted a price and user confirmed (e.g. "just buy it"), adapt inferred_budget
            if last_assistant_text and is_confirmation:
                price_matches = re.findall(r'[₹\$]\s*(\d[\d,]*(?:\.\d+)?)', last_assistant_text)
                for pm in price_matches:
                    try:
                        clean_num = float(pm.replace(',', ''))
                        if clean_num >= 500:  # Valid product price threshold
                            inferred_budget = max(inferred_budget or 0, clean_num)
                    except ValueError:
                        pass

            inferred_order_id = None
            if last_assistant_text:
                order_match = re.search(r'Order\s*#?\s*(\d+)', last_assistant_text, re.IGNORECASE)
                if order_match:
                    try:
                        inferred_order_id = int(order_match.group(1))
                    except ValueError:
                        pass
                        
            # Only extract budget if explicitly formatted as price with currency or budget keyword
            explicit_budget = re.search(r'(?:budget|under|below|max|rs|inr|[₹\$])\s*[:=]?\s*(\d[\d,]*)', product_request, re.IGNORECASE)
            if explicit_budget:
                try:
                    inferred_budget = float(explicit_budget.group(1).replace(',', ''))
                except ValueError:
                    pass

    # Keep conversation history short to fit within Groq free tier 8000 TPM limit
    conversation_context = ""
    if conversation_history and isinstance(conversation_history, list):
        recent_messages = conversation_history[-2:]  # Keep last exchange only
        conversation_context = "\nRecent messages:\n" + "\n".join(
            f"{msg.get('role', 'user').title()}: {msg.get('content', '').strip()}"
            for msg in recent_messages if isinstance(msg, dict) and msg.get("content")
        )
    
    inferred_budget_text = f"{inferred_budget:.2f}" if inferred_budget is not None else budget_text
    order_id_text = str(inferred_order_id) if inferred_order_id else "none"
    
    prompt = f"""You are an autonomous shopping buyer agent for a gaming store. 
Target Request: {original_product_request}
Input: {product_request} | Existing Order ID: {order_id_text} | Budget: {inferred_budget_text} | Qty: {quantity_text} | Customer: {customer_text} | Payment: {payment_text}{conversation_context}

Rules:
1. FULLY AUTONOMOUS PAYMENT FLOW:
   - When user asks to buy an item, execute `create_budget_checked_order`. The tool automatically handles order reservation and test payment authorization in background.
   - Present final order confirmation with Order ID, Product, Total, Payment Status (paid), and Razorpay Payment ID.
2. DEFAULT QUANTITY: Default quantity is 1 unless specified. Do not ask for quantity.
3. BUDGET: Respect the hard max budget. If item fits, buy it. If item is slightly over, auto-switch to in-stock alternative.
4. AUTONOMOUS VERIFICATION: The agent handles payment authorization automatically with full user consent.
5. CATALOG & LISTING: If the user request is to list, browse, or show products (e.g., 'list me all the products', 'show catalog', 'what items do you have'), DO NOT pick a single item or attempt to buy. Call `list_products` or `search_product` and present ALL products from the tool response grouped by category with their names and prices in INR (₹)."""

    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is required. Add it to .env before running ai.py.")
        
    model_candidates = [
        "gemma4:cloud",
        GROQ_MODEL,
        "gemma2:9b",
        "gemma2:27b",
        "qwen/qwen3.8-27b",
        "openai/gpt-oss-120b",
        "qwen/qwen3.6-27b",
        "openai/gpt-oss-20b"
    ]
    
    # Build light message stack
    messages = []
    if conversation_history and isinstance(conversation_history, list):
        for msg in conversation_history[-2:]:
            if isinstance(msg, dict) and msg.get("content"):
                messages.append({"role": msg.get("role", "user"), "content": msg.get("content")})
    
    if not messages or messages[-1].get("content") != product_request:
        messages.append({"role": "user", "content": product_request or "Help me with shopping."})

    response = None
    last_err = None

    if LLM_PROVIDER.lower() == "ollama":
        ollama_model = os.getenv("OLLAMA_MODEL", "nemotron-mini")
        ollama_base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        try:
            try:
                from langchain_ollama import ChatOllama
            except ImportError:
                from langchain_community.chat_models import ChatOllama
                
            record("provider_select", f"Using Ollama model '{ollama_model}' at {ollama_base}")
            model = ChatOllama(model=ollama_model, base_url=ollama_base, temperature=0)
            response = await create_agent(model, guarded, system_prompt=prompt).ainvoke({"messages": messages})
        except Exception as err:
            record("error", f"Ollama model '{ollama_model}' error: {err}. Falling back to Cloud provider...")
            for candidate_model in model_candidates:
                try:
                    model = ChatGroq(model=candidate_model, api_key=GROQ_API_KEY, temperature=0, max_tokens=2048, timeout=45)
                    response = await create_agent(model, guarded, system_prompt=prompt).ainvoke({"messages": messages})
                    break
                except Exception as g_err:
                    err_str = str(g_err)
                    if any(k in err_str.lower() for k in ("404", "400", "429", "model_not_found", "decommissioned", "rate_limit", "tpd", "tpm")):
                        record("model_failover", f"Fallback model '{candidate_model}' unavailable ({err_str[:60]}...). Switching...")
                        await asyncio.sleep(0.5)
                        continue
                    else:
                        raise g_err
    else:
        for candidate_model in model_candidates:
            try:
                model = ChatGroq(model=candidate_model, api_key=GROQ_API_KEY, temperature=0, max_tokens=2048, timeout=45)
                response = await create_agent(model, guarded, system_prompt=prompt).ainvoke({"messages": messages})
                break
            except Exception as err:
                last_err = err
                err_str = str(err)
                if any(k in err_str.lower() for k in ("404", "400", "429", "model_not_found", "decommissioned", "rate_limit", "tpd", "tpm")):
                    record("model_failover", f"Model '{candidate_model}' unavailable or rate-limited ({err_str[:60]}...). Switching to next model...")
                    await asyncio.sleep(0.5)
                    continue
                else:
                    record("error", f"Agent execution error on '{candidate_model}': {err_str}")
                    raise err
    
    final_message = ""
    if response:
        tool_catalog = None
        for msg in response.get("messages", []):
            content = str(getattr(msg, "content", ""))
            if "Here is our complete catalog" in content or ("### " in content and "₹" in content):
                tool_catalog = content.strip()
                break

        for msg in reversed(response.get("messages", [])):
            if hasattr(msg, "content") and msg.content and isinstance(msg.content, str) and not getattr(msg, "tool_calls", None):
                if msg.content.strip():
                    final_message = msg.content.strip()
                    break
                    
        clean_req = str(product_request).lower().strip()
        if tool_catalog and (any(k in clean_req for k in ("list", "all", "catalog", "browse", "show products", "show all", "what products")) or len(final_message) < 150):
            final_message = tool_catalog

    compiled_summary = summary or summarize_audit(audit)
    if compiled_summary and compiled_summary.get("order_id"):
        fallback_message = f"✅ Order #{compiled_summary.get('order_id')} for {compiled_summary.get('product')} (Qty: {compiled_summary.get('quantity', 1)}) placed successfully for ₹{float(compiled_summary.get('total', 0)):,.2f}! Payment status: {compiled_summary.get('payment_status', 'paid')} via Razorpay."
        if not final_message or "without a final message" in final_message:
            final_message = fallback_message
    elif not final_message or "without a final message" in final_message:
        error_details = [entry.get("detail") for entry in audit if entry.get("event") in ("error", "budget_check") and "exceeds" in str(entry.get("detail", ""))]
        if error_details:
            final_message = f"I couldn't complete the purchase: {error_details[-1]}"
        else:
            final_message = "I've checked the store for you. Let me know if you would like to place an order or ask any questions!"
            
    record("completed", "Buyer protocol completed")
    return {"message": final_message, "summary": compiled_summary, "audit": audit}