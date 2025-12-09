import os
from fastapi import FastAPI
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.database import init_db
from app.routers.webhooks import router as telegram_router
from app.routers.paystack_webhook import router as paystack_router

# Use config or env
TOKEN = os.getenv("BOT_TOKEN", "")

app = FastAPI(title="Raffle Bot API")

@app.on_event("startup")
async def startup():
    # create tables
    await init_db()

    # create bot and dispatcher
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # store in app.state so routers can access
    app.state.bot = bot
    app.state.dp = dp

    # also expose bot variable to the bot module (some handlers call bot.*)
    try:
        import app.bot as bot_module
        bot_module.bot = bot
    except Exception:
        # not fatal, some layouts may not import it
        pass

    # register handlers (router) in bot module
    from app.bot import register_handlers
    register_handlers(dp)


# include routers
app.include_router(telegram_router)
app.include_router(paystack_router)


@app.get("/")
async def root():
    return {"status": "OK", "bot": "running"}
