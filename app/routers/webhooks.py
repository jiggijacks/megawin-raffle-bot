# app/routers/webhooks.py
from fastapi import APIRouter, Request
from aiogram import types

router = APIRouter()


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """
    Telegram sends updates → convert to aiogram Update → dispatch.
    """

    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "invalid json"}

    bot = request.app.state.bot     # created in main.py
    dp = request.app.state.dp       # dispatcher created in main.py

    try:
        update = types.Update(**body)
    except Exception as e:
        print("❌ Update parse error:", e)
        return {"ok": False, "error": "update parse error"}

    try:
        await dp.feed_update(bot, update)
    except Exception as e:
        print("❌ Handler error:", e)
        return {"ok": False, "error": "handler crashed"}

    return {"ok": True}
