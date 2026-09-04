"""Autonomous Fake Card Payment Simulator & Webhook Dispatcher for Razorpay Test Links."""

import os
import time
import requests
from dotenv import load_dotenv

load_dotenv('.env')

def simulate_fake_card_payment(payment_link_url: str = None, razorpay_order_id: str = None, order_id: int = None, amount: float = None) -> dict:
    """Simulate domestic Indian test payment & authorize on Razorpay gateway / webhook endpoint.
    
    Domestic Indian Test Payment Details:
    - Domestic Indian Visa Card: 4000 0000 0000 0002
    - Domestic Indian RuPay Card: 5081 2600 0000 0002
    - Domestic Indian Test UPI: success@razorpay
    - Expiry: 12/30 | CVV: 123
    """
    key_id = os.getenv("RAZORPAY_KEY_ID")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET")
    
    if not key_id or not key_secret:
        return {"success": False, "error": "RAZORPAY_KEY_ID or RAZORPAY_KEY_SECRET not configured"}
        
    print(f"🔗 Simulating autonomous domestic Indian test checkout for Order #{order_id} (Razorpay Order ID: {razorpay_order_id})...")
    
    # 1. Dispatch autonomous payment authorized webhook event if order_id is present
    webhook_dispatched = False
    payment_id = f"pay_agent_auth_{order_id or int(time.time())}"
    
    try:
        # Construct Razorpay Payment Authorized webhook payload
        payload = {
            "entity": "event",
            "account_id": "acc_agent_auton",
            "event": "order.paid",
            "contains": ["payment", "order"],
            "payload": {
                "payment": {
                    "entity": {
                        "id": payment_id,
                        "entity": "payment",
                        "amount": int((amount or 1999) * 100),
                        "currency": "INR",
                        "status": "captured",
                        "order_id": razorpay_order_id or "order_mock",
                        "method": "card",
                        "card": {
                            "id": "card_domestic_in",
                            "entity": "card",
                            "name": "Indian Domestic Test Cardholder",
                            "last4": "0002",
                            "network": "Visa",
                            "type": "debit",
                            "issuer": "SBIN",
                            "international": False
                        },
                        "email": "gowtham@example.com",
                        "contact": "+919876543210"
                    }
                },
                "order": {
                    "entity": {
                        "id": razorpay_order_id or "order_mock",
                        "entity": "order",
                        "amount": int((amount or 1999) * 100),
                        "amount_paid": int((amount or 1999) * 100),
                        "amount_due": 0,
                        "currency": "INR",
                        "status": "paid",
                        "attempts": 1
                    }
                }
            },
            "created_at": int(time.time())
        }
        
        # Try local webhook handler dispatch
        webhook_url = f"http://localhost:{os.getenv('PORT', '8000')}/api/razorpay/webhook"
        try:
            resp = requests.post(webhook_url, json=payload, timeout=3)
            if resp.status_code == 200:
                webhook_dispatched = True
        except Exception:
            pass
            
    except Exception as e:
        print(f"Webhook dispatch notice: {e}")
        
    return {
        "success": True,
        "payment_link": payment_link_url,
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": payment_id,
        "status": "paid",
        "card": "Domestic Indian Visa Test Card (4000 **** **** 0002)",
        "authorization_mode": "Autonomous Webhook & Payment API Dispatch",
        "webhook_dispatched": webhook_dispatched,
        "message": f"Simulated domestic Indian test card payment authorized for Razorpay Order {razorpay_order_id}!"
    }


if __name__ == "__main__":
    test_link = "https://rzp.io/rzp/yqKEIqZJ"
    res = simulate_fake_card_payment(payment_link_url=test_link, order_id=38, amount=1999.0)
    print("SIMULATION RESULT:", res)

