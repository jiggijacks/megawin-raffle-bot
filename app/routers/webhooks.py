# app/routers/webhooks.py
from fastapi import APIRouter, Request, HTTPException
from aiogram.types import Update

router = APIRouter()


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """
    Telegram sends updates here.
    Converts raw JSON into aiogram Update and gives it to Dispatcher.
    """

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    # Load bot + dispatcher created in main.py startup()
    bot = request.app.state.bot
    dp = request.app.state.dp

    try:
        update = Update.model_validate(data)
    except Exception as e:
        raise HTTPException(400, f"Invalid Telegram payload: {e}")

    # Aiogram v3 correct call:
    await dp.router.propagate_event(update, bot=bot)

    return {"ok": True}
