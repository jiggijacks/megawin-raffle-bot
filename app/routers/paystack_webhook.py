from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select, insert
import os

from app.database import async_session, User, Ticket, RaffleEntry, Transaction
from app.paystack import verify_payment
from app.utils import generate_ticket_code

router = APIRouter(prefix="/webhook", tags=["paystack"])

BOT = None  # injected from main.py


@router.post("/paystack")
async def paystack_webhook(request: Request):
    payload = await request.json()

    event = payload.get("event")
    data = payload.get("data", {})

    if event != "charge.success":
        return {"status": "ignored"}

    reference = data.get("reference")
    metadata = data.get("metadata", {})
    tg_user_id = metadata.get("tg_user_id")

    if not reference or not tg_user_id:
        raise HTTPException(status_code=400, detail="Invalid metadata")

    # 🔎 Verify payment with Paystack
    verify = await verify_payment(reference)
    if not verify.get("status"):
        raise HTTPException(status_code=400, detail="Payment verification failed")

    amount = verify["data"]["amount"] // 100

    async with async_session() as db:
        # Get raffle entry
        q = await db.execute(
            select(RaffleEntry).where(RaffleEntry.reference == reference)
        )
        entry = q.scalar_one_or_none()

        if not entry or entry.confirmed:
            return {"status": "already processed"}

        # Get user
        q = await db.execute(
            select(User).where(User.telegram_id == str(tg_user_id))
        )
        user = q.scalar_one()

        # 🎟 Create tickets
        tickets = []
        for _ in range(entry.quantity):
            code = generate_ticket_code()
            tickets.append(
                {
                    "user_id": user.id,
                    "code": code,
                }
            )

        await db.execute(insert(Ticket), tickets)

        # 💾 Save transaction
        await db.execute(
            insert(Transaction).values(
                user_id=user.id,
                reference=reference,
                amount=amount,
                status="success",
            )
        )

        # ✅ Mark raffle entry confirmed
        entry.confirmed = True
        await db.commit()

    # 📢 Notify user on Telegram
    try:
        await BOT.send_message(
            int(tg_user_id),
            f"✅ Payment confirmed!\n\n"
            f"🎟 Tickets issued: {entry.quantity}\n"
            f"💰 Amount: ₦{amount:,}\n\n"
            f"Good luck 🍀"
        )
    except Exception as e:
        print("Telegram notify failed:", e)

    return {"status": "success"}
