# main.py (in project root or app/main.py depending on your layout)
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.routers.webhooks import router as webhooks_router
from app.bot import bot, dp

app = FastAPI()

# optional: remove old raffle.db only if you need fresh schema
if os.getenv("RESET_DB_AT_STARTUP", "false").lower() in ("1","true","yes"):
    if os.path.exists("raffle.db"):
        print("🔥 Removing old raffle.db (schema outdated)")
        os.remove("raffle.db")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

print("🚀 Loading webhooks router...")
app.include_router(webhooks_router)
print("✅ Router loaded!")

TELEGRAM_WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://your-railway-domain.up.railway.app/webhook/telegram")

@app.on_event("startup")
async def on_startup():
    print("🚀 Initializing database...")
    await init_db()
    print("✅ Database initialized.")

    print("🚀 Attaching bot + dispatcher...")
    app.state.bot = bot
    app.state.dp = dp
    print("✅ Attached.")

    if os.getenv("USE_WEBHOOK", "true").lower() in ("1","true","yes"):
        print("🚀 Setting webhook:", TELEGRAM_WEBHOOK_URL)
        await bot.set_webhook(TELEGRAM_WEBHOOK_URL)
        print("✅ Webhook set.")
