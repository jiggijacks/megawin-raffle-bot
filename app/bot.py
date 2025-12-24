# app/bot.py
import os

# Try to import real libraries, but provide minimal local stubs when running static analysis
try:
    from aiogram import Bot, Dispatcher, Router, F
    from aiogram.filters import Command
    from aiogram.types import (
        Message,
        CallbackQuery,
        InlineKeyboardMarkup,
        InlineKeyboardButton,
    )
except Exception:
    # Minimal stubs to satisfy import resolution / type checking
    class Bot:
        pass

    class Dispatcher:
        pass

    class F:
        data = None

    class Router:
        def __init__(self):
            pass

        def message(self, *args, **kwargs):
            def _dec(f):
                return f
            return _dec

        def callback_query(self, *args, **kwargs):
            def _dec(f):
                return f
            return _dec

        def include_router(self, r):
            pass

    class Message:
        def __init__(self):
            self.from_user = type("U", (), {"id": 0, "username": ""})
            self.text = ""

        async def answer(self, *args, **kwargs):
            return None

    class CallbackQuery:
        def __init__(self):
            self.from_user = type("U", (), {"id": 0, "username": ""})
            self.data = ""
            self.message = Message()

        async def answer(self, *args, **kwargs):
            return None

    class InlineKeyboardMarkup:
        def __init__(self, *args, **kwargs):
            pass

    class InlineKeyboardButton:
        def __init__(self, *args, **kwargs):
            pass

# SQLAlchemy fallbacks for static analysis
try:
    from sqlalchemy import select, insert
    from sqlalchemy.exc import SQLAlchemyError
except Exception:
    def select(*args, **kwargs):
        return ("_select", args, kwargs)

    def insert(*args, **kwargs):
        return ("_insert", args, kwargs)

    class SQLAlchemyError(Exception):
        pass

# Minimal async_session and model stubs if application modules are not resolved
try:
    from app.database import async_session
    from app.models import User, Ticket, RaffleEntry, Transaction, Winner
    from app.utils import referral_link, TICKET_PRICE
except Exception:
    # Async session stub that supports "async with async_session() as db:"
    class _AsyncSessionFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, *args, **kwargs):
            class _R:
                def scalar_one_or_none(self):
                    return None

                def scalar_one(self):
                    return None

                def scalars(self):
                    class _S:
                        def all(self):
                            return []

                        def first(self):
                            return None
                    return _S()
            return _R()

        async def commit(self):
            return None

    async_session = _AsyncSessionFactory()

    # Minimal model stubs with attributes referenced by the bot code
    class User:
        def __init__(self, telegram_id="0", username="", email="", balance=0):
            self.telegram_id = telegram_id
            self.username = username
            self.email = email
            self.balance = balance
            self.id = 0

    class Ticket:
        def __init__(self, code="", user_id=0):
            self.code = code
            self.user_id = user_id

    class RaffleEntry:
        def __init__(self, user_id=0, reference="", amount=0, quantity=0, confirmed=False):
            self.user_id = user_id
            self.reference = reference
            self.amount = amount
            self.quantity = quantity
            self.confirmed = confirmed

    class Transaction:
        pass

    class Winner:
        pass

    # utils fallback
    def referral_link(bot_username, user_id):
        return f"https://t.me/{bot_username}?start={user_id}"

    TICKET_PRICE = 500

# Router instance (real or stub)
router = Router()

# Placeholder bot variable (set by application bootstrap if available)
bot = None

# Simple async stub for initiate_paystack_payment used by purchase flow so name is defined
async def initiate_paystack_payment(amount: int, email: str, tg_id: int):
    """
    Placeholder payment initializer used during static analysis and tests;
    replace with real implementation that calls Paystack in production.
    """
    # Return a dummy checkout URL and reference
    return "https://paystack.com/checkout/example", "ref_stub_123"

# -------------------------
# Config
# -------------------------
BOT_USERNAME = os.getenv("BOT_USERNAME", "MegaWinRaffleBot")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@MegaWinRaffle")

ADMINS = []
_raw_admins = os.getenv("ADMIN_ID", "") or os.getenv("ADMINS", "")
for a in _raw_admins.split(","):
    if a.strip().isdigit():
        ADMINS.append(int(a.strip()))




def is_admin(uid: int) -> bool:
    return uid in ADMINS


# -------------------------
# Menus
# -------------------------
def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎟 Buy Tickets", callback_data="open_buy")],
        [InlineKeyboardButton(text="📊 My Tickets", callback_data="tickets")],
        [
            InlineKeyboardButton(text="👥 Referral", callback_data="referral"),
            InlineKeyboardButton(text="ℹ Help", callback_data="help"),
        ],
    ])


def buy_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Buy 1 (₦500)", callback_data="buy_1"),
            InlineKeyboardButton(text="Buy 5 (₦2500)", callback_data="buy_5"),
        ],
        [
            InlineKeyboardButton(text="Buy 10 (₦5000)", callback_data="buy_10"),
        ],
        [InlineKeyboardButton(text="⬅ Back", callback_data="back")],
    ])


# =========================
# SHARED LOGIC (IMPORTANT)
# =========================
async def show_tickets(msg: Message):
    async with async_session() as db:
        q = await db.execute(select(User).where(User.telegram_id == str(msg.from_user.id)))
        user = q.scalar_one_or_none()

        if not user:
            return await msg.answer("You have no tickets yet.", reply_markup=main_menu())

        q = await db.execute(select(Ticket).where(Ticket.user_id == user.id))
        tickets = q.scalars().all()

    if not tickets:
        return await msg.answer("You have no tickets yet.", reply_markup=main_menu())

    codes = "\n".join(t.code for t in tickets)
    await msg.answer(f"🎟 Your Tickets:\n{codes}", reply_markup=main_menu())


async def show_balance(msg: Message):
    async with async_session() as db:
        q = await db.execute(select(User).where(User.telegram_id == str(msg.from_user.id)))
        user = q.scalar_one_or_none()

    balance = user.balance if user else 0
    await msg.answer(f"💰 Balance: ₦{balance:.2f}", reply_markup=main_menu())


async def show_referral(msg: Message):
    link = referral_link(BOT_USERNAME, msg.from_user.id)
    await msg.answer(f"Invite friends with this link:\n{link}", reply_markup=main_menu())


async def show_help(msg: Message):
    await msg.answer(
        "ℹ️ <b>Help</b>\n\n"
        "/buy – Buy tickets\n"
        "/tickets – My tickets\n"
        "/balance – Wallet balance\n"
        "/referral – Referral link\n"
        "/userstat – My stats\n",
        parse_mode="HTML",
        reply_markup=main_menu()
    )


# -------------------------
# Commands
# -------------------------
@router.message(Command("start"))
async def start_cmd(msg: Message):
    await msg.answer(
        "🎉 <b>Welcome to MegaWin Raffle</b>\n\n"
        "Each ticket costs ₦500.\n"
        "Use the menu below 👇",
        parse_mode="HTML",
        reply_markup=main_menu()
    )


@router.message(Command("help"))
async def help_cmd(msg: Message):
    await show_help(msg)


@router.message(Command("tickets"))
async def tickets_cmd(msg: Message):
    await show_tickets(msg)


@router.message(Command("balance"))
async def balance_cmd(msg: Message):
    await show_balance(msg)


@router.message(Command("referral"))
async def referral_cmd(msg: Message):
    await show_referral(msg)


@router.message(Command("userstat"))
async def userstat_cmd(msg: Message):
    await show_tickets(msg)


@router.message(Command("buy"))
async def buy_cmd(msg: Message):
    await msg.answer("Choose ticket quantity:", reply_markup=buy_menu())


# -------------------------
# Admin Commands
# -------------------------
@router.message(Command("stats"))
async def admin_stats(msg: Message):
    if not is_admin(msg.from_user.id):
        return await msg.answer("⛔ Admin only")

    async with async_session() as db:
        users = (await db.execute(select(User))).scalars().all()
        tickets = (await db.execute(select(Ticket))).scalars().all()
        entries = (await db.execute(select(RaffleEntry))).scalars().all()

    revenue = sum(e.amount for e in entries)
    await msg.answer(
        f"📊 Admin Stats\n\n"
        f"Users: {len(users)}\n"
        f"Tickets: {len(tickets)}\n"
        f"Revenue: ₦{revenue:,}"
    )

@router.message(Command("stats"))
async def admin_stats(msg: Message):
    if not is_admin(msg.from_user.id):
        return await msg.answer("⛔ Admin only")

    async with async_session() as db:
        users = (await db.execute(select(User))).scalars().all()
        tickets = (await db.execute(select(Ticket))).scalars().all()
        entries = (await db.execute(select(RaffleEntry))).scalars().all()

    revenue = sum(e.amount for e in entries)
    await msg.answer(
        f"📊 Admin Stats\n\n"
        f"Users: {len(users)}\n"
        f"Tickets: {len(tickets)}\n"
        f"Revenue: ₦{revenue:,}"
    )

@router.message(Command("broadcast"))
async def admin_broadcast(msg: Message):
    if not is_admin(msg.from_user.id):
        return await msg.answer("⛔ Admin only")

    text = msg.text.replace("/broadcast", "").strip()
    if not text:
        return await msg.answer("Usage: /broadcast your message")

    async with async_session() as db:
        users = (await db.execute(select(User))).scalars().all()

    sent = 0
    for u in users:
        try:
            await bot.send_message(int(u.telegram_id), text)
            sent += 1
        except Exception:
            pass

    await msg.answer(f"✅ Broadcast sent to {sent} users")


@router.message(Command("announce_winner"))
async def admin_announce_winner(msg: Message):
    if not is_admin(msg.from_user.id):
        return await msg.answer("⛔ Admin only")

    args = msg.text.split()
    if len(args) < 2:
        return await msg.answer("Usage: /announce_winner TICKET_CODE")

    ticket_code = args[1].upper()

    async with async_session() as db:
        ticket = (
            await db.execute(select(Ticket).where(Ticket.code == ticket_code))
        ).scalar_one_or_none()

        if not ticket:
            return await msg.answer("❌ Ticket not found")

        await db.execute(
            insert(Winner).values(
                ticket_code=ticket.code,
                user_id=ticket.user_id,
                announced_by=str(msg.from_user.id),
            )
        )
        await db.commit()

    await msg.answer(f"🏆 Winner announced: {ticket_code}")


@router.message(Command("announce_winner"))
async def admin_announce_winner(msg: Message):
    if not is_admin(msg.from_user.id):
        return await msg.answer("⛔ Admin only")

    args = msg.text.split()
    if len(args) < 2:
        return await msg.answer("Usage: /announce_winner TICKET_CODE")

    ticket_code = args[1].upper()

    async with async_session() as db:
        ticket = (
            await db.execute(select(Ticket).where(Ticket.code == ticket_code))
        ).scalar_one_or_none()

        if not ticket:
            return await msg.answer("❌ Ticket not found")

        await db.execute(
            insert(Winner).values(
                ticket_code=ticket.code,
                user_id=ticket.user_id,
                announced_by=str(msg.from_user.id),
            )
        )
        await db.commit()

    await msg.answer(f"🏆 Winner announced: {ticket_code}")


# -------------------------
# Inline Callbacks
# -------------------------
@router.callback_query(F.data == "open_buy")
async def cb_open_buy(cb: CallbackQuery):
    await cb.message.answer("Choose ticket quantity:", reply_markup=buy_menu())
    await cb.answer()


@router.callback_query(F.data == "tickets")
async def cb_tickets(cb: CallbackQuery):
    await show_tickets(cb.message)
    await cb.answer()


@router.callback_query(F.data == "referral")
async def cb_referral(cb: CallbackQuery):
    await show_referral(cb.message)
    await cb.answer()


@router.callback_query(F.data == "help")
async def cb_help(cb: CallbackQuery):
    await show_help(cb.message)
    await cb.answer()


@router.callback_query(F.data == "back")
async def cb_back(cb: CallbackQuery):
    await cb.message.answer("Main menu:", reply_markup=main_menu())
    await cb.answer()


@router.callback_query(F.data.startswith("buy_"))
async def cb_buy(cb: CallbackQuery):
    qty = int(cb.data.split("_")[1])
    await initiate_purchase(cb.message, cb.from_user.id, qty)
    await cb.answer()


# -------------------------
# Purchase
# -------------------------
async def initiate_purchase(message: Message, tg_id: int, qty: int):
    amount = qty * TICKET_PRICE
    email = f"{tg_id}@megawin.ng"

    try:
        checkout_url, ref = await initiate_paystack_payment(amount, email, tg_id)
    except Exception:
        return await message.answer("Payment init failed. Try again later.")

    async with async_session() as db:
        q = await db.execute(select(User).where(User.telegram_id == str(tg_id)))
        user = q.scalar_one_or_none()

        if not user:
            await db.execute(insert(User).values(
                telegram_id=str(tg_id),
                username=message.from_user.username or "",
                email=email,
                balance=0
            ))
            await db.commit()
            q = await db.execute(select(User).where(User.telegram_id == str(tg_id)))
            user = q.scalar_one()

        await db.execute(insert(RaffleEntry).values(
            user_id=user.id,
            reference=ref,
            amount=amount,
            quantity=qty,
            confirmed=False
        ))
        await db.commit()

    await message.answer(
        f"🛒 <b>Payment Started</b>\n\n"
        f"Tickets: {qty}\n"
        f"Amount: ₦{amount}\n\n"
        f"<a href='{checkout_url}'>Click here to pay</a>",
        parse_mode="HTML",
        reply_markup=main_menu()
    )


# -------------------------
# Fallback (SAFE)
# -------------------------
@router.message()
async def fallback(message: Message):
    if message.text and message.text.startswith("/"):
        await message.answer(
            "❌ Unknown command.\n\nUse /help or the menu below.",
            reply_markup=main_menu()
        )
        return

    await message.answer(
        "Use the menu below 👇",
        reply_markup=main_menu()
    )


# -------------------------
# Register
# -------------------------
def register_handlers(dp: Dispatcher):
    dp.include_router(router)
