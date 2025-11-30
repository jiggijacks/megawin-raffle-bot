import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.bot import bot, dp
from app.webhooks import router

app = FastAPI()
app.state.bot = bot     # <-- REQUIRED
app.state.dp = dp       # <-- REQUIRED

app.include_router(router)



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
    await bot.set_webhook(WEBHOOK_URL)


@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()
