import aiohttp
from .config import PAYSTACK_SECRET_KEY, PAYSTACK_URL

async def create_payment_link(tg_id: int, amount: int):
    url = "https://api.paystack.co/transaction/initialize"
    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"
    }
    payload = {
        "email": f"user_{tg_id}@megawinraffle.com",
        "amount": amount * 100,  # Convert to kobo
        "metadata": {"telegram_id": tg_id},
        "callback_url": PAYSTACK_URL,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as response:
            return await response.json()
