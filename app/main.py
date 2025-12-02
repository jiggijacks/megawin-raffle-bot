import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.routers.webhooks import router as webhooks_router
from app.bot import bot, dp


app = FastAPI()

# -------------------------------
# Correct DB cleanup (SQLite)
# -------------------------------
if os.path.exists("raffle.db"):
    print("🔥 Removing old raffle.db (schema outdated)")
    os.remove("raffle.db")

# -------------------------------
# Webhook URL
# -------------------------------
TELEGRAM_WEBHOOK_URL = os.getenv(
    "WEBHOOK_URL",
    "https://disciplined-expression-telegram-bot.up.railway.app/webhook/telegram",
)

# -------------------------------
# CORS
# -------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------
# Register routers
# -------------------------------
print("🚀 Loading webhooks router...")
app.include_router(webhooks_router)
print("✅ Router loaded!")


# -------------------------------
# Startup
# -------------------------------
@app.on_event("startup")
async def on_startup():
    print("🚀 Initializing database...")
    await init_db()
    print("✅ Database initialized.")

    print("🚀 Attaching bot + dispatcher...")
    app.state.bot = bot
    app.state.dp = dp
    print("✅ Attached.")

    print("🚀 Setting webhook...")
    await bot.set_webhook(TELEGRAM_WEBHOOK_URL)
    print("✅ Webhook set:", TELEGRAM_WEBHOOK_URL)


# -------------------------------
# Shutdown
# -------------------------------
@app.on_event("shutdown")
async def on_shutdown():
    print("🛑 Removing webhook...")
    await bot.delete_webhook()
    print("✅ Webhook removed.")
