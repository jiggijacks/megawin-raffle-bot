--- OLD: app/utils.py
+++ NEW: app/utils.py
@@
-import random
-import string
+import random
+import string

-def generate_ticket_code():
-    letters = string.ascii_uppercase
-    digits = string.digits
-    return "T-" + "".join(random.choices(letters + digits, k=10))
+TICKET_PRICE = 500
+
+def generate_ticket_code():
+    letters = string.ascii_uppercase
+    digits = string.digits
+    return "#" + random.choice(letters) + random.choice(digits) + random.choice(letters) + ''.join(random.choices(digits, k=3))

+def referral_link(bot_username: str, user_telegram_id: int):
+    return f"https://t.me/{bot_username}?start=ref_{user_telegram_id}"
