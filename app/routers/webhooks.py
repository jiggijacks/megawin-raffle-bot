# app/routers/webhooks.py
from fastapi import APIRouter, Request
from aiogram import types

router = APIRouter()

@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "invalid json"}

    bot = request.app.state.bot
    dp = request.app.state.dp

    # try pydantic model validate first (aiogram v3)
    try:
        update = types.Update.model_validate(body)
    except Exception:
        try:
            update = types.Update(**body)
        except Exception as e:
            print("❌ Update parse error:", e)
            return {"ok": False, "error": "update parse error"}

    try:
        await dp.feed_update(bot, update)
    except Exception as e:
        print("❌ Handler error:", e)
        return {"ok": False, "error": "handler crashed", "detail": str(e)}

    return {"ok": True}
