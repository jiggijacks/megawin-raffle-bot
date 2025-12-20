from fastapi import APIRouter, Request, HTTPException
import os
import hmac
import hashlib

from sqlalchemy import select, insert, update

from app.database import async_session
from app.models import User, Ticket, RaffleEntry, Transaction
from app.paystack import verify_payment
from app.utils import generate_ticket_code
from app.bot import bot

router = APIRouter(prefix="/webhook/paystack")

PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET", "")
PAYSTACK_WEBHOOK_SECRET = os.getenv("PAYSTACK_WEBHOOK_SECRET", "")


def verify_signature(payload: bytes, signature: str) -> bool:
    if not PAYSTACK_WEBHOOK_SECRET:
        return True  # allow if not set (for testing)

    computed = hmac.new(
        PAYSTACK_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(computed, signature)


@router.post("")
async def paystack_webhook(request: Request):
    payload = await request.body()
    signature = request.headers.get("x-paystack-signature", "")

    if not verify_signature(payload, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    data = await request.json()

    if data.get("event") != "charge.success":
        return {"status": "ignored"}

    reference = data["data"]["reference"]

    # Verify payment again with Paystack
    verification = await verify_payment(reference)
    if not verification.get("status"):
        return {"status": "verification_failed"}

    pay_data = verification["data"]
    amount = pay_data["amount"] // 100
    email = pay_data["customer"]["email"]
    tg_user_id = pay_data.get("metadata", {}).get("tg_user_id")

    async with async_session() as db:
        q = await db.execute(
            select(RaffleEntry).where(RaffleEntry.reference == reference)
        )
        entry = q.scalar_one_or_none()

        if not entry or entry.confirmed:
            return {"status": "already_processed"}

        # Confirm entry
        await db.execute(
            update(RaffleEntry)
            .where(RaffleEntry.id == entry.id)
            .values(confirmed=True)
        )

        # Get user
        q = await db.execute(select(User).where(User.id == entry.user_id))
        user = q.scalar_one()

        # Issue tickets
        tickets = []
        for _ in range(entry.quantity):
            code = generate_ticket_code()
            tickets.append(code)
            await db.execute(insert(Ticket).values(
                user_id=user.id,
                code=code
            ))

        # Save transaction
        await db.execute(insert(Transaction).values(
            user_id=user.id,
            reference=reference,
            amount=amount,
            status="success"
        ))

        await db.commit()

    # Notify user on Telegram
    try:
        if bot:
            await bot.send_message(
                int(user.telegram_id),
                "✅ <b>Payment Confirmed!</b>\n\n"
                f"🎟 Tickets issued: {entry.quantity}\n"
                f"💳 Amount: ₦{amount:,}\n\n"
                "Good luck 🍀",
                parse_mode="HTML"
            )
    except Exception as e:
        print("Telegram notify failed:", e)

    return {"status": "ok"}
