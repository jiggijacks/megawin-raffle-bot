# app/routers/webhooks.py
from fastapi import APIRouter, Request, Header
from aiogram import types
from aiogram.types import Update
import asyncio
import os
import traceback

router = APIRouter()

# Optional: set this env var to the same token you passed when calling setWebhook
WEBHOOK_SECRET_TOKEN = os.getenv("WEBHOOK_SECRET_TOKEN")  # e.g. "my-super-secret"

@router.post("/webhook/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_secret: str | None = Header(None, alias="X-Telegram-Bot-Api-Secret-Token"),
):
    """
    Telegram webhook receiver.
    - Quick ack to Telegram (returns immediately).
    - Schedules dp.feed_update(bot, update) in background so handlers run async.
    """

    # 1) Optional: verify secret token if you configured one
    if WEBHOOK_SECRET_TOKEN:
        if not x_telegram_secret or x_telegram_secret != WEBHOOK_SECRET_TOKEN:
            print("Webhook: invalid secret token")
            return {"ok": False, "error": "invalid webhook secret"}

    # 2) parse body
    try:
        body = await request.json()
    except Exception as e:
        print("Webhook: invalid json body:", e)
        return {"ok": False, "error": "invalid json"}

    # 3) get bot and dispatcher from app state
    bot = getattr(request.app.state, "bot", None)
    dp = getattr(request.app.state, "dp", None)
    if bot is None or dp is None:
        print("Webhook: app.state.bot or app.state.dp is not set")
        return {"ok": False, "error": "server not ready"}

    # 4) validate/parse Update (use pydantic model_validate for safety)
    try:
        # model_validate is preferred for pydantic v2 (aiogram uses it)
        update = Update.model_validate(body)
    except Exception as e:
        # fallback: try direct construction (older aiogram versions), but log failure
        try:
            update = types.Update(**body)
        except Exception as ee:
            print("Webhook: Update parse error:", e)
            traceback.print_exc()
            return {"ok": False, "error": "update parse error"}

    # 5) schedule processing in background and return immediately
    try:
        asyncio.create_task(dp.feed_update(bot, update))
    except Exception as e:
        print("Webhook: failed to schedule dp.feed_update:", e)
        traceback.print_exc()
        return {"ok": False, "error": "scheduling failed"}

    return {"ok": True}
