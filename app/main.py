from fastapi import FastAPI
from aiogram import Bot, Dispatcher
from app.bot import bot, dp
from app.webhooks import router
from config import WEBHOOK_URL

app = FastAPI()

@app.on_event("startup")
async def on_startup():
    # Attach bot and dp to app state
    app.state.bot = bot
    app.state.dp = dp

    # Set webhook
    await bot.set_webhook(WEBHOOK_URL)

@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()
    await bot.session.close()

# Register webhook router
app.include_router(router)


@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    await dp.feed_update(bot, data)
    return {"status": "ok"}
