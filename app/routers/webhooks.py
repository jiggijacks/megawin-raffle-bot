# app/routers/webhooks.py
from fastapi import APIRouter, Request
from aiogram import types

router = APIRouter()


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """
    Telegram sends updates here.
    We pass them into aiogram's dispatcher stored in app.state.dp.
    """

    payload = await request.json()

    bot = request.app.state.bot         # Bot instance
    dp = request.app.state.dp           # Dispatcher instance

    update = types.Update(**payload)

    await dp.feed_update(bot, update)

    return {"ok": True}
