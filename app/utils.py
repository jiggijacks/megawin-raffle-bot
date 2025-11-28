import random
import string
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def generate_reference() -> str:
    """
    Generates a Paystack-safe unique reference
    """
    return "MWR" + datetime.now().strftime("%Y%m%d%H%M%S") + ''.join(
        random.choices(string.ascii_uppercase + string.digits, k=6)
    )


def generate_ticket_code() -> str:
    """
    Generates a unique ticket code for raffle entries
    """
    return "T-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))


def log(message: str):
    """
    Simple log wrapper
    """
    logger.info(message)
