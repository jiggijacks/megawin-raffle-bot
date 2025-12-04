# routers/paystack_webhook.py
import os
from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select, insert
from app.database import async_session, RaffleEntry, Ticket, Transaction, User
from app.utils import generate_ticket_code

router = APIRouter()


@router.post("/webhook/paystack")
async def paystack_webhook(request: Request):
    """
    Handles Paystack payment verification webhook.
    Expected JSON payload contains 'event' and 'data' fields (Paystack standard).
    """
    PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET_KEY")
    # Optional: verify ip/header signature if you want stronger security
    body = await request.json()

    # paystack usually wraps event/data, but some setups post {status, reference, ...}
    data = body.get("data") if isinstance(body, dict) and body.get("data") else body

    reference = data.get("reference")
    status = data.get("status") or data.get("gateway_response") or data.get("paid")
    # normalize status
    status = (status or "").lower()

    if not reference:
        raise HTTPException(status_code=400, detail="No reference in payload")

    async with async_session() as db:
        q = await db.execute(select(RaffleEntry).where(RaffleEntry.reference == reference))
        entry = q.scalar_one_or_none()
        if not entry:
            # unknown reference — ignore or 404
            return {"ok": False, "reason": "unknown_reference"}

        if entry.confirmed:
            return {"ok": True, "reason": "already_confirmed"}

        # Accept statuses like "success", "paid", or boolean True in 'paid'
        accepted = False
        if status in ("success", "paid", "true", "ok", "completed") or data.get("paid") is True:
            accepted = True
        # Some Paystack payloads use 'status' == 'success'
        if not accepted:
            # do not confirm, but respond OK to webhook
            return {"ok": False, "reason": "payment_not_successful"}

        # Mark entry confirmed
        entry.confirmed = True
        db.add(entry)
        # Create transaction
        await db.execute(insert(Transaction).values(user_id=entry.user_id, amount=entry.amount, reference=entry.reference))

        # create tickets for quantity
        created_codes = []
        for _ in range(entry.quantity or 0):
            # generate until unique
            code = generate_ticket_code()
            exists_q = await db.execute(select(Ticket).where(Ticket.code == code))
            if exists_q.scalar_one_or_none():
                code = generate_ticket_code()
            await db.execute(insert(Ticket).values(user_id=entry.user_id, code=code))
            created_codes.append(code)

        await db.commit()

    # Optionally notify user by DM — do this asynchronously outside db context
    # We'll just return OK
    return {"ok": True, "tickets_created": len(created_codes)}
