# app/bot.py
import os
import random
import string
import logging
from datetime import datetime

import aiohttp
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
    Update,
)
from sqlalchemy import select, func

from app.database import async_session, init_db, User, RaffleEntry

from urllib.parse import urlparse

# =======================
# ENV & CONFIG
# =======================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0")) if os.getenv("ADMIN_ID") else 0
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@MegaWinRaffle")

TELEGRAM_WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL")  # full URL
PAYSTACK_WEBHOOK_URL = os.getenv("PAYSTACK_WEBHOOK_URL")  # full URL
USE_WEBHOOK = os.getenv("USE_WEBHOOK", "true").lower() == "true"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing in environment")

# derive paths from URLs
def extract_path(url: str | None, default_path: str) -> str:
    if not url:
        return default_path
    parsed = urlparse(url)
    return parsed.path or default_path

TELEGRAM_WEBHOOK_PATH = extract_path(TELEGRAM_WEBHOOK_URL, "/webhook/telegram")
PAYSTACK_WEBHOOK_PATH = extract_path(PAYSTACK_WEBHOOK_URL, "/webhook/paystack")

# ticket price (Naira)
TICKET_PRICE = 500
# how many referrals per free ticket
REFERRALS_PER_FREE_TICKET = 5
# affiliate commission per payment (Naira)
AFFILIATE_COMMISSION = 50

# =======================
# LOGGING
# =======================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("MegaWinRaffleBot")


# =======================
# BOT & APP
# =======================

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
app = FastAPI()


# =======================
# HELPERS
# =======================

def generate_ticket_code() -> str:
    """Generate ticket like #A94XQ2."""
    chars = string.ascii_uppercase + string.digits
    return "#" + "".join(random.choices(chars, k=6))


async def get_or_create_user(tg_id: int, username: str | None = None) -> User:
    async with async_session() as session:
        q = await session.execute(select(User).where(User.telegram_id == tg_id))
        user = q.scalar_one_or_none()

        if user:
            if username and user.username != username:
                user.username = username
                await session.commit()
            return user

        user = User(
            telegram_id=tg_id,
            username=username,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def user_in_required_channel(user_id: int) -> bool:
    """Check if user joined REQUIRED_CHANNEL."""
    if not REQUIRED_CHANNEL or REQUIRED_CHANNEL == "none":
        return True  # no channel requirement

    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.warning(f"Channel check failed: {e}")
        return False


async def set_bot_commands():
    commands = [
        BotCommand(command="start", description="Start / referral link"),
        BotCommand(command="help", description="How to use the bot"),
        BotCommand(command="buy", description="Buy a raffle ticket"),
        BotCommand(command="ticket", description="View your tickets"),
        BotCommand(command="balance", description="Check your balance"),
        BotCommand(command="referrals", description="Your referrals"),
        BotCommand(command="affiliate", description="Affiliate dashboard"),
        BotCommand(command="leaderboard", description="Top users (admin)"),
    ]
    await bot.set_my_commands(commands)


# =======================
# BASIC ROUTES (FastAPI)
# =======================

@app.get("/")
async def root():
    return {"status": "ok", "message": "MegaWin Raffle bot server running"}


@app.get("/health")
async def health():
    return {"status": "ok"}


# =======================
# COMMAND HANDLERS
# =======================

# /start — join check + referral + affiliate
async def cmd_start(message: Message):
    tg_id = message.from_user.id
    username = message.from_user.username

    # 1. Channel check
    if not await user_in_required_channel(tg_id):
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📢 Join Channel",
                        url=f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="✅ I Joined",
                        callback_data="check_joined",
                    )
                ],
            ]
        )
        await message.answer(
            "<b>❗ You must join our channel to use this bot.</b>\n\n"
            f"👉 <b>{REQUIRED_CHANNEL}</b>\n\n"
            "After joining, tap <b>I Joined</b>.",
            reply_markup=kb,
        )
        return

    # 2. Get or create user
    user = await get_or_create_user(tg_id, username)

    # 3. Handle start payload
    args = message.text.split()
    if len(args) > 1:
        payload = args[1]

        async with async_session() as session:
            # Reload user from session
            q = await session.execute(select(User).where(User.telegram_id == tg_id))
            user = q.scalar_one_or_none()
            if not user:
                user = User(telegram_id=tg_id, username=username)
                session.add(user)
                await session.commit()
                await session.refresh(user)

            # Affiliate link? e.g. "aff622882174"
            if payload.startswith("aff"):
                aff_code = payload
                q_aff = await session.execute(
                    select(User).where(User.affiliate_code == aff_code)
                )
                affiliate = q_aff.scalar_one_or_none()
                if affiliate and affiliate.id != user.id:
                    user.affiliate_id = affiliate.id
                    await session.commit()

            else:
                # Referral by telegram_id, avoid self-ref
                try:
                    ref_tg_id = int(payload)
                    if ref_tg_id != tg_id and not user.referred_by:
                        user.referred_by = ref_tg_id
                        await session.commit()
                except ValueError:
                    pass

    # 4. Main menu buttons
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎟 Buy Ticket", callback_data="buy_ticket")],
            [InlineKeyboardButton(text="🎫 My Tickets", callback_data="view_tickets")],
            [InlineKeyboardButton(text="💰 My Balance", callback_data="view_balance")],
            [InlineKeyboardButton(text="👥 Referrals", callback_data="my_referrals")],
            [InlineKeyboardButton(text="💼 Affiliate", callback_data="view_affiliate")],
            [InlineKeyboardButton(text="❓ Help", callback_data="help_cmd")],
        ]
    )

    ref_link = f"https://t.me/{(await bot.get_me()).username}?start={tg_id}"

    await message.answer(
        "🎉 <b>Welcome to MegaWin Raffle!</b>\n\n"
        "Buy tickets, invite friends and stand a chance to win big prizes.\n\n"
        "Your referral link:\n"
        f"<code>{ref_link}</code>",
        reply_markup=kb,
    )


dp.message.register(cmd_start, F.text.startswith("/start"))


# /help
async def cmd_help(message: Message):
    await message.answer(
        "💡 <b>How to use MegaWin Raffle</b>\n\n"
        f"• Each ticket costs ₦{TICKET_PRICE}\n"
        f"• Every {REFERRALS_PER_FREE_TICKET} referrals = 1 free ticket\n"
        "• Affiliates earn ₦50 per paid ticket\n\n"
        "Commands:\n"
        "• /buy — Buy a raffle ticket\n"
        "• /ticket — View your tickets\n"
        "• /balance — Check your balance\n"
        "• /referrals — Your referral link\n"
        "• /affiliate — Affiliate dashboard\n"
    )


dp.message.register(cmd_help, F.text == "/help")


# /buy — initialize payment
async def cmd_buy(message: Message):
    if not PAYSTACK_SECRET_KEY or not PAYSTACK_WEBHOOK_URL:
        return await message.answer("❌ Payment is not configured. Please try again later.")

    tg_id = message.from_user.id
    await get_or_create_user(tg_id, message.from_user.username)

    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
        payload = {
            "email": f"user_{tg_id}@megawinraffle.com",
            "amount": TICKET_PRICE * 100,  # kobo
            "metadata": {
                "telegram_id": tg_id,
            },
            "callback_url": PAYSTACK_WEBHOOK_URL,  # not required but ok
        }

        async with session.post(
            "https://api.paystack.co/transaction/initialize",
            json=payload,
            headers=headers,
        ) as resp:
            data = await resp.json()

    if not data.get("status"):
        logger.error(f"Paystack init failed: {data}")
        return await message.answer("❌ Payment initialization failed. Please try again.")

    auth_url = data["data"]["authorization_url"]

    await message.answer(
        f"<b>💳 Ticket Price: ₦{TICKET_PRICE}</b>\n\n"
        f"Tap below to pay securely with Paystack:\n"
        f"<a href='{auth_url}'>Pay ₦{TICKET_PRICE} via Paystack</a>"
    )


dp.message.register(cmd_buy, F.text == "/buy")


# /ticket — view tickets
async def cmd_ticket(message: Message):
    tg_id = message.from_user.id

    async with async_session() as session:
        q_user = await session.execute(select(User).where(User.telegram_id == tg_id))
        user = q_user.scalar_one_or_none()

        if not user:
            return await message.answer("🚫 No account found. Use /start first.")

        q_tickets = await session.execute(
            select(RaffleEntry).where(RaffleEntry.user_id == user.id).order_by(
                RaffleEntry.created_at.desc()
            )
        )
        tickets = q_tickets.scalars().all()

    if not tickets:
        return await message.answer("You have no tickets yet.\nUse /buy to get your first ticket.")

    lines = []
    for t in tickets:
        tag = "🎁 Free" if t.is_free else "💵 Paid"
        dt_str = t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else "-"
        lines.append(f"{t.ticket_code} • {tag} • {dt_str}")

    await message.answer("🎫 <b>Your Tickets</b>\n\n" + "\n".join(lines))


dp.message.register(cmd_ticket, F.text == "/ticket")


# /balance — no negative
async def cmd_balance(message: Message):
    tg_id = message.from_user.id

    async with async_session() as session:
        q_user = await session.execute(select(User).where(User.telegram_id == tg_id))
        user = q_user.scalar_one_or_none()

        if not user:
            return await message.answer("No history available yet.")

        q_tickets = await session.execute(
            select(RaffleEntry).where(RaffleEntry.user_id == user.id)
        )
        tickets = q_tickets.scalars().all()

    paid = len([t for t in tickets if not t.is_free])
    free = len([t for t in tickets if t.is_free])

    spent = paid * TICKET_PRICE
    value_free = free * TICKET_PRICE

    # Never show negative balance
    net_value = max(0, value_free - spent)

    await message.answer(
        "💰 <b>Your Balance</b>\n\n"
        f"Paid Tickets: {paid} (₦{spent})\n"
        f"Free Tickets: {free} (₦{value_free})\n\n"
        f"Reward Balance (non-negative): <b>₦{net_value}</b>"
    )


dp.message.register(cmd_balance, F.text == "/balance")


# /referrals
async def cmd_referrals(message: Message):
    tg_id = message.from_user.id

    async with async_session() as session:
        q_user = await session.execute(select(User).where(User.telegram_id == tg_id))
        user = q_user.scalar_one_or_none()

    ref_link = f"https://t.me/{(await bot.get_me()).username}?start={tg_id}"

    total_refs = user.total_referrals if user else 0

    await message.answer(
        f"👥 <b>Your Referrals</b>\n\n"
        f"Total successful referrals: <b>{total_refs}</b>\n\n"
        "Share this link with friends:\n"
        f"<code>{ref_link}</code>\n\n"
        f"Every {REFERRALS_PER_FREE_TICKET} referrals = 1 free ticket."
    )


dp.message.register(cmd_referrals, F.text == "/referrals")


# /affiliate
async def cmd_affiliate(message: Message):
    tg_id = message.from_user.id

    async with async_session() as session:
        q_user = await session.execute(select(User).where(User.telegram_id == tg_id))
        user = q_user.scalar_one_or_none()

        if not user:
            user = User(telegram_id=tg_id, username=message.from_user.username)
            session.add(user)
            await session.commit()
            await session.refresh(user)

        if not user.affiliate_code:
            user.affiliate_code = f"aff{tg_id}"
            await session.commit()
            await session.refresh(user)

    aff_link = f"https://t.me/{(await bot.get_me()).username}?start={user.affiliate_code}"

    await message.answer(
        "💼 <b>Affiliate Dashboard</b>\n\n"
        f"Affiliate code: <code>{user.affiliate_code}</code>\n"
        f"Affiliate link:\n<code>{aff_link}</code>\n\n"
        f"Commission balance: <b>₦{user.commission_balance}</b>\n"
        f"Earn ₦{AFFILIATE_COMMISSION} for every paid ticket via your link."
    )


dp.message.register(cmd_affiliate, F.text == "/affiliate")


# /leaderboard (admin only)
async def cmd_leaderboard(message: Message):
    if message.from_user.id != ADMIN_ID:
        return await message.answer("🚫 Admins only.")

    async with async_session() as session:
        # Top referrers
        q_ref = await session.execute(
            select(User).order_by(User.total_referrals.desc()).limit(10)
        )
        top_referrers = q_ref.scalars().all()

        # Top buyers
        q_buy = await session.execute(
            select(User, func.count(RaffleEntry.id).label("tickets_count"))
            .join(RaffleEntry, RaffleEntry.user_id == User.id)
            .group_by(User.id)
            .order_by(func.count(RaffleEntry.id).desc())
            .limit(10)
        )
        top_buyers_data = q_buy.all()

    text = "🏆 <b>Leaderboard</b>\n\n<b>Top Referrers:</b>\n"
    if not top_referrers:
        text += "No referrals yet.\n"
    else:
        for i, u in enumerate(top_referrers, start=1):
            uname = f"@{u.username}" if u.username else str(u.telegram_id)
            text += f"{i}. {uname} — {u.total_referrals} referrals\n"

    text += "\n<b>Top Buyers:</b>\n"
    if not top_buyers_data:
        text += "No tickets purchased yet.\n"
    else:
        for i, (u, count) in enumerate(top_buyers_data, start=1):
            uname = f"@{u.username}" if u.username else str(u.telegram_id)
            text += f"{i}. {uname} — {count} tickets\n"

    await message.answer(text)


dp.message.register(cmd_leaderboard, F.text == "/leaderboard")


# =======================
# CALLBACK HANDLERS
# =======================

async def cb_check_joined(callback: CallbackQuery):
    if await user_in_required_channel(callback.from_user.id):
        await callback.message.edit_text("✅ You have joined! Now send /start again.")
    else:
        await callback.answer("❗ You still haven't joined the channel.", show_alert=True)


dp.callback_query.register(cb_check_joined, F.data == "check_joined")


async def cb_buy_ticket(callback: CallbackQuery):
    await cmd_buy(callback.message)
    await callback.answer()


dp.callback_query.register(cb_buy_ticket, F.data == "buy_ticket")


async def cb_view_tickets(callback: CallbackQuery):
    await cmd_ticket(callback.message)
    await callback.answer()


dp.callback_query.register(cb_view_tickets, F.data == "view_tickets")


async def cb_view_balance(callback: CallbackQuery):
    await cmd_balance(callback.message)
    await callback.answer()


dp.callback_query.register(cb_view_balance, F.data == "view_balance")


async def cb_my_referrals(callback: CallbackQuery):
    await cmd_referrals(callback.message)
    await callback.answer()


dp.callback_query.register(cb_my_referrals, F.data == "my_referrals")


async def cb_view_affiliate(callback: CallbackQuery):
    await cmd_affiliate(callback.message)
    await callback.answer()


dp.callback_query.register(cb_view_affiliate, F.data == "view_affiliate")


async def cb_help_cmd(callback: CallbackQuery):
    await cmd_help(callback.message)
    await callback.answer()


dp.callback_query.register(cb_help_cmd, F.data == "help_cmd")


# =======================
# PAYSTACK WEBHOOK
# =======================

@app.post(PAYSTACK_WEBHOOK_PATH)
async def paystack_webhook(request: Request):
    """Handle Paystack charge.success events."""
    try:
        payload = await request.json()
        event = payload.get("event", "")
        data = payload.get("data", {})

        logger.info(f"🔔 Paystack event: {event}")

        if event != "charge.success":
            return JSONResponse({"status": "ignored"})

        if data.get("status") != "success":
            return JSONResponse({"status": "ignored"})

        metadata = data.get("metadata", {}) or {}
        tg_id = metadata.get("telegram_id")
        reference = data.get("reference")
        amount_kobo = data.get("amount") or 0
        amount_naira = int(amount_kobo / 100)

        if not tg_id or not reference:
            return JSONResponse({"status": "error", "message": "Missing telegram_id or reference"})

        tg_id = int(tg_id)

        async with async_session() as session:
            # get user
            q_user = await session.execute(select(User).where(User.telegram_id == tg_id))
            user = q_user.scalar_one_or_none()
            if not user:
                user = User(telegram_id=tg_id)
                session.add(user)
                await session.commit()
                await session.refresh(user)

            # duplicate check
            q_dup = await session.execute(
                select(RaffleEntry).where(RaffleEntry.payment_ref == reference)
            )
            if q_dup.scalar_one_or_none():
                return JSONResponse({"status": "duplicate"})

            # number of tickets = amount / price
            tickets_count = max(1, amount_naira // TICKET_PRICE)

            for _ in range(tickets_count):
                entry = RaffleEntry(
                    user_id=user.id,
                    ticket_code=generate_ticket_code(),
                    is_free=False,
                    amount_paid=TICKET_PRICE,
                    payment_ref=reference,
                )
                session.add(entry)

            # REFERRAL → every 5 paid = 1 free
            if user.referred_by:
                q_ref = await session.execute(
                    select(User).where(User.telegram_id == user.referred_by)
                )
                referrer = q_ref.scalar_one_or_none()
                if referrer:
                    referrer.total_referrals = (referrer.total_referrals or 0) + tickets_count
                    referrer.referral_progress = (referrer.referral_progress or 0) + tickets_count

                    while referrer.referral_progress >= REFERRALS_PER_FREE_TICKET:
                        referrer.referral_progress -= REFERRALS_PER_FREE_TICKET
                        free_ticket = RaffleEntry(
                            user_id=referrer.id,
                            ticket_code=generate_ticket_code(),
                            is_free=True,
                            amount_paid=0,
                            payment_ref=f"ref_bonus_{referrer.id}_{datetime.utcnow().timestamp()}",
                        )
                        session.add(free_ticket)

                        try:
                            await bot.send_message(
                                referrer.telegram_id,
                                "🎉 You earned a FREE ticket for your referrals!",
                            )
                        except Exception:
                            pass

            # AFFILIATE commission
            if user.affiliate_id:
                q_aff = await session.execute(
                    select(User).where(User.id == user.affiliate_id)
                )
                affiliate = q_aff.scalar_one_or_none()
                if affiliate:
                    affiliate.commission_balance = (affiliate.commission_balance or 0) + (
                        AFFILIATE_COMMISSION * tickets_count
                    )

                    try:
                        await bot.send_message(
                            affiliate.telegram_id,
                            f"💸 You earned ₦{AFFILIATE_COMMISSION * tickets_count} "
                            "from your affiliate link!",
                        )
                    except Exception:
                        pass

            await session.commit()

        # Notify buyer
        try:
            await bot.send_message(
                tg_id,
                f"✅ Payment confirmed!\n\n"
                f"🎟 You received <b>{tickets_count}</b> ticket(s).\n"
                "Use /ticket to view your tickets.",
            )
        except Exception as e:
            logger.warning(f"Failed to notify user after payment: {e}")

        return JSONResponse({"status": "ok"})

    except Exception as e:
        logger.exception(f"Paystack webhook error: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# =======================
# TELEGRAM WEBHOOK HANDLER
# =======================

@app.post(TELEGRAM_WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return {"ok": True}


# =======================
# FASTAPI STARTUP / SHUTDOWN
# =======================

@app.on_event("startup")
async def on_startup():
    logger.info("🚀 Starting MegaWin Raffle Bot (webhook mode)")
    await init_db()
    await set_bot_commands()

    if USE_WEBHOOK and TELEGRAM_WEBHOOK_URL:
        try:
            await bot.set_webhook(TELEGRAM_WEBHOOK_URL, drop_pending_updates=True)
            logger.info(f"✅ Telegram webhook set: {TELEGRAM_WEBHOOK_URL}")
        except Exception as e:
            logger.error(f"Failed to set webhook: {e}")


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("🛑 Shutting down…")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logger.warning(f"Failed to delete webhook: {e}")
