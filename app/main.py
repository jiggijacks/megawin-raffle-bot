# app/main.py
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher
from aiogram.types import Update

from app.config import BOT_TOKEN
from app.database import engine, Base
from app.bot import register_handlers
from app.paystack import verify_paystack_webhook

app = FastAPI()

# 🤖 Telegram
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
register_handlers(dp)


# -------------------------
# Paystack Webhook
# -------------------------
@app.post("/webhook/paystack")
async def paystack_webhook(request: Request):
    return await verify_paystack_webhook(request)


# -------------------------
# Telegram Webhook
# -------------------------
@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}


# -------------------------
# Startup
# -------------------------
@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Bot started and DB initialized")
