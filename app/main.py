--- OLD: main.py
+++ NEW: main.py
@@
 import os
 from fastapi import FastAPI
 from fastapi.middleware.cors import CORSMiddleware
-from database import init_db
-from app.routers.webhooks import router as webhooks_router
-from app.bot import bot, dp
+from app.database import init_db
+from app.routers.webhooks import router as webhooks_router
+from app.bot import bot, dp

 app = FastAPI()

-print("🚀 Loading webhooks router...")
-app.include_router(webhooks_router)
-print("✅ Router loaded!")
+print("🚀 Loading routers...")
+app.include_router(webhooks_router)
+print("✅ Routers ready")

 TELEGRAM_WEBHOOK_URL = os.getenv(
-    "WEBHOOK_URL",
-    "https://disciplined-expression-telegram-bot.up.railway.app/webhook/telegram",
+    "WEBHOOK_URL",
+    "https://YOUR-RAILWAY-URL.up.railway.app/webhook/telegram",
 )

@@
 @app.on_event("startup")
 async def on_startup():
-    await init_db()
+    print("🚀 Initializing database…")
+    await init_db()
+    print("✅ DB ready")

-    if USE_WEBHOOK:
-        await bot.set_webhook(TELEGRAM_WEBHOOK_URL)
+    print("🚀 Attaching bot + dp")
+    app.state.bot = bot
+    app.state.dp = dp
+
+    print(f"🚀 Setting webhook → {TELEGRAM_WEBHOOK_URL}")
+    await bot.set_webhook(TELEGRAM_WEBHOOK_URL)
+    print("✅ Webhook set")
