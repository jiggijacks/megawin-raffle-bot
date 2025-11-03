# app/bot.py
import os
import asyncio
import logging
import random
import aiohttp
from datetime import datetime
from fastapi import FastAPI, Request, Response
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, BotCommand
from aiogram.enums import ParseMode
from sqlalchemy import select, func, distinct, delete

from app.database import async_session, init_db, User, RaffleEntry  # User & RaffleEntry models assumed

# ---- Your DB layer (adjust imports if your paths differ)
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", "8080"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "https://megawinraffle.up.railway.app")  # no trailing slash

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN not set")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger(__name__)
logger.info("✅ Environment loaded")

# Set up bot and app
app = FastAPI()
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------
async def get_or_create_user(telegram_id: int, username: str | None = None) -> User:
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

def main_menu(me_username: str | None, telegram_id: int) -> InlineKeyboardMarkup:
    link = f"https://t.me/{me_username}?start={telegram_id}" if me_username else "Open bot and copy your link."
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎟 Buy Ticket", callback_data="buy_ticket")],
        [InlineKeyboardButton(text="🎫 My Tickets", callback_data="view_tickets")],
        [InlineKeyboardButton(text="👥 Referrals", callback_data="my_referrals")],
        [InlineKeyboardButton(text="❓ Help", callback_data="help_cmd")],
        [InlineKeyboardButton(text="🔗 Copy Referral Link", url=link if me_username else None)]
    ])

# ---------------------------------------------------------
# COMMANDS
# ---------------------------------------------------------
# Update your bot.py where the decorators are used
@dp.message(Command("start"))
async def cmd_start(message: Message):
    telegram_id = message.from_user.id
    username = message.from_user.username
    user = await get_or_create_user(telegram_id, username)

    args = (message.get_args() or "").strip()
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

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
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
        "💡 <b>How to play</b>\n"
        "• /buy — Buy a raffle ticket (₦500)\n"
        "• /ticket — View your tickets\n"
        "• /referrals — See your referral count\n\n"
        "<b>Admin</b>\n"
        "• /winners — pick winner and reset tickets\n"
        "• /stats — totals\n"
        "• /buyers — list users who currently have paid tickets"
    )

@dp.message(Command("buy"))
async def cmd_buy(message: Message):
    """Initialize Paystack payment WITHOUT adding a ticket yet."""
    telegram_id = message.from_user.id
    username = message.from_user.username
    user = await get_or_create_user(telegram_id, username)

    if not PAYSTACK_SECRET_KEY:
        await message.answer("❌ Paystack key not set.")
        return

    async with aiohttp.ClientSession() as session_http:
        payload = {
            "email": f"user_{telegram_id}@megawinraffle.com",
            "amount": 500 * 100,  # kobo
            "metadata": {"telegram_id": telegram_id},
            "callback_url": f"{PUBLIC_URL}/webhook/paystack"
        }
        headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
        async with session_http.post("https://api.paystack.co/transaction/initialize", json=payload, headers=headers) as resp:
            res = await resp.json()

    if res.get("status"):
        pay_url = res["data"]["authorization_url"]
        await message.answer(
            "💳 Click to complete your payment:\n"
            f"{pay_url}\n\n"
            "✅ Your ticket will be added automatically once payment is confirmed."
        )
    else:
        await message.answer("❌ Could not start Paystack payment. Try again.")

@dp.message(Command("ticket"))
async def cmd_ticket(message: Message):
    """Show ticket number and the time it was created."""
    telegram_id = message.from_user.id
    async with async_session() as s:
        async with s.begin():
            q = await s.execute(select(User).filter_by(telegram_id=telegram_id))
            user = q.scalar_one_or_none()
            if not user:
                await message.answer("🚫 You have no tickets yet.")
                return
            q2 = await s.execute(select(RaffleEntry).filter_by(user_id=user.id))
            tickets = q2.scalars().all()
            if not tickets:
                await message.answer("🚫 You have no tickets yet. Use /buy.")
                return
            lines = []
            for t in tickets:
                kind = "Free" if t.free_ticket else "Paid"
                dt = t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else "-"
                lines.append(f"🎫 Ticket #{t.id} • {kind} • {dt}")
            await message.answer("\n".join(lines))

@dp.message(Command("referrals"))
async def cmd_referrals(message: Message):
    telegram_id = message.from_user.id
    async with async_session() as s:
        async with s.begin():
            q = await s.execute(select(User).filter_by(telegram_id=telegram_id))
            user = q.scalar_one_or_none()
            count = user.referral_count if user else 0
    await message.answer(f"👥 You have referred <b>{count}</b> user(s).")

@dp.message(Command("winners"))
async def cmd_winners(message: Message):
    """Pick a random winner, announce, then RESET tickets (clear table)."""
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Only admin can run this command.")
        return

    async with async_session() as s:
        async with s.begin():
            q = await s.execute(select(RaffleEntry))
            entries = q.scalars().all()
            if not entries:
                await message.answer("📭 No tickets to draw.")
                return
            winner_entry = random.choice(entries)
            q2 = await s.execute(select(User).filter_by(id=winner_entry.user_id))
            winner_user = q2.scalar_one_or_none()

            # Announce
            handle = f"@{winner_user.username}" if winner_user and winner_user.username else str(winner_user.telegram_id if winner_user else "-")
            await message.answer(f"🏆 <b>Winner:</b> {handle}\n🎫 Ticket #{winner_entry.id}")

            # RESET: clear all tickets so nobody can reuse a ticket
            await s.execute(delete(RaffleEntry))  # <-- This resets all tickets

    await message.answer("♻️ All tickets have been reset for the next draw.")

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Only admin can view stats.")
        return
    async with async_session() as s:
        async with s.begin():
            users = await s.scalar(select(func.count(User.id)))
            tickets = await s.scalar(select(func.count(RaffleEntry.id)))
            free = await s.scalar(select(func.count(RaffleEntry.id)).filter_by(free_ticket=True))
    await message.answer(f"📊 <b>Stats</b>\n👥 Users: {users}\n🎟 Tickets: {tickets}\n🆓 Free: {free or 0}")

@dp.message(Command("buyers"))
async def cmd_buyers(message: Message):
    """Admin: list active users who have at least one PAID ticket (not free)."""
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Only admin can view buyers.")
        return

    async with async_session() as s:
        async with s.begin():
            q = await s.execute(
                select(distinct(RaffleEntry.user_id)).where(RaffleEntry.free_ticket == False)  # noqa
            )
            user_ids = [row[0] for row in q.all()]
            if not user_ids:
                await message.answer("📭 No active paid buyers found.")
                return
            q2 = await s.execute(select(User).where(User.id.in_(user_ids)))
            users = q2.scalars().all()

    lines = []
    for u in users:
        lines.append(f"• {('@'+u.username) if u.username else u.telegram_id}")
    await message.answer("🛒 <b>Paid buyers (current tickets)</b>\n" + "\n".join(lines))

# ---------------------------------------------------------
# CALLBACK HANDLERS (buttons)
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
# PAYSTACK WEBHOOK & TELEGRAM WEBHOOK
# ---------------------------------------------------------
@app.post("/webhook/paystack")
async def paystack_webhook(request: Request):
    data = await request.json()
    event = data.get("event")
    if event != "charge.success":
        return {"status": "ignored"}
    # Proceed with the payment success logic, etc.
    return {"status": "ok"}
