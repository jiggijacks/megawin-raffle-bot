# app/bot.py
import os
import asyncio
from typing import Optional

from aiogram import Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from aiogram.enums import ParseMode

from sqlalchemy import select, insert, delete, update
from app.database import async_session, User, Ticket, RaffleEntry, Transaction, Winner

from app.paystack import create_paystack_payment
from app.utils import generate_ticket_code, referral_link, TICKET_PRICE

# module-level bot is set from main.py at startup:
# `import app.bot as bot_module; bot_module.bot = Bot(...)`
bot = None  # type: ignore

router = Router()

# config from env
BOT_USERNAME = os.getenv("BOT_USERNAME", "MegaWinRaffleBot")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@MegaWinRaffle")
ADMINS = [int(x) for x in os.getenv("ADMINS", os.getenv("ADMIN_ID", "622882174")).split(",") if x.strip()]


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


@router.message(Command("start"))
async def start_cmd(msg: Message):
    # best-effort channel check
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
        "Each ticket costs ₦500. Buy tickets, get random ticket codes (e.g. #A1Z286).\n"
        "Admin picks winners manually and announces them for transparency.\n\n"
        "Use the menu below to get started."
    )

    if not member_ok and CHANNEL_USERNAME:
        await msg.answer(
            f"⚠️ Please join our channel: https://t.me/{CHANNEL_USERNAME.lstrip('@')}"
        )

    await msg.answer(welcome_text, reply_markup=main_menu())


@router.message(Command("help"))
async def help_cmd(msg: Message):
    text = (
        "ℹ️ /help\n\n"
        "/buy — Buy tickets\n"
        "/tickets — Show your ticket codes\n"
        "/balance — Show balance\n"
        "/referral — Get referral link\n"
        "/userstat — Show your stats\n\n"
        "Admin:\n"
        "/stats — Overview\n"
        "/transactions — Latest transactions\n"
        "/broadcast <message> — Broadcast to users\n"
        "/announce_winner <TICKET_CODE> [notes] — Announce winner (manual)\n"
        "/draw_reset — Reset tickets after draw\n"
    )
    await msg.answer(text, reply_markup=main_menu())


# BUY handlers (one callback + /buy)
@router.callback_query(F.data.startswith("buy"))
async def buy_cb(cb: CallbackQuery):
    parts = cb.data.split("_")
    qty = 1
    if len(parts) == 2 and parts[1].isdigit():
        qty = int(parts[1])
    await initiate_purchase(cb.message, cb.from_user.id, qty, cb)


@router.message(Command("buy"))
async def buy_cmd(msg: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("Buy 1 (₦500)", callback_data="buy_1")],
        [InlineKeyboardButton("Buy 5 (₦2500)", callback_data="buy_5")],
        [InlineKeyboardButton("Buy 10 (₦5000)", callback_data="buy_10")],
        [InlineKeyboardButton("Custom amount", callback_data="buy_custom")],
    ])
    await msg.answer("🎟 How many tickets do you want?", reply_markup=kb)


async def initiate_purchase(
    message: Message,
    tg_user_id: int,
    quantity: int,
    callback: Optional[CallbackQuery] = None
):
    amount = TICKET_PRICE * max(1, int(quantity))
    email = f"{tg_user_id}@megawin.ng"

    # create paystack checkout, include tg id in metadata so webhook can match
    try:
        checkout_url, ref = await create_paystack_payment(amount, email, metadata={"tg_user_id": str(tg_user_id)})
    except Exception as e:
        txt = f"⚠️ Could not initialize Paystack payment. {e}"
        if callback:
            await callback.message.answer(txt)
            await callback.answer()
        else:
            await message.answer(txt)
        return

    # create pending raffle entry
    async with async_session() as db:
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

        await db.execute(insert(RaffleEntry).values(
            user_id=user.id,
            reference=ref,
            amount=amount,
            quantity=quantity,
            confirmed=False,
        ))
        await db.commit()

    txt = (
        f"🛒 <b>Ticket Purchase Started</b>\n\n"
        f"Amount: ₦{amount:,}\nTickets: {quantity}\n\n"
        f"<a href='{checkout_url}'>Click here to complete payment</a>\n\n"
        "Tickets will be issued automatically after payment is confirmed."
    )

    if callback:
        await callback.message.answer(txt, parse_mode="HTML", reply_markup=main_menu())
        await callback.answer()
    else:
        await message.answer(txt, parse_mode="HTML", reply_markup=main_menu())


# user commands
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
    await msg.answer(f"Share this link:\n{link}", reply_markup=main_menu())


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


# admin commands
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
    # channel announce (best-effort)
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
    if not is_admin(msg.from_user.id):
        return await msg.reply("Unauthorized.")
    async with async_session() as db:
        await db.execute(delete(Ticket))
        await db.commit()
    await msg.answer("✅ All tickets deleted (reset).")


# inline callbacks
@router.callback_query(F.data == "my_tickets")
async def cb_my_tickets(cb: CallbackQuery):
    await tickets_cmd(cb.message)


@router.callback_query(F.data == "referral")
async def cb_referral(cb: CallbackQuery):
    link = referral_link(BOT_USERNAME, cb.from_user.id)
    await cb.message.answer(f"Share this link:\n{link}", reply_markup=main_menu())
    await cb.answer()


@router.callback_query(F.data == "help_btn")
async def cb_help(cb: CallbackQuery):
    await help_cmd(cb.message)
    await cb.answer()


@router.message()
async def fallback(message: Message):
    await message.answer("Use the menu or /help", reply_markup=main_menu())


# function used by main.py to attach router
def register_handlers(dp: Dispatcher):
    """
    Attach this router to the passed Dispatcher.
    main.py should create bot, dp and call register_handlers(dp)
    """
    dp.include_router(router)
