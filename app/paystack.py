import os
import hmac
import hashlib
import httpx

from fastapi import HTTPException, Request
from sqlalchemy import select, insert
from app.database import async_session
from app.models import RaffleEntry, Ticket, User, Transaction
from app.utils import generate_ticket_code

PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET")
PAYSTACK_WEBHOOK_SECRET = os.getenv("PAYSTACK_WEBHOOK_SECRET")


async def verify_paystack_webhook(request: Request):
    # Extract payload
    body = await request.body()

    # Validate signature
    signature = request.headers.get("x-paystack-signature")
    if not signature:
        raise HTTPException(status_code=400, detail="Signature missing")

    hashed = hmac.new(
        PAYSTACK_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha512
    ).hexdigest()

    if hashed != signature:
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()

    # Only accept successful charge events
    if payload.get("event") != "charge.success":
        return {"status": "ignored"}

    reference = payload["data"]["reference"]

    async with async_session() as db:
        # Fetch pending entry
        q = await db.execute(
            select(RaffleEntry).where(
                RaffleEntry.reference == reference,
                RaffleEntry.confirmed == False,
            )
        )
        entry = q.scalar_one_or_none()
        if not entry:
            return {"status": "duplicate_or_not_found"}

        # Mark entry as paid
        entry.confirmed = True

        # Fetch user
        usrq = await db.execute(
            select(User).where(User.id == entry.user_id)
        )
        user = usrq.scalar_one()

        # Create tickets
        tickets = []
        for _ in range(entry.quantity):
            code = generate_ticket_code()
            db.add(Ticket(user_id=user.id, code=code))
            tickets.append(code)

        # Save transaction record
        db.add(
            Transaction(
                user_id=user.id,
                reference=entry.reference,
                amount=entry.amount
            )
        )

        await db.commit()

    return {"status": "success"}
