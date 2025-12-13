import random
import string
import uuid

# 🎟 Ticket price (₦)
TICKET_PRICE = 500


# ============================================================
#                    TICKET CODE
# ============================================================
def generate_ticket_code() -> str:
    """
    Generates a unique raffle ticket code
    Example: MW-8F3A2C
    """
    return "MW-" + "".join(
        random.choices(string.ascii_uppercase + string.digits, k=6)
    )


# ============================================================
#                 PAYSTACK REFERENCE
# ============================================================
def generate_reference() -> str:
    """
    Unique payment reference for Paystack
    """
    return f"MW-{uuid.uuid4().hex[:12].upper()}"


# ============================================================
#                 REFERRAL LINK
# ============================================================
def referral_link(bot_username: str, user_id: int) -> str:
    return f"https://t.me/{bot_username}?start=ref_{user_id}"
