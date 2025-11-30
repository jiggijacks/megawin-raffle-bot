from fastapi import APIRouter, Request
from aiogram import Bot
from aiogram.types import Update

router = APIRouter()

@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    bot: Bot = request.app.state.bot     # now this exists
    dp = request.app.state.dp            # now this exists

    data = await request.json()
    update = Update.model_validate(data)

    await dp.feed_update(bot, update)
    return {"ok": True}
