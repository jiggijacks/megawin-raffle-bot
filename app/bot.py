import os
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.enums import ParseMode
from sqlalchemy import select, insert
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from app.database import RaffleEntry

from app.database import async_session, User
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
    async with async_session() as db:
        # register user
        q = await db.execute(
            select(User).where(User.telegram_id == msg.from_user.id)
        )
        user = q.scalar_one_or_none()

        if not user:
            await db.execute(
                insert(User).values(
                    telegram_id=msg.from_user.id,
                    username=msg.from_user.username or "",
                )
            )
            await db.commit()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Buy Tickets", callback_data="buy")],
        [InlineKeyboardButton(text="📊 My Balance", callback_data="bal")],
    ])

    await msg.answer(
        "🎉 *Welcome to MegaWin Raffle!*\n\n"
        "You can buy tickets using Paystack.\n"
        "Good luck! 🍀",
        reply_markup=kb,
        parse_mode="Markdown"
    )


# --------------------------
# CHECK BALANCE
# --------------------------
@router.callback_query(F.data == "bal")
async def check_balance(cb):
    async with async_session() as db:
        q = await db.execute(
            select(User).where(User.telegram_id == cb.from_user.id)
        )
        user = q.scalar_one()

    await cb.message.answer(
        f"💰 *Your Balance:* ₦{user.balance:,}",
        parse_mode="Markdown"
    )
    await cb.answer()


# --------------------------
# BUY TICKETS
# --------------------------
@router.callback_query(F.data == "buy")
async def buy(cb):
    amount = 1000  # static demo price

    email = f"{cb.from_user.id}@megawin.ng"
    checkout_url, ref = await create_paystack_payment(amount, email)

    async with async_session() as db:
        await db.execute(
            insert(RaffleEntry).values(
                user_id=cb.from_user.id,
                reference=ref,
                amount=amount
            )
        )
        await db.commit()

    await cb.message.answer(
        f"🔥 *Ticket Purchase Started!*\n\n"
        f"Click below to complete payment:\n\n{checkout_url}",
        parse_mode="Markdown"
    )
    await cb.answer()


# EXPORT DISPATCHER
def connect_bot(token: str | None = None, dispatcher: Dispatcher | None = None):
    """
    Create and return a Bot and Dispatcher configured with the module router.
    If token or dispatcher are provided they will be used; otherwise the module
    TOKEN and a new Dispatcher are used.
    """
    tok = token or TOKEN
    bot_instance = Bot(token=tok, parse_mode=ParseMode.HTML)
    dp_instance = dispatcher or Dispatcher()
    dp_instance.include_router(router)
    return bot_instance, dp_instance

    connect_bot(bot, dp)  # connect dispatcher to webhook handler
    return bot, dp
