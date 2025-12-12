# app/bot.py
import os
import asyncio
from typing import Optional

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from sqlalchemy import select, insert
from sqlalchemy.exc import SQLAlchemyError

from app.database import async_session, User, Ticket, RaffleEntry, Transaction, Winner
from app.paystack import create_paystack_payment
from app.utils import referral_link, generate_ticket_code, TICKET_PRICE

router = Router()

# Bot instance will be injected from main.py like:
# import app.bot as bot_module; bot_module.bot = bot
bot: Bot | None = None

# Environment / config
BOT_USERNAME = os.getenv("BOT_USERNAME", "MegaWinRaffleBot")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@MegaWinRaffle")
ADMINS = [int(x) for x in os.getenv("ADMIN_ID", "").split(",") if x.strip()]


# -------------------------
# Key helpers & keyboards
# -------------------------
def _is_admin(uid: int) -> bool:
    try:
        return int(uid) in ADMINS
    except Exception:
        return False


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("🎟 Buy Tickets", callback_data="open_buy_menu")],
        [InlineKeyboardButton("📊 My Tickets", callback_data="my_tickets")],
        [
            InlineKeyboardButton("👥 Referral", callback_data="referral"),
            InlineKeyboardButton("ℹ Help", callback_data="help_btn")
        ],
    ])


def buy_options_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton("Buy 1 (₦500)", callback_data="buy_1"),
            InlineKeyboardButton("Buy 5 (₦2500)", callback_data="buy_5"),
        ],
        [
            InlineKeyboardButton("Buy 10 (₦5000)", callback_data="buy_10"),
            InlineKeyboardButton("Custom amount", callback_data="buy_custom"),
        ],
        [InlineKeyboardButton("⬅ Back", callback_data="back_to_main")],
    ])


# -------------------------
# Utility DB helpers
# -------------------------
async def ensure_user(session, tg_user) -> User:
    """Return User row for the given telegram user (create if missing)."""
    tg = str(tg_user.id)
    q = await session.execute(select(User).where(User.telegram_id == tg))
    user = q.scalar_one_or_none()
    if user:
        return user

    await session.execute(insert(User).values(
        telegram_id=tg,
        username=tg_user.username or "",
        email=f"{tg}@megawin.ng",
        balance=0.0,
    ))
    await session.commit()
    q = await session.execute(select(User).where(User.telegram_id == tg))
    return q.scalar_one()


# -------------------------
# Text message handlers (slash-safe)
# -------------------------
@router.message()
async def generic_message_handler(msg: Message):
    """
    Single fallback entrypoint for message updates.
    Supports:
      - /start, /help
      - /buy <n>
      - /tickets, /balance, /referral, /userstat
      - admin commands starting with /stats /transactions /broadcast /announce_winner /draw_reset
      - plain numeric messages interpreted as 'buy <n>'
    """
    text = (msg.text or "").strip()
    if not text:
        return

    # normalize
    lower = text.lower()

    # --- start/help ---
    if lower.startswith("/start") or lower == "start":
        return await handle_start(msg)
    if lower.startswith("/help") or lower == "help":
        return await handle_help(msg)

    # --- buy via "/buy N" or "buy N" ---
    if lower.startswith("/buy") or lower.startswith("buy "):
        parts = text.split(maxsplit=1)
        if len(parts) == 2 and parts[1].strip().isdigit():
            qty = int(parts[1].strip())
            return await initiate_purchase(msg, msg.from_user.id, qty)
        # otherwise show buy options
        await msg.answer("Choose ticket option:", reply_markup=buy_options_menu())
        return

    # --- plain number -> treat as custom buy amount ---
    if text.isdigit():
        qty = int(text)
        if qty <= 0:
            return await msg.answer("Send a positive number of tickets.")
        return await initiate_purchase(msg, msg.from_user.id, qty)

    # --- tickets / balance / referral / userstat ---
    if lower.startswith("/tickets") or lower == "tickets":
        return await tickets_cmd(msg)
    if lower.startswith("/balance") or lower == "balance":
        return await balance_cmd(msg)
    if lower.startswith("/referral") or lower == "referral":
        return await ref_cmd(msg)
    if lower.startswith("/userstat") or lower == "userstat":
        return await userstat_cmd(msg)

    # --- admin commands ---
    if lower.startswith("/stats") or lower == "stats":
        return await stats_cmd(msg)
    if lower.startswith("/transactions") or lower == "transactions":
        return await transactions_cmd(msg)
    if lower.startswith("/broadcast"):
        return await broadcast_cmd(msg)
    if lower.startswith("/announce_winner"):
        return await announce_winner_cmd(msg)
    if lower.startswith("/draw_reset") or lower == "draw_reset":
        return await draw_reset_cmd(msg)

    # fallback
    await msg.answer("Use the menu below or type /help", reply_markup=main_menu())


# -------------------------
# Start / Help handlers
# -------------------------
async def handle_start(msg: Message):
    try:
        async with async_session() as db:
            await ensure_user(db, msg.from_user)
    except Exception as e:
        print("DB ensure_user failed:", e)

    text = (
        "🎉 <b>Welcome to MegaWin Raffle!</b>\n\n"
        "Each ticket costs <b>₦500</b>.\n"
        "Buy tickets, view your ticket numbers, and admins will announce winners.\n\n"
        "Use the buttons below to get started."
    )
    await msg.answer(text, reply_markup=main_menu())


async def handle_help(msg: Message):
    text = (
        "ℹ️ <b>Help</b>\n\n"
        "Use the inline menu or these quick text commands:\n"
        "/buy <n> — Buy n tickets (or press Buy Tickets)\n"
        "/tickets — Show your tickets\n"
        "/balance — Wallet balance\n"
        "/referral — Get referral link\n"
        "/userstat — Your stats\n\n"
        "Admin commands (admins only):\n"
        "/stats /transactions /broadcast <msg> /announce_winner <CODE> /draw_reset"
    )
    await msg.answer(text, reply_markup=main_menu())


# -------------------------
# Inline callback handlers
# -------------------------
@router.callback_query(F.data == "open_buy_menu")
async def cb_open_buy(cb: CallbackQuery):
    await cb.message.answer("🎟 Choose ticket quantity:", reply_markup=buy_options_menu())
    await cb.answer()


@router.callback_query(F.data == "back_to_main")
async def cb_back_to_main(cb: CallbackQuery):
    await cb.message.answer("Main menu:", reply_markup=main_menu())
    await cb.answer()


@router.callback_query(F.data.startswith("buy_"))
async def cb_buy(cb: CallbackQuery):
    # buy_1, buy_5, buy_10, buy_custom
    parts = cb.data.split("_", 1)
    if len(parts) < 2:
        return await cb.answer()

    choice = parts[1]
    if choice.isdigit():
        qty = int(choice)
        await initiate_purchase(cb.message, cb.from_user.id, qty, cb)
        return

    if choice == "custom":
        await cb.message.answer("Send the number of tickets you want to buy (e.g. 3).", reply_markup=main_menu())
        await cb.answer()
        return

    await cb.answer()


@router.callback_query(F.data == "my_tickets")
async def cb_my_tickets(cb: CallbackQuery):
    await tickets_cmd(cb.message)
    await cb.answer()


@router.callback_query(F.data == "referral")
async def cb_referral(cb: CallbackQuery):
    await ref_cmd(cb.message)
    await cb.answer()


@router.callback_query(F.data == "help_btn")
async def cb_help_btn(cb: CallbackQuery):
    await handle_help(cb.message)
    await cb.answer()


# -------------------------
# Purchase flow (create Paystack checkout + RaffleEntry)
# -------------------------
async def initiate_purchase(message: Message, tg_user_id: int, qty: int, cb: Optional[CallbackQuery] = None):
    if qty <= 0:
        return await message.answer("Please request a positive number of tickets.")

    amount = qty * TICKET_PRICE
    email = f"{tg_user_id}@megawin.ng"

    # Create Paystack session (create_paystack_payment must accept tg_user_id metadata)
    try:
        checkout_url, ref = await create_paystack_payment(amount, email, tg_user_id=tg_user_id)
    except Exception as e:
        print("Paystack init error:", e)
        txt = "⚠️ Could not initialize Paystack payment. Try again later."
        if cb:
            await cb.message.answer(txt)
            await cb.answer()
        else:
            await message.answer(txt)
        return

    # Save pending raffle entry
    try:
        async with async_session() as db:
            q = await db.execute(select(User).where(User.telegram_id == str(tg_user_id)))
            user = q.scalar_one_or_none()
            if not user:
                await db.execute(insert(User).values(
                    telegram_id=str(tg_user_id),
                    username=message.from_user.username or "",
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
                quantity=qty,
                confirmed=False,
            ))
            await db.commit()
    except Exception as e:
        print("DB error saving RaffleEntry:", e)
        txt = "⚠️ Server error saving purchase. Contact admin."
        if cb:
            await cb.message.answer(txt)
            await cb.answer()
        else:
            await message.answer(txt)
        return

    txt = (
        f"🛒 <b>Purchase Started</b>\n\n"
        f"Amount: ₦{amount:,}\n"
        f"Tickets: {qty}\n\n"
        f"<a href='{checkout_url}'>Click here to complete payment</a>\n\n"
        "Your tickets will be issued automatically once payment is confirmed."
    )

    if cb:
        await cb.message.answer(txt, parse_mode="HTML", reply_markup=main_menu())
        await cb.answer()
    else:
        await message.answer(txt, parse_mode="HTML", reply_markup=main_menu())


# -------------------------
# Tickets / Balance / Referral / Userstat
# -------------------------
async def tickets_cmd(msg: Message):
    async with async_session() as db:
        q = await db.execute(select(User).where(User.telegram_id == str(msg.from_user.id)))
        user = q.scalar_one_or_none()
        if not user:
            return await msg.answer("You have no tickets yet. Buy via the menu.", reply_markup=main_menu())

        q = await db.execute(select(Ticket).where(Ticket.user_id == user.id))
        rows = q.scalars().all()

    if not rows:
        return await msg.answer("You have no tickets yet. Buy via the menu.", reply_markup=main_menu())

    codes = "\n".join([r.code for r in rows])
    await msg.answer(f"🎟️ Your tickets:\n{codes}", reply_markup=main_menu())


async def balance_cmd(msg: Message):
    async with async_session() as db:
        q = await db.execute(select(User).where(User.telegram_id == str(msg.from_user.id)))
        user = q.scalar_one_or_none()
    bal = user.balance if user else 0.0
    await msg.answer(f"💰 Balance: ₦{bal:.2f}", reply_markup=main_menu())


async def ref_cmd(msg: Message):
    link = referral_link(BOT_USERNAME, msg.from_user.id)
    await msg.answer(f"Share this referral link:\n{link}", reply_markup=main_menu())


async def userstat_cmd(msg: Message):
    async with async_session() as db:
        q = await db.execute(select(User).where(User.telegram_id == str(msg.from_user.id)))
        user = q.scalar_one_or_none()
        if not user:
            return await msg.answer("No stats available.", reply_markup=main_menu())
        q = await db.execute(select(Ticket).where(Ticket.user_id == user.id))
        tcount = len(q.scalars().all())
    await msg.answer(f"📊 Your stats:\nTickets: {tcount}", reply_markup=main_menu())


# -------------------------
# Admin commands (typed)
# -------------------------
async def stats_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return await msg.reply("Unauthorized.")
    async with async_session() as db:
        users = (await db.execute(select(User))).scalars().all()
        tickets = (await db.execute(select(Ticket))).scalars().all()
        entries = (await db.execute(select(RaffleEntry))).scalars().all()
    total_revenue = sum([e.amount for e in entries])
    await msg.answer(f"📈 Stats:\nUsers: {len(users)}\nTickets: {len(tickets)}\nRevenue: ₦{total_revenue:,}")


async def transactions_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return await msg.reply("Unauthorized.")
    async with async_session() as db:
        q = await db.execute(select(Transaction).order_by(Transaction.created_at.desc()).limit(50))
        rows = q.scalars().all()
    if not rows:
        return await msg.answer("No transactions yet.")
    out = [f"{r.created_at} | ₦{r.amount} | ref={r.reference}" for r in rows]
    await msg.answer("Recent transactions:\n" + "\n".join(out))


async def broadcast_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return await msg.reply("Unauthorized.")
    text = msg.text.partition(" ")[2].strip()
    if not text:
        return await msg.reply("Usage: /broadcast <message>")
    async with async_session() as db:
        users = (await db.execute(select(User))).scalars().all()
    sent = 0
    for u in users:
        try:
            if bot:
                await bot.send_message(int(u.telegram_id), text)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            continue
    await msg.answer(f"Broadcast sent to {sent} users.")


async def announce_winner_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return await msg.reply("Unauthorized.")
    parts = msg.text.split(maxsplit=2)
    if len(parts) < 2:
        return await msg.reply("Usage: /announce_winner <TICKET_CODE> [notes]")
    ticket_code = parts[1].strip().upper()
    notes = parts[2] if len(parts) > 2 else ""
    async with async_session() as db:
        q = await db.execute(select(Ticket).where(Ticket.code == ticket_code))
        ticket = q.scalar_one_or_none()
        if not ticket:
            return await msg.reply("Ticket code not found.")
        await db.execute(insert(Winner).values(
            ticket_code=ticket.code,
            user_id=ticket.user_id,
            announced_by=str(msg.from_user.id),
            notes=notes,
        ))
        await db.commit()
        q = await db.execute(select(User).where(User.id == ticket.user_id))
        user = q.scalar_one()
    announce_text = (
        f"🏆 <b>WINNER ANNOUNCEMENT</b>\n\n"
        f"Winner ticket: <b>{ticket_code}</b>\n"
        f"Winner Telegram: <a href=\"tg://user?id={user.telegram_id}\">{user.username or user.telegram_id}</a>\n\n"
        f"Announced by admin.\n\nTransparency: each draw is handled manually and logged."
    )
    # post to channel (best-effort) and DM winner
    try:
        if bot:
            await bot.send_message(CHANNEL_USERNAME, announce_text, parse_mode="HTML")
    except Exception:
        pass
    try:
        if bot:
            await bot.send_message(int(user.telegram_id), f"🎉 Congratulations! You won with ticket {ticket_code}!\n\nAdmin notes: {notes}")
    except Exception:
        pass
    await msg.answer("Winner announced and logged.", reply_markup=main_menu())


async def draw_reset_cmd(msg: Message):
    if not _is_admin(msg.from_user.id):
        return await msg.reply("Unauthorized.")
    async with async_session() as db:
        await db.execute(Ticket.__table__.delete())
        await db.commit()
    await msg.answer("✅ All tickets have been reset (deleted).", reply_markup=main_menu())


# -------------------------
# Safe router registration for main.py
# -------------------------
def register_handlers(dp: Dispatcher):
    """
    Attach router to provided dispatcher. Safe to call multiple times.
    Also prints a message to logs so you can see attachment.
    """
    try:
        dp.include_router(router)
        print("✔ Router loaded.")
    except RuntimeError:
        # already attached
        print("✔ Router was already attached.")


# Note: main.py should set `app.bot` into this module:
# import app.bot as bot_module; bot_module.bot = bot
# and call register_handlers(dp)
#
# Also your Paystack webhook handler should:
#  - verify payment
#  - create Ticket rows (unique codes)
#  - set RaffleEntry.confirmed = True
#  - insert Transaction row
#  - send DM to the user via app.state.bot (or via this module 'bot')
#
# That paystack webhook code is separate (routers/paystack_webhook.py).
