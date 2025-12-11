from fastapi import APIRouter, Request, HTTPException
from app.paystack import verify_payment
from app.database import async_session, RaffleEntry, Ticket, Transaction, User
from app.utils import generate_ticket_code
from sqlalchemy import select, insert
from sqlalchemy.exc import NoResultFound

router = APIRouter()


@router.post("/webhook/paystack")
async def paystack_webhook(request: Request):
    """
    Paystack webhook handler that verifies transaction and issues tickets.
    """
    payload = await request.json()

    # extract reference from typical event structure
    data = payload.get("data", {}) or {}
    reference = data.get("reference") or payload.get("reference")
    if not reference:
        raise HTTPException(status_code=400, detail="no reference")

    # verify with Paystack
    try:
        verification = await verify_payment(reference)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"verification failed: {e}")

    if not verification.get("status"):
        # verification API call itself failed
        return {"ok": False, "reason": "verification API returned non-OK"}

    tx = verification.get("data", {}) or {}
    if tx.get("status") != "success":
        # transaction not successful
        return {"ok": False, "status": tx.get("status")}

    # get metadata (we stored user_id, tickets in create_paystack_payment)
    metadata = tx.get("metadata") or {}
    metadata_user_id = metadata.get("user_id")
    metadata_tickets = int(metadata.get("tickets") or 0)

    # attempt to find the raffle entry by reference
    async with async_session() as db:
        q = await db.execute(select(RaffleEntry).where(RaffleEntry.reference == reference))
        entry = q.scalar_one_or_none()

        # fallback: if not found, try to locate by metadata user_id and latest unconfirmed entry
        if not entry and metadata_user_id:
            q = await db.execute(select(User).where(User.id == int(metadata_user_id)))
            user = q.scalar_one_or_none()
            if user:
                q = await db.execute(
                    select(RaffleEntry)
                    .where(RaffleEntry.user_id == user.id)
                    .order_by(RaffleEntry.created_at.desc())
                )
                entry = q.scalar_one_or_none()

        if not entry:
            # nothing to process
            return {"ok": False, "reason": "no_matching_entry"}

        if entry.confirmed:
            return {"ok": True, "processed": False, "reason": "already_confirmed"}

        # create Transaction row
        await db.execute(insert(Transaction).values(
            user_id=entry.user_id,
            amount=entry.amount,
            reference=entry.reference
        ))

        # create tickets (quantity from entry)
        created_codes = []
        qty = entry.quantity or metadata_tickets or 1
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
            RaffleEntry.__table__.update().where(RaffleEntry.id == entry.id).values(confirmed=True)
        )

        await db.commit()

        # notify user (try)
        try:
            q = await db.execute(select(User).where(User.id == entry.user_id))
            user = q.scalar_one_or_none()
            if user:
                # send DM
                try:
                    await request.app.state.bot.send_message(
                        int(user.telegram_id),
                        "✅ Payment received — your tickets have been issued:\n\n" +
                        "\n".join(created_codes)
                    )
                except Exception:
                    # ignore DM failure
                    pass
        except Exception:
            pass

    return {"ok": True, "codes": created_codes}
