# app/paystack.py
import os
import httpx
from app.utils import generate_reference

PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET", "")
PAYSTACK_BASE_URL = os.getenv("PAYSTACK_BASE_URL", "https://api.paystack.co")

HEADERS = {"Authorization": f"Bearer {PAYSTACK_SECRET}", "Content-Type": "application/json"}

async def create_paystack_payment(amount: int, email: str, tg_user_id: int | None = None):
    if not PAYSTACK_SECRET:
        raise Exception("PAYSTACK_SECRET not configured")
    ref = generate_reference()
    payload = {"email": email, "amount": amount * 100, "reference": ref, "metadata": {"tg_user_id": tg_user_id}}
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(f"{PAYSTACK_BASE_URL}/transaction/initialize", json=payload, headers=HEADERS)
        data = r.json()
        if not data.get("status"):
            raise Exception(f"Paystack init failed: {data}")
        return data["data"]["authorization_url"], ref

async def verify_payment(reference: str):
    if not PAYSTACK_SECRET:
        raise Exception("PAYSTACK_SECRET not configured")
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}", headers=HEADERS)
        return r.json()
