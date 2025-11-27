import os

# Load environment variables from .env
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
RAILWAY_DOMAIN = os.getenv("RAILWAY_DOMAIN")
TELEGRAM_WEBHOOK_PATH = "/webhook/telegram"
PAYSTACK_WEBHOOK_PATH = "/webhook/paystack"

WEBHOOK_URL = f"{RAILWAY_DOMAIN}{TELEGRAM_WEBHOOK_PATH}"
PAYSTACK_URL = f"{RAILWAY_DOMAIN}{PAYSTACK_WEBHOOK_PATH}"
