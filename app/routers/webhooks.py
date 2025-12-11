from fastapi import APIRouter, Request
from aiogram import types

router = APIRouter()


@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """
    Receive Telegram updates and feed them into aiogram Dispatcher.
    Uses types.Update.model_validate to avoid BaseModel positional error.
    """
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "invalid json"}

    bot = request.app.state.bot
    dp = request.app.state.dp

    try:
        # pydantic v2 style model validate
        update = types.Update.model_validate(body)
    except Exception as e:
        print("Update parse error:", e)
        return {"ok": False, "error": "update parse error"}

    try:
        # feed update to dispatcher
        await dp.feed_update(bot, update)
    except Exception as e:
        # don't crash; return 200 so Telegram stops retrying excessively
        print("Handler error:", e)
        return {"ok": False, "error": "handler crashed"}

    return {"ok": True}
