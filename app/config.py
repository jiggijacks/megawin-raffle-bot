import os
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "MegaWinRaffleBot")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@MegaWinRaffle")
ADMIN_ID = os.getenv("ADMIN_ID", "")  # comma separated allowed
DATABASE_URL = os.getenv("DATABASE_URL", "")
RAILWAY_DOMAIN = os.getenv("RAILWAY_PUBLIC_URL", "")  # your railway public URL
USE_WEBHOOK = os.getenv("USE_WEBHOOK", "true").lower() in ("1", "true", "yes")

# Paystack settings (match your Railway env keys)
PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET_KEY", "")
PAYSTACK_PUBLIC = os.getenv("PAYSTACK_PUBLIC", "")
PAYSTACK_BASE_URL = os.getenv("PAYSTACK_BASE_URL", "https://api.paystack.co")
PAYSTACK_WEBHOOK_URL = os.getenv("PAYSTACK_WEBHOOK_URL", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")  # arbitrary string for validating webhooks if you want
