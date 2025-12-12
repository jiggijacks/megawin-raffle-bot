# app/main.py
import os
from fastapi import FastAPI
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.database import init_db
from app.routers.webhooks import router as telegram_router
from app.routers.paystack_webhook import router as paystack_router

TOKEN = os.getenv("BOT_TOKEN", "")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN env var is required")

app = FastAPI(title="Raffle Bot API")

@app.on_event("startup")
async def startup():
    # initialize DB tables
    await init_db()

    # create bot + dispatcher and expose via app.state
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    app.state.bot = bot
    app.state.dp = dp

    # inject bot into bot module so handlers can use 'bot' variable
    # (this avoids importing app.main from other modules)
    import importlib
    bot_module = importlib.import_module("app.bot")
    setattr(bot_module, "bot", bot)

    # register handlers (safe idempotent)
    from app.bot import register_handlers
    register_handlers(dp)

    # NOTE: for webhook mode we do NOT call dp.startup() (not required).
    # Aiogram handlers will be invoked by calling dp.feed_update(...) from the webhook.

# attach routers
app.include_router(telegram_router)
app.include_router(paystack_router)

@app.get("/")
async def root():
    return {"status": "OK", "bot": "running"}
