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
    print("🔄 Starting bot...")

    # Initialize database
    await init_db()

    # Create bot and dispatcher
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Store bot & dp in global state
    app.state.bot = bot
    app.state.dp = dp

    # Inject bot into app.bot
    import app.bot as bot_module
    bot_module.bot = bot

    # Register all handlers
    from app.bot import register_handlers
    register_handlers(dp)

    print("✔ Router loaded. No manual dp.startup() needed for webhooks.")


# Shutdown
@app.on_event("shutdown")
async def shutdown():
    bot = app.state.bot
    await bot.session.close()
    print("✔ Bot session closed.")


# Attach routers
app.include_router(telegram_router)
app.include_router(paystack_router)


@app.get("/")
async def root():
    return {"status": "running"}
