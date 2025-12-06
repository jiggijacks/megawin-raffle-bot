# app/paystack.py
import os
import httpx
from typing import Optional, Dict
from app.utils import generate_reference

# accept either PAYSTACK_SECRET_KEY or PAYSTACK_SECRET for compatibility
PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET_KEY") or os.getenv("PAYSTACK_SECRET")
PAYSTACK_PUBLIC = os.getenv("PAYSTACK_PUBLIC") or os.getenv("PAYSTACK_PUBLIC_KEY", "")

BASE_URL = os.getenv("PAYSTACK_BASE_URL", "https://api.paystack.co")


async def create_paystack_payment(amount: int, email: str, metadata: Optional[Dict] = None):
    """
    Initialize Paystack transaction. Returns (checkout_url, reference).
    - amount: integer in NAIRA (we multiply by 100)
    - metadata: optional dictionary (we use it to pass tg_user_id)
    """
    if not PAYSTACK_SECRET:
        raise Exception("PAYSTACK secret key not configured (PAYSTACK_SECRET_KEY or PAYSTACK_SECRET)")

    ref = generate_reference()
    payload = {
        "email": email,
        "amount": int(amount) * 100,
        "reference": ref,
    }
    if metadata:
        payload["metadata"] = metadata

    async with httpx.AsyncClient(timeout=20.0) as client:
        res = await client.post(
            f"{BASE_URL}/transaction/initialize",
            json=payload,
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET}"}
        )
        data = res.json()
        if not data.get("status"):
            raise Exception(f"Paystack initialize failed: {data}")
        return data["data"]["authorization_url"], ref


async def verify_payment(reference: str):
    """
    Verify a transaction by reference. Returns Paystack response dict.
    """
    if not PAYSTACK_SECRET:
        raise Exception("PAYSTACK secret key not configured (PAYSTACK_SECRET_KEY or PAYSTACK_SECRET)")

    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.get(
            f"{BASE_URL}/transaction/verify/{reference}",
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET}"}
        )
        return res.json()
