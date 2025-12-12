import os
import asyncio
from fastapi import FastAPI
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.database import init_db

bot = None
dp = None

app = FastAPI(title="Raffle Bot API")


# ----------------------------------------------------------
#   START AIROGRAM BOT BEFORE FASTAPI STARTUP
# ----------------------------------------------------------
async def start_bot():
    global bot, dp

    print("🔄 Starting bot...")

    from app.bot import register_handlers

    TOKEN = os.getenv("BOT_TOKEN", "")
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Register handlers
    register_handlers(dp)

    print("✔ Handlers registered. Bot ready for webhook.")
    return bot, dp


# ----------------------------------------------------------
#   FASTAPI STARTUP
# ----------------------------------------------------------
@app.on_event("startup")
async def startup():
    global bot, dp

    print("🚀 Initializing database...")
    await init_db()

    # Start Aiogram manually before FastAPI accepts webhooks
    if bot is None or dp is None:
        bot, dp = await start_bot()

    # Attach to app.state for webhook
    app.state.bot = bot
    app.state.dp = dp

    print("✔ FastAPI & Aiogram fully initialized.")


# ----------------------------------------------------------
#   WEBHOOK ROUTES
# ----------------------------------------------------------
from app.routers.webhooks import router as telegram_router
from app.routers.paystack_webhook import router as paystack_router

app.include_router(telegram_router)
app.include_router(paystack_router)


@app.get("/")
async def root():
    return {"status": "OK", "bot": "running"}
