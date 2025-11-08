import os
import logging
import random
import aiohttp
import uvicorn
from fastapi import FastAPI, Request, Response
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.enums import ParseMode
from sqlalchemy import select, func

from app.database import async_session, init_db, User, RaffleEntry

# ---------------------------------------------------------
# ENVIRONMENT + CONFIG
# ---------------------------------------------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", "8000"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://megawinraffle.up.railway.app/webhook/telegram")

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN not set in environment!")

# ---------------------------------------------------------
# LOGGING
# ---------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)
logger.info("✅ BOT_TOKEN loaded successfully")

# ---------------------------------------------------------
# SETUP BOT + FASTAPI
# ---------------------------------------------------------
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()
app = FastAPI()

# ---------------------------------------------------------
# DB UTILITIES
# ---------------------------------------------------------
async def get_or_create_user(telegram_id: int, username: str | None = None):
    async with async_session() as session:
        async with session.begin():
            q = await session.execute(select(User).filter_by(telegram_id=telegram_id))
            user = q.scalar_one_or_none()
            if user:
                if username and user.username != username:
                    user.username = username
                    session.add(user)
                return user
            new = User(telegram_id=telegram_id, username=username)
            session.add(new)
            await session.flush()
            return new

# ---------------------------------------------------------
# TELEGRAM COMMANDS
# ---------------------------------------------------------
@dp.message(Command("start"))
async def cmd_start(message: Message, command: Command):
    telegram_id = message.from_user.id
    username = message.from_user.username
    user = await get_or_create_user(telegram_id, username)

    args = (command.args or "").strip()
    if args:
        try:
            ref_id = int(args)
            if ref_id != telegram_id:
                async with async_session() as session:
                    async with session.begin():
                        q = await session.execute(select(User).filter_by(telegram_id=ref_id))
                        ref_user = q.scalar_one_or_none()
                        if ref_user:
                            ref_user.referral_count = (ref_user.referral_count or 0) + 1
                            session.add(ref_user)
                            if ref_user.referral_count >= 5:
                                ticket = RaffleEntry(user_id=ref_user.id, free_ticket=True)
                                session.add(ticket)
                                ref_user.referral_count -= 5
                                await bot.send_message(ref_user.telegram_id, "🎉 You referred 5 users and earned a free ticket!")
        except ValueError:
            pass

    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={telegram_id}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[  # buttons for users
        [InlineKeyboardButton(text="🎟 Buy Ticket", callback_data="buy_ticket")],
        [InlineKeyboardButton(text="🎫 My Tickets", callback_data="view_tickets")],
        [InlineKeyboardButton(text="👥 Referrals", callback_data="my_referrals")],
        [InlineKeyboardButton(text="❓ Help", callback_data="help_cmd")]
    ])

    await message.answer(
        f"🎉 <b>Welcome to MegaWin Raffle!</b>\n\n"
        f"Invite friends with your link:\n{link}\n\n"
        f"Use the buttons below to get started 👇",
        reply_markup=keyboard
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "💡 How to play:\n"
        "• /buy — Buy a raffle ticket (₦500)\n"
        "• /ticket — View your tickets\n"
        "• /referrals — See your referral count\n\n"
        "Admin only:\n"
        "• /winners — pick a random winner\n"
        "• /buyers — view active users\n"
        "• /stats — view platform stats"
    )


@dp.message(Command("buy"))
async def cmd_buy(message: Message):
    telegram_id = message.from_user.id
    username = message.from_user.username
    user = await get_or_create_user(telegram_id, username)

    if not PAYSTACK_SECRET_KEY:
        await message.answer("❌ Paystack key not set.")
        return

    async with aiohttp.ClientSession() as session:
        payload = {
            "email": f"user_{telegram_id}@megawinraffle.com",
            "amount": 500 * 100,
            "metadata": {"telegram_id": telegram_id},
            "callback_url": WEBHOOK_URL
        }
        headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
        async with session.post("https://api.paystack.co/transaction/initialize", json=payload, headers=headers) as resp:
            res = await resp.json()

    if res.get("status"):
        ref = res["data"]["reference"]
        pay_url = res["data"]["authorization_url"]
        # Save the payment reference here to check after successful payment
        await message.answer(f"💳 Click below to pay ₦500:\n{pay_url}")
    else:
        await message.answer("❌ Could not start Paystack payment.")


@dp.message(Command("ticket"))
async def cmd_ticket(message: Message):
    telegram_id = message.from_user.id
    async with async_session() as s:
        async with s.begin():
            q = await s.execute(select(User).filter_by(telegram_id=telegram_id))
            user = q.scalar_one_or_none()
            if not user:
                await message.answer("🚫 You don't have any tickets yet.")
                return
            q2 = await s.execute(select(RaffleEntry).filter_by(user_id=user.id))
            tickets = q2.scalars().all()
            if not tickets:
                await message.answer("🚫 You have no tickets yet. Use /buy.")
                return
            msg = "\n".join(
                f"🎫 #{t.id} | {'Free' if t.free_ticket else 'Paid'} | {t.created_at.strftime('%Y-%m-%d %H:%M')}"
                for t in tickets
            )
            await message.answer(msg)


@dp.message(Command("referrals"))
async def cmd_referrals(message: Message):
    telegram_id = message.from_user.id
    async with async_session() as s:
        async with s.begin():
            q = await s.execute(select(User).filter_by(telegram_id=telegram_id))
            user = q.scalar_one_or_none()
            count = user.referral_count if user else 0
            link = f"https://t.me/{(await bot.get_me()).username}?start={telegram_id}"
            await message.answer(f"👥 You have referred {count} user(s).\n\nYour referral link:\n{link}")


@dp.message(Command("winners"))
async def cmd_winners(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Only admin can run this command.")
        return
    async with async_session() as s:
        async with s.begin():
            q = await s.execute(select(RaffleEntry))
            entries = q.scalars().all()
            if not entries:
                await message.answer("No tickets yet.")
                return
            winner = random.choice(entries)
            q2 = await s.execute(select(User).filter_by(id=winner.user_id))
            user = q2.scalar_one_or_none()
            await message.answer(f"🏆 Winner: @{user.username or user.telegram_id}\nTicket #{winner.id}")
            
            # Reset all tickets after selecting a winner
            await s.execute('DELETE FROM raffle_entries')
            await s.commit()  # Commit the changes to reset all tickets


@dp.message(Command("buyers"))
async def cmd_buyers(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Only admin can view the active users.")
        return
    
    async with async_session() as s:
        async with s.begin():
            q = await s.execute(select(RaffleEntry).filter(RaffleEntry.payment_ref != None))  # Filter only purchased tickets
            users = q.scalars().all()
            if not users:
                await message.answer("No users have purchased tickets yet.")
                return
            msg = "\n".join(
                f"User ID: {user.user_id}, Ticket ID: {user.id}, Purchased at: {user.created_at}"
                for user in users
            )
            await message.answer(f"👥 Active Users:\n{msg}")


# ---------------------------------------------------------
# CALLBACK HANDLERS
# ---------------------------------------------------------
@dp.callback_query(F.data == "buy_ticket")
async def cb_buy(callback: CallbackQuery):
    await cmd_buy(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "view_tickets")
async def cb_tickets(callback: CallbackQuery):
    await cmd_ticket(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "my_referrals")
async def cb_ref(callback: CallbackQuery):
    await cmd_referrals(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "help_cmd")
async def cb_help(callback: CallbackQuery):
    await cmd_help(callback.message)
    await callback.answer()


# ---------------------------------------------------------
# FASTAPI: PAYSTACK WEBHOOK
# ---------------------------------------------------------
@app.post("/webhook/paystack")
async def paystack_webhook(request: Request):
    data = await request.json()
    event = data.get("event")
    logger.info(f"📩 Paystack event: {event}")
    if event != "charge.success":
        return {"status": "ignored"}

    telegram_id = data["data"]["metadata"].get("telegram_id")
    ref = data["data"].get("reference")

    async with async_session() as s:
        async with s.begin():
            q = await s.execute(select(User).filter_by(telegram_id=telegram_id))
            user = q.scalar_one_or_none()
            if not user:
                user = User(telegram_id=telegram_id)
                s.add(user)
                await s.flush()

            q2 = await s.execute(select(RaffleEntry).filter_by(payment_ref=ref))
            entry = q2.scalar_one_or_none()
            if not entry:
                s.add(RaffleEntry(user_id=user.id, payment_ref=ref, free_ticket=False))
                await bot.send_message(
                    telegram_id,
                    "✅ <b>Payment confirmed!</b>\nYour raffle ticket has been added.\nUse /ticket to view your tickets.",
                    parse_mode="HTML"
                )
    return {"status": "ok"}


# ---------------------------------------------------------
# FASTAPI: TELEGRAM WEBHOOK
# ---------------------------------------------------------
@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = Update.model_validate(data)  # ✅ convert raw dict → Update object
        await dp.feed_update(bot, update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"❌ Telegram webhook error: {e}")
        return {"status": "error", "message": str(e)}


# -----------------------
# Start bot via webhook (Railway mode)
# -----------------------
async def main():
    await init_db()
    logging.info("✅ Database initialized")

    # Remove any old webhook (just to be safe)
    await bot.delete_webhook(drop_pending_updates=True)

    # Set webhook to your Railway domain
    webhook_url = os.getenv("WEBHOOK_URL", "https://megawinraffle.up.railway.app/webhook/telegram")
    await bot.set_webhook(
        url=webhook_url,
        allowed_updates=["message", "callback_query"]
    )
    logging.info(f"✅ Webhook set successfully at {webhook_url}")

    # Start FastAPI server
    config = uvicorn.Config(app=app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    import asyncio
    import uvicorn

    async def on_startup():
        await init_db()
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_webhook(
            url=WEBHOOK_URL,
            allowed_updates=["message", "callback_query"],
        )
        logger.info("✅ Webhook set successfully at /webhook/telegram")

    asyncio.run(on_startup())

    logger.info("🌐 Starting FastAPI app...")
    uvicorn.run("app.bot:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
