import os
import httpx
from app.utils import generate_reference

PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET", "")


BASE_URL = "https://api.paystack.co"


async def create_paystack_payment(amount: int, email: str):
    """
    Initializes a Paystack inline transaction
    """
    ref = generate_reference()

    payload = {
        "email": email,
        "amount": amount * 100,  # Paystack uses kobo
        "reference": ref,
        "callback_url": "https://t.me/MegaWinRaffle"
    }

    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{BASE_URL}/transaction/initialize",
            json=payload,
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET}"}
        )
        data = res.json()

        if not data.get("status"):
            raise Exception(data)

        return data["data"]["authorization_url"], ref


async def verify_payment(reference: str):
    """
    Should be called from webhook.
    """
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{BASE_URL}/transaction/verify/{reference}",
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET}"}
        )

        data = res.json()
        return data
