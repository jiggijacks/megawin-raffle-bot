from fastapi import APIRouter, Request
from aiogram.types import Update

router = APIRouter()

@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()

    # Parse incoming Telegram Update
    try:
        update = Update.model_validate(data)
    except Exception as e:
        print("❌ Webhook parse error:", e)
        print("Payload:", data)
        return {"ok": True}  # prevent Telegram retries

    bot = request.app.state.bot
    dp = request.app.state.dp

    # Pass update to Aiogram
    await dp.feed_update(bot, update)

    return {"ok": True}
