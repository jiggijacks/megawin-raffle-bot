import os
import asyncio
from typing import Optional

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.enums import ParseMode

from sqlalchemy import select, insert
from app.database import async_session, User, Ticket, RaffleEntry, Transaction, Winner
from app.paystack import create_paystack_payment
from app.utils import referral_link, generate_ticket_code, TICKET_PRICE

router = Router()

# === ENV SETUP ===
BOT_USERNAME = os.getenv("BOT_USERNAME", "MegaWinRaffleBot")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@MegaWinRaffle")
ADMINS = [int(x) for x in os.getenv("ADMIN_ID", "").split(",") if x.strip()]

# This will be injected from main.py
bot: Bot = None


# ============================================================
#                        HELPERS
# ============================================================
def _is_admin(uid: int) -> bool:
    return uid in ADMINS


def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎟 Buy Tickets", callback_data="open_buy_menu")],
        [InlineKeyboardButton(text="📊 My Tickets", callback_data="my_tickets")],
        [
            InlineKeyboardButton(text="👥 Referral", callback_data="referral"),
            InlineKeyboardButton(text="ℹ Help", callback_data="help_btn"),
        ]
    ])


def buy_options_menu():
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


# ============================================================
#                        COMMANDS
# ============================================================
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
        "/buy — Buy tickets\n"
        "/tickets — Show your ticket codes\n"
        "/balance — Show wallet balance\n"
        "/referral — Get your referral link\n"
        "/userstat — Show your statistics\n\n"
        "<b>Admin Commands:</b>\n"
        "/stats /transactions /broadcast /announce_winner /draw_reset"
    )
    await msg.answer(text, reply_markup=main_menu(), parse_mode="HTML")


# ============================================================
#                     INLINE BUTTON HANDLERS
# ============================================================
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
    parts = cb.data.split("_", 1)

    if parts[1].isdigit():
        qty = int(parts[1])
        await initiate_purchase(cb.message, cb.from_user.id, qty, cb)
        return

    if parts[1] == "custom":
        await cb.message.answer("Send the number of tickets (e.g. 3)", reply_markup=main_menu())
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


# ============================================================
#                   /buy and numeric handler
# ============================================================
@router.message(Command("buy"))
async def buy_cmd(msg: Message):
    parts = msg.text.split(maxsplit=1)
    if len(parts) > 1 and parts[1].isdigit():
        qty = int(parts[1])
        return await initiate_purchase(msg, msg.from_user.id, qty)

    await msg.answer("Choose ticket option:", reply_markup=buy_options_menu())


@router.message()
async def numeric_purchase_handler(msg: Message):
    txt = (msg.text or "").strip()
    if not txt.isdigit():
        return  # fallback handles it

    qty = int(txt)
    if qty <= 0:
        await msg.answer("Send a positive number.")
        return

    await initiate_purchase(msg, msg.from_user.id, qty)


# ============================================================
#                     PURCHASE FUNCTION
# ============================================================
async def initiate_purchase(message: Message, tg_user_id: int, qty: int, cb: CallbackQuery = None):
    amount = qty * TICKET_PRICE
    email = f"{tg_user_id}@megawin.ng"

    try:
        url, ref = await create_paystack_payment(amount, email, tg_user_id=tg_user_id)
    except Exception as e:
        error_text = "⚠️ Could not initialize Paystack payment. Try again."
        if cb:
            await cb.message.answer(error_text)
            await cb.answer()
        else:
            await message.answer(error_text)
        print("Paystack init error:", e)
        return

    async with async_session() as db:
        q = await db.execute(select(User).where(User.telegram_id == str(tg_user_id)))
        user = q.scalar_one_or_none()

        if not user:
            await db.execute(insert(User).values(
                telegram_id=str(tg_user_id),
                username=message.from_user.username or "",
                email=email
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

    txt = (
        f"🛒 <b>Purchase Started</b>\n\n"
        f"Amount: ₦{amount:,}\n"
        f"Tickets: {qty}\n\n"
        f"<a href='{url}'>Click here to pay</a>\n\n"
        "Your tickets will be issued automatically after payment."
    )

    if cb:
        await cb.message.answer(txt, parse_mode="HTML", reply_markup=main_menu())
        await cb.answer()
    else:
        await message.answer(txt, parse_mode="HTML", reply_markup=main_menu())


# ============================================================
#    TICKETS / BALANCE / REFERRAL / USERSTAT COMMAND HANDLERS
# ============================================================
@router.message(Command("tickets"))
async def tickets_cmd(msg: Message):
    async with async_session() as db:
        q = await db.execute(select(User).where(User.telegram_id == str(msg.from_user.id)))
        user = q.scalar_one_or_none()

        if not user:
            return await msg.answer("You have no tickets yet.", reply_markup=main_menu())

        q = await db.execute(select(Ticket).where(Ticket.user_id == user.id))
        rows = q.scalars().all()

    if not rows:
        return await msg.answer("You have no tickets yet.", reply_markup=main_menu())

    await msg.answer(
        "🎟 Your Tickets:\n" + "\n".join([r.code for r in rows]),
        reply_markup=main_menu()
    )


@router.message(Command("balance"))
async def balance_cmd(msg: Message):
    async with async_session() as db:
        q = await db.execute(select(User).where(User.telegram_id == str(msg.from_user.id)))
        user = q.scalar_one_or_none()

    bal = user.balance if user else 0
    await msg.answer(f"💰 Balance: ₦{bal}", reply_markup=main_menu())


@router.message(Command("referral"))
async def ref_cmd(msg: Message):
    link = referral_link(BOT_USERNAME, msg.from_user.id)
    await msg.answer(f"👥 Referral link:\n{link}", reply_markup=main_menu())


@router.message(Command("userstat"))
async def userstat_cmd(msg: Message):
    async with async_session() as db:
        q = await db.execute(select(User).where(User.telegram_id == str(msg.from_user.id)))
        user = q.scalar_one_or_none()

        if not user:
            return await msg.answer("No stats available.", reply_markup=main_menu())

        q = await db.execute(select(Ticket).where(Ticket.user_id == user.id))
        tcount = len(q.scalars().all())

    await msg.answer(
        f"📊 Your Stats:\nTickets: {tcount}",
        reply_markup=main_menu()
    )


# ============================================================
#                    ADMIN COMMANDS
# ============================================================
@router.message(Command("stats"))
async def cmd_stats(msg: Message):
    if not _is_admin(msg.from_user.id):
        return await msg.reply("Unauthorized.")

    async with async_session() as db:
        total_users = (await db.execute(select(User))).scalars().all()
        total_tickets = (await db.execute(select(Ticket))).scalars().all()
        revenue = (await db.execute(select(RaffleEntry))).scalars().all()

    total_revenue = sum([r.amount for r in revenue])

    await msg.answer(
        f"📈 Stats:\nUsers: {len(total_users)}\nTickets: {len(total_tickets)}\nRevenue: ₦{total_revenue:,}"
    )


@router.message(Command("transactions"))
async def cmd_transactions(msg: Message):
    if not _is_admin(msg.from_user.id):
        return await msg.reply("Unauthorized.")

    async with async_session() as db:
        q = await db.execute(select(Transaction).order_by(Transaction.created_at.desc()).limit(20))
        rows = q.scalars().all()

    if not rows:
        return await msg.answer("No transactions yet.")

    out = []
    for r in rows:
        out.append(f"{r.created_at} | ₦{r.amount} | ref={r.reference}")

    await msg.answer("Recent Transactions:\n" + "\n".join(out))


@router.message(Command("broadcast"))
async def cmd_broadcast(msg: Message):
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
            await bot.send_message(int(u.telegram_id), text)
            sent += 1
        except:
            pass
        await asyncio.sleep(0.05)

    await msg.answer(f"Broadcast sent to {sent} users.")


@router.message(Command("announce_winner"))
async def cmd_announce_winner(msg: Message):
    if not _is_admin(msg.from_user.id):
        return await msg.reply("Unauthorized.")

    args = msg.text.split(maxsplit=2)
    if len(args) < 2:
        return await msg.reply("Usage: /announce_winner <TICKET_CODE>")

    code = args[1].upper()

    async with async_session() as db:
        q = await db.execute(select(Ticket).where(Ticket.code == code))
        ticket = q.scalar_one_or_none()

        if not ticket:
            return await msg.reply("Ticket not found.")

        await db.execute(insert(Winner).values(
            ticket_code=code,
            user_id=ticket.user_id,
            announced_by=str(msg.from_user.id)
        ))
        await db.commit()

        q = await db.execute(select(User).where(User.id == ticket.user_id))
        user = q.scalar_one()

    text = (
        f"🏆 <b>WINNER ANNOUNCED</b>\n\n"
        f"Ticket: <b>{code}</b>\n"
        f"User: <a href='tg://user?id={user.telegram_id}'>{user.username or user.telegram_id}</a>"
    )

    try:
        await bot.send_message(CHANNEL_USERNAME, text, parse_mode="HTML")
    except:
        pass

    try:
        await bot.send_message(int(user.telegram_id), f"🎉 Congratulations! You won with ticket {code}!")
    except:
        pass

    await msg.answer("Winner announced.")


@router.message(Command("draw_reset"))
async def cmd_reset(msg: Message):
    if not _is_admin(msg.from_user.id):
        return await msg.reply("Unauthorized.")

    async with async_session() as db:
        await db.execute(Ticket.__table__.delete())
        await db.commit()

    await msg.answer("All tickets deleted.", reply_markup=main_menu())


# ============================================================
#                        FALLBACK
# ============================================================
@router.message()
async def fallback(msg: Message):
    if (msg.text or "").isdigit():
        return
    await msg.answer("Use the menu or /help", reply_markup=main_menu())


# ============================================================
#                     REGISTER ROUTER
# ============================================================
def register_handlers(dp: Dispatcher):
    dp.include_router(router)
