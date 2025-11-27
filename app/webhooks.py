from fastapi import APIRouter, Request, HTTPException
from aiogram import Bot
from aiogram.types import Update

from app.database import async_session, User, Ticket
from app.paystack import verify_payment
from app.utils import generate_ticket_code, logger
from sqlalchemy import select

router = APIRouter()


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    bot: Bot = request.app.state.bot
    body = await request.body()

    update = Update.model_validate_json(body)
    await bot.dispatcher.feed_update(bot, update)
    return {"ok": True}


@router.post("/webhook/paystack")
async def paystack_webhook(request: Request):
    body = await request.json()
    event = body.get("event")

    if event != "charge.success":
        return {"status": "ignored"}

    data = body["data"]
    ref = data["reference"]
    amount = data["amount"] // 100
    telegram_id = data["metadata"]["telegram_id"]

    if not await verify_payment(ref):
        raise HTTPException(400, "Verification failed")

    ticket_count = amount // 500

    async with async_session() as session:
        r = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = r.scalar()

        if not user:
            user = User(telegram_id=telegram_id)
            session.add(user)
            await session.commit()

        for _ in range(ticket_count):
            session.add(Ticket(user_id=user.id, code=generate_ticket_code()))

        await session.commit()

    bot: Bot = request.app.state.bot
    await bot.send_message(telegram_id, f"Payment confirmed! {ticket_count} tickets added.")

    return {"status": "success"}
