# app/routers/paystack_webhook.py
from fastapi import APIRouter, Request, Header, HTTPException
from paystack import verify_payment
from app.database import async_session, RaffleEntry, Ticket, Transaction, User
from utils import generate_ticket_code
from sqlalchemy import select, insert
from sqlalchemy.exc import NoResultFound

router = APIRouter()

@router.post("/webhook/paystack")
async def paystack_webhook(request: Request, x_paystack_signature: str | None = Header(None)):
    """
    Paystack webhook handler.
    Verifies transaction, creates Transaction and Ticket rows, marks entry confirmed.
    """
    payload = await request.json()
    data = payload.get("data") or {}
    reference = data.get("reference") or payload.get("reference")
    if not reference:
        raise HTTPException(status_code=400, detail="No reference in payload")

    # Verify via Paystack REST API
    try:
        verification = await verify_payment(reference)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"verify failed: {e}")

    status = verification.get("data", {}).get("status")
    if status != "success":
        return {"ok": False, "reason": "payment not successful", "status": status}

    metadata = verification.get("data", {}).get("metadata", {}) or {}
    tg_user_id = metadata.get("tg_user_id")
    email = verification.get("data", {}).get("customer", {}).get("email") or ""

    async with async_session() as db:
        q = await db.execute(select(RaffleEntry).where(RaffleEntry.reference == reference))
        entry = q.scalar_one_or_none()

        if not entry and email:
            # fallback: find user by email and latest unconfirmed entry
            q = await db.execute(select(User).where(User.email == email))
            user = q.scalar_one_or_none()
            if user:
                q = await db.execute(select(RaffleEntry).where(RaffleEntry.user_id == user.id).order_by(RaffleEntry.created_at.desc()))
                entry = q.scalar_one_or_none()

        if not entry:
            return {"ok": False, "reason": "no raffle entry"}

        if entry.confirmed:
            return {"ok": True, "processed": False, "reason": "already confirmed"}

        # create transaction row
        await db.execute(insert(Transaction).values(user_id=entry.user_id, amount=entry.amount, reference=entry.reference))

        # create tickets
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

        # mark entry confirmed
        await db.execute(
            RaffleEntry.__table__.update().where(RaffleEntry.id == entry.id).values(confirmed=True)
        )
        await db.commit()

    return {"ok": True, "codes": created_codes}
