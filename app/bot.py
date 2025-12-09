# app/bot.py
import os
import asyncio
from typing import Optional

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
)
from aiogram.enums import ParseMode

from sqlalchemy import select, insert, delete, update
from sqlalchemy.exc import NoResultFound, SQLAlchemyError
from app.database import async_session, User, Ticket, RaffleEntry, Transaction, Winner

from paystack import create_paystack_payment
from utils import generate_ticket_code, referral_link, TICKET_PRICE

# Config via env
TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "MegaWinRaffleBot")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@MegaWinRaffle")
ADMINS = [int(x) for x in os.getenv("ADMIN_ID", "").split(",") if x.strip()]

# Bot object will be injected at runtime from main.py
bot: Bot  # type: ignore

# router for handlers
router = Router()

# --- Helpers ---
def _is_admin(user_id: int) -> bool:
    try:
        return int(user_id) in ADMINS
    except Exception:
        return False

def main_menu():
    # Build as plain dicts to avoid aiogram/Pydantic positional signature differences
    kb = {
        "inline_keyboard": [
            [{"text": "🎟 Buy Tickets", "callback_data": "open_buy_menu"}],
            [{"text": "📊 My Tickets", "callback_data": "my_tickets"}],
            [
                {"text": "👥 Referral", "callback_data": "referral"},
                {"text": "ℹ Help", "callback_data": "help_btn"},
            ],
        ]
    }
    return kb

def buy_options_menu():
    kb = {
        "inline_keyboard": [
            [
                {"text": "Buy 1 (₦500)", "callback_data": "buy_1"},
                {"text": "Buy 5 (₦2500)", "callback_data": "buy_5"},
            ],
            [
                {"text": "Buy 10 (₦5000)", "callback_data": "buy_10"},
                {"text": "Custom amount", "callback_data": "buy_custom"},
            ],
            [{"text": "⬅ Back", "callback_data": "back_to_main"}],
        ]
    }
    return kb

# --- /start and /help ---
@router.message(Command("start"))
async def start_cmd(msg: Message):
    welcome_text = (
        "🎉 <b>Welcome to MegaWin Raffle!</b>\n\n"
        "Win prizes by buying tickets (₦500 each).\n"
        "Buy multiple tickets, then admins will pick winners manually and announce.\n\n"
        "Use the menu below to get started."
    )
    await msg.answer(welcome_text, reply_markup=main_menu(), parse_mode="HTML")

@router.message(Command("help"))
async def help_cmd(msg: Message):
    text = (
        "ℹ️ <b>Help</b>\n\n"
        "/buy - Buy tickets\n"
        "/tickets - Show your ticket codes\n"
        "/balance - Show balance\n"
        "/referral - Get referral link\n"
        "/userstat - Your stats\n\n"
        "Admin commands:\n"
        "/stats /transactions /broadcast /announce_winner /draw_reset\n"
    )
    await msg.answer(text, reply_markup=main_menu(), parse_mode="HTML")

# --- Buy menu open ---
@router.callback_query(F.data == "open_buy_menu")
async def cb_open_buy(cb: CallbackQuery):
    await cb.message.answer("🎟 Choose how many tickets to buy:", reply_markup=buy_options_menu())
    await cb.answer()

@router.callback_query(F.data == "back_to_main")
async def cb_back(cb: CallbackQuery):
    await cb.message.answer("Main menu:", reply_markup=main_menu())
    await cb.answer()

# --- Handle buy callback (1,5,10,custom) ---
@router.callback_query(F.data.startswith("buy_"))
async def buy_cb(cb: CallbackQuery):
    data = cb.data  # e.g. buy_1 or buy_custom
    parts = data.split("_", 1)
    qty = 1
    if len(parts) > 1 and parts[1].isdigit():
        qty = int(parts[1])
        await initiate_purchase(cb.message, cb.from_user.id, qty, cb)
    elif parts[1] == "custom":
        # ask user for number
        await cb.message.answer("Send the number of tickets you want to buy (e.g. 3):", reply_markup=main_menu())
        await cb.answer()
        # we rely on fallback message handler to accept integer input (see below)
    else:
        await cb.answer()

# --- /buy command (shortcut opens buy menu) ---
@router.message(Command("buy"))
async def buy_cmd(msg: Message):
    await msg.answer("Choose ticket option:", reply_markup=buy_options_menu())

# --- handle numeric message after 'custom' prompt ---
@router.message()
async def numeric_purchase_handler(message: Message):
    # If user sends a plain integer and it's >0, treat as custom buy
    txt = (message.text or "").strip()
    if not txt.isdigit():
        # fallback: ignore other messages (main fallback below)
        return
    qty = int(txt)
    if qty <= 0:
        await message.answer("Please send a positive number.")
        return
    await initiate_purchase(message, message.from_user.id, qty, None)

# --- initiate purchase ---
async def initiate_purchase(message: Message, tg_user_id: int, quantity: int, callback: Optional[CallbackQuery]=None):
    amount = TICKET_PRICE * quantity
    email = f"{tg_user_id}@megawin.ng"

    try:
        checkout_url, ref = await create_paystack_payment(amount, email, tg_user_id=tg_user_id)
    except Exception as e:
        txt = "⚠️ Could not initialize Paystack payment. Try again."
        if callback:
            await callback.message.answer(txt)
            await callback.answer()
        else:
            await message.answer(txt)
        return

    # Save pending raffle entry
    async with async_session() as db:
        q = await db.execute(select(User).where(User.telegram_id == str(tg_user_id)))
        user = q.scalar_one_or_none()
        if not user:
            await db.execute(insert(User).values(telegram_id=str(tg_user_id), username=message.from_user.username or "", email=email))
            await db.commit()
            q = await db.execute(select(User).where(User.telegram_id == str(tg_user_id)))
            user = q.scalar_one()

        await db.execute(insert(RaffleEntry).values(user_id=user.id, reference=ref, amount=amount, quantity=quantity, confirmed=False))
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

# --- tickets / balance / referral / userstat ---
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

# --- Admin commands: stats, transactions, broadcast, announce_winner, draw_reset ---
@router.message(Command("stats"))
async def stats_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
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
    if not _is_admin(msg.from_user.id):
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
    if not _is_admin(msg.from_user.id):
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
    if not _is_admin(msg.from_user.id):
        return await msg.reply("Unauthorized.")
    text = (msg.text or "").strip()
    args = text.split(maxsplit=2)
    if len(args) < 2:
        return await msg.reply("Usage: /announce_winner <TICKET_CODE> [notes]")
    ticket_code = args[1].strip().upper()
    notes = args[2] if len(args) >= 3 else ""
    async with async_session() as db:
        q = await db.execute(select(Ticket).where(Ticket.code == ticket_code))
        ticket = q.scalar_one_or_none()
        if not ticket:
            return await msg.reply("Ticket code not found.")
        await db.execute(insert(Winner).values(ticket_code=ticket_code, user_id=ticket.user_id, announced_by=str(msg.from_user.id), notes=notes))
        await db.commit()
        q = await db.execute(select(User).where(User.id == ticket.user_id))
        user = q.scalar_one()
    announce_text = (
        f"🏆 <b>WINNER ANNOUNCEMENT</b>\n\n"
        f"Winner ticket: <b>{ticket_code}</b>\n"
        f"Winner Telegram: <a href=\"tg://user?id={user.telegram_id}\">{user.username or user.telegram_id}</a>\n\n"
        f"Announced by admin."
    )
    try:
        await bot.send_message(CHANNEL_USERNAME, announce_text, parse_mode="HTML")
    except Exception:
        pass
    try:
        await bot.send_message(int(user.telegram_id), f"🎉 Congratulations! You won with ticket {ticket_code}!\n\nAdmin notes: {notes}")
    except Exception:
        pass
    await msg.reply("Winner announced and logged.", reply_markup=main_menu())

@router.message(Command("draw_reset"))
async def draw_reset_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return await msg.reply("Unauthorized.")
    async with async_session() as db:
        await db.execute(delete(Ticket))
        await db.commit()
    await msg.answer("✅ All tickets have been reset (deleted).")

# Fallback - if message not matched above and not a number-handled by numeric_purchase_handler,
# show menu
@router.message()
async def fallback(message: Message):
    # ignore if message is a digit (handled above)
    txt = (message.text or "").strip()
    if txt.isdigit():
        return
    await message.answer("Use the menu or /help", reply_markup=main_menu())

# Register router safely
def register_handlers(dp: Dispatcher):
    try:
        dp.include_router(router)
    except RuntimeError:
        # router already attached — ignore
        pass
