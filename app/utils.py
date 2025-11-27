import secrets
import string
# utils.py

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MegaWinBot")

def log(message: str):
    logger.info(message)


def generate_reference():
    return "MW" + ''.join(
        secrets.choice(string.ascii_uppercase + string.digits)
        for _ in range(12)
    )
