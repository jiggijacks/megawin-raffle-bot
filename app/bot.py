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

from sqlalchemy import select, insert
from sqlalchemy.exc import SQLAlchemyError

from app.database import async_session
from app.models import User, Ticket, RaffleEntry, Transaction, Winner
from app.paystack import create_paystack_payment
from app.utils import referral_link, TICKET_PRICE

router = Router()

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

bot: Bot | None = None


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
        checkout_url, ref = await create_paystack_payment(amount, email, tg_id)
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
