import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db
from app.bot import bot, dp
from app.routers.webhooks import router as telegram_router
from app.routers.paystack_webhook import router as paystack_router

app = FastAPI()

# ---------------------------
# CORS
# ---------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------
# Register Routers
# ---------------------------
print("🚀 Registering routers...")
app.include_router(telegram_router)
app.include_router(paystack_router)
print("✅ Routers registered.")


# ---------------------------
# Webhook Configuration
# ---------------------------
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
USE_WEBHOOK = os.getenv("USE_WEBHOOK", "true").lower() == "true"


# ---------------------------
# Startup Event
# ---------------------------
@app.on_event("startup")
async def startup_event():
    print("🚀 Running startup tasks...")

    # Initialize database tables
    print("→ Initializing DB...")
    await init_db()
    print("✅ DB initialized.")

    # Set Telegram webhook
    if USE_WEBHOOK and WEBHOOK_URL:
        print(f"→ Setting Telegram webhook to: {WEBHOOK_URL}")
        try:
            await bot.set_webhook(WEBHOOK_URL)
            print("✅ Telegram webhook set.")
        except Exception as e:
            print(f"❌ Failed to set webhook: {e}")


# ---------------------------
# Shutdown Event
# ---------------------------
@app.on_event("shutdown")
async def shutdown_event():
    print("🔻 Shutting down... removing webhook...")
    try:
        await bot.delete_webhook()
        print("Webhook removed.")
    except Exception as e:
        print(f"Failed to delete webhook: {e}")
