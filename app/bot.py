import logging
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.utils import executor
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from .config import BOT_TOKEN
from .models import User, RaffleEntry
from .database import SessionLocal
from .ticket import generate_ticket_code
from .paystack import create_payment_link

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

# Start command
@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    user = await get_or_create_user(message.from_user.id)
    # Channel membership check
    await message.answer("Welcome to MegaWin Raffle Bot! Use /buy to purchase a ticket.")

# Buy ticket command
@dp.message_handler(commands=["buy"])
async def cmd_buy(message: types.Message):
    user = await get_or_create_user(message.from_user.id)
    payment_link = await create_payment_link(user.telegram_id, 500)
    await message.answer(f"Click here to buy your ticket: {payment_link['data']['authorization_url']}")

# View tickets
@dp.message_handler(commands=["tickets"])
async def cmd_tickets(message: types.Message):
    user = await get_user_by_telegram_id(message.from_user.id)
    tickets = await get_user_tickets(user.id)
    ticket_list = "\n".join([f"Ticket Code: {ticket.ticket_code}" for ticket in tickets])
    await message.answer(f"Your tickets: {ticket_list}")

async def get_user_by_telegram_id(tg_id: int):
    db = SessionLocal()
    return db.query(User).filter(User.telegram_id == tg_id).first()

async def get_user_tickets(user_id: int):
    db = SessionLocal()
    return db.query(RaffleEntry).filter(RaffleEntry.user_id == user_id).all()

if __name__ == "__main__":
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)
