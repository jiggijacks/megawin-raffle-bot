from fastapi import APIRouter, Request
from aiogram import Bot
from aiogram.dispatcher.router import Dispatcher

router = APIRouter()

@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    bot: Bot = request.app.state.bot
    dp: Dispatcher = request.app.state.dp

    update = await request.json()

    await dp.feed_webhook_update(bot, update)
    return {"status": "ok"}



