# app/main.py

import asyncio
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher
from aiogram.types import Update

from app.config import BOT_TOKEN
from app.database import engine, Base
from app.bot import register_handlers
from app.paystack import verify_paystack_webhook
from app.paystack import paystack_webhook_handler


app = FastAPI()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# load telegram command handlers
register_handlers(dp)


@app.post("/webhook/paystack")
async def paystack_webhook(request: Request):
    return await paystack_webhook_handler(request)


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}


@app.on_event("startup")
async def on_startup():
    await init_db()
    print("✅ Bot started")


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Database ready")
