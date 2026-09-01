"""Compatibility launcher and exports for the structured AI buyer."""

import asyncio
import os

from commerce.ai.buyer import BuyerProtocolError, run_buyer

__all__ = ["BuyerProtocolError", "run_buyer"]


async def main():
    result = await run_buyer(
        product_request=os.getenv("PRODUCT_REQUEST"),
        budget=os.getenv("BUYER_BUDGET"),
        customer_name=os.getenv("CUSTOMER_NAME"),
        customer_email=os.getenv("CUSTOMER_EMAIL"),
        shipping_address=os.getenv("SHIPPING_ADDRESS"),
        quantity=os.getenv("PRODUCT_QUANTITY"),
        payment_method=os.getenv("PAYMENT_METHOD"),
    )
    print("\nFINAL RESPONSE:\n")
    print(result["message"])


if __name__ == "__main__":
    asyncio.run(main())
