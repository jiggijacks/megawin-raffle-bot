# app/routers/webhooks.py
from fastapi import APIRouter, Request
from aiogram import Bot
from aiogram.types import Update

router = APIRouter()

@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    print("🔥 WEBHOOK HIT")
    bot: Bot = request.app.state.bot
    dp = request.app.state.dp

    data = await request.json()
    print("📩 Incoming update:", data)
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}
