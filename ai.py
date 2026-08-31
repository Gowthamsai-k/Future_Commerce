"""Compatibility launcher and exports for the structured AI buyer."""

import asyncio
import os

from commerce.ai.buyer import BuyerProtocolError, run_buyer

__all__ = ["BuyerProtocolError", "run_buyer"]


async def main():
    result = await run_buyer(
        product_request=os.getenv("PRODUCT_REQUEST", "gaming mouse"),
        budget=float(os.getenv("BUYER_BUDGET", "2000")),
        customer_name=os.getenv("CUSTOMER_NAME", "AI Buyer"),
        customer_email=os.getenv("CUSTOMER_EMAIL", "ai-buyer@example.com"),
        shipping_address=os.getenv("SHIPPING_ADDRESS", "Not provided"),
        quantity=int(os.getenv("PRODUCT_QUANTITY", "1")),
        payment_method=os.getenv("PAYMENT_METHOD", "card"),
    )
    print("\nFINAL RESPONSE:\n")
    print(result["message"])


if __name__ == "__main__":
    asyncio.run(main())
