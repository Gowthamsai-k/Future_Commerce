import asyncio
import json
import os

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from commerce.ai.buyer import run_buyer
from commerce.config import AI_API_HOST, AI_API_PORT, AUDIT_FILE


async def buyer(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "Request body must be valid JSON"}, status_code=400)

    if not isinstance(payload, dict):
        return JSONResponse({"error": "Request body must be a JSON object"}, status_code=400)

    if not payload.get("product_request"):
        return JSONResponse({"error": "Missing required field: product_request"}, status_code=400)

    async def stream():
        audit = []
        events = asyncio.Queue()
        finished = asyncio.Event()

        def publish(event):
            events.put_nowait(event)

        async def run():
            try:
                result = await run_buyer(
                    product_request=payload.get("product_request"),
                    budget=payload.get("budget"),
                    customer_name=payload.get("customer_name"),
                    customer_email=payload.get("customer_email"),
                    shipping_address=payload.get("shipping_address"),
                    quantity=payload.get("quantity"),
                    payment_method=payload.get("payment_method") or "razorpay",
                    conversation_history=payload.get("conversation_history", []),
                    audit=audit,
                    audit_callback=publish,
                )
                return {"message": result["message"], "summary": result.get("summary", {})}
            except Exception as error:
                return {"error": str(error)}
            finally:
                finished.set()

        task = asyncio.create_task(run())
        try:
            while not finished.is_set() or not events.empty():
                try:
                    event = await asyncio.wait_for(events.get(), timeout=0.2)
                    yield json.dumps({"type": "audit", "data": event}) + "\n"
                except asyncio.TimeoutError:
                    continue
            result = await task
            AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
            with AUDIT_FILE.open("a", encoding="utf-8") as log:
                for event in audit:
                    log.write(json.dumps(event) + "\n")
            yield json.dumps({"type": "result", "data": {**result, "audit": audit}}) + "\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(stream(), media_type="application/x-ndjson")


async def health(request: Request):
    return JSONResponse({"status": "ok", "service": "ai-buyer"})

routes = [
    Route("/api/buyer", buyer, methods=["POST"]),
    Route("/health", health, methods=["GET"])
]

dist_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "ai-face", "dist")
if os.path.exists(dist_dir):
    routes.append(Mount("/", app=StaticFiles(directory=dist_dir, html=True), name="static"))

app = CORSMiddleware(Starlette(routes=routes), allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])


def main():
    import uvicorn
    port = int(os.getenv("PORT", AI_API_PORT))
    uvicorn.run(app, host="0.0.0.0", port=port)