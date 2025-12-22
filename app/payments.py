import os
import httpx

PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET")

async def create_paystack_payment(amount, email, user_id):

    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET}",
        "Content-Type": "application/json"
    }

    data = {
        "email": email,
        "amount": amount * 100,
        "metadata": {
            "telegram_id": user_id
        }
    }

    async with httpx.AsyncClient() as client:
        r = await client.post("https://api.paystack.co/transaction/initialize",
            headers=headers, json=data)

    r.raise_for_status()

    response = r.json()

    checkout_url = response["data"]["authorization_url"]
    reference = response["data"]["reference"]

    return checkout_url, reference
