import os
from fastapi import FastAPI
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode

from app.database import init_db
from app.routers.webhooks import router as telegram_router
from app.routers.paystack_webhook import router as paystack_router
from app.bot import register_handlers

BOT_TOKEN = os.getenv("BOT_TOKEN")

app = FastAPI(title="Raffle Bot API")


@app.on_event("startup")
async def startup():
    await init_db()

    bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher()

    register_handlers(dp)

    app.state.bot = bot
    app.state.dp = dp

    print("✅ Bot & Dispatcher ready")


app.include_router(telegram_router)
app.include_router(paystack_router)


@app.get("/")
async def root():
    return {"status": "OK"}
