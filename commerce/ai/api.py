import asyncio
import json

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from commerce.ai.buyer import run_buyer
from commerce.config import AI_API_HOST, AI_API_PORT, AUDIT_FILE


async def buyer(request: Request):
    payload = await request.json()
    required = ["product_request", "budget"]
    missing = [field for field in required if not payload.get(field)]
    if missing:
        return JSONResponse({"error": f"Missing required fields: {', '.join(missing)}"}, status_code=400)

    async def stream():
        audit = []
        events = asyncio.Queue()
        finished = asyncio.Event()

        def publish(event):
            events.put_nowait(event)

        async def run():
            try:
                result = await run_buyer(
                    product_request=payload.get("product_request", ""),
                    budget=payload.get("budget", 0),
                    customer_name=payload.get("customer_name") or "AI Buyer",
                    customer_email=payload.get("customer_email") or "ai-buyer@example.com",
                    shipping_address=payload.get("shipping_address") or "Not provided",
                    quantity=payload.get("quantity", 1),
                    payment_method=payload.get("payment_method", "card"),
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


app = CORSMiddleware(Starlette(routes=[Route("/api/buyer", buyer, methods=["POST"]), Route("/health", health, methods=["GET"])]), allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])


def main():
    import uvicorn
    uvicorn.run(app, host=AI_API_HOST, port=AI_API_PORT)