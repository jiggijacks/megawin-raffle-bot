from fastapi import APIRouter, Request
from aiogram.types import Update
from app.main import app

router = APIRouter(prefix="/webhook")

@router.post("/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()

    try:
        update = Update.model_validate(data)
    except Exception as e:
        print("❌ Webhook parse error:", e)
        print("Payload:", data)
        return {"ok": True}

    bot = app.state.bot
    dp  = app.state.dp

    await dp.feed_update(bot, update)
    return {"ok": True}
