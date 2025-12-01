import os
from app.routers.webhooks import router as webhooks_router
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.bot import bot, dp              # ← now importing both bot and dp
from app.webhooks import router

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



# Webhook URL for Telegram
WEBHOOK_URL = os.getenv(
    "WEBHOOK_URL",
    "https://disciplined-expression-telegram-bot.up.railway.app/webhook/telegram",
)


@app.on_event("startup")
async def on_startup():
    app.state.bot = bot            # <<< REQUIRED
    app.state.dp = dp              # <<< Recommended

    if USE_WEBHOOK:
        await bot.set_webhook(TELEGRAM_WEBHOOK_URL)


@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()
