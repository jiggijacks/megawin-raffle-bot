import os
from fastapi import FastAPI
from aiogram import Bot
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiogram.webhook import Setting as WebhookSetting
from aiohttp import web

from app.bot import build_bot
from app.webhooks import router as paystack_router
from app.database import init_db

WEBHOOK_DOMAIN = os.getenv(
    "WEBHOOK_DOMAIN",
    "https://disciplined-expression-telegram-bot.up.railway.app"
)

WEBHOOK_PATH = "/webhook/telegram"
WEBHOOK_URL = WEBHOOK_DOMAIN + WEBHOOK_PATH

app = FastAPI()

# include paystack webhook
app.include_router(paystack_router)


@app.on_event("startup")
async def startup():
    await init_db()

    bot, dp = build_bot()

    await bot.set_webhook(WEBHOOK_URL)

    # aiohttp webhook app
    aio_app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(
        aio_app, path=WEBHOOK_PATH
    )

    runner = web.AppRunner(aio_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8081)
    await site.start()

    print("🚀 Bot webhook started:", WEBHOOK_URL)
