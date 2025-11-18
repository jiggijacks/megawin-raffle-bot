import random
import string

def generate_ticket_code():
    """Generate a random ticket code."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
