from fastapi import APIRouter, Request
from aiogram.types import Update
from app.main import app

router = APIRouter()

@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update(**data)

    bot = app.state.bot
    dp = app.state.dp

    await dp.feed_webhook_update(bot, update)

    return {"ok": True}
