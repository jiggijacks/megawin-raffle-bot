import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.webhooks import router as webhooks_router
from app.bot import bot, dp              # import bot & dp from your bot module

app = FastAPI()

# Include webhook routes
app.include_router(webhooks_router)

# CORS (optional)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# Webhook URL
TELEGRAM_WEBHOOK_URL = os.getenv(
    "WEBHOOK_URL",
    "https://disciplined-expression-telegram-bot.up.railway.app/webhook/telegram",
)

USE_WEBHOOK = True   # <— Set depending on your setup


@app.on_event("startup")
async def on_startup():
    app.state.bot = bot            # <<< REQUIRED
    app.state.dp = dp              # <<< Recommended

    if USE_WEBHOOK:
        await bot.set_webhook(WEBHOOK_URL)


@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()
