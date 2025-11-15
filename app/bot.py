import os
import logging
import random
import aiohttp
import uvicorn
import sys
import asyncio
import random
import string
import os
import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from datetime import datetime, timedelta
from dotenv import load_dotenv
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse
from aiogram import Bot, Dispatcher
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
from app.database import async_session, init_db, User, RaffleEntry

print(sys.path)
load_dotenv()

# Environment
BOT_TOKEN = os.getenv("BOT_TOKEN")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", "8080"))
PUBLIC_URL = os.getenv("PUBLIC_URL", "https://megawinraffle.up.railway.app")
TELEGRAM_WEBHOOK_PATH = "/webhook/telegram"
PAYSTACK_WEBHOOK_PATH = "/webhook/paystack"

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN not set in environment")

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
logger.info("✅ Environment loaded")

# Bot / Dispatcher / FastAPI
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

def generate_ticket_code():
    letter = random.choice(string.ascii_uppercase)
    number = random.randint(100, 999)
    return f"#{letter}{number}"

# ---------------------------------------------------------
# COMMAND HANDLERS
# ---------------------------------------------------------
@dp.message(Command("start"))
async def cmd_start(message: Message, command: Command):
    tg_id = message.from_user.id
    username = message.from_user.username
    user = await get_or_create_user(tg_id, username)

        # Handle affiliate and referrals
    args = getattr(command, "args", None)
    if not args:
        try:
            args = message.get_args()
        except Exception:
            args = None

    if args:
        if args.startswith("aff"):
            # ✅ Affiliate join (different from referral)
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
        else:
            # ✅ Regular referral (no ticket reward yet)
            try:
                ref_tg_id = int(args)
                if ref_tg_id == tg_id:
                    await message.answer("⚠️ You can’t refer yourself.")
                    return

                async with async_session() as s:
                    async with s.begin():
                        q = await s.execute(select(User).where(User.telegram_id == ref_tg_id))
                        ref_user = q.scalar_one_or_none()

                        if ref_user and user.referred_by is None:
                            user.referred_by = ref_tg_id
                            s.add(user)
                            await s.commit()
                            await message.answer(
                                f"🎯 You joined using a referral from <b>{ref_user.username or ref_tg_id}</b>!"
                            )
            except ValueError:
                pass


    ref_link = f"https://t.me/{(await bot.get_me()).username}?start={tg_id}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🎟 Buy Ticket", callback_data="buy_ticket")],
    [InlineKeyboardButton(text="🎫 My Tickets", callback_data="view_tickets")],
    [InlineKeyboardButton(text="💰 My Balance", callback_data="view_balance")],
    [InlineKeyboardButton(text="👥 Referrals", callback_data="my_referrals")],
    [InlineKeyboardButton(text="💼 Affiliate", callback_data="view_affiliate")],
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

# Same structure for other command handlers and webhook handling...



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

# ---------------------------------------------------------
# Error Handling for Flood Control (v3.x)
# ---------------------------------------------------------
async def handle_flood_error():
    """Handle flood control errors and retry."""
    try:
        await bot.send_message(chat_id=ADMIN_ID, text="Testing flood control!")
    except Exception as e:
        retry_after = getattr(e, "retry_after", None)
        if retry_after:
            logger.warning(f"Rate limit exceeded, retrying in {retry_after}s")
            await asyncio.sleep(retry_after)
            try:
                await bot.send_message(chat_id=ADMIN_ID, text="Testing flood control!")
            except Exception as e2:
                logger.warning(f"Failed to resend after wait: {e2}")
        else:
            logger.warning(f"Failed to send message due to unexpected error: {e}")

        

# ---------------------------------------------------------
# FASTAPI STARTUP / SHUTDOWN
# ---------------------------------------------------------

@app.on_event("startup")
async def on_startup():
    """Code to run when the app starts"""
    logger.info("🚀 App startup!")
    await init_db()  # Initialize your database
    await set_bot_commands()  # Set bot commands
    try:
        # Set up the webhook for Telegram bot
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_webhook(f"{PUBLIC_URL}{TELEGRAM_WEBHOOK_PATH}")
        logger.info("✅ Telegram webhook set successfully.")
    except Exception as e:
        # Handle FloodWait-like exceptions or any other error gracefully.
        # Some aiogram versions expose 'retry_after' on the exception (e.g. FloodWait/TelegramRetryAfter).
        retry_after = getattr(e, "retry_after", None)
        if retry_after:
            logger.warning(f"⏳ Flood control exceeded. Retrying in {retry_after} seconds...")
            await asyncio.sleep(retry_after)
            try:
                await bot.set_webhook(f"{PUBLIC_URL}{TELEGRAM_WEBHOOK_PATH}")
                logger.info("✅ Telegram webhook set successfully (after retry).")
            except Exception as e2:
                logger.error(f"❌ Failed to set webhook after retry: {e2}")
        else:
            logger.error(f"❌ Failed to set webhook: {e}")

@app.on_event("shutdown")
async def on_shutdown():
    """Code to run when the app shuts down"""
    logger.info("🛑 App shutdown...")
    try:
        # Remove the webhook when the app shuts down
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logger.error(f"❌ Failed to delete webhook: {e}")

background_state = {"stop": None, "countdown": None, "auto_draw": None}


@app.on_event("startup")
async def start_background_tasks():
    if background_state["stop"] is not None:
        return

    stop_event = asyncio.Event()
    background_state["stop"] = stop_event

    background_state["countdown"] = asyncio.create_task(daily_countdown_task(stop_event))
    background_state["auto_draw"] = asyncio.create_task(auto_winner_task(stop_event))

    logger.info("🚀 Background scheduler started.")


@app.on_event("shutdown")
async def stop_background_tasks():
    stop = background_state.get("stop")
    if stop:
        stop.set()
        await asyncio.sleep(0.5)

        for t in ("countdown", "auto_draw"):
            task = background_state.get(t)
            if task and not task.done():
                task.cancel()

        logger.info("🛑 Background scheduler stopped.")
# ---------------------------------------------------------


# Your existing background task notifications (reuse same bot)
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
@dp.callback_query(lambda c: c.data == "buy_ticket")
async def cb_buy(callback: CallbackQuery):
    await cmd_buy(callback.message)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "view_tickets")
async def cb_tickets(callback: CallbackQuery):
    await cmd_ticket(callback.message)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "my_referrals")
async def cb_ref(callback: CallbackQuery):
    await cmd_referrals(callback.message)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "help_cmd")
async def cb_help(callback: CallbackQuery):
    await cmd_help(callback.message)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "view_balance")
async def cb_balance(callback: CallbackQuery):
    await cmd_balance(callback.message)
    await callback.answer()

# ---------------------------------------------------------
# TELEGRAM WEBHOOK
# ---------------------------------------------------------
@app.post(TELEGRAM_WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    """Handle Telegram updates."""
    try:
        data = await request.json()
        try:
            update = Update.model_validate(data)
        except Exception:
            update = Update(**data)
        await dp.feed_raw_update(bot, data)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"❌ Telegram webhook error: {e}")
        return {"status": "error", "message": str(e)}



async def set_webhook_with_retry():
    """Attempt to set the telegram webhook with retries on FloodWait."""
    

    retries = 5
    for i in range(retries):
        try:
            await bot.set_webhook(f"{PUBLIC_URL}{TELEGRAM_WEBHOOK_PATH}")
            logger.info("✅ Telegram webhook set")
            break
        except FloodWait as e:
            logger.warning(f"⏳ Flood control exceeded. Retrying in {e.retry_after} seconds...")
            await asyncio.sleep(e.retry_after)
        except Exception as e:
            logger.error(f"❌ Failed to set webhook: {e}")
            break


# ---------------------------------------------------------
# PAYSTACK WEBHOOK
# ---------------------------------------------------------


@app.post(PAYSTACK_WEBHOOK_PATH)
async def paystack_webhook(request: Request):
    """Handle Paystack webhook and add confirmed tickets + referral reward."""
    try:
        payload = await request.json()
        event = payload.get("event")
        data = payload.get("data", {})
        logger.info(f"📩 Paystack event: {event}")

        if event != "charge.success" or data.get("status") != "success":
            return {"status": "ignored"}

        tg_id = data.get("metadata", {}).get("telegram_id")
        ref = data.get("reference")

        if not tg_id or not ref:
            return {"status": "error", "message": "Missing telegram_id or reference"}

        try:
            tg_id_int = int(tg_id)
        except Exception:
            tg_id_int = tg_id

        ticket_count = 0

        async with async_session() as db:

            # ✔ Get user
            uq = await db.execute(select(User).where(User.telegram_id == tg_id_int))
            user = uq.scalar_one_or_none()
            if not user:
                return {"status": "error", "message": "User not found"}

            # ✔ Prevent duplicate credit
            q = await db.execute(select(RaffleEntry).where(RaffleEntry.payment_ref == ref))
            entry = q.scalar_one_or_none()

            if not entry:

                # ✔ Promo logic
                ticket_count = promo.multiplier if promo.active else 1

                # Add tickets
                for _ in range(ticket_count):
                    db.add(RaffleEntry(
                        user_id=user.id,
                        payment_ref=ref,
                        free_ticket=False
                    ))

                # -------------------------------
                # 🔥 REFERRAL REWARD (ONLY FOR PAID USERS)
                # -------------------------------
                if getattr(user, "referred_by", None):

                    q_ref = await db.execute(
                        select(User).where(User.telegram_id == user.referred_by)
                    )
                    referrer = q_ref.scalar_one_or_none()

                    if referrer:
                        referrer.referral_count = (referrer.referral_count or 0) + 1

                        # Every 5 paid referrals = free ticket
                        if referrer.referral_count >= 5:
                            db.add(RaffleEntry(
                                user_id=referrer.id,
                                free_ticket=True,
                                payment_ref=f"ref_reward_{referrer.id}"
                            ))
                            referrer.referral_count = 0

                            # notify referrer
                            try:
                                await bot.send_message(
                                    referrer.telegram_id,
                                    "🎉 You referred 5 paying users and earned a FREE ticket!"
                                )
                            except:
                                pass

                        db.add(referrer)

                # -------------------------------
                # 💸 AFFILIATE COMMISSION
                # -------------------------------
                notify_affiliate_id = None

                if getattr(user, "affiliate_id", None):

                    q_aff = await db.execute(
                        select(User).where(User.id == user.affiliate_id)
                    )
                    affiliate = q_aff.scalar_one_or_none()

                    if affiliate:
                        affiliate.commission_balance = (affiliate.commission_balance or 0) + 50
                        db.add(affiliate)

                        try:
                            notify_affiliate_id = int(affiliate.telegram_id)
                        except:
                            notify_affiliate_id = None

                await db.commit()

                # Notify affiliate
                if notify_affiliate_id:
                    try:
                        await bot.send_message(
                            notify_affiliate_id,
                            "💸 You earned ₦50 commission from your affiliate link!"
                        )
                    except:
                        pass

        # Notify buyer
        try:
            await bot.send_message(
                tg_id_int,
                f"✅ Payment confirmed!\n🎟 You received <b>{ticket_count}</b> ticket(s).\nUse /ticket to view."
            )
        except:
            pass

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"❌ Paystack webhook processing error: {e}")
        return {"status": "error", "message": str(e)}



@app.get("/webhook/paystack")
async def paystack_redirect():
    """Handles Paystack redirect after payment (bank transfer or card)."""
    telegram_bot_link = "https://t.me/MegaWinRafflebot"  # 👈 change to your actual bot link, e.g. https://t.me/MegaWinRaffleBot

    html_content = """
    <html>
    <head>
        <meta http-equiv="refresh" content="3; url=https://t.me/MegaWinRafflebot" />
        <style>
            body {
                background-color: #fafafa;
                font-family: Arial, sans-serif;
                text-align: center;
                padding-top: 10%;
                color: #333;
            }
            .card {
                display: inline-block;
                padding: 30px;
                border-radius: 15px;
                background: white;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            }
            h2 {
                color: #28a745;
            }
            p {
                color: #555;
            }
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

# ENV configuration
DRAW_DATETIME_STR = os.getenv("DRAW_DATETIME")  # like 2025-11-20T18:00:00Z
DAILY_BROADCAST_HOUR = int(os.getenv("DAILY_BROADCAST_HOUR", "12"))


async def auto_winner_task(stop_event: asyncio.Event):
    """Automatically pick & announce winner at DRAW_DATETIME."""
    draw_dt = parse_draw_datetime()
    if not draw_dt:
        logger.info("Auto-winner disabled — DRAW_DATETIME not set.")
        return

    now = datetime.now(timezone.utc)
    if draw_dt <= now:
        logger.info("DRAW_DATETIME already passed — skipping auto-winner.")
        return

    wait_time = (draw_dt - now).total_seconds()
    logger.info(f"🏆 Auto-winner scheduled at {draw_dt.isoformat()}")

    # wait until draw time unless stopping early
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=wait_time)
        return
    except asyncio.TimeoutError:
        pass

    # Time to draw winner
    try:
        async with async_session() as s:
            q = await s.execute(select(RaffleEntry))
            entries = q.scalars().all()

            if not entries:
                msg = "📢 No tickets sold — no winner selected."
                await broadcast_message(msg)
                return

            winner_entry = random.choice(entries)

            q2 = await s.execute(select(User).where(User.id == winner_entry.user_id))
            winner = q2.scalar_one_or_none()

            announcement = (
                f"🏆 <b>MEGAWIN DRAW RESULT</b>\n\n"
                f"🎉 Winner: @{winner.username or winner.telegram_id}\n"
                f"🎫 Ticket #{winner_entry.id}\n\n"
                "Congratulations! We will contact the winner privately."
            )

            await broadcast_message(announcement)

            # Private message
            try:
                await bot.send_message(winner.telegram_id,
                                       "🏆 Congratulations! You won the MegaWin draw!")
            except:
                pass

            # Optionally reset all tickets
            await s.execute("DELETE FROM raffle_entries")
            await s.commit()

            logger.info("🏆 Auto-winner announced successfully.")

    except Exception as e:
        logger.error(f"Auto-winner failed: {e}")


def parse_draw_datetime():
    """Return draw datetime in UTC or None."""
    if not DRAW_DATETIME_STR:
        return None
    try:
        dt = datetime.fromisoformat(DRAW_DATETIME_STR.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc)
    except:
        logger.warning("Invalid DRAW_DATETIME format.")
        return None


async def get_all_user_ids():
    """Return list of Telegram IDs for all users (excluding admin)."""
    async with async_session() as s:
        q = await s.execute(select(User.telegram_id))
        rows = q.all()

    ids = []
    for r in rows:
        try:
            tid = int(r[0])
            if tid != ADMIN_ID:
                ids.append(tid)
        except:
            continue
    return ids


async def daily_countdown_task(stop_event: asyncio.Event):
    """Background task: send daily countdown message."""
    logger.info("⏳ Starting daily countdown scheduler...")
    while not stop_event.is_set():

        now = datetime.now(timezone.utc)

        # Schedule next run (next DAILY_BROADCAST_HOUR)
        next_run = now.replace(hour=DAILY_BROADCAST_HOUR, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)

        wait_time = (next_run - now).total_seconds()

        # Sleep until time (unless shutdown event triggers)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=wait_time)
            break  # stop event triggered
        except asyncio.TimeoutError:
            pass

        # Send countdown message
        draw_dt = parse_draw_datetime()
        if draw_dt:
            delta = draw_dt - datetime.now(timezone.utc)

            if delta.total_seconds() <= 0:
                msg = "🎉 The MegaWin draw is happening soon — stay tuned!"
            else:
                days = delta.days
                if days > 0:
                    msg = f"⏳ {days} day(s) left till the next MegaWin draw!"
                else:
                    hours = int(delta.total_seconds() // 3600)
                    msg = f"⏳ {hours} hour(s) left till the MegaWin draw!"
        else:
            msg = "⏳ Countdown is active — use /buy to join MegaWin!"

        user_ids = await get_all_user_ids()

        for uid in user_ids:
            try:
                await bot.send_message(uid, msg)
                await asyncio.sleep(0.05)  # avoid flood limit
            except Exception as e:
                logger.debug(f"Countdown failed for {uid}: {e}")

    logger.info("⏳ Countdown scheduler stopped.")

    

# ---------------------------------------------------------
# STARTUP / SHUTDOWN
# ---------------------------------------------------------
# Note: the startup and shutdown handlers are already declared above with
# @app.on_event("startup") and @app.on_event("shutdown"), and 'app' was
# created earlier as FastAPI(), so we don't recreate the app or use a
# separate lifespan here to avoid referencing undefined names.



# ---------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------
if __name__ == "__main__":
    # Run Uvicorn by import string to avoid issues with objects created at import time
    # (for example when using auto-reload or certain event-loop interactions).
    uvicorn.run("app.bot:app", host="0.0.0.0", port=PORT, log_level="info")
