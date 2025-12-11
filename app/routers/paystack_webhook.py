import os
import hmac
import hashlib
from fastapi import APIRouter, Request, Header, HTTPException

from app.paystack import verify_payment
from app.database import async_session, RaffleEntry, Ticket, Transaction, User
from app.utils import generate_ticket_code
from sqlalchemy import select, insert

router = APIRouter()

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

def verify_signature(raw_body: bytes, signature: str | None):
    if not WEBHOOK_SECRET:
        print("WARNING: WEBHOOK_SECRET NOT SET — SKIPPING SIGNATURE CHECK")
        return True

    computed = hmac.new(
        WEBHOOK_SECRET.encode(),
        raw_body,
        hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(computed, signature or "")

@router.post("/webhook/paystack")
async def paystack_webhook(request: Request, x_paystack_signature: str | None = Header(None)):

    raw = await request.body()
    if not verify_signature(raw, x_paystack_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()
    data = payload.get("data", {})
    reference = data.get("reference")

    if not reference:
        raise HTTPException(status_code=400, detail="Missing reference")

    verification = await verify_payment(reference)

    if verification.get("data", {}).get("status") != "success":
        return {"ok": False, "reason": "not successful"}

    metadata = verification["data"].get("metadata", {})
    tg_user_id = metadata.get("tg_user_id")

    created = []

    async with async_session() as db:

        # Load entry
        q = await db.execute(select(RaffleEntry).where(RaffleEntry.reference == reference))
        entry = q.scalar_one_or_none()

        if not entry:
            return {"ok": False, "reason": "entry not found"}

        if entry.confirmed:
            return {"ok": True, "processed": False, "reason": "already confirmed"}

        await db.execute(insert(Transaction).values(
            user_id=entry.user_id,
            amount=entry.amount,
            reference=reference
        ))

        # Create tickets
        for _ in range(entry.quantity):
            code = generate_ticket_code()

            # uniqueness
            while True:
                q = await db.execute(select(Ticket).where(Ticket.code == code))
                if not q.scalar_one_or_none():
                    break
                code = generate_ticket_code()

            await db.execute(insert(Ticket).values(user_id=entry.user_id, code=code))
            created.append(code)

        await db.execute(
            RaffleEntry.__table__.update()
            .where(RaffleEntry.id == entry.id)
            .values(confirmed=True)
        )

        await db.commit()

    # notify user
    try:
        bot = request.app.state.bot
        q = await async_session().execute(select(User).where(User.id == entry.user_id))
        user = q.scalar_one()

        if user and user.telegram_id:
            await bot.send_message(
                int(user.telegram_id),
                "🎉 Payment Successful!\nYour tickets:\n" + "\n".join(created)
            )
    except Exception as e:
        print("DM failed:", e)

    return {"ok": True, "tickets": created}
