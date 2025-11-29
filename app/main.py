from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher
from aiogram.types import Update

import os

from app.bot import bot, dp
from app.webhooks import router as paystack_router

WEBHOOK_URL = os.getenv("WEBHOOK_URL")

app = FastAPI()

# Attach Paystack webhook router
app.include_router(paystack_router)


@app.on_event("startup")
async def on_startup():
    # set telegram webhook
    await bot.set_webhook(WEBHOOK_URL)


@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()


@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    await dp.feed_update(bot, data)
    return {"status": "ok"}
