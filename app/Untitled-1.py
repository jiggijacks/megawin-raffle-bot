# ============================
# MEGAWIN RAFFLE BOT (WEBHOOK)
# CLEAN AIROGRAM V3 VERSION
# ============================

import os
import random
import string
import logging
import asyncio
from datetime import datetime, timedelta, timezone

import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
    Update,
)

from sqlalchemy import select, func

# Database
from app.database import async_session, init_db, User, RaffleEntry


# ==================================
# LOAD ENVIRONMENT VARIABLES
# ==================================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

RAILWAY_DOMAIN = "https://megawinraffle.up.railway.app"
TELEGRAM_WEBHOOK_PATH = "/webhook/telegram"
PAYSTACK_WEBHOOK_PATH = "/webhook/paystack"

WEBHOOK_URL = f"{RAILWAY_DOMAIN}{TELEGRAM_WEBHOOK_PATH}"
PAYSTACK_URL = f"{RAILWAY_DOMAIN}{PAYSTACK_WEBHOOK_PATH}"

REQUIRED_CHANNEL = "@MegaWinRaffle"

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN missing in environment!")


# ==================================
# LOGGING
# ==================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("MegaWinRaffle")


# ==================================
# BOT INITIALIZATION
# ==================================
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()
app = FastAPI()
# ==================================
# HELPERS & UTILITY FUNCTIONS
# ==================================

def generate_ticket_code():
    """Generate a unique ticket code."""
    letter = random.choice(string.ascii_uppercase)
    number = random.randint(100, 999)
    return f"#{letter}{number}"


async def get_or_create_user(tg_id: int, username: str | None = None):
    async with async_session() as session:
        q = await session.execute(select(User).where(User.telegram_id == tg_id))
        user = q.scalar_one_or_none()

        if user:
            if username and user.username != username:
                user.username = username
                await session.commit()
            return user

        user = User(telegram_id=tg_id, username=username)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def user_in_channel(user_id: int):
    """Check whether user has joined the required Telegram channel."""
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status in ("member", "administrator", "creator")
    except:
        return False


async def set_bot_commands():
    """Register bot commands."""
    commands = [
        BotCommand(command="start", description="Start bot / referral link"),
        BotCommand(command="help", description="How to use the bot"),
        BotCommand(command="buy", description="Buy a raffle ticket"),
        BotCommand(command="ticket", description="View your tickets"),
        BotCommand(command="balance", description="Check your balance"),
        BotCommand(command="referrals", description="Your referrals"),
        BotCommand(command="affiliate", description="Affiliate dashboard"),
        BotCommand(command="leaderboard", description="Top users"),
    ]
    await bot.set_my_commands(commands)

# ==================================
# ==================================
# PROMO MULTIPLIER SYSTEM
# ==================================

class PromoManager:
    def __init__(self):
        self.active = False
        self.multiplier = 1
        self.expires_at = None
        self._task = None

    def status(self):
        if not self.active:
            return "❌ No active promo."
        remaining = (self.expires_at - datetime.utcnow()).total_seconds()
        hours_left = int(remaining // 3600)
        return f"🔥 Promo Active (x{self.multiplier}) • Expires in ~{hours_left}h"

    async def start(self, multiplier: int, duration_hours: int = 24):
        """Start a promo for a fixed duration."""
        self.active = True
        self.multiplier = multiplier
        self.expires_at = datetime.utcnow() + timedelta(hours=duration_hours)

        # Cancel previous task
        if self._task and not self._task.done():
            self._task.cancel()

        self._task = asyncio.create_task(self._expire_after())

    async def _expire_after(self):
        """Automatically expire promo."""
        try:
            await asyncio.sleep((self.expires_at - datetime.utcnow()).total_seconds())
            self.stop()
            logger.info("Promo expired automatically.")
        except asyncio.CancelledError:
            pass

    def stop(self):
        """Stop promo manually."""
        self.active = False
        self.multiplier = 1
        self.expires_at = None
        if self._task and not self._task.done():
            self._task.cancel()


promo = PromoManager()
# ==================================
# ==================================
# /START COMMAND — REFERRAL + AFFILIATE + JOIN CHECK
# ==================================

async def cmd_start(message: Message, command: F = None):
    tg_id = message.from_user.id
    username = message.from_user.username

    # 1. Channel join check
    if not await user_in_channel(tg_id):
        join_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Join Channel", url="https://t.me/MegaWinRaffle")],
            [InlineKeyboardButton(text="✅ I Joined", callback_data="check_joined")]
        ])
        await message.answer(
            "<b>❗ You must join our channel to use the bot</b>\n\n"
            "👉 <b>@MegaWinRaffle</b>\nTap the button below…",
            reply_markup=join_kb
        )
        return

    # 2. Create or load user
    user = await get_or_create_user(tg_id, username)

    # 3. Referral handling
    args = message.text.split()
    if len(args) > 1:
        ref_code = args[1]

        if ref_code.startswith("aff"):  # affiliate link
            async with async_session() as s:
                q = await s.execute(select(User).where(User.affiliate_code == ref_code))
                affiliate = q.scalar_one_or_none()
                if affiliate and affiliate.id != user.id:
                    user.affiliate_id = affiliate.id
                    await s.commit()
        else:
            try:
                ref_tg = int(ref_code)
                if ref_tg != tg_id:
                    user.referred_by = ref_tg
                    async with async_session() as s:
                        s.add(user)
                        await s.commit()
            except ValueError:
                pass

    # 4. Buttons
    buttons = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎟 Buy Ticket", callback_data="buy_ticket")],
        [InlineKeyboardButton(text="🎫 My Tickets", callback_data="view_tickets")],
        [InlineKeyboardButton(text="💰 My Balance", callback_data="view_balance")],
        [InlineKeyboardButton(text="👥 Referrals", callback_data="my_referrals")],
        [InlineKeyboardButton(text="💼 Affiliate", callback_data="view_affiliate")],
        [InlineKeyboardButton(text="❓ Help", callback_data="help_cmd")]
    ])

    ref_link = f"https://t.me/MegaWinRaffleBot?start={tg_id}"

    await message.answer(
        "🎉 <b>Welcome to MegaWin Raffle!</b>\n\n"
        "Earn tickets, invite friends, win huge prizes!\n"
        "Your referral link:\n"
        f"<code>{ref_link}</code>",
        reply_markup=buttons,
    )


# REGISTER HANDLER
dp.message.register(cmd_start, F.text.startswith("/start"))
# ==================================

# ==================================
# GENERAL COMMAND HANDLERS
# ==================================

async def cmd_help(message: Message):
    await message.answer(
        "💡 <b>How to Play MegaWin Raffle</b>\n\n"
        "• /buy — Buy a raffle ticket\n"
        "• /ticket — View your tickets\n"
        "• /balance — Check your balance\n"
        "• /referrals — View your referral stats\n"
        "• /affiliate — Affiliate dashboard\n"
        "• /leaderboard — Top referrers & buyers\n"
    )

dp.message.register(cmd_help, F.text == "/help")



# ==================================
# /BUY — Paystack Transaction Init
# ==================================

async def cmd_buy(message: Message):
    if not PAYSTACK_SECRET_KEY:
        return await message.answer("❌ Paystack key missing!")

    tg_id = message.from_user.id
    user = await get_or_create_user(tg_id, message.from_user.username)

    callback_url = PAYSTACK_URL

    async with aiohttp.ClientSession() as s:
        headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
        payload = {
            "email": f"user_{tg_id}@megawinraffle.com",
            "amount": 500 * 100,
            "metadata": {"telegram_id": tg_id,
                         "promo_multiplier": promo.multiplier if promo.active else 1},
            "callback_url": callback_url,
        }

        async with s.post(
            "https://api.paystack.co/transaction/initialize",
            json=payload,
            headers=headers
        ) as resp:
            res = await resp.json()

    if not res.get("status"):
        return await message.answer("❌ Payment initialization failed.")

    pay_url = res["data"]["authorization_url"]

    await message.answer(
        f"<b>💳 Pay ₦500</b>\n\n"
        f"Click to pay:\n<a href='{pay_url}'>Pay via Paystack</a>\n\n"
        f"{'🔥 Promo active: bonus tickets apply!' if promo.active else ''}"
    )

dp.message.register(cmd_buy, F.text == "/buy")



# ==================================
# /TICKET — VIEW USER’S TICKETS
# ==================================

async def cmd_ticket(message: Message):
    tg_id = message.from_user.id

    async with async_session() as s:
        q = await s.execute(select(User).where(User.telegram_id == tg_id))
        user = q.scalar_one_or_none()

        if not user:
            return await message.answer("🚫 No account found. Use /start.")

        q2 = await s.execute(select(RaffleEntry).where(RaffleEntry.user_id == user.id))
        tickets = q2.scalars().all()

    if not tickets:
        return await message.answer("You have no tickets yet.\nUse /buy.")

    lines = []
    for t in tickets:
        tag = "🎁 Free" if t.free_ticket else "💵 Paid"
        date_str = t.created_at.strftime("%Y-%m-%d %H:%M")
        lines.append(f"{t.ticket_code} • {tag} • {date_str}")

    await message.answer(
        "🎫 <b>Your Tickets</b>\n\n" + "\n".join(lines)
    )

dp.message.register(cmd_ticket, F.text == "/ticket")



# ==================================
# /BALANCE — SPENT vs EARNED
# ==================================

async def cmd_balance(message: Message):
    tg_id = message.from_user.id

    async with async_session() as s:
        q = await s.execute(select(User).where(User.telegram_id == tg_id))
        user = q.scalar_one_or_none()

        if not user:
            return await message.answer("No history available.")

        q2 = await s.execute(select(RaffleEntry).where(RaffleEntry.user_id == user.id))
        tickets = q2.scalars().all()

    paid = len([t for t in tickets if not t.free_ticket])
    free = len([t for t in tickets if t.free_ticket])
    spent = paid * 500
    earned = free * 500

    await message.answer(
        f"💰 <b>Your Balance</b>\n\n"
        f"Tickets Bought: {paid} (₦{spent})\n"
        f"Free Tickets Earned: {free} (₦{earned})\n"
        f"Net Balance: ₦{earned - spent}"
    )

dp.message.register(cmd_balance, F.text == "/balance")



# ==================================
# /REFERRALS — COUNT
# ==================================

async def cmd_referrals(message: Message):
    tg_id = message.from_user.id
    ref_link = f"https://t.me/MegaWinRaffleBot?start={tg_id}"

    async with async_session() as s:
        q = await s.execute(select(User).where(User.telegram_id == tg_id))
        user = q.scalar_one_or_none()

    count = user.referral_count if user else 0

    await message.answer(
        f"👥 You referred <b>{count}</b> user(s)\n\n"
        f"Your link:\n<code>{ref_link}</code>"
    )

dp.message.register(cmd_referrals, F.text == "/referrals")



# ==================================
# /AFFILIATE — DASHBOARD
# ==================================

async def cmd_affiliate(message: Message):
    tg_id = message.from_user.id

    async with async_session() as s:
        q = await s.execute(select(User).where(User.telegram_id == tg_id))
        user = q.scalar_one_or_none()

        if not user:
            return await message.answer("Use /start first.")

        if not user.affiliate_code:
            user.affiliate_code = f"aff{tg_id}"
            await s.commit()

    code = user.affiliate_code
    link = f"https://t.me/MegaWinRaffleBot?start={code}"

    await message.answer(
        f"💼 <b>Affiliate Dashboard</b>\n\n"
        f"Code: <code>{code}</code>\n"
        f"Link:\n<code>{link}</code>"
    )

dp.message.register(cmd_affiliate, F.text == "/affiliate")



# ==================================
# /LEADERBOARD — TOP REFERRERS & BUYERS
# ==================================

async def cmd_leaderboard(message: Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("Admins only.")

    async with async_session() as s:
        top_refs = await s.execute(
            select(User).order_by(User.referral_count.desc()).limit(10)
        )
        referrers = top_refs.scalars().all()

        buyers = await s.execute(
            select(User).join(RaffleEntry)
            .group_by(User.id)
            .order_by(func.count(RaffleEntry.id).desc())
            .limit(10)
        )
        top_buyers = buyers.scalars().all()

    msg = "🏆 <b>Leaderboard</b>\n\n<b>Top Referrers:</b>\n"
    for i, u in enumerate(referrers, 1):
        msg += f"{i}. @{u.username} — {u.referral_count}\n"

    msg += "\n<b>Top Buyers:</b>\n"
    for i, u in enumerate(top_buyers, 1):
        msg += f"{i}. @{u.username}\n"

    await message.answer(msg)

dp.message.register(cmd_leaderboard, F.text == "/leaderboard")
# ==================================
# ==================================
# CALLBACK HANDLERS
# ==================================

# 1. "I Joined" button
async def cb_check_joined(callback: CallbackQuery):
    if await user_in_channel(callback.from_user.id):
        await callback.message.edit_text("✅ You have joined! Send /start again.")
    else:
        await callback.answer("❗ You still haven't joined.", show_alert=True)

dp.callback_query.register(cb_check_joined, F.data == "check_joined")


# 2. Buy Ticket callback
async def cb_buy_ticket(callback: CallbackQuery):
    await cmd_buy(callback.message)
    await callback.answer()

dp.callback_query.register(cb_buy_ticket, F.data == "buy_ticket")


# 3. My Tickets
async def cb_view_tickets(callback: CallbackQuery):
    await cmd_ticket(callback.message)
    await callback.answer()

dp.callback_query.register(cb_view_tickets, F.data == "view_tickets")


# 4. Balance
async def cb_view_balance(callback: CallbackQuery):
    await cmd_balance(callback.message)
    await callback.answer()

dp.callback_query.register(cb_view_balance, F.data == "view_balance")


# 5. Referrals
async def cb_my_referrals(callback: CallbackQuery):
    await cmd_referrals(callback.message)
    await callback.answer()

dp.callback_query.register(cb_my_referrals, F.data == "my_referrals")


# 6. Affiliate
async def cb_view_affiliate(callback: CallbackQuery):
    await cmd_affiliate(callback.message)
    await callback.answer()

dp.callback_query.register(cb_view_affiliate, F.data == "view_affiliate")


# 7. Help
async def cb_help_cmd(callback: CallbackQuery):
    await cmd_help(callback.message)
    await callback.answer()

dp.callback_query.register(cb_help_cmd, F.data == "help_cmd")
# ==================================
# ==================================
# PAYSTACK WEBHOOK — CHARGE SUCCESS
# ==================================

@app.post(PAYSTACK_WEBHOOK_PATH)
async def paystack_webhook(request: Request):
    """Handle Paystack's charge.success events."""
    try:
        payload = await request.json()
        event = payload.get("event", "")
        data = payload.get("data", {})

        logger.info(f"🔔 Paystack event: {event}")

        # Only accept successful charge events
        if event != "charge.success":
            return {"status": "ignored"}

        if data.get("status") != "success":
            return {"status": "ignored"}

        metadata = data.get("metadata", {})
        tg_id = metadata.get("telegram_id")
        promo_multiplier = metadata.get("promo_multiplier", 1)

        reference = data.get("reference")
        amount_paid = data.get("amount") / 100  # Convert kobo to naira

        if not tg_id or not reference:
            return {"error": "Missing telegram_id or reference"}

        # Prevent casting errors
        try:
            tg_id = int(tg_id)
        except:
            pass

        async with async_session() as db:
            # Get user
            q = await db.execute(select(User).where(User.telegram_id == tg_id))
            user = q.scalar_one_or_none()
            if not user:
                return {"error": "User not found"}

            # Prevent duplicate processing
            check = await db.execute(
                select(RaffleEntry).where(RaffleEntry.payment_ref == reference)
            )
            duplicate = check.scalar_one_or_none()
            if duplicate:
                return {"status": "duplicate"}

            # Ticket creation
            ticket_count = promo_multiplier
            entries = []

            for _ in range(ticket_count):
                entry = RaffleEntry(
                    user_id=user.id,
                    ticket_code=generate_ticket_code(),
                    free_ticket=False,
                    payment_ref=reference,
                )
                db.add(entry)
                entries.append(entry)

            # -------------------------
            # REFERRAL: every 5 paid referrals → free ticket
            # -------------------------
            if user.referred_by:
                q2 = await db.execute(
                    select(User).where(User.telegram_id == user.referred_by)
                )
                referrer = q2.scalar_one_or_none()

                if referrer:
                    referrer.referral_count = (referrer.referral_count or 0) + 1

                    if referrer.referral_count >= 5:
                        # Grant free ticket
                        free_ticket = RaffleEntry(
                            user_id=referrer.id,
                            free_ticket=True,
                            ticket_code=generate_ticket_code(),
                            payment_ref=f"ref_bonus_{referrer.id}"
                        )
                        db.add(free_ticket)

                        referrer.referral_count = 0  # reset

                        # Notify referrer
                        try:
                            await bot.send_message(
                                referrer.telegram_id,
                                "🎉 You earned a FREE ticket for 5 referrals!"
                            )
                        except:
                            pass

            # -------------------------
            # AFFILIATE COMMISSION ₦50
            # -------------------------
            if user.affiliate_id:
                q_aff = await db.execute(
                    select(User).where(User.id == user.affiliate_id)
                )
                affiliate = q_aff.scalar_one_or_none()

                if affiliate:
                    affiliate.commission_balance = (affiliate.commission_balance or 0) + 50
                    db.add(affiliate)

                    # Notify affiliate
                    try:
                        await bot.send_message(
                            affiliate.telegram_id,
                            "💸 You earned ₦50 from your affiliate link!"
                        )
                    except:
                        pass

            await db.commit()

        # Notify buyer
        try:
            await bot.send_message(
                tg_id,
                f"✅ Payment confirmed!\n🎟 You received <b>{ticket_count}</b> ticket(s).\nUse /ticket to view."
            )
        except:
            pass

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"❌ Paystack Webhook Error: {e}")
        return {"status": "error", "message": str(e)}
# ==================================

# ==================================
# AUTO-WINNER SYSTEM & COUNTDOWN BROADCAST
# ==================================

DRAW_DATETIME_STR = os.getenv("DRAW_DATETIME")  # Example: 2025-12-01T20:00:00Z
DAILY_BROADCAST_HOUR = int(os.getenv("DAILY_BROADCAST_HOUR", "12"))

background_state = {"stop": None, "countdown": None, "auto_draw": None}


def parse_draw_datetime():
    """Convert DRAW_DATETIME env string → UTC datetime."""
    if not DRAW_DATETIME_STR:
        return None

    try:
        dt = datetime.fromisoformat(DRAW_DATETIME_STR.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc)
    except:
        logger.warning("Invalid DRAW_DATETIME format.")
        return None


async def broadcast_message(text: str):
    """Send broadcast to all users."""
    async with async_session() as s:
        q = await s.execute(select(User.telegram_id))
        user_ids = [u[0] for u in q.all() if u[0] != ADMIN_ID]

    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
            await asyncio.sleep(0.05)
        except:
            pass


# -------------------------------
# AUTO DRAW WINNER TASK
# -------------------------------

async def auto_winner_task(stop_event: asyncio.Event):
    draw_dt = parse_draw_datetime()
    if not draw_dt:
        logger.info("Auto-draw disabled (DRAW_DATETIME missing).")
        return

    now = datetime.now(timezone.utc)
    if draw_dt <= now:
        logger.info("DRAW_DATETIME has passed; skipping.")
        return

    wait_for = (draw_dt - now).total_seconds()
    logger.info(f"🎯 Auto-winner scheduled for {draw_dt}")

    try:
        await asyncio.wait_for(stop_event.wait(), timeout=wait_for)
        return
    except asyncio.TimeoutError:
        pass

    # Time to pick a winner
    async with async_session() as s:
        q = await s.execute(select(RaffleEntry))
        entries = q.scalars().all()

        if not entries:
            await broadcast_message("📢 No tickets → No winner this round.")
            return

        winner_entry = random.choice(entries)

        q2 = await s.execute(select(User).where(User.id == winner_entry.user_id))
        winner = q2.scalar_one_or_none()

        announcement = (
            "🏆 <b>MEGAWIN DRAW RESULT</b>\n\n"
            f"🎉 Winner: @{winner.username or winner.telegram_id}\n"
            f"🎫 Ticket Code: {winner_entry.ticket_code}\n\n"
            "Congratulations! We will contact you."
        )

        await broadcast_message(announcement)

        try:
            await bot.send_message(
                winner.telegram_id, "🏆 Congratulations! You won the MegaWin draw!"
            )
        except:
            pass

        # Clear ticket table
        await s.execute("DELETE FROM raffle_entries")
        await s.commit()

        logger.info("Winner selected & tickets reset.")


# -------------------------------
# DAILY COUNTDOWN TASK
# -------------------------------

async def daily_countdown_task(stop_event: asyncio.Event):
    logger.info("⏳ Countdown Task Running...")

    while not stop_event.is_set():
        now = datetime.now(timezone.utc)

        # Schedule next run
        next_run = now.replace(hour=DAILY_BROADCAST_HOUR, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)

        wait_for = (next_run - now).total_seconds()

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=wait_for)
            break
        except asyncio.TimeoutError:
            pass

        # Build countdown message
        draw_dt = parse_draw_datetime()

        if not draw_dt:
            continue

        delta = draw_dt - datetime.now(timezone.utc)
        seconds = delta.total_seconds()

        if seconds <= 0:
            msg = "🎉 MegaWin Draw is happening today!"
        else:
            days = int(seconds // 86400)
            hours = int((seconds % 86400) // 3600)

            if days > 0:
                msg = f"⏳ {days} day(s) left until the next MegaWin draw!"
            else:
                msg = f"⏳ {hours} hour(s) left until the MegaWin draw!"

        await broadcast_message(msg)

    logger.info("Countdown Task Stopped.")


# ==================================
# FASTAPI STARTUP / SHUTDOWN
# ==================================

@app.on_event("startup")
async def on_startup():
    logger.info("🚀 Starting MegaWin Raffle Bot")

    await init_db()
    await set_bot_commands()

    # Set webhook
    try:
        await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
        logger.info(f"✅ Webhook set: {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"Webhook error: {e}")

    # Background tasks
    if background_state["stop"] is None:
        stop_event = asyncio.Event()
        background_state["stop"] = stop_event

        background_state["auto_draw"] = asyncio.create_task(auto_winner_task(stop_event))
        background_state["countdown"] = asyncio.create_task(daily_countdown_task(stop_event))

        logger.info("⏳ Background tasks launched.")


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("🛑 Shutdown...")

    stop_event = background_state.get("stop")
    if stop_event:
        stop_event.set()

    for key in ("auto_draw", "countdown"):
        task = background_state.get(key)
        if task and not task.done():
            task.cancel()

    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except:
        pass

    logger.info("🛑 Shutdown complete.")


# ==================================
# TELEGRAM UPDATE HANDLER
# ==================================

@app.post(TELEGRAM_WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    body = await request.json()
    try:
        update = Update.model_validate(body)
    except:
        update = Update(**body)

    await dp.feed_raw_update(bot, body)
    return {"ok": True}


# ==================================
# ENTRYPOINT — FOR RAILWAY
# ==================================

def start():
    import uvicorn
    uvicorn.run(
        "app.bot:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        log_level="info"
    )
