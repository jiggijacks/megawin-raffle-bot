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
    # create DB tables
    await init_db()

    # create global bot + dispatcher
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # store bot + dp so webhook handlers can access them
    app.state.bot = bot
    app.state.dp = dp

    # inject bot into app.bot module so handlers that call `bot.send_message` work
    try:
        import app.bot as bot_module
        bot_module.bot = bot
    except Exception:
        # not fatal: register_handlers will still attach handlers
        pass

    # register handlers (attach router to dispatcher)
    # we call register_handlers which safely includes the router (idempotent)
    try:
        from app.bot import register_handlers
        register_handlers(dp)
    except Exception as e:
        print("Failed to register handlers:", e)

    # start dispatcher lifecycle (optional; safe if aiogram needs startup)
    try:
        await dp.startup()
    except Exception as e:
        print("Dispatcher startup error:", e)


# include routers
app.include_router(telegram_router)
app.include_router(paystack_router)


@app.get("/")
async def root():
    return {"status": "OK", "bot": "running"}
