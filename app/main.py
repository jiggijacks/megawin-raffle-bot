# app/main.py
import asyncio
from fastapi import FastAPI, Request, Header
from app.paystack import verify_paystack_webhook
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from app.database import engine
from app.database import Base
from app.config import BOT_TOKEN
from app.bot import register_handlers

app = FastAPI()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# 🔑 THIS LINE FIXES EVERYTHING
register_handlers(dp)

@app.post("/webhook/paystack")
async def paystack_webhook(
        request: Request,
        x_paystack_signature: str = Header(None)
):
    body = await request.body()
    result = verify_paystack_webhook(body, x_paystack_signature)
    return {"status": result}

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}


@app.on_event("startup")
async def on_startup():
    await init_db()
    print("✅ Bot started and commands registered")

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Database initialized")