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
    Paystack webhook → Verify transaction, create tickets, notify user
    """

    payload = await request.json()

    # ---- EXTRACT REFERENCE ----
    data = payload.get("data") or {}
    reference = data.get("reference") or payload.get("reference")
    if not reference:
        raise HTTPException(status_code=400, detail="No reference in payload")

    # ---- VERIFY THROUGH PAYSTACK ----
    verification = await verify_payment(reference)
    status = verification.get("data", {}).get("status")

    if status != "success":
        return {"ok": False, "reason": "payment not successful", "status": status}

    # Customer email (fallback method)
    email = verification.get("data", {}).get("customer", {}).get("email", "")

    # ---- FIND ENTRY ----
    async with async_session() as db:
        q = await db.execute(select(RaffleEntry).where(RaffleEntry.reference == reference))
        entry = q.scalar_one_or_none()

        # fallback: match by email
        if not entry and email:
            uq = await db.execute(select(User).where(User.email == email))
            user = uq.scalar_one_or_none()
            if user:
                eq = await db.execute(
                    select(RaffleEntry)
                    .where(RaffleEntry.user_id == user.id)
                    .order_by(RaffleEntry.created_at.desc())
                )
                entry = eq.scalar_one_or_none()

        if not entry:
            return {"ok": False, "reason": "no raffle entry"}

        # ---- ALREADY PROCESSED ----
        if entry.confirmed:
            return {"ok": True, "processed": False, "reason": "already confirmed"}

        # ---- GET USER ----
        uq = await db.execute(select(User).where(User.id == entry.user_id))
        user = uq.scalar_one()

        # ---- CREATE TRANSACTION ----
        await db.execute(
            insert(Transaction).values(
                user_id=user.id,
                amount=entry.amount,
                reference=entry.reference,
            )
        )

        # ---- CREATE TICKETS ----
        created_codes = []
        for _ in range(entry.quantity or 1):
            code = generate_ticket_code()

            # Ensure unique code
            while True:
                tq = await db.execute(select(Ticket).where(Ticket.code == code))
                if not tq.scalar_one_or_none():
                    break
                code = generate_ticket_code()

            await db.execute(
                insert(Ticket).values(
                    user_id=user.id,
                    code=code
                )
            )
            created_codes.append(code)

        # ---- MARK AS CONFIRMED ----
        entry.confirmed = True
        await db.commit()

    # ---- SEND TELEGRAM MESSAGE TO USER ----
    try:
        bot = request.app.state.bot
        ticket_text = "\n".join(created_codes)

        await bot.send_message(
            chat_id=int(user.telegram_id),
            text=(
                "✅ <b>Payment Confirmed!</b>\n\n"
                f"You purchased <b>{entry.quantity}</b> ticket(s).\n"
                "Your ticket codes:\n\n"
                f"<code>{ticket_text}</code>\n\n"
                "Good luck! 🍀"
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        print("⚠️ Failed to notify user:", e)

    return {"ok": True, "codes": created_codes}
