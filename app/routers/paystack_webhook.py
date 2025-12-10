# app/routers/paystack_webhook.py
from fastapi import APIRouter, Request, Header, HTTPException
from app.paystack import verify_payment
from app.database import async_session, RaffleEntry, Ticket, Transaction, User
from app.utils import generate_ticket_code
from sqlalchemy import select, insert
from sqlalchemy.exc import NoResultFound
import traceback

router = APIRouter()

@router.post("/webhook/paystack")
async def paystack_webhook(request: Request, x_paystack_signature: str | None = Header(None)):
    """
    Paystack webhook handler.
    Verifies transaction, creates Transaction and Ticket rows, marks entry confirmed.
    """
    try:
        payload = await request.json()
    except Exception as e:
        print("Paystack webhook: invalid json", e)
        raise HTTPException(status_code=400, detail="invalid json")

    data = payload.get("data") or {}
    reference = data.get("reference") or payload.get("reference")
    if not reference:
        raise HTTPException(status_code=400, detail="No reference in payload")

    # Verify via Paystack REST API (verify_payment should call Paystack verify endpoint)
    try:
        verification = await verify_payment(reference)
    except Exception as e:
        print("Paystack verify error:", e)
        raise HTTPException(status_code=500, detail=f"verify failed: {e}")

    status = verification.get("data", {}).get("status")
    if status != "success":
        print("Paystack webhook: payment not successful", reference, status)
        return {"ok": False, "reason": "payment not successful", "status": status}

    metadata = verification.get("data", {}).get("metadata", {}) or {}
    tg_user_id = metadata.get("tg_user_id")
    email = verification.get("data", {}).get("customer", {}).get("email") or ""

    created_codes = []
    async with async_session() as db:
        # find the pending raffle entry
        q = await db.execute(select(RaffleEntry).where(RaffleEntry.reference == reference))
        entry = q.scalar_one_or_none()

        # fallback: if not found, try by email -> latest unconfirmed entry
        if not entry and email:
            q = await db.execute(select(User).where(User.email == email))
            user = q.scalar_one_or_none()
            if user:
                q = await db.execute(select(RaffleEntry).where(RaffleEntry.user_id == user.id).order_by(RaffleEntry.created_at.desc()))
                entry = q.scalar_one_or_none()

        if not entry:
            print("Paystack webhook: no raffle entry found for reference", reference)
            return {"ok": False, "reason": "no raffle entry"}

        if getattr(entry, "confirmed", False):
            print("Paystack webhook: entry already confirmed", reference)
            return {"ok": True, "processed": False, "reason": "already confirmed"}

        # create transaction row
        try:
            await db.execute(insert(Transaction).values(user_id=entry.user_id, amount=entry.amount, reference=entry.reference))
        except Exception as e:
            print("Error inserting transaction:", e)
            traceback.print_exc()

        # create tickets (one row per quantity)
        for _ in range(getattr(entry, "quantity", 1) or 1):
            code = generate_ticket_code()
            # ensure unique
            for _retry in range(20):
                q = await db.execute(select(Ticket).where(Ticket.code == code))
                if not q.scalar_one_or_none():
                    break
                code = generate_ticket_code()
            try:
                await db.execute(insert(Ticket).values(user_id=entry.user_id, code=code))
            except Exception as e:
                print("Error inserting ticket:", e)
                traceback.print_exc()
                continue
            created_codes.append(code)

        # mark entry confirmed
        try:
            await db.execute(
                RaffleEntry.__table__.update().where(RaffleEntry.id == entry.id).values(confirmed=True)
            )
            await db.commit()
        except Exception as e:
            print("Error marking entry confirmed:", e)
            traceback.print_exc()

    # notify the user (using app state bot if available)
    try:
        bot = request.app.state.bot
        # attempt to find telegram id from User table
        async with async_session() as db:
            uq = await db.execute(select(User).where(User.id == entry.user_id))
            u = uq.scalar_one_or_none()
        if u:
            tg = int(u.telegram_id) if getattr(u, "telegram_id", None) else (int(tg_user_id) if tg_user_id else None)
            if tg:
                body = "\n".join(created_codes[:50])
                more = len(created_codes) - len(created_codes[:50])
                if more > 0:
                    body += f"\n...and {more} more"
                try:
                    await bot.send_message(tg, f"✅ <b>Payment verified!</b>\nYour tickets:\n{body}")
                except Exception:
                    print("Could not send DM to user", tg)
    except Exception as e:
        print("Notification error:", e)

    print("Paystack webhook: tickets created for reference", reference, created_codes[:6])
    return {"ok": True, "codes": created_codes}
