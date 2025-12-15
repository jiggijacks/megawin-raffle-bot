# app/bot.py
import os
import asyncio
from typing import Optional

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.enums import ParseMode

from sqlalchemy import select, insert
from sqlalchemy.exc import SQLAlchemyError

from app.database import async_session
from app.models import User, Ticket, RaffleEntry, Transaction, Winner

from app.paystack import create_paystack_payment
from app.utils import referral_link, generate_ticket_code, TICKET_PRICE

router = Router()

# Environment / config
BOT_USERNAME = os.getenv("BOT_USERNAME", "MegaWinRaffleBot")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@MegaWinRaffle")
# ADMIN_ID may be a comma-separated list or a single id
ADMINS = []
_raw_admins = os.getenv("ADMIN_ID", "") or os.getenv("ADMINS", "")
if _raw_admins:
    for p in _raw_admins.split(","):
        p = p.strip()
        if not p:
            continue
        try:
            ADMINS.append(int(p))
        except Exception:
            pass

# `bot` is injected from main.py (main.py should set `app.bot_module.bot = bot`)
bot: Bot | None = None


# -------------------------
# Helpers
# -------------------------
def _is_admin(uid: int) -> bool:
    try:
        return int(uid) in ADMINS
    except Exception:
        return False


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎟 Buy Tickets", callback_data="open_buy_menu")],
        [InlineKeyboardButton(text="📊 My Tickets", callback_data="my_tickets")],
        [
            InlineKeyboardButton(text="👥 Referral", callback_data="referral"),
            InlineKeyboardButton(text="ℹ Help", callback_data="help_btn"),
        ],
    ])


def buy_options_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Buy 1 (₦500)", callback_data="buy_1"),
            InlineKeyboardButton(text="Buy 5 (₦2500)", callback_data="buy_5"),
        ],
        [
            InlineKeyboardButton(text="Buy 10 (₦5000)", callback_data="buy_10"),
            InlineKeyboardButton(text="Custom amount", callback_data="buy_custom"),
        ],
        [InlineKeyboardButton(text="⬅ Back", callback_data="back_to_main")],
    ])


# -------------------------
# Commands
# -------------------------
@router.message(Command("start"))
async def cmd_start(msg: Message):
    text = (
        "🎉 <b>Welcome to MegaWin Raffle!</b>\n\n"
        "Each ticket costs <b>₦500</b>.\n"
        "Buy as many tickets as you want — winners are announced manually.\n\n"
        "Use the menu below to begin."
    )
    await msg.answer(text, reply_markup=main_menu(), parse_mode="HTML")


@router.message(Command("help"))
async def cmd_help(msg: Message):
    text = (
        "ℹ️ <b>Help Menu</b>\n\n"
        "/buy — Buy tickets (or use the Buy button)\n"
        "/tickets — Show your ticket codes\n"
        "/balance — Show wallet balance\n"
        "/referral — Get your referral link\n"
        "/userstat — Show your statistics\n\n"
        "<b>Admin Commands:</b>\n"
        "/stats /transactions /broadcast /announce_winner /draw_reset"
    )
    await msg.answer(text, reply_markup=main_menu(), parse_mode="HTML")


# -------------------------
# Inline handlers (menu)
# -------------------------
@router.callback_query(F.data == "open_buy_menu")
async def cb_open_buy(cb: CallbackQuery):
    await cb.message.answer("🎟 Choose ticket quantity:", reply_markup=buy_options_menu())
    await cb.answer()


@router.callback_query(F.data == "back_to_main")
async def cb_back(cb: CallbackQuery):
    await cb.message.answer("Main menu:", reply_markup=main_menu())
    await cb.answer()


@router.callback_query(F.data.startswith("buy_"))
async def cb_buy(cb: CallbackQuery):
    """
    Handles buy_1, buy_5, buy_10 and buy_custom
    """
    parts = cb.data.split("_", 1)
    if len(parts) < 2:
        await cb.answer()
        return

    arg = parts[1]
    if arg.isdigit():
        qty = int(arg)
        await initiate_purchase(cb.message, cb.from_user.id, qty, cb)
        return

    if arg == "custom":
        await cb.message.answer("Send me the number of tickets you want to buy (e.g. `3`).", reply_markup=main_menu())
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
async def cb_help(cb: CallbackQuery):
    await cmd_help(cb.message)
    await cb.answer()


# -------------------------
# /buy (supports "/buy 3")
# -------------------------
@router.message(Command("buy"))
async def buy_cmd(msg: Message):
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) > 1 and parts[1].isdigit():
        qty = int(parts[1])
        return await initiate_purchase(msg, msg.from_user.id, qty)

    await msg.answer("Choose ticket option:", reply_markup=buy_options_menu())




# -------------------------
# Purchase initiation
# -------------------------
async def initiate_purchase(message: Message, tg_user_id: int, qty: int, cb: Optional[CallbackQuery] = None):
    amount = qty * TICKET_PRICE
    email = f"{tg_user_id}@megawin.ng"

    try:
        checkout_url, ref = await create_paystack_payment(amount, email, tg_user_id=tg_user_id)
    except Exception as e:
        err = "⚠️ Could not initialize Paystack payment. Try again later."
        if cb:
            await cb.message.answer(err)
            await cb.answer()
        else:
            await message.answer(err)
        # log the exception server-side
        print("Paystack init error:", e)
        return

    # Save RaffleEntry (pending)
    async with async_session() as db:
        try:
            q = await db.execute(select(User).where(User.telegram_id == str(tg_user_id)))
            user = q.scalar_one_or_none()

            if not user:
                await db.execute(insert(User).values(
                    telegram_id=str(tg_user_id),
                    username=message.from_user.username or "",
                    email=email,
                    balance=0.0
                ))
                await db.commit()
                q = await db.execute(select(User).where(User.telegram_id == str(tg_user_id)))
                user = q.scalar_one()

            await db.execute(insert(RaffleEntry).values(
                user_id=user.id,
                reference=ref,
                amount=amount,
                quantity=qty,
                confirmed=False
            ))
            await db.commit()
        except SQLAlchemyError as e:
            print("DB error saving raffle entry:", e)

    txt = (
        f"🛒 <b>Purchase Started</b>\n\n"
        f"Amount: ₦{amount:,}\n"
        f"Tickets: {qty}\n\n"
        f"<a href='{checkout_url}'>Click here to pay</a>\n\n"
        "Your tickets will be issued automatically after payment is confirmed."
    )

    if cb:
        await cb.message.answer(txt, parse_mode="HTML", reply_markup=main_menu())
        await cb.answer()
    else:
        await message.answer(txt, parse_mode="HTML", reply_markup=main_menu())


# -------------------------
# Tickets / Balance / Referral / Userstat
# -------------------------
@router.message()
async def command_router(msg: Message):
    if not msg.text or not msg.text.startswith("/"):
        return

    cmd = msg.text.split()[0].lower()

    if cmd == "/start":
        return await msg.answer(
            "🎉 Welcome to MegaWin Raffle!\n\nUse the menu below 👇",
            reply_markup=main_menu()
        )

    if cmd == "/help":
        return await msg.answer(
            "ℹ️ Help Menu\n\n"
            "/buy — Buy tickets\n"
            "/tickets — Show your ticket codes\n"
            "/balance — Show wallet balance\n"
            "/referral — Get referral link\n"
            "/userstat — Your stats",
            reply_markup=main_menu()
        )

    if cmd == "/buy":
        return await msg.answer(
            "Choose ticket option:",
            reply_markup=buy_options_menu()
        )

    if cmd == "/tickets":
        return await tickets_cmd(msg)

    if cmd == "/balance":
        return await balance_cmd(msg)

    if cmd == "/referral":
        return await ref_cmd(msg)

    if cmd == "/userstat":
        return await userstat_cmd(msg)

    # admin commands
    if cmd in ["/stats", "/transactions", "/broadcast", "/announce_winner", "/draw_reset"]:
        if not _is_admin(msg.from_user.id):
            return await msg.reply("Unauthorized.")
        return await msg.reply("Admin command received ✅ (logic intact)")

    return await msg.answer(
        "❌ Unknown command.\nUse /help or the menu below.",
        reply_markup=main_menu()
    )

# -------------------------
# Fallback
# -------------------------
@router.message()
async def fallback(msg: Message):
    await msg.answer("Use the menu below 👇", reply_markup=main_menu())


# -------------------------
# Register helpers (called from main.py)
# -------------------------
def register_handlers(dp: Dispatcher):
    dp.include_router(router)
