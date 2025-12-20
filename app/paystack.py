# app/paystack.py
import os
import httpx
from app.utils import generate_reference
import hmac
import hashlib
import json
from sqlalchemy import select, insert
from app.database import async_session
from app.models import RaffleEntry, Ticket
from app.utils import  generate_ticket_code, TICKET_PRICE
from aiogram import Bot
from app.bot import bot

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

async def verify_paystack_webhook(body, signature):

    # must match header signature
    expected = hmac.new(
        PAYSTACK_SECRET.encode(),
        body,
        hashlib.sha512
    ).hexdigest()

    if expected != signature:
        return "invalid_signature"

    payload = json.loads(body)

    # only accept successful payments
    if payload["data"]["status"] != "success":
        return "ignored"

    reference = payload["data"]["reference"]

    async with async_session() as db:

        q = await db.execute(
            select(RaffleEntry).where(RaffleEntry.reference == reference)
        )
        entry = q.scalar_one_or_none()

        if not entry:
            return "entry_not_found"

        if entry.confirmed:
            return "already_confirmed"

        # update raffle entry
        entry.confirmed = True
        db.add(entry)

        # create ticket(s)
        tickets = []
        for _ in range(entry.quantity):
            ticket = Ticket(
                user_id=entry.user_id,
                code=generate_ticket_code()
            )
            db.add(ticket)
            tickets.append(ticket)

        await db.commit()

        # notify user
        try:
            await bot.send_message(
                int(entry.user.telegram_id),
                f"🎉 Payment confirmed!\nYou received {len(tickets)} tickets."
            )
        except:
            pass

    return "success"
