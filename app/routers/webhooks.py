from fastapi import APIRouter, Request
from aiogram import types

router = APIRouter()

@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """Receive Telegram updates and pass them to Aiogram dispatcher."""
    try:
        data = await request.json()
    except:
        return {"ok": False, "error": "Invalid JSON"}

    bot = request.app.state.bot
    dp = request.app.state.dp

    try:
        update = types.Update(**data)
    except Exception as e:
        print("❌ Update Parse Error:", e)
        return {"ok": False}

    try:
        await dp.feed_update(bot, update)
    except Exception as e:
        print("❌ Handler Error:", e)

    return {"ok": True}
