# app/routers/paystack_webhook.py
from fastapi import APIRouter, Request, Header, HTTPException
from app.paystack import verify_payment
from app.database import async_session, RaffleEntry, Ticket, Transaction, User
from app.utils import generate_ticket_code
from sqlalchemy import select, insert

router = APIRouter()

@router.post("/webhook/paystack")
async def paystack_webhook(request: Request, x_paystack_signature: str | None = Header(None)):
    """
    Very small Paystack webhook handler.
    - Verifies the reference with Paystack API
    - If successful, creates Transaction + Ticket rows and notifies user via Telegram bot
    """
    payload = await request.json()
    data = payload.get("data") or {}
    reference = data.get("reference") or payload.get("reference")
    if not reference:
        raise HTTPException(status_code=400, detail="no reference")

    # Verify using Paystack API
    try:
        verified = await verify_payment(reference)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"paystack verify failed: {e}")

    status = verified.get("data", {}).get("status")
    if status != "success":
        return {"ok": False, "reason": "not successful", "status": status}

    # find raffle entry by reference (or fallback by email)
    email = verified.get("data", {}).get("customer", {}).get("email", "")
    metadata = verified.get("data", {}).get("metadata", {}) or {}
    tg_user_id = metadata.get("tg_user_id")

    async with async_session() as db:
        q = await db.execute(select(RaffleEntry).where(RaffleEntry.reference == reference))
        entry = q.scalar_one_or_none()

        if not entry and email:
            q = await db.execute(select(User).where(User.email == email))
            user = q.scalar_one_or_none()
            if user:
                q = await db.execute(select(RaffleEntry).where(RaffleEntry.user_id == user.id).order_by(RaffleEntry.created_at.desc()))
                entry = q.scalar_one_or_none()

        if not entry:
            return {"ok": False, "reason": "no raffle entry"}

        if entry.confirmed:
            return {"ok": True, "processed": False, "reason": "already confirmed"}

        # create Transaction row
        await db.execute(insert(Transaction).values(
            user_id=entry.user_id,
            amount=entry.amount,
            reference=entry.reference
        ))

        # create ticket rows
        created_codes = []
        for _ in range(entry.quantity or 1):
            code = generate_ticket_code()
            # ensure unique
            while True:
                q = await db.execute(select(Ticket).where(Ticket.code == code))
                if not q.scalar_one_or_none():
                    break
                code = generate_ticket_code()
            await db.execute(insert(Ticket).values(user_id=entry.user_id, code=code))
            created_codes.append(code)

        # mark raffle entry confirmed
        await db.execute(RaffleEntry.__table__.update().where(RaffleEntry.id == entry.id).values(confirmed=True))
        await db.commit()

        # notify user on Telegram (use bot from app.state)
        try:
            bot = request.app.state.bot
            # fetch user
            q = await db.execute(select(User).where(User.id == entry.user_id))
            user = q.scalar_one()
            text = (
                f"✅ Payment confirmed!\n\n"
                f"You purchased {entry.quantity} ticket(s).\n"
                f"Your ticket codes:\n" + "\n".join(created_codes)
            )
            await bot.send_message(int(user.telegram_id), text)
        except Exception as e:
            print("Warning: could not notify user:", e)

    return {"ok": True, "codes": created_codes}
