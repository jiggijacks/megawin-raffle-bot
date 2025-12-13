# app/paystack.py
import os
import httpx
from app.utils import generate_reference

PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET", "")
BASE_URL = os.getenv("PAYSTACK_BASE_URL", "https://api.paystack.co")

if not PAYSTACK_SECRET:
    raise Exception("PAYSTACK_SECRET environment variable not set!")

HEADERS = {
    "Authorization": f"Bearer {PAYSTACK_SECRET}",
    "Content-Type": "application/json",
}


async def create_paystack_payment(amount: int, email: str, tg_user_id: int | None = None):
    """
    Creates a Paystack payment session and returns:
        (authorization_url, reference)
    """

    reference = generate_reference()

    payload = {
        "email": email,
        "amount": amount * 100,  # Paystack accepts kobo
        "reference": reference,
        "metadata": {
            "tg_user_id": tg_user_id
        }
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            r = await client.post(
                f"{BASE_URL}/transaction/initialize",
                json=payload,
                headers=HEADERS
            )
        except Exception as e:
            print("Error contacting Paystack:", e)
            raise

        data = r.json()

        if not data.get("status"):
            print("Paystack init failed:", data)
            raise Exception(f"Paystack error: {data}")

        return data["data"]["authorization_url"], reference



async def verify_payment(reference: str) -> dict:
    """
    Fetch transaction details from Paystack:
        returns r.json()
    """
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(
            f"{BASE_URL}/transaction/verify/{reference}",
            headers=HEADERS
        )
        return r.json()
