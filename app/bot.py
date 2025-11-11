# app/bot.py
import os
import logging
import random
import aiohttp
import uvicorn

from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import HTMLResponse
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    BotCommand,
    Update
)
from sqlalchemy import select, func

# your own DB utilities / models
from app.database import async_session, init_db, User, RaffleEntry

# ---------------------------------------------------------
# ENVIRONMENT
# ---------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", "8080"))

PUBLIC_URL = os.getenv("PUBLIC_URL", "https://megawinraffle.up.railway.app")
TELEGRAM_WEBHOOK_PATH = "/webhook/telegram"
PAYSTACK_WEBHOOK_PATH = "/webhook/paystack"

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN not set in environment")

# ---------------------------------------------------------
# LOGGING
# ---------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
logger.info("✅ Environment loaded")

# ---------------------------------------------------------
# BOT / DISPATCHER / FASTAPI
# ---------------------------------------------------------
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
app = FastAPI()

# ---------------------------------------------------------
# PROMO MANAGER (with auto-expiration)
# ---------------------------------------------------------
import asyncio
from datetime import datetime, timedelta

class PromoManager:
    def __init__(self):
        self.active = False
        self.multiplier = 1
        self.expires_at = None
        self._task = None

    def status(self):
        if not self.active:
            return "❌ No active promo."
        remaining = (self.expires_at - datetime.utcnow()).total_seconds() if self.expires_at else 0
        hours_left = int(remaining // 3600)
        return f"🔥 Promo Active (x{self.multiplier}) | Expires in ~{hours_left}h"

    async def start(self, multiplier: int, duration_hours: int = 24):
        """Start promo for a set duration (default 24h)."""
        self.active = True
        self.multiplier = multiplier
        self.expires_at = datetime.utcnow() + timedelta(hours=duration_hours)

        # Cancel any existing expiration task
        if self._task and not self._task.done():
            self._task.cancel()

        self._task = asyncio.create_task(self._auto_expire())

    async def _auto_expire(self):
        """Automatically stop promo after duration."""
        try:
            await asyncio.sleep((self.expires_at - datetime.utcnow()).total_seconds())
            self.stop()
            logger.info("🕒 Promo period expired automatically.")
        except asyncio.CancelledError:
            pass

    def stop(self):
        """Manually stop promo."""
        self.active = False
        self.multiplier = 1
        self.expires_at = None
        if self._task and not self._task.done():
            self._task.cancel()

# Initialize promo system
promo = PromoManager()


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------
async def get_or_create_user(telegram_id: int, username: str | None = None):
    async with async_session() as session:
        q = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = q.scalar_one_or_none()
        if user:
            if username and user.username != username:
                user.username = username
                await session.commit()
            return user
        user = User(telegram_id=telegram_id, username=username)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def set_bot_commands():
    cmds = [
        BotCommand(command="start", description="Start / Referral link"),
        BotCommand(command="help", description="How to use the bot"),
        BotCommand(command="buy", description="Buy a raffle ticket (₦500)"),
        BotCommand(command="ticket", description="View your tickets"),
        BotCommand(command="referrals", description="Your referral count"),
        BotCommand(command="balance", description="Check your spend & referral earnings")  # ✅ NEW
    ]
    await bot.set_my_commands(cmds)


# ---------------------------------------------------------
# COMMAND HANDLERS
# ---------------------------------------------------------
@dp.message(Command("start"))
async def cmd_start(message: Message, command: Command):
    """Welcome message with referral + affiliate link logic."""
    tg_id = message.from_user.id
    username = message.from_user.username
    user = await get_or_create_user(tg_id, username)

    # Get any argument passed to /start
    args = getattr(command, "args", None)
    if not args:
        try:
            args = message.get_args()
        except Exception:
            args = None

    if args:
        # ✅ Step 1: Handle affiliate links first (e.g., aff123456)
        if args.startswith("aff"):
            affiliate_code = args.strip()
            async with async_session() as s:
                async with s.begin():
                    q = await s.execute(select(User).where(User.affiliate_code == affiliate_code))
                    affiliate = q.scalar_one_or_none()
                    if affiliate:
                        user.affiliate_id = affiliate.id
                        s.add(user)
                        await s.commit()
                        await message.answer(
                            f"🤝 You joined via affiliate link from <b>{affiliate.username or affiliate.telegram_id}</b>!"
                        )

        # ✅ Step 2: Handle normal referrals (numeric user IDs)
        else:
            try:
                ref_tg_id = int(args)
                if ref_tg_id == tg_id:
                    await message.answer("⚠️ You can’t refer yourself.")
                    return

                async with async_session() as s:
                    async with s.begin():
                        q = await s.execute(select(User).where(User.telegram_id == ref_tg_id))
                        ref_user = q.scalar_one_or_none()

                        # Prevent multiple referral counts from same user
                        q2 = await s.execute(
                            select(User).where(User.referred_by == ref_tg_id, User.telegram_id == tg_id)
                        )
                        already_referred = q2.scalar_one_or_none()

                        if ref_user and not already_referred:
                            user.referred_by = ref_tg_id
                            ref_user.referral_count = (ref_user.referral_count or 0) + 1
                            s.add_all([user, ref_user])

                            if ref_user.referral_count >= 5:
                                ticket = RaffleEntry(user_id=ref_user.id, free_ticket=True)
                                s.add(ticket)
                                ref_user.referral_count -= 5
                                await bot.send_message(
                                    ref_user.telegram_id,
                                    "🎉 You referred 5 users and earned a free ticket!"
                                )

                            await s.commit()
            except ValueError:
                pass  # Ignore invalid referral IDs

    # ✅ Step 3: Send welcome message and action buttons
    ref_link = f"https://t.me/{(await bot.get_me()).username}?start={tg_id}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎟 Buy Ticket", callback_data="buy_ticket")],
        [InlineKeyboardButton(text="🎫 My Tickets", callback_data="view_tickets")],
        [InlineKeyboardButton(text="💰 My Balance", callback_data="view_balance")],
        [InlineKeyboardButton(text="❓ Help", callback_data="help_cmd")],
    ])

    await message.answer(
        "🎉 <b>Welcome to MegaWin Raffle!</b>\n\n"
        "💸 Buy tickets, earn rewards, and win big!\n"
        "👥 Invite friends with your unique link:\n"
        f"<code>{ref_link}</code>\n\n"
        "🪙 You can also join our affiliate program with /affiliate\n\n"
        "Use the buttons below to get started 👇",
        reply_markup=kb,
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Show help and available commands."""
    await message.answer(
        "💡 <b>How to Play</b>\n"
        "• /buy — Buy a raffle ticket (₦500)\n"
        "• /ticket — View your tickets & balance\n"
        "• /userstat — View your lifetime stats\n"
        "• /balance — Check spend & referral rewards\n"
        "• /help — Show this help guide\n\n"
        "<b>Admin Only:</b>\n"
        "• /winners — Pick random winner and reset\n"
        "• /promo — Manage promo events\n"
        "• /transactions — View recent transactions\n"
        "• /stats — Platform-wide analytics"
    )



@dp.message(Command("buy"))
async def cmd_buy(message: Message):
    """Initialize Paystack transaction and apply promo multiplier if active."""
    if not PAYSTACK_SECRET_KEY:
        await message.answer("❌ Paystack key not set.")
        return

    tg_id = message.from_user.id
    username = message.from_user.username
    user = await get_or_create_user(tg_id, username)

    callback_url = f"{PUBLIC_URL}{PAYSTACK_WEBHOOK_PATH}" if PUBLIC_URL else None

    async with aiohttp.ClientSession() as s:
        headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
                   "Content-Type": "application/json"}
        payload = {
            "email": f"user_{tg_id}@megawinraffle.com",
            "amount": 500 * 100,  # ₦500 in kobo
            "metadata": {
                "telegram_id": tg_id,
                "promo_multiplier": promo.multiplier if promo.active else 1
            },
            "callback_url": callback_url,
        }
        async with s.post("https://api.paystack.co/transaction/initialize",
                          headers=headers, json=payload) as resp:
            res = await resp.json()

    if res.get("status"):
        ref = res["data"]["reference"]
        pay_url = res["data"]["authorization_url"]

        await message.answer(
            f"💳 <b>Payment</b>\n\n"
            f"Click below to complete your payment:\n"
            f"👉 <a href=\"{pay_url}\">Pay ₦500 via Paystack</a>\n\n"
            f"{'🔥 Promo Active! You’ll earn extra tickets for this payment.' if promo.active else ''}\n"
            f"Once payment is confirmed, your raffle ticket(s) will be added automatically. ✅",
            disable_web_page_preview=True,
        )
    else:
        await message.answer("❌ Could not start Paystack payment. Please try again.")


@dp.message(Command("winners"))
async def cmd_winners(message: Message):
    """Pick a random winner and reset all tickets."""
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Only admin can run this command.")
        return

    async with async_session() as s:
        q = await s.execute(select(RaffleEntry))
        entries = q.scalars().all()
        if not entries:
            await message.answer("📭 No tickets yet.")
            return

        winner = random.choice(entries)
        q2 = await s.execute(select(User).where(User.id == winner.user_id))
        user = q2.scalar_one_or_none()

        await message.answer(
            f"🏆 <b>Winner:</b> @{user.username or user.telegram_id}\n🎫 Ticket #{winner.id}"
        )

        # Reset tickets after drawing
        await s.execute("DELETE FROM raffle_entries")
        await s.commit()
        await message.answer("🔁 All tickets have been reset for the next round!")


@dp.message(Command("userstat"))
async def cmd_userstat(message: Message):
    """Show user's lifetime statistics."""
    tg_id = message.from_user.id
    async with async_session() as s:
        q = await s.execute(select(User).where(User.telegram_id == tg_id))
        user = q.scalar_one_or_none()
        if not user:
            await message.answer("🚫 You don't have any record yet.")
            return

        q2 = await s.execute(select(RaffleEntry).where(RaffleEntry.user_id == user.id))
        tickets = q2.scalars().all()

        total_tickets = len(tickets)
        free_tickets = sum(1 for t in tickets if t.free_ticket)
        paid_tickets = total_tickets - free_tickets
        total_spent = paid_tickets * 500
        total_earned = free_tickets * 500
        balance = abs(total_earned - total_spent)

        await message.answer(
            f"📊 <b>Your MegaWin Stats</b>\n\n"
            f"🎟 Total Tickets: {total_tickets}\n"
            f"💸 Total Spent: ₦{total_spent:,}\n"
            f"🎁 Free Tickets Earned: {free_tickets}\n"
            f"💰 Net Balance: ₦{balance:,}\n"
            f"🏆 Wins: Coming soon!"
        )



@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    """Admin-only: show summary statistics."""
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Only the admin can view stats.")
        return

    async with async_session() as s:
        total_users = await s.scalar(select(func.count(User.id)))
        total_tickets = await s.scalar(select(func.count(RaffleEntry.id)))
        total_free = await s.scalar(
            select(func.count(RaffleEntry.id)).where(RaffleEntry.free_ticket == True)
        )

        paid_tickets = (total_tickets or 0) - (total_free or 0)
        total_value = paid_tickets * 500  # ₦500 per paid ticket

    await message.answer(
        "📊 <b>Platform Stats</b>\n"
        f"👥 Total Users: {total_users or 0}\n"
        f"🎟 Total Tickets: {total_tickets or 0}\n"
        f"🆓 Free Tickets: {total_free or 0}\n"
        f"💰 Ticket Value (₦500 each): ₦{total_value:,.0f}"
    )


@dp.message(Command("ticket"))
async def cmd_ticket(message: Message):
    """Show user's tickets and summary with clean layout."""
    tg_id = message.from_user.id
    async with async_session() as s:
        q = await s.execute(select(User).where(User.telegram_id == tg_id))
        user = q.scalar_one_or_none()
        if not user:
            await message.answer("🚫 You don't have any tickets yet.")
            return

        q2 = await s.execute(select(RaffleEntry).where(RaffleEntry.user_id == user.id))
        tickets = q2.scalars().all()
        if not tickets:
            await message.answer("🚫 You have no tickets yet. Use /buy.")
            return

        total_tickets = len(tickets)
        free_tickets = sum(1 for t in tickets if t.free_ticket)
        paid_tickets = total_tickets - free_tickets
        total_value = paid_tickets * 500
        balance_value = free_tickets * 500 - paid_tickets * 500
        balance_display = abs(balance_value)

        await message.answer(
            f"🎟 <b>Your Ticket Summary</b>\n\n"
            f"🎫 Available Tickets: {total_tickets}\n"
            f"🎁 Free Tickets: {free_tickets}\n"
            f"💰 Net Balance: ₦{balance_display:,}"
        )



@dp.message(Command("balance"))
async def cmd_balance(message: Message):
    """Show user's balance summary."""
    telegram_id = message.from_user.id

    async with async_session() as s:
        async with s.begin():
            q = await s.execute(select(User).filter_by(telegram_id=telegram_id))
            user = q.scalar_one_or_none()
            if not user:
                await message.answer("🚫 You don't have any transactions yet.")
                return

            q_tickets = await s.execute(select(RaffleEntry).filter_by(user_id=user.id))
            tickets = q_tickets.scalars().all()
            paid_tickets = [t for t in tickets if not t.free_ticket]
            free_tickets = [t for t in tickets if t.free_ticket]

            spent = len(paid_tickets) * 500
            earned = len(free_tickets) * 500
            balance = abs(earned - spent)

            await message.answer(
                f"💰 <b>Your Balance Summary</b>\n\n"
                f"🪙 Tickets Bought: {len(paid_tickets)} (₦{spent:,})\n"
                f"🎁 Free Tickets Earned: {len(free_tickets)} (₦{earned:,})\n\n"
                f"📊 <b>Net Balance:</b> ₦{balance:,}"
            )

@dp.message(Command("promo"))
async def cmd_promo(message: Message):
    """Admin-only: manage timed promo events with broadcast."""
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Only admin can manage promo events.")
        return

    parts = message.text.split()
    if len(parts) == 1:
        await message.answer(f"📢 Current Promo: {promo.status()}")
        return

    action = parts[1].lower()
    if action == "start" and len(parts) >= 3:
        try:
            multiplier = int(parts[2])
            hours = int(parts[3]) if len(parts) > 3 else 24
            if multiplier < 1 or hours < 1:
                raise ValueError

            # ✅ Start the promo
            await promo.start(multiplier, hours)

            # ✅ Broadcast message to all users
            promo_text = (
                f"🔥 <b>Double Ticket Promo is LIVE!</b>\n\n"
                f"Earn <b>x{multiplier}</b> tickets for every payment made in the next {hours} hour(s)! 🕒\n\n"
                f"Use /buy to grab your ticket now! 🎟"
            )

            # First notify admin
            await message.answer("✅ Promo started and broadcast sent to all users.")
            # Then send the message to everyone
            await broadcast_message(promo_text)

        except ValueError:
            await message.answer(
                "⚠️ Usage: /promo start <multiplier> [hours] (e.g. /promo start 2 12)"
            )

    elif action == "stop":
        promo.stop()
        await message.answer("🛑 Promo stopped manually.")

    else:
        await message.answer("⚠️ Usage:\n/promo start <multiplier> [hours]\n/promo stop")


async def broadcast_message(text: str):
    """Send message to all registered users."""
    async with async_session() as s:
        q = await s.execute(select(User.telegram_id))
        user_ids = [u[0] for u in q.all() if u[0] != ADMIN_ID]

    sent, failed = 0, 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            failed += 1
            logger.warning(f"Failed to send to {uid}: {e}")

    logger.info(f"📢 Broadcast done — Sent: {sent}, Failed: {failed}")



@dp.message(Command("transactions"))
async def cmd_transactions(message: Message):
    """Admin-only: View all transactions, payments, and affiliate commissions."""
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Only the admin can view transactions.")
        return

    async with async_session() as db:
        # Get all payments
        q = await db.execute(select(RaffleEntry).order_by(RaffleEntry.created_at.desc()))
        transactions = q.scalars().all()

        if not transactions:
            await message.answer("❌ No transactions found.")
            return

        # Format transactions
        msg_lines = ["💳 <b>Transactions</b>:\n"]

        for entry in transactions:
            user = await db.execute(select(User).where(User.id == entry.user_id))
            user = user.scalar_one_or_none()
            if user:
                # Check for affiliate commission
                affiliate_message = ""
                if getattr(user, "affiliate_id", None):
                    affiliate = await db.execute(select(User).where(User.id == user.affiliate_id))
                    affiliate = affiliate.scalar_one_or_none()
                    if affiliate:
                        affiliate_message = f"💸 Commission Earned: ₦{affiliate.commission_balance or 0}"

                msg_lines.append(
                    f"🎟 Ticket #{entry.id} | User: @{user.username} | "
                    f"Payment Reference: {entry.payment_ref} | "
                    f"Status: {'Verified' if entry.payment_ref else 'Pending'}\n"
                    f"{affiliate_message}"
                )

        await message.answer("\n".join(msg_lines))



@dp.message(Command("referrals"))
async def cmd_referrals(message: Message):
    telegram_id = message.from_user.id
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={telegram_id}"

    async with async_session() as s:
        async with s.begin():
            q = await s.execute(select(User).filter_by(telegram_id=telegram_id))
            user = q.scalar_one_or_none()
            count = user.referral_count if user else 0
            await message.answer(
                f"👥 You have referred {count} user(s).\n\nYour referral link:\n{link}"
            )

@dp.message(Command("affiliate"))
async def cmd_affiliate(message: Message):
    """Generate affiliate link and show commission balance."""
    tg_id = message.from_user.id
    async with async_session() as s:
        async with s.begin():
            q = await s.execute(select(User).where(User.telegram_id == tg_id))
            user = q.scalar_one_or_none()
            if not user:
                await message.answer("🚫 Please use /start first.")
                return

            # Generate affiliate code if missing
            if not user.affiliate_code:
                user.affiliate_code = f"aff{tg_id}"
                s.add(user)
                await s.commit()

            code = user.affiliate_code
            link = f"https://t.me/{(await bot.get_me()).username}?start={code}"
            balance = getattr(user, "commission_balance", 0)

            await message.answer(
                f"💼 <b>Affiliate Dashboard</b>\n\n"
                f"🔗 Your Link:\n<code>{link}</code>\n\n"
                f"💰 Commission Balance: ₦{balance:,.0f}\n\n"
                f"Earn ₦50 for each successful ticket sale through your link!"
            )

@dp.message(Command("leaderboard"))
async def cmd_leaderboard(message: Message):
    """Show the top 10 referrers and most active ticket buyers."""
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Only the admin can view the leaderboard.")
        return

    async with async_session() as db:
        # Get the top 10 referrers
        referrers = await db.execute(
            select(User).order_by(User.referral_count.desc()).limit(10)
        )
        top_referrers = referrers.scalars().all()

        # Get the most active ticket buyers (by the number of tickets purchased)
        buyers = await db.execute(
            select(User)
            .join(RaffleEntry)
            .group_by(User.id)
            .order_by(func.count(RaffleEntry.id).desc())
            .limit(10)
        )
        top_buyers = buyers.scalars().all()

        # Format leaderboard message
        msg_lines = ["🏆 <b>Leaderboard</b>\n"]
        msg_lines.append("\n<b>Top 10 Referrers:</b>")
        for i, referrer in enumerate(top_referrers, start=1):
            msg_lines.append(f"{i}. @{referrer.username} - {referrer.referral_count} Referrals")

        msg_lines.append("\n<b>Top 10 Active Ticket Buyers:</b>")
        for i, buyer in enumerate(top_buyers, start=1):
            msg_lines.append(f"{i}. @{buyer.username} - {buyer.ticket_count} Tickets")

        await message.answer("\n".join(msg_lines))

from fastapi import FastAPI, BackgroundTasks
import time
from aiogram import Bot
import logging

# Assuming 'bot' is your instance of aiogram Bot and 'ADMIN_ID' is the admin user ID
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN not set in environment!")
bot = Bot(token=BOT_TOKEN)

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI()

from fastapi import BackgroundTasks
import time

async def send_countdown():
    """Send a countdown message to remind users of the upcoming draw."""
    draw_date = "2025-12-31"  # example date
    current_time = time.time()
    draw_time = time.mktime(time.strptime(draw_date, "%Y-%m-%d"))
    time_left = int(draw_time - current_time)

    if time_left > 0:
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=f"⏳ {time_left // 86400} days left till the next MegaWin draw!"  # 86400 seconds = 1 day
        )

@app.on_event("startup")
async def send_scheduled_message(background_tasks: BackgroundTasks):
    """Start the countdown in the background."""
    background_tasks.add_task(send_countdown)


# FastAPI setup and Bot initialization
from fastapi import FastAPI, BackgroundTasks
import time
from aiogram import Bot
import logging

# Assuming 'bot' is your instance of aiogram Bot and 'ADMIN_ID' is the admin user ID
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN not set in environment!")
bot = Bot(token=BOT_TOKEN)

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI()

@app.on_event("startup")
async def on_startup():
    await init_db()
    await set_bot_commands()
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_webhook(f"{PUBLIC_URL}{TELEGRAM_WEBHOOK_PATH}", allowed_updates=["message", "callback_query"])
        logger.info("✅ Telegram webhook set")
    except Exception as e:
        logger.error(f"❌ Failed to set webhook: {e}")

@app.on_event("shutdown")
async def on_shutdown():
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass

# Your other bot-related functions...


# Your existing background task notifications
async def notify_free_ticket(user_id: int):
    """Notify users when they earn a free ticket."""
    await bot.send_message(
        user_id,
        "🎟️ Congratulations! You've earned a free ticket for referring 5 people. 🎉"
    )

async def notify_draw_date_coming(user_id: int):
    """Notify users when the draw date is near."""
    await bot.send_message(
        user_id,
        "⏳ The MegaWin draw is just around the corner! Stay tuned. 📅"
    )

async def notify_winner(user_id: int):
    """Notify users when winners are announced."""
    await bot.send_message(
        user_id,
        "🏆 The winners of MegaWin draw have been announced! Check the leaderboard! 🎉"
    )

# Use the BackgroundTasks in a specific endpoint if needed
@app.get("/send-message")
async def send_message(background_tasks: BackgroundTasks):
    """Route to trigger sending a message."""
    background_tasks.add_task(notify_free_ticket, 123456)  # Example user_id for testing
    return {"message": "Scheduled message has been sent."}



# You can use these functions in the related code sections, for example, when a user refers others or when a winner is drawn.


# ---------------------------------------------------------
# CALLBACKS
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

@dp.callback_query(F.data == "my_balance")
async def cb_balance(callback: CallbackQuery):
    await cmd_balance(callback.message)
    await callback.answer()

# ---------------------------------------------------------
# TELEGRAM WEBHOOK
# ---------------------------------------------------------
@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = Update.model_validate(data)
        await dp.feed_update(bot, update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"❌ Telegram webhook error: {e}")
        return {"status": "error", "message": str(e)}

# ---------------------------------------------------------
# PAYSTACK WEBHOOK
# ---------------------------------------------------------
@app.post(PAYSTACK_WEBHOOK_PATH)
async def paystack_webhook(request: Request):
    """Handle Paystack webhook and add confirmed tickets."""
    payload = await request.json()
    event = payload.get("event")
    data = payload.get("data", {})
    logger.info(f"📩 Paystack event: {event}")

    # Only handle successful payments
    if event != "charge.success" or data.get("status") != "success":
        return {"status": "ignored"}

    tg_id = data.get("metadata", {}).get("telegram_id")
    ref = data.get("reference")

    if not tg_id or not ref:
        return {"status": "error", "message": "Missing telegram_id or reference"}

    async with async_session() as db:
        uq = await db.execute(select(User).where(User.telegram_id == tg_id))
        user = uq.scalar_one_or_none()
        if not user:
            user = User(telegram_id=tg_id)
            db.add(user)
            await db.flush()

        # Prevent duplicate tickets for same reference
        q = await db.execute(select(RaffleEntry).where(RaffleEntry.payment_ref == ref))
        entry = q.scalar_one_or_none()

        if not entry:
            # ✅ Apply promo multiplier (if active)
            ticket_count = promo.multiplier if promo.active else 1
            for _ in range(ticket_count):
                db.add(RaffleEntry(user_id=user.id, payment_ref=ref, free_ticket=False))

            # ✅ Affiliate commission reward
            if getattr(user, "affiliate_id", None):
                q_aff = await db.execute(select(User).where(User.id == user.affiliate_id))
                affiliate = q_aff.scalar_one_or_none()
                if affiliate:
                    affiliate.commission_balance = (affiliate.commission_balance or 0) + 50  # ₦50 commission
                    db.add(affiliate)
                    try:
                        await bot.send_message(
                            affiliate.telegram_id,
                            f"💸 You earned ₦50 commission from your affiliate link! 💰"
                        )
                    except Exception as e:
                        logger.warning(f"Failed to notify affiliate: {e}")

            await db.commit()

    # ✅ Notify the buyer
    try:
        await bot.send_message(
            chat_id=int(tg_id),
            text=(
                f"✅ <b>Payment confirmed!</b>\n"
                f"🎟 You received <b>{ticket_count}</b> ticket{'s' if ticket_count > 1 else ''} "
                f"for your payment.\nUse /ticket to view your tickets."
            ),
        )
    except Exception as e:
        logger.warning(f"Failed to notify user {tg_id}: {e}")

    return {"status": "ok"}


from fastapi.responses import HTMLResponse

from fastapi.responses import HTMLResponse

@app.get("/webhook/paystack")
async def paystack_redirect():
    """Handles Paystack redirect after payment (bank transfer or card)."""
    telegram_bot_link = "https://t.me/MegaWinRafflebot"  # 👈 change to your actual bot link, e.g. https://t.me/MegaWinRaffleBot

    html_content = f"""
    <html>
    <head>
        <meta http-equiv="refresh" content="3; url=https://t.me/MegaWinRafflebot" />
        <style>
            body {{
                background-color: #fafafa;
                font-family: Arial, sans-serif;
                text-align: center;
                padding-top: 10%;
                color: #333;
            }}
            .card {{
                display: inline-block;
                padding: 30px;
                border-radius: 15px;
                background: white;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            }}
            h2 {{
                color: #28a745;
            }}
            p {{
                color: #555;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <h2>✅ Payment Successful!</h2>
            <p>You’ll be redirected to Telegram in a few seconds...</p>
            <p>If not, <a href="https://t.me/MegaWinRafflebot">click here</a>.</p>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)



# ---------------------------------------------------------
# STARTUP / SHUTDOWN
# ---------------------------------------------------------
@app.on_event("startup")
async def on_startup():
    await init_db()
    await set_bot_commands()
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_webhook(f"{PUBLIC_URL}{TELEGRAM_WEBHOOK_PATH}",
                              allowed_updates=["message", "callback_query"])
        logger.info("✅ Telegram webhook set")
    except Exception as e:
        logger.error(f"❌ Failed to set webhook: {e}")

@app.on_event("shutdown")
async def on_shutdown():
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass

# ---------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
