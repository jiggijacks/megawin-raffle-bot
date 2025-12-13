import os


# ============================================================
#                       BOT CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "MegaWinRaffleBot")

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN environment variable is missing")


# ============================================================
#                       ADMINS
# ============================================================

ADMIN_ID_RAW = os.getenv("ADMIN_ID", "")
ADMIN_IDS = [
    int(x.strip())
    for x in ADMIN_ID_RAW.split(",")
    if x.strip().isdigit()
]


# ============================================================
#                       PAYSTACK
# ============================================================

PAYSTACK_SECRET = os
