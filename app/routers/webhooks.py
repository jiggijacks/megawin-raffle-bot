from fastapi import APIRouter, Request
from aiogram.types import Update

router = APIRouter()


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.model_validate(data)

    dp = request.app.state.dp
    bot = request.app.state.bot

    await dp.feed_update(bot, update)
    return {"ok": True}
