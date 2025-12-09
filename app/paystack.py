import os
import httpx
from app.utils import generate_reference

PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET_KEY", "")
BASE_URL = os.getenv("PAYSTACK_BASE_URL", "https://api.paystack.co")

async def create_paystack_payment(amount: int, email: str, tg_user_id: int | None = None):
    """
    Initialize Paystack transaction.
    amount: naira (int) -> Paystack expects kobo so multiplied by 100
    returns (authorization_url, reference)
    """
    if not PAYSTACK_SECRET:
        raise Exception("PAYSTACK_SECRET_KEY not configured")

    ref = generate_reference()
    payload = {
        "email": email,
        "amount": amount * 100,
        "reference": ref,
        "metadata": {"tg_user_id": tg_user_id}
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        res = await client.post(f"{BASE_URL}/transaction/initialize", json=payload, headers={"Authorization": f"Bearer {PAYSTACK_SECRET}"})
        data = res.json()
        if not data.get("status"):
            raise Exception(f"Paystack init failed: {data}")
        return data["data"]["authorization_url"], ref

async def verify_payment(reference: str):
    if not PAYSTACK_SECRET:
        raise Exception("PAYSTACK_SECRET_KEY not configured")
    async with httpx.AsyncClient(timeout=20.0) as client:
        res = await client.get(f"{BASE_URL}/transaction/verify/{reference}", headers={"Authorization": f"Bearer {PAYSTACK_SECRET}"})
        return res.json()
