# app/routers/webhooks.py
from fastapi import APIRouter, Request
from aiogram import types
from app.utils import handle_telegram_update

router = APIRouter()


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """
    This receives Telegram updates and forwards them
    into aiogram's Dispatcher stored in app.state.dp.
    """
    payload = await request.json()
    
    # access bot + dp through request.app.state
    bot = request.app.state.bot
    dp = request.app.state.dp

    update = types.Update(**payload)

    await dp.feed_update(bot, update)
    return {"ok": True}
