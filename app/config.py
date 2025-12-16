import os

# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Database
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./raffle.db"
)

# Paystack
PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET")
PAYSTACK_PUBLIC = os.getenv("PAYSTACK_PUBLIC")

# Admin
ADMIN_IDS = []
for x in os.getenv("ADMIN_IDS", "").split(","):
    x = x.strip()
    if not x:
        continue
    try:
        ADMIN_IDS.append(int(x))
    except ValueError:
        continue
