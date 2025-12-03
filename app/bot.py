# app/bot.py
import os
import asyncio
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.enums import ParseMode
from sqlalchemy import select, insert, delete
from sqlalchemy.exc import NoResultFound

from app.database import async_session, User, Ticket, RaffleEntry, Transaction, Winner
from app.paystack import create_paystack_payment
from app.utils import generate_ticket_code, referral_link, TICKET_PRICE

TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "MegaWinRaffleBot")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@MegaWinRaffle")
ADMINS = [int(x) for x in os.getenv("ADMINS", "622882174").split(",") if x.strip()]

bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()
router = Router()
dp.include_router(router)

def main_menu():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎟 Buy Ticket", callback_data="buy_1")],
        [InlineKeyboardButton(text="📊 My Tickets", callback_data="my_tickets")],
        [
            InlineKeyboardButton(text="👥 Referral", callback_data="referral"),
            InlineKeyboardButton(text="ℹ Help", callback_data="help_btn")
        ],
    ])
    return kb

async def ensure_user(session, telegram_user):
    tg = str(telegram_user.id)
    q = await session.execute(select(User).where(User.telegram_id == tg))
    user = q.scalar_one_or_none()
    if user:
        return user
    await session.execute(insert(User).values(
        telegram_id=tg,
        username=telegram_user.username or "",
        email=f"{tg}@megawin.ng",
        balance=0.0
    ))
    await session.commit()
    q = await session.execute(select(User).where(User.telegram_id == tg))
    return q.scalar_one()

@router.message(Command("start"))
async def start_cmd(msg: Message):
    try:
        await bot.get_chat_member(CHANNEL_USERNAME, msg.from_user.id)
        member_ok = True
    except Exception:
        member_ok = False

    async with async_session() as db:
        await ensure_user(db, msg.from_user)

    welcome_text = (
        "🎉 <b>Welcome to MegaWin Raffle!</b>\n\n"
        "Win exciting prizes by buying raffle tickets. Each ticket costs ₦500.\n\n"
        "How it works:\n"
        "• Buy tickets → each ticket gets a unique code (e.g. #A1Z286)\n"
        "• Admin announces the winner (picked manually using an external tool)\n"
        "• Tickets are reset after each draw\n\n"
        "Use the menu below to get started."
    )

    if not member_ok:
        await msg.answer(
            f"⚠️ Please join our channel to participate and stay updated:\nhttps://t.me/{CHANNEL_USERNAME.lstrip('@')}"
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
        "Admin: /stats /transactions /broadcast /announce_winner /draw_reset"
    )
    await msg.answer(text, reply_markup=main_menu())

@router.callback_query(F.data.startswith("buy"))
async def buy_cb(cb: CallbackQuery):
    data = cb.data
    qty = 1
    if "_" in data:
        try:
            qty = int(data.split("_")[1])
        except:
            qty = 1
    await handle_purchase(cb.message, cb.from_user.id, qty, cb)

@router.message(Command("buy"))
async def buy_cmd(msg: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("Buy 1 (₦500)", callback_data="buy_1")],
        [InlineKeyboardButton("Buy 5 (₦2500)", callback_data="buy_5")],
        [InlineKeyboardButton("Buy 10 (₦5000)", callback_data="buy_10")],
        [InlineKeyboardButton("Custom amount", callback_data="buy_custom")],
    ])
    await msg.answer("Choose number of tickets to buy:", reply_markup=kb)

async def handle_purchase(message, tg_user_id, quantity:int, callback=None):
    amount = TICKET_PRICE * quantity
    email = f"{tg_user_id}@megawin.ng"
    checkout_url, ref = await create_paystack_payment(amount, email)

    codes = []
    async with async_session() as db:
        q = await db.execute(select(User).where(User.telegram_id == str(tg_user_id)))
        user = q.scalar_one_or_none()
        if not user:
            await db.execute(insert(User).values(telegram_id=str(tg_user_id), email=email, username=""))
            await db.commit()
            q = await db.execute(select(User).where(User.telegram_id == str(tg_user_id)))
            user = q.scalar_one()

        await db.execute(insert(RaffleEntry).values(user_id=user.id, reference=ref, amount=amount))
        await db.execute(insert(Transaction).values(user_id=user.id, amount=amount, reference=ref))

        for _ in range(quantity):
            code = generate_ticket_code()
            exists = await db.execute(select(Ticket).where(Ticket.code == code))
            if exists.scalar_one_or_none():
                code = generate_ticket_code()
            await db.execute(insert(Ticket).values(user_id=user.id, code=code))
            codes.append(code)
        await db.commit()

    text = (
        f"🔥 Ticket purchase initiated for ₦{amount:,}.\n"
        f"Complete payment here:\n{checkout_url}\n\n"
        "Your ticket codes (temporary until payment verification):\n" +
        "\n".join(codes)
    )
    if callback:
        await callback.message.answer(text, reply_markup=main_menu())
        await callback.answer()
    else:
        await message.answer(text, reply_markup=main_menu())

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

def is_admin(user_id: int):
    return int(user_id) in ADMINS

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
    if not is_admin(msg.from_user.id):
        return await msg.reply("Unauthorized.")
    async with async_session() as db:
        await db.execute(delete(Ticket))
        await db.commit()
    await msg.answer("✅ All tickets have been reset (deleted).")

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

@router.message()
async def fallback(message: Message):
    await message.answer("Use the menu or /help", reply_markup=main_menu())
