import os
from fastapi import FastAPI
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.database import init_db
from app.routers.webhooks import router as telegram_router
from app.routers.paystack_webhook import router as paystack_router

TOKEN = os.getenv("BOT_TOKEN", "")

app = FastAPI(title="Raffle Bot API")


@app.on_event("startup")
async def startup():
    print("🔄 Starting application...")

    # Initialize DB
    await init_db()

    # Initialize bot + dispatcher
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Store globally
    app.state.bot = bot
    app.state.dp = dp

    # Inject bot into bot.py so handlers can use send_message()
    try:
        import app.bot as bot_module
        bot_module.bot = bot
        print("✔ Bot injected into app.bot")
    except Exception as e:
        print("❌ Failed injecting bot:", e)

    # Register handlers
    from app.bot import register_handlers
    register_handlers(dp)

    print("🚀 Dispatcher & Handlers Loaded")


# Register webhook routers
app.include_router(telegram_router)
app.include_router(paystack_router)


@app.get("/")
async def root():
    return {"status": "OK", "message": "Bot is running"}
