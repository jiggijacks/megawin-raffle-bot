from fastapi import APIRouter, Request
from aiogram import Bot, Dispatcher
from aiogram.types import Update

router = APIRouter()


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """Receive Telegram updates from webhook and feed to dispatcher."""

    bot: Bot = request.app.state.bot
    dp: Dispatcher = request.app.state.dp

    data = await request.json()
    update = Update.model_validate(data)

    await dp.feed_update(bot, update)

    return {"ok": True}
