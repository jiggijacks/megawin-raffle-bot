--- OLD: app/routers/webhooks.py
+++ NEW: app/routers/webhooks.py
@@
 @router.post("/webhook/telegram")
 async def telegram_webhook(request: Request):
-    bot: Bot = bot
-    dp = dp
+    print("🔥 WEBHOOK HIT")
+    bot: Bot = request.app.state.bot
+    dp = request.app.state.dp

     data = await request.json()
+    print("📩 Incoming update:", data)
     update = Update.model_validate(data)

     await dp.feed_update(bot, update)
     return {"ok": True}
