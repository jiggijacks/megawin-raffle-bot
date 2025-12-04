# app/routers/paystack_webhook.py
import hashlib
import hmac
import json
import os
from fastapi import APIRouter, Request, HTTPException

from sqlalchemy import select, insert
from app.database import async_session, User, Ticket, Transaction, RaffleEntry
from app.utils import generate_ticket_code, TICKET_PRICE

router = APIRouter(prefix="/webhook/paystack")

PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET_KEY")


def verify_signature(request_body: bytes, signature: str) -> bool:
    """Verify Paystack HMAC signature header"""
    mac = hmac.new(
        PAYSTACK_SECRET.encode("utf-8"),
        msg=request_body,
        digestmod=hashlib.sha512,
    )
    return hmac.compare_digest(mac.hexdigest(), signature)


@router.post("")
async def paystack_webhook(request: Request):
    signature = request.headers.get("x-paystack-signature")
    body = await request.body()

    if not signature:
        raise HTTPException(status_code=400, detail="Missing signature")

    if not verify_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    data = json.loads(body)
    event = data.get("event")

    # ⚠ Only process successful payments
    if event != "charge.success":
        return {"status": "ignored"}

    reference = data["data"]["reference"]
    amount_paid_kobo = data["data"]["amount"]
    amount_paid = amount_paid_kobo / 100  # convert to naira

    async with async_session() as db:
        # Find raffle entry
        q = await db.execute(select(RaffleEntry).where(RaffleEntry.reference == reference))
        entry = q.scalar_one_or_none()

        if not entry:
            return {"status": "unknown_reference"}

        # Avoid double-credit
        q = await db.execute(select(Transaction).where(Transaction.reference == reference))
        exists = q.scalar_one_or_none()
        if exists:
            return {"status": "already_processed"}

        # Create transaction row
        await db.execute(
            insert(Transaction).values(
                user_id=entry.user_id,
                amount=amount_paid,
                reference=reference,
            )
        )

        # Number of tickets = amount_paid / 500
        qty = int(amount_paid / TICKET_PRICE)
        codes = []

        for _ in range(qty):
            ticket_code = generate_ticket_code()
            await db.execute(
                insert(Ticket).values(
                    user_id=entry.user_id,
                    code=ticket_code,
                )
            )
            codes.append(ticket_code)

        # Commit all DB changes
        await db.commit()

    # Notify user (non-blocking)
    # Import bot here to avoid circular import
    from app.bot import bot

    try:
        await bot.send_message(
            chat_id=entry.user_id,
            text=(
                "🎉 <b>Payment Confirmed!</b>\n\n"
                f"Reference: <code>{reference}</code>\n"
                f"Amount Paid: ₦{amount_paid:,.0f}\n"
                f"Tickets Created ({qty}):\n" +
                "\n".join(codes)
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass

    return {"status": "success", "tickets_created": qty}
