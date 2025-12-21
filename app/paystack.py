import hashlib
import hmac
import json
from fastapi import Request, HTTPException
from app.database import async_session
from app.models import User, RaffleEntry, Ticket
from sqlalchemy import select, update
from app.bot import bot
import os

PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET")


async def verify_paystack_webhook(request: Request):

    # Raw body for hashing
    body_bytes = await request.body()

    # Signature from header
    signature = request.headers.get("x-paystack-signature")

    if not signature:
        raise HTTPException(status_code=400, detail="Missing signature")

    # Hash using LIVE SECRET KEY  
    computed = hmac.new(
        PAYSTACK_SECRET.encode('utf-8'),
        body_bytes,
        hashlib.sha512
    ).hexdigest()

    if computed != signature:
        raise HTTPException(status_code=400, detail="Invalid signature")

    data = await request.json()

    if data["event"] != "charge.success":
        return {"status": "ignored"}

    ref = data["data"]["reference"]

    # Find unpaid entry
    async with async_session() as db:
        q = await db.execute(select(RaffleEntry).where(
            RaffleEntry.reference == ref,
            RaffleEntry.confirmed == False
        ))
        entry = q.scalar_one_or_none()

        if not entry:
            return {"status": "no entry"}

        # Mark paid
        await db.execute(
            update(RaffleEntry)
            .where(RaffleEntry.id == entry.id)
            .values(confirmed=True)
        )

        # Add tickets
        for _ in range(entry.quantity):
            await db.execute(
                Ticket.__table__.insert().values(user_id=entry.user_id)
            )

        await db.commit()

    # Notify user
    await bot.send_message(
        entry.user_id,
        "🎉 Payment confirmed! Your raffle tickets have been issued."
    )

    return {"status": "success"}
