import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.webhooks import router as webhooks_router
from app.bot import bot, dp

app = FastAPI()

# Include routers
print("🚀 Loading webhooks router...")
app.include_router(webhooks_router)
print("✅ Router loaded!")


# CORS
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

USE_WEBHOOK = True  # set to True for Railway

# AUTO-RESET DB IF SCHEMA CHANGED
if os.path.exists("test.db"):
    print("🔥 Removing old DB (schema outdated)")
    os.remove("test.db")


@app.on_event("startup")
async def on_startup():
    app.state.bot = bot
    app.state.dp = dp

    if USE_WEBHOOK:
        await bot.set_webhook(TELEGRAM_WEBHOOK_URL)


@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()


