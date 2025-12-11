import os
import httpx
from app.utils import generate_reference

PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET", "")
BASE_URL = os.getenv("PAYSTACK_BASE_URL", "https://api.paystack.co")

if not PAYSTACK_SECRET:
    # don't crash import-time in dev; caller should handle exception where used
    raise Exception("PAYSTACK_SECRET environment variable not set!")

HEADERS = {
    "Authorization": f"Bearer {PAYSTACK_SECRET}",
    "Content-Type": "application/json",
}


async def create_paystack_payment(amount: int, email: str, tg_user_id: int | None = None, tickets: int | None = None):
    """
    amount in Naira (int).
    returns (authorization_url, reference)
    """
    ref = generate_reference()
    payload = {
        "email": email,
        "amount": amount * 100,
        "reference": ref,
        "metadata": {
            "user_id": tg_user_id,
            "tickets": tickets or (amount // 500)
        }
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(f"{BASE_URL}/transaction/initialize", json=payload, headers=HEADERS)
        data = r.json()
        if not data.get("status"):
            raise Exception(f"Paystack init failed: {data}")
        return data["data"]["authorization_url"], ref


async def verify_payment(reference: str):
    """
    Returns the raw Paystack verify response (dict).
    Caller should check status and data.status == "success".
    """
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(f"{BASE_URL}/transaction/verify/{reference}", headers=HEADERS)
        return r.json()
