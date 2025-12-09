# app/routers/webhooks.py
from fastapi import APIRouter, Request
from aiogram import types
import asyncio

router = APIRouter()

@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "invalid json"}

    bot = request.app.state.bot
    dp = request.app.state.dp

    try:
        update = types.Update(**body)
    except Exception as e:
        print("❌ Update parse error:", e)
        return {"ok": False, "error": "update parse error"}

    # ✅ respond fast to Telegram, process update in background
    asyncio.create_task(dp.feed_update(bot, update))
    return {"ok": True}
