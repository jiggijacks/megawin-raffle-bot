from fastapi import APIRouter, Request
from aiogram import types

router = APIRouter()


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):

    # Telegram sends JSON update here
    payload = await request.json()

    bot = request.app.state.bot
    dp = request.app.state.dp

    # Convert JSON → aiogram Update
    update = types.Update(**payload)

    # Send update into dispatcher (Aiogram v3 correct method)
    await dp.feed_update(bot, update)

    return {"ok": True}
