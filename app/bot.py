import os
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

from sqlalchemy import select, insert

from app.database import async_session, User, RaffleEntry
from app.paystack import create_paystack_payment

TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()
router = Router()
dp.include_router(router)


# --------------------------
# START
# --------------------------
@router.message(Command("start"))
async def start_cmd(msg: Message):
    tg_id = msg.from_user.id
    email = f"{tg_id}@megawin.ng"

    async with async_session() as db:

        q = await db.execute(
            select(User).where(User.telegram_id == tg_id)
        )
        user = q.scalar_one_or_none()

        # CREATE USER IF MISSING
        if not user:
            result = await db.execute(
                insert(User).values(
                    telegram_id=tg_id,
                    email=email
                ).returning(User.id)
            )
            await db.commit()

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Buy Tickets", callback_data="buy")],
            [InlineKeyboardButton(text="📊 My Tickets", callback_data="bal")],
        ]
    )

    await msg.answer(
        "🎉 <b>Welcome to MegaWin Raffle!</b>\n\n"
        "You can buy tickets using Paystack.\n"
        "Good luck! 🍀",
        reply_markup=kb,
    )


# --------------------------
# CHECK MY TICKETS
# --------------------------
@router.callback_query(F.data == "bal")
async def check_balance(cb):
    tg_id = cb.from_user.id

    async with async_session() as db:
        q = await db.execute(
            select(User).where(User.telegram_id == tg_id)
        )
        user = q.scalar_one()

        # Count tickets
        ticket_count = len(user.tickets)

    await cb.message.answer(
        f"🎟️ <b>Your Tickets:</b> {ticket_count}",
    )
    await cb.answer()


# --------------------------
# BUY TICKETS
# --------------------------
@router.callback_query(F.data == "buy")
async def buy(cb):
    tg_id = cb.from_user.id
    amount = 1000

    email = f"{tg_id}@megawin.ng"
    checkout_url, ref = await create_paystack_payment(amount, email)

    async with async_session() as db:
        # Get real DB user id
        q = await db.execute(
            select(User).where(User.telegram_id == tg_id)
        )
        user = q.scalar_one()

        await db.execute(
            insert(RaffleEntry).values(
                user_id=user.id,
                reference=ref,
                amount=amount,
            )
        )
        await db.commit()

    await cb.message.answer(
        f"🔥 <b>Ticket Purchase Started!</b>\n\n"
        f"Complete payment:\n{checkout_url}"
    )
    await cb.answer()
