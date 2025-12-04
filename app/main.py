import os
from fastapi import FastAPI
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.database import init_db
from app.routers.webhooks import router as telegram_router
from app.routers.paystack_webhook import router as paystack_router

TOKEN = os.getenv("BOT_TOKEN")

app = FastAPI(title="Raffle Bot API")

# ------------------------------------------------
# Startup: create DB, Bot, Dispatcher
# ------------------------------------------------
@app.on_event("startup")
async def startup():
    await init_db()

    bot = Bot(
        token=TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()

    # store bot + dp inside app.state, so webhook can access them
    app.state.bot = bot
    app.state.dp = dp

    # import handlers AFTER dp is created
    from app.bot import register_handlers
    register_handlers(dp)


# ------------------------------------------------
# Routers
# ------------------------------------------------
app.include_router(telegram_router)
app.include_router(paystack_router)


# ------------------------------------------------
# Health endpoint
# ------------------------------------------------
@app.get("/")
async def root():
    return {"status": "OK", "bot": "running"}
