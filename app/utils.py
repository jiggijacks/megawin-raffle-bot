import random
import string


def generate_reference() -> str:
    """Generate Paystack transaction reference."""
    return "REF_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=12))


def generate_ticket_code() -> str:
    """Generate ticket code in #A1Z286 format (random)."""
    prefix = random.choice(string.ascii_uppercase)
    mid = "".join(random.choices(string.ascii_uppercase + string.digits, k=2))
    nums = "".join(random.choices(string.digits, k=3))
    return f"#{prefix}{mid}{nums}"
