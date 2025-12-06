import os
from dotenv import load_dotenv

load_dotenv()

# ========== TELEGRAM ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "MegaWinRaffleBot")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@MegaWinRaffle")

# ========== PAYSTACK ==========
PAYSTACK_PUBLIC = os.getenv("PAYSTACK_PUBLIC")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")

# Base Paystack URL (production)
PAYSTACK_BASE_URL = os.getenv("PAYSTACK_BASE_URL", "https://api.paystack.co")

# Webhook
PAYSTACK_WEBHOOK_URL = os.getenv("PAYSTACK_WEBHOOK_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "AnyRandomString")

# ========== APP WEBHOOK URLs ==========
RAILWAY_PUBLIC_URL = os.getenv("RAILWAY_PUBLIC_URL")

TELEGRAM_WEBHOOK_PATH = "/webhook/telegram"
PAYSTACK_WEBHOOK_PATH = "/webhook/paystack"

WEBHOOK_URL = f"{RAILWAY_PUBLIC_URL}{TELEGRAM_WEBHOOK_PATH}"
PAYSTACK_URL = f"{RAILWAY_PUBLIC_URL}{PAYSTACK_WEBHOOK_PATH}"
