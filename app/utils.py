import random
import string

# ============================================================
# GLOBAL SETTINGS
# ============================================================

# Cost per ticket in naira
TICKET_PRICE = 500

# ============================================================
# REFERENCE & TICKET GENERATORS
# ============================================================

def generate_reference() -> str:
    """Generate Paystack transaction reference."""
    return "REF_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=12))


def generate_ticket_code() -> str:
    """Generate ticket code in #A1Z286 format."""
    prefix = random.choice(string.ascii_uppercase)
    mid = "".join(random.choices(string.ascii_uppercase + string.digits, k=2))
    nums = "".join(random.choices(string.digits, k=3))
    return f"#{prefix}{mid}{nums}"


# ============================================================
# REFERRAL SYSTEM
# ============================================================

def referral_link(user_id: int) -> str:
    """
    Creates a referral link like:
    https://t.me/MegaWinRaffleBot?start=ref_12345
    """
    return f"https://t.me/MegaWinRaffleBot?start=ref_{user_id}"
