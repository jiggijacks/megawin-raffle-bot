from fastapi import APIRouter, Request
from aiogram import types

router = APIRouter()

@router.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    bot = request.app.state.bot
    dp = request.app.state.dp

    try:
        body = await request.json()
        update = types.Update.de_json(body)
    except Exception as e:
        print("❌ Webhook parse error:", e)
        return {"ok": False}

    try:
        await dp.process_update(update)
    except Exception as e:
        print("❌ Update Handling Error:", e)

    return {"ok": True}
