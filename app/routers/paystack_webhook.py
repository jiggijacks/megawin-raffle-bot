# app/routers/paystack_webhook.py
from fastapi import APIRouter, Request, Header, HTTPException
from app.paystack import verify_payment
from app.database import async_session, RaffleEntry, Ticket, Transaction, User
from app.utils import generate_ticket_code
from sqlalchemy import select, insert, update
from sqlalchemy.exc import NoResultFound

router = APIRouter()


@router.post("/webhook/paystack")
async def paystack_webhook(request: Request, x_paystack_signature: str | None = Header(None)):
    """
    Paystack webhook handler:
      - verifies reference with Paystack API
      - if successful and not processed, mark raffle_entry confirmed,
        create Transaction row and Ticket rows for the requested quantity.
    """
    payload = await request.json()

    # extract reference from webhook payload (flexible)
    data = payload.get("data") or {}
    reference = data.get("reference") or payload.get("reference")
    if not reference:
        raise HTTPException(status_code=400, detail="No reference found in payload")

    # Verify with Paystack API to be safe
    try:
        verification = await verify_payment(reference)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Verification failed: {e}")

    status = verification.get("data", {}).get("status")
    if status != "success":
        # ignore non-final/failed payments
        return {"ok": False, "reason": "payment not successful", "status": status}

    metadata = verification.get("data", {}).get("metadata") or {}
    tg_user_id = metadata.get("tg_user_id")
    email = verification.get("data", {}).get("customer", {}).get("email") or ""

    async with async_session() as db:
        # find the raffle entry by reference
        q = await db.execute(select(RaffleEntry).where(RaffleEntry.reference == reference))
        entry = q.scalar_one_or_none()

        if not entry and email:
            # fallback: find user by email and latest unconfirmed entry
            q = await db.execute(select(User).where(User.email == email))
            user = q.scalar_one_or_none()
            if user:
                q = await db.execute(
                    select(RaffleEntry).where(RaffleEntry.user_id == user.id).order_by(RaffleEntry.created_at.desc())
                )
                entry = q.scalar_one_or_none()

        if not entry:
            return {"ok": False, "reason": "no raffle entry found"}

        if entry.confirmed:
            return {"ok": True, "processed": False, "reason": "already confirmed"}

        # record transaction
        await db.execute(
            insert(Transaction).values(
                user_id=entry.user_id,
                amount=entry.amount,
                reference=entry.reference
            )
        )

        # create tickets
        created_codes = []
        qty = int(entry.quantity or 1)
        for _ in range(qty):
            code = generate_ticket_code()
            # ensure unique
            while True:
                q = await db.execute(select(Ticket).where(Ticket.code == code))
                if not q.scalar_one_or_none():
                    break
                code = generate_ticket_code()
            await db.execute(insert(Ticket).values(user_id=entry.user_id, code=code))
            created_codes.append(code)

        # mark entry as confirmed
        await db.execute(
            update(RaffleEntry).where(RaffleEntry.id == entry.id).values(confirmed=True)
        )
        await db.commit()

    return {"ok": True, "codes": created_codes}
