# app/bot.py
import os
import asyncio
from typing import Optional, List

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from aiogram.enums import ParseMode

from sqlalchemy import select, insert, delete
from sqlalchemy.exc import NoResultFound, SQLAlchemyError
from app.database import async_session, User, Ticket, RaffleEntry

from app.paystack import create_paystack_payment
from app.utils import generate_ticket_code, referral_link, TICKET_PRICE

# Config via env
TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "MegaWinRaffleBot")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@MegaWinRaffle")  # ensure leading @
ADMINS = [int(x) for x in os.getenv("ADMINS", "622882174").split(",") if x.strip()]

# Bot & dispatcher
bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# -------------------------
# Helpers
# -------------------------
def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎟 Buy Ticket", callback_data="buy_1")],
        [InlineKeyboardButton(text="📊 My Tickets", callback_data="my_tickets")],
        [
            InlineKeyboardButton(text="👥 Referral", callback_data="referral"),
            InlineKeyboardButton(text="ℹ Help", callback_data="help_btn")
        ],
    ])
    return kb

async def ensure_user(session, telegram_user) -> User:
    """Return User row for the given telegram_user (create if missing)."""
    tg = str(telegram_user.id)
    q = await session.execute(select(User).where(User.telegram_id == tg))
    user = q.scalar_one_or_none()
    if user:
        return user

    await session.execute(
        insert(User).values(
            telegram_id=tg,
            username=telegram_user.username or "",
            email=f"{tg}@megawin.ng",
            balance=0.0,
        )
    )
    await session.commit()
    q = await session.execute(select(User).where(User.telegram_id == tg))
    return q.scalar_one()

def is_admin(user_id: int) -> bool:
    try:
        return int(user_id) in ADMINS
    except Exception:
        return False

# -------------------------
# Commands: /start, /help
# -------------------------
@router.message(Command("start"))
async def start_cmd(msg: Message):
    # Check channel membership (best-effort)
    member_ok = True
    if CHANNEL_USERNAME:
        try:
            await bot.get_chat_member(CHANNEL_USERNAME, msg.from_user.id)
        except Exception:
            member_ok = False

    async with async_session() as db:
        await ensure_user(db, msg.from_user)

    welcome_text = (
        "🎉 <b>Welcome to MegaWin Raffle!</b>\n\n"
        "Win exciting prizes by buying raffle tickets. Each ticket costs ₦500.\n\n"
        "How it works:\n"
        "• Buy tickets → each ticket gets a unique code (e.g. #A1Z286)\n"
        "• Admin will announce the winner (picked manually using a 3rd-party tool)\n"
        "• Tickets are reset after each draw\n\n"
        "Use the menu below to get started."
    )

    if not member_ok and CHANNEL_USERNAME:
        await msg.answer(
            f"⚠️ Please join our channel to participate and stay updated:\n"
            f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"
        )

    await msg.answer(welcome_text, reply_markup=main_menu())

@router.message(Command("help"))
async def help_cmd(msg: Message):
    text = (
        "ℹ️ <b>Help</b>\n\n"
        "/buy - Buy tickets\n"
        "/tickets - Show your ticket codes\n"
        "/balance - Show balance\n"
        "/referral - Get referral link\n"
        "/userstat - Your stats\n\n"
        "Admin commands (admins only):\n"
        "/stats - Overview\n"
        "/transactions - Latest transactions\n"
        "/broadcast <message> - Send message to users\n"
        "/announce_winner <TICKET_CODE> [notes] - Announce manual winner\n"
        "/draw_reset - Clear tickets after a draw\n"
    )
    await msg.answer(text, reply_markup=main_menu())

# -------------------------
# Purchase flow (inline + command)
# -------------------------
@router.callback_query(F.data.startswith("buy"))
async def buy_cb(cb: CallbackQuery):
    # callback data like buy_1 or buy_5
    qty = 1
    try:
        parts = cb.data.split("_")
        if len(parts) == 2:
            qty = int(parts[1])
    except Exception:
        qty = 1
    await handle_purchase(cb.message, cb.from_user.id, qty, cb)

# --------------------------
# BUY INLINE BUTTON HANDLER
# --------------------------
@router.callback_query(F.data.startswith("buy"))
async def buy_cb(cb: CallbackQuery):
    """
    Handles buy_1, buy_5, buy_10, buy_custom
    """
    parts = cb.data.split("_")
    qty = 1

    if len(parts) == 2 and parts[1].isdigit():
        qty = int(parts[1])

    await initiate_purchase(cb.message, cb.from_user.id, qty, cb)


# --------------------------
# /buy COMMAND
# --------------------------
@router.message(Command("buy"))
async def buy_cmd(msg: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("Buy 1 (₦500)", callback_data="buy_1")],
        [InlineKeyboardButton("Buy 5 (₦2500)", callback_data="buy_5")],
        [InlineKeyboardButton("Buy 10 (₦5000)", callback_data="buy_10")],
        [InlineKeyboardButton("Custom amount", callback_data="buy_custom")],
    ])
    await msg.answer("🎟 How many tickets do you want to buy?", reply_markup=kb)


# --------------------------
# PURCHASE INITIATION FUNCTION
# --------------------------
async def initiate_purchase(
    message: Message,
    tg_user_id: int,
    quantity: int,
    callback: Optional[CallbackQuery] = None
):
    """
    Create Paystack checkout.
    IMPORTANT:
    - NO tickets are created here.
    - Only a RaffleEntry is stored.
    - Tickets will be created after Paystack webhook confirms payment.
    """
    amount = TICKET_PRICE * quantity
    email = f"{tg_user_id}@megawin.ng"

    # Create Paystack session
    try:
        checkout_url, ref = await create_paystack_payment(amount, email)
    except Exception:
        txt = "⚠️ Could not initialize Paystack payment. Try again."
        if callback:
            await callback.message.answer(txt)
            await callback.answer()
        else:
            await message.answer(txt)
        return

    # Save reference (no ticket yet)
    async with async_session() as db:
        # ensure user exists
        q = await db.execute(select(User).where(User.telegram_id == str(tg_user_id)))
        user = q.scalar_one_or_none()

        if not user:
            await db.execute(insert(User).values(
                telegram_id=str(tg_user_id),
                username="",
                email=email,
                balance=0.0,
            ))
            await db.commit()
            q = await db.execute(select(User).where(User.telegram_id == str(tg_user_id)))
            user = q.scalar_one()

        # create pending purchase record
        await db.execute(insert(RaffleEntry).values(
            user_id=user.id,
            reference=ref,
            amount=amount,
            quantity=quantity,
        ))

        await db.commit()

    txt = (
        f"🛒 <b>Ticket Purchase Started!</b>\n\n"
        f"Amount: ₦{amount:,}\n"
        f"Tickets: {quantity}\n\n"
        f"<a href='{checkout_url}'>Click here to complete payment</a>\n\n"
        "🎫 Your tickets will be issued automatically once Paystack confirms your payment."
    )

    if callback:
        await callback.message.answer(txt, parse_mode="HTML", reply_markup=main_menu())
        await callback.answer()
    else:
        await message.answer(txt, parse_mode="HTML", reply_markup=main_menu())


# -------------------------
# /tickets /balance /referral /userstat
# -------------------------
@router.message(Command("tickets"))
async def tickets_cmd(msg: Message):
    async with async_session() as db:
        q = await db.execute(select(User).where(User.telegram_id == str(msg.from_user.id)))
        user = q.scalar_one_or_none()
        if not user:
            return await msg.answer("You have no tickets. Use /buy to purchase.", reply_markup=main_menu())
        q = await db.execute(select(Ticket).where(Ticket.user_id == user.id))
        rows = q.scalars().all()
        if not rows:
            return await msg.answer("You have no tickets. Use /buy to purchase.", reply_markup=main_menu())
        codes = [r.code for r in rows]
        await msg.answer("🎟️ Your tickets:\n" + "\n".join(codes), reply_markup=main_menu())

@router.message(Command("balance"))
async def balance_cmd(msg: Message):
    async with async_session() as db:
        q = await db.execute(select(User).where(User.telegram_id == str(msg.from_user.id)))
        user = q.scalar_one_or_none()
        bal = user.balance if user else 0.0
        await msg.answer(f"💰 Balance: ₦{bal:.2f}", reply_markup=main_menu())

@router.message(Command("referral"))
async def ref_cmd(msg: Message):
    link = referral_link(BOT_USERNAME, msg.from_user.id)
    await msg.answer(f"Share this link to invite friends:\n{link}", reply_markup=main_menu())

@router.message(Command("userstat"))
async def userstat_cmd(msg: Message):
    async with async_session() as db:
        q = await db.execute(select(User).where(User.telegram_id == str(msg.from_user.id)))
        user = q.scalar_one_or_none()
        if not user:
            return await msg.answer("No stats yet.", reply_markup=main_menu())
        q = await db.execute(select(Ticket).where(Ticket.user_id == user.id))
        tcount = len(q.scalars().all())
        await msg.answer(f"📊 Your stats:\nTickets: {tcount}\nJoined: {user.created_at}", reply_markup=main_menu())

# -------------------------
# Admin commands
# -------------------------
@router.message(Command("stats"))
async def stats_cmd(msg: Message):
    if not is_admin(msg.from_user.id):
        return await msg.reply("Unauthorized.")
    async with async_session() as db:
        q = await db.execute(select(User))
        total_users = len(q.scalars().all())
        q = await db.execute(select(Ticket))
        total_tickets = len(q.scalars().all())
        q = await db.execute(select(RaffleEntry))
        total_revenue = sum([r.amount for r in q.scalars().all()])
    await msg.answer(f"📈 Stats:\nUsers: {total_users}\nTickets: {total_tickets}\nRevenue: ₦{total_revenue:.2f}")

@router.message(Command("transactions"))
async def transactions_cmd(msg: Message):
    if not is_admin(msg.from_user.id):
        return await msg.reply("Unauthorized.")
    async with async_session() as db:
        q = await db.execute(select(Transaction).order_by(Transaction.created_at.desc()).limit(20))
        rows = q.scalars().all()
    if not rows:
        return await msg.answer("No transactions yet.")
    out = []
    for r in rows:
        out.append(f"{r.created_at.date()} | user_id={r.user_id} | ₦{r.amount} | ref={r.reference}")
    await msg.answer("Recent transactions:\n" + "\n".join(out))

@router.message(Command("broadcast"))
async def broadcast_cmd(msg: Message):
    if not is_admin(msg.from_user.id):
        return await msg.reply("Unauthorized.")
    text = msg.text.partition(" ")[2].strip()
    if not text:
        return await msg.reply("Usage: /broadcast <message>")
    async with async_session() as db:
        q = await db.execute(select(User))
        users = q.scalars().all()
    sent = 0
    for u in users:
        try:
            await bot.send_message(int(u.telegram_id), f"📣 Broadcast:\n\n{text}")
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            continue
    await msg.answer(f"Broadcast sent to {sent} users.")

@router.message(Command("announce_winner"))
async def announce_winner_cmd(msg: Message):
    """
    Usage: /announce_winner <TICKET_CODE> [optional notes]
    Admin manually picks winner using external tool then runs this to announce.
    """
    if not is_admin(msg.from_user.id):
        return await msg.reply("Unauthorized.")
    args = msg.text.split(maxsplit=2)
    if len(args) < 2:
        return await msg.reply("Usage: /announce_winner <TICKET_CODE> [notes]")
    ticket_code = args[1].strip().upper()
    notes = args[2] if len(args) > 2 else ""
    async with async_session() as db:
        q = await db.execute(select(Ticket).where(Ticket.code == ticket_code))
        ticket = q.scalar_one_or_none()
        if not ticket:
            return await msg.reply("Ticket code not found.")
        # log winner
        await db.execute(insert(Winner).values(ticket_code=ticket.code, user_id=ticket.user_id, announced_by=str(msg.from_user.id), notes=notes))
        await db.commit()
        q = await db.execute(select(User).where(User.id == ticket.user_id))
        user = q.scalar_one()
    announce_text = (
        f"🏆 <b>WINNER ANNOUNCEMENT</b>\n\n"
        f"Winner ticket: <b>{ticket_code}</b>\n"
        f"Winner Telegram: <a href=\"tg://user?id={user.telegram_id}\">{user.username or user.telegram_id}</a>\n\n"
        f"Announced by admin.\n\nTransparency: each draw is handled manually and logged."
    )
    # try announce in channel
    try:
        await bot.send_message(CHANNEL_USERNAME, announce_text, parse_mode="HTML")
    except Exception:
        pass
    # DM winner
    try:
        await bot.send_message(int(user.telegram_id), f"🎉 Congratulations! You won with ticket {ticket_code}!\n\nAdmin notes: {notes}")
    except Exception:
        pass

    await msg.reply("Winner announced and logged.", reply_markup=main_menu())

@router.message(Command("draw_reset"))
async def draw_reset_cmd(msg: Message):
    """Admin command to wipe all ticket rows (after draw)."""
    if not is_admin(msg.from_user.id):
        return await msg.reply("Unauthorized.")
    async with async_session() as db:
        await db.execute(delete(Ticket))
        await db.commit()
    await msg.answer("✅ All tickets have been reset (deleted).")

# -------------------------
# Inline callbacks: my_tickets, referral, help
# -------------------------
@router.callback_query(F.data == "my_tickets")
async def cb_my_tickets(cb: CallbackQuery):
    await tickets_cmd(cb.message)

@router.callback_query(F.data == "referral")
async def cb_referral(cb: CallbackQuery):
    link = referral_link(BOT_USERNAME, cb.from_user.id)
    await cb.message.answer(f"Share this link to invite friends:\n{link}", reply_markup=main_menu())
    await cb.answer()

@router.callback_query(F.data == "help_btn")
async def cb_help(cb: CallbackQuery):
    await help_cmd(cb.message)
    await cb.answer()

# -------------------------
# Fallback
# -------------------------
@router.message()
async def fallback(message: Message):
    await message.answer("Use the menu or /help", reply_markup=main_menu())
