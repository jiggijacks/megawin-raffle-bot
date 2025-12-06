# app/utils.py
import random
import string
from typing import Optional

# Cost per ticket (₦)
TICKET_PRICE = 500

# ---------- reference generator ----------
def generate_reference() -> str:
    """Short Paystack-like reference for transactions."""
    return "REF_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=12))

# ---------- ticket code ----------
def generate_ticket_code() -> str:
    """Generate ticket code in '#A1Z286' style."""
    prefix = random.choice(string.ascii_uppercase)
    mid = "".join(random.choices(string.ascii_uppercase + string.digits, k=2))
    nums = "".join(random.choices(string.digits, k=3))
    return f"#{prefix}{mid}{nums}"

# ---------- referral link ----------
def referral_link(bot_username_or_name: Optional[str], user_id: int) -> str:
    """
    Create referral link.
    Accepts either full bot username ('MegaWinRaffleBot' or '@MegaWinRaffleBot')
    or None (fallback to 'MegaWinRaffleBot').
    """
    bot_name = bot_username_or_name or "MegaWinRaffleBot"
    # strip leading @ if present; telegram t.me links don't use the @
    bot_name = bot_name.lstrip("@")
    return f"https://t.me/{bot_name}?start=ref_{user_id}"

async def handle_telegram_update(data: dict):
    try:
        update = Update.model_validate(data)
        await dp.feed_update(bot, update)
    except Exception:
        traceback.print_exc()
