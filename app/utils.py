# app/utils.py
import random
import string

TICKET_PRICE = 500  # ₦500 per ticket

def generate_ticket_code():
    # format: #A1Z286  -> Letter Digit Letter Digit Digit Digit
    letters = string.ascii_uppercase
    digits = string.digits
    return "#" + random.choice(letters) + random.choice(digits) + random.choice(letters) + ''.join(random.choices(digits, k=3))

def referral_link(bot_username: str, user_telegram_id: int):
    return f"https://t.me/{bot_username}?start=ref_{user_telegram_id}"
