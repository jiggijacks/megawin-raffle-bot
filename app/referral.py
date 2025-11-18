def handle_referral(user, referral_code):
    """Handle referral logic."""
    if referral_code and referral_code != user.referral_code:
        referred_user = get_user_by_referral(referral_code)
        if referred_user:
            user.referred_by = referred_user.id
            user.referral_count += 1
            return True
    return False
