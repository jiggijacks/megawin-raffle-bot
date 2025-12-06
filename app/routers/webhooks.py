from fastapi import APIRouter, Request
from aiogram.types import Update
import traceback

from app.bot import bot, dp

router = APIRouter()

@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()
    try:
        update = Update.model_validate(data)
        await dp.feed_update(bot, update)
    except Exception:
        traceback.print_exc()
    return {"ok": True}
