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

    # Initialize bot & dispatcher
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # Make bot & dispatcher globally available for webhook
    app.state.bot = bot
    app.state.dp = dp

    # Inject bot inside app.bot
    import app.bot as bot_module
    bot_module.bot = bot

    # Register handlers without re-importing to avoid circular import
    bot_module.register_handlers(dp)

    # This MUST run or /commands will never fire
    await dp.startup()
    print("✔ Dispatcher started.")


@app.on_event("shutdown")
async def shutdown():
    dp = getattr(app.state, "dp", None)
    if dp:
        await dp.shutdown()

    bot = getattr(app.state, "bot", None)
    if bot:
        # ensure the bot's aiohttp session is closed
        try:
            await bot.close()
        except Exception:
            pass

    print("✔ Dispatcher shutdown.")


# Mount webhooks
app.include_router(telegram_router)
app.include_router(paystack_router)


@app.get("/")
async def root():
    return {"status": "running"}
