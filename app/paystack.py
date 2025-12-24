# app/paystack.py
import os
import hmac
import hashlib
from fastapi import Request, HTTPException
from sqlalchemy import select, update, insert

from app.database import async_session
from app.models import User, RaffleEntry, Ticket
from aiogram import Bot

# 🔐 Paystack live secret key
PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET")
if not PAYSTACK_SECRET:
    raise RuntimeError("PAYSTACK_SECRET not set")

# 🤖 Telegram bot (NO circular overwrite)
bot = Bot(token=os.getenv("BOT_TOKEN"))


async def verify_paystack_webhook(request: Request):
    """
    Paystack webhook endpoint
    URL: /webhook/paystack
    """

    body = await request.body()
    signature = request.headers.get("x-paystack-signature")

    if not signature:
        raise HTTPException(status_code=400, detail="Missing signature")

    # ✅ Verify signature using LIVE SECRET KEY
    computed = hmac.new(
        PAYSTACK_SECRET.encode(),
        body,
        hashlib.sha512
    ).hexdigest()

    if not hmac.compare_digest(computed, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    payload = await request.json()

    # Ignore non-success events
    if payload.get("event") != "charge.success":
        return {"status": "ignored"}

    reference = payload["data"]["reference"]

    async with async_session() as db:
        # 🔎 Find unpaid raffle entry
        q = await db.execute(
            select(RaffleEntry).where(
                RaffleEntry.reference == reference,
                RaffleEntry.confirmed == False
            )
        )
        entry = q.scalar_one_or_none()

        if not entry:
            return {"status": "no_entry"}

        # ✅ Mark as paid
        await db.execute(
            update(RaffleEntry)
            .where(RaffleEntry.id == entry.id)
            .values(confirmed=True)
        )

        # 🎟 Issue tickets
        for _ in range(entry.quantity):
            await db.execute(
                insert(Ticket).values(user_id=entry.user_id)
            )

        # 🔎 Get Telegram user
        q = await db.execute(select(User).where(User.id == entry.user_id))
        user = q.scalar_one()

        await db.commit()

    # 📩 Notify user on Telegram
    try:
        await bot.send_message(
            int(user.telegram_id),
            "🎉 <b>Payment Confirmed!</b>\n\n"
            f"🎟 Tickets issued: {entry.quantity}\n"
            "Good luck 🍀",
            parse_mode="HTML"
        )
    except Exception as e:
        print("Telegram notify failed:", e)

    return {"status": "success"}
