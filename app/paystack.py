import httpx
import os
import uuid

PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET")
PAYSTACK_URL = "https://api.paystack.co/transaction/initialize"

async def create_paystack_payment(email: str, amount: int, user_id: int):
    reference = f"raffle_{user_id}_{uuid.uuid4().hex}"

    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET}",
        "Content-Type": "application/json",
    }

    payload = {
        "email": email,
        "amount": amount * 100,  # Paystack uses kobo
        "reference": reference,
        "callback_url": "https://YOUR_DOMAIN/webhook/paystack"
    }

    async with httpx.AsyncClient() as client:
        res = await client.post(PAYSTACK_URL, json=payload, headers=headers)
        data = res.json()

    if not data.get("status"):
        raise Exception("Paystack init failed")

    return data["data"]["authorization_url"], reference
