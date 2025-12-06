import os
from fastapi import FastAPI
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import BOT_TOKEN
from app.database import init_db
from app.routers.webhooks import router as telegram_router
from app.routers.paystack_webhook import router as paystack_router

app = FastAPI(title="Raffle Bot API")

TOKEN = BOT_TOKEN


@app.on_event("startup")
async def startup():
    # Initialize DB
    await init_db()

    # Create bot + dispatcher
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Save instances in app state
    app.state.bot = bot
    app.state.dp = dp

    # Allow bot.py to access `bot`
    import app.bot as bot_module
    bot_module.bot = bot

    # Register bot handlers
    from app.bot import register_handlers
    register_handlers(dp)

    print("🚀 Bot loaded and routers attached.")


# Routers for Webhooks
app.include_router(telegram_router)
app.include_router(paystack_router)


@app.get("/")
async def root():
    return {"status": "OK", "bot": "running"}
