# Future Commerce MCP server

The project is organized by responsibility. Root Python files remain small
compatibility launchers, while application code lives in the `commerce/`
package.

Start the MCP store server:

```bash
python server.py
```

Open the forwarded port `8000` in the Ports panel. The root URL (`/`) shows a
server status message, and MCP clients should connect to `/mcp`.

For the stdio client, run:

```bash
MCP_TRANSPORT=stdio python server.py
```

Start the AI buyer API in a second terminal:

```bash
python ai_api.py
```

The development frontend calls `/api/buyer` through the Vite proxy, which
forwards to the AI API on port `9000`. For a separately hosted API, create
`ai-face/.env.local` with `VITE_AI_API_URL=http://your-host:9000/api/buyer`
and restart Vite.

Start the UI in a third terminal:

```bash
cd ai-face
npm run dev
```

## Project structure

| Path | Responsibility |
| --- | --- |
| `commerce/config.py` | Loads `.env` and centralizes ports, database, MCP, model, and audit settings. |
| `commerce/db/connection.py` | Creates configured SQLite connections. |
| `commerce/db/schema.py` | Creates and migrates products, customers, and orders tables. |
| `commerce/db/seed.py` | Adds the initial gaming product catalog when the database is empty. |
| `commerce/store/service.py` | Contains product, customer, inventory, order, payment, and cancellation business rules. |
| `commerce/mcp/server.py` | Registers MCP tools and serves the MCP HTTP/stdio transports. |
| `commerce/ai/buyer.py` | Runs the strict AI buyer, budget guard, retries, and audit events. |
| `commerce/ai/api.py` | Exposes the streaming `/api/buyer` endpoint and persists audit JSONL records. |
| `server.py`, `database.py`, `products.py` | Backward-compatible launchers/exports for existing scripts. |
| `ai.py`, `ai_api.py` | Backward-compatible launchers for the AI buyer and API. |
| `ai-face/` | React/Vite buyer interface. |

The normal request path is: browser -> `commerce/ai/api.py` ->
`commerce/ai/buyer.py` -> MCP -> `commerce/store/service.py` -> SQLite.

## Store tools

The MCP server exposes product search and inventory tools, plus order tools:

- `list_products`: browse products that are in stock, optionally by category.
- `search_product`: search by need, category, and minimum or maximum price.
- `find_alternative_products`: find similar in-stock products when a choice is unavailable.
- `register_customer` and `get_customer`: create and retrieve a stable buyer identity.
- `create_order`: reserve stock and create an order. Optional customer and payment fields can be supplied.
- `process_payment`: record a payment result; failed payments cancel the order and release stock.
- `list_orders`: list all orders, with optional `status` or `customer_email` filters.
- `list_customer_orders`: list the complete order history for a customer ID.
- `get_order`: retrieve one order with product and customer details.
- `cancel_order`: cancel an order and restore its reserved stock.
- `update_order_status`: move an order through `created`, `processing`, `shipped`, `delivered`, or `cancelled`.

## AI buyer

Run the store first, then configure `GROQ_API_KEY` in `.env` and optionally set
`PRODUCT_REQUEST`, `BUYER_BUDGET`, `PRODUCT_QUANTITY`, `CUSTOMER_NAME`,
`CUSTOMER_EMAIL`, `SHIPPING_ADDRESS`, and `PAYMENT_METHOD` before running:

```bash
python ai.py
```

The buyer uses the MCP server at `MCP_URL` (default:
`http://127.0.0.1:8000/mcp`). Purchases are blocked in code when their item
total exceeds `BUYER_BUDGET`; the model cannot override that limit.
The Groq model can be changed with `GROQ_MODEL` (default:
`openai/gpt-oss-20b`).
