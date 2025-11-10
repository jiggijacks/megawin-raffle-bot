# app/bot.py
import os
import logging
import random
import aiohttp
import uvicorn

from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import HTMLResponse
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    BotCommand,
    Update
)
from sqlalchemy import select, func

# your own DB utilities / models
from app.database import async_session, init_db, User, RaffleEntry

# ---------------------------------------------------------
# ENVIRONMENT
# ---------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", "8080"))

PUBLIC_URL = os.getenv("PUBLIC_URL", "https://megawinraffle.up.railway.app")
TELEGRAM_WEBHOOK_PATH = "/webhook/telegram"
PAYSTACK_WEBHOOK_PATH = "/webhook/paystack"

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN not set in environment")

# ---------------------------------------------------------
# LOGGING
# ---------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
logger.info("✅ Environment loaded")

# ---------------------------------------------------------
# BOT / DISPATCHER / FASTAPI
# ---------------------------------------------------------
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
app = FastAPI()

# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------
async def get_or_create_user(telegram_id: int, username: str | None = None):
    async with async_session() as session:
        q = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = q.scalar_one_or_none()
        if user:
            if username and user.username != username:
                user.username = username
                await session.commit()
            return user
        user = User(telegram_id=telegram_id, username=username)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def set_bot_commands():
    cmds = [
        BotCommand(command="start", description="Start / Referral link"),
        BotCommand(command="help", description="How to use the bot"),
        BotCommand(command="buy", description="Buy a raffle ticket (₦500)"),
        BotCommand(command="ticket", description="View your tickets"),
        BotCommand(command="referrals", description="Your referral count"),
        BotCommand(command="balance", description="Check your spend & referral earnings")  # ✅ NEW
    ]
    await bot.set_my_commands(cmds)


# ---------------------------------------------------------
# COMMAND HANDLERS
# ---------------------------------------------------------
@dp.message(Command("start"))
async def cmd_start(message: Message, command: Command):
    telegram_id = message.from_user.id
    username = message.from_user.username
    user = await get_or_create_user(telegram_id, username)

    me = await bot.get_me()
    ref_link = f"https://t.me/{me.username}?start={telegram_id}"

    # ✅ Improved welcome message
    bot_intro = (
        "🎉 <b>Welcome to MegaWin Raffle!</b>\n\n"
        "💰 Buy tickets to win amazing cash prizes.\n"
        "🎟 Each ticket costs ₦500 and increases your chance of winning.\n"
        "👥 Invite 5 friends with your referral link to get 1 free ticket!\n\n"
        "Use the buttons below to start playing 👇"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎟 Buy Ticket", callback_data="buy_ticket")],
        [InlineKeyboardButton(text="🎫 My Tickets", callback_data="view_tickets")],
        [InlineKeyboardButton(text="👥 Referrals", callback_data="my_referrals")],
        [InlineKeyboardButton(text="❓ Help", callback_data="help_cmd")],
    ])

    await message.answer(
        f"{bot_intro}\n\n🔗 Your referral link:\n<code>{ref_link}</code>",
        reply_markup=kb
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "💡 <b>How to play</b>\n"
        "• /buy — Buy a raffle ticket (₦500)\n"
        "• /ticket — View your tickets\n"
        "• /balance — View your balance summary\n"
        "• /referrals — See your referral count\n\n"
        "<b>Admin only</b>:\n"
        "• /winners — pick a random winner\n"
        "• /stats — view platform stats"
    )

@dp.message(Command("buy"))
async def cmd_buy(message: Message):
    if not PAYSTACK_SECRET_KEY:
        await message.answer("❌ Paystack key not set.")
        return

    tg_id = message.from_user.id
    username = message.from_user.username
    user = await get_or_create_user(tg_id, username)
    callback_url = f"{PUBLIC_URL}{PAYSTACK_WEBHOOK_PATH}"

    async with aiohttp.ClientSession() as s:
        headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"}
        payload = {
            "email": f"user_{tg_id}@megawinraffle.com",
            "amount": 500 * 100,
            "metadata": {"telegram_id": tg_id},
            "callback_url": callback_url,
        }
        async with s.post("https://api.paystack.co/transaction/initialize", headers=headers, json=payload) as resp:
            res = await resp.json()

    if res.get("status"):
        ref = res["data"]["reference"]
        pay_url = res["data"]["authorization_url"]

        async with async_session() as s:
            s.add(RaffleEntry(user_id=user.id, payment_ref=ref, free_ticket=False))
            await s.commit()

        await message.answer(
            f"💳 <b>Payment</b>\nClick below to complete your payment:\n"
            f"👉 <a href='{pay_url}'>Pay ₦500 via Paystack</a>\n\n"
            f"Once payment is confirmed, your ticket will be added automatically. ✅",
            disable_web_page_preview=True,
        )
    else:
        await message.answer("❌ Could not start Paystack payment. Try again.")

@dp.message(Command("winners"))
async def cmd_winners(message: Message):
    """Admin-only: pick a random winner and reset tickets."""
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Only the admin can use this command.")
        return

    async with async_session() as s:
        q = await s.execute(select(RaffleEntry))
        entries = q.scalars().all()
        if not entries:
            await message.answer("📭 No raffle tickets yet.")
            return

        winner = random.choice(entries)
        q2 = await s.execute(select(User).where(User.id == winner.user_id))
        user = q2.scalar_one_or_none()

        winner_name = (
            f"@{user.username}" if user and user.username else f"ID {user.telegram_id}"
        )

        await message.answer(
            f"🏆 <b>Winner:</b> {winner_name}\n🎫 Ticket #{winner.id}\n\n"
            f"🎉 Congratulations to our lucky winner!"
        )

        # ✅ Reset tickets after winner is picked
        await s.execute("DELETE FROM raffle_entries;")
        await s.commit()
        await message.answer("🔁 All tickets have been reset for the next round!")


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    """Admin-only: show summary statistics."""
    if message.from_user.id != ADMIN_ID:
        await message.answer("🚫 Only the admin can view stats.")
        return

    async with async_session() as s:
        total_users = await s.scalar(select(func.count(User.id)))
        total_tickets = await s.scalar(select(func.count(RaffleEntry.id)))
        total_free = await s.scalar(
            select(func.count(RaffleEntry.id)).where(RaffleEntry.free_ticket == True)
        )

        paid_tickets = (total_tickets or 0) - (total_free or 0)
        total_value = paid_tickets * 500  # ₦500 per paid ticket

    await message.answer(
        "📊 <b>Platform Stats</b>\n"
        f"👥 Total Users: {total_users or 0}\n"
        f"🎟 Total Tickets: {total_tickets or 0}\n"
        f"🆓 Free Tickets: {total_free or 0}\n"
        f"💰 Ticket Value (₦500 each): ₦{total_value:,.0f}"
    )


@dp.message(Command("ticket"))
async def cmd_ticket(message: Message):
    """Show user's tickets and total count/value."""
    tg_id = message.from_user.id
    async with async_session() as s:
        q = await s.execute(select(User).where(User.telegram_id == tg_id))
        user = q.scalar_one_or_none()
        if not user:
            await message.answer("🚫 You don't have any tickets yet.")
            return

        q2 = await s.execute(select(RaffleEntry).where(RaffleEntry.user_id == user.id))
        tickets = q2.scalars().all()
        if not tickets:
            await message.answer("🚫 You have no tickets yet. Use /buy.")
            return

        msg_lines = []
        total_free = 0
        for t in tickets:
            kind = "Free" if getattr(t, "free_ticket", False) else "Paid"
            if kind == "Free":
                total_free += 1
            created = getattr(t, "created_at", None)
            when = created.strftime("%Y-%m-%d %H:%M") if created else "-"
            msg_lines.append(f"🎫 #{t.id} | {kind} | {when}")

        total_tickets = len(tickets)
        paid_tickets = total_tickets - total_free
        total_value = paid_tickets * 500  # ₦500 per paid ticket

        msg_lines.append("\n📍 <b>Summary</b>")
        msg_lines.append(f"🎟 Total Tickets: {total_tickets}")
        msg_lines.append(f"💰 Value: ₦{total_value:,.0f}")

        await message.answer("\n".join(msg_lines))

@dp.message(Command("balance"))
async def cmd_balance(message: Message):
    """Show how much a user has spent and earned from referrals."""
    telegram_id = message.from_user.id

    async with async_session() as s:
        async with s.begin():
            # Get user
            q = await s.execute(select(User).filter_by(telegram_id=telegram_id))
            user = q.scalar_one_or_none()
            if not user:
                await message.answer("🚫 You don't have any transactions yet.")
                return

            # Tickets bought (each ₦500)
            q_tickets = await s.execute(select(RaffleEntry).filter_by(user_id=user.id))
            tickets = q_tickets.scalars().all()
            paid_tickets = [t for t in tickets if not t.free_ticket]
            free_tickets = [t for t in tickets if t.free_ticket]

            spent = len(paid_tickets) * 500
            earned = len(free_tickets) * 500  # free tickets = referral rewards
            balance = earned - spent

            await message.answer(
                f"💰 <b>Your Balance Summary</b>\n\n"
                f"🪙 Tickets Bought: {len(paid_tickets)} (₦{spent})\n"
                f"🎁 Free Tickets Earned: {len(free_tickets)} (₦{earned})\n\n"
                f"📊 <b>Net Balance:</b> ₦{balance}"
            )



@dp.message(Command("referrals"))
async def cmd_referrals(message: Message):
    telegram_id = message.from_user.id
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={telegram_id}"

    async with async_session() as s:
        async with s.begin():
            q = await s.execute(select(User).filter_by(telegram_id=telegram_id))
            user = q.scalar_one_or_none()
            count = user.referral_count if user else 0
            await message.answer(
                f"👥 You have referred {count} user(s).\n\nYour referral link:\n{link}"
            )



# ---------------------------------------------------------
# CALLBACKS
# ---------------------------------------------------------
@dp.callback_query(F.data == "buy_ticket")
async def cb_buy(callback: CallbackQuery):
    await cmd_buy(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "view_tickets")
async def cb_tickets(callback: CallbackQuery):
    await cmd_ticket(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "my_referrals")
async def cb_ref(callback: CallbackQuery):
    await cmd_referrals(callback.message)
    await callback.answer()

@dp.callback_query(F.data == "help_cmd")
async def cb_help(callback: CallbackQuery):
    await cmd_help(callback.message)
    await callback.answer()

# ---------------------------------------------------------
# TELEGRAM WEBHOOK
# ---------------------------------------------------------
@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = Update.model_validate(data)
        await dp.feed_update(bot, update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"❌ Telegram webhook error: {e}")
        return {"status": "error", "message": str(e)}

# ---------------------------------------------------------
# PAYSTACK WEBHOOK
# ---------------------------------------------------------
@app.post(PAYSTACK_WEBHOOK_PATH)
async def paystack_webhook(request: Request):
    payload = await request.json()
    event = payload.get("event")
    data = payload.get("data", {})
    logger.info(f"📩 Paystack event: {event}")

    if event != "charge.success":
        return {"status": "ignored"}

    tg_id = data.get("metadata", {}).get("telegram_id")
    ref = data.get("reference")

    async with async_session() as db:
        uq = await db.execute(select(User).where(User.telegram_id == tg_id))
        user = uq.scalar_one_or_none()
        if not user:
            user = User(telegram_id=tg_id)
            db.add(user)
            await db.flush()

        q = await db.execute(select(RaffleEntry).where(RaffleEntry.payment_ref == ref))
        entry = q.scalar_one_or_none()
        if not entry:
            entry = RaffleEntry(user_id=user.id, payment_ref=ref, free_ticket=False)
            db.add(entry)
        await db.commit()

    try:
        await bot.send_message(
            chat_id=int(tg_id),
            text="✅ Payment confirmed! Your raffle ticket has been added.\nUse /ticket to view it.",
        )
    except Exception as e:
        logger.warning(f"Failed to notify user {tg_id}: {e}")

    return {"status": "ok"}

from fastapi.responses import HTMLResponse

from fastapi.responses import HTMLResponse

@app.get("/webhook/paystack")
async def paystack_redirect():
    """Handles Paystack redirect after payment (bank transfer or card)."""
    telegram_bot_link = "https://t.me/MegaWinRafflebot"  # 👈 change to your actual bot link, e.g. https://t.me/MegaWinRaffleBot

    html_content = f"""
    <html>
    <head>
        <meta http-equiv="refresh" content="3; url=https://t.me/MegaWinRafflebot" />
        <style>
            body {{
                background-color: #fafafa;
                font-family: Arial, sans-serif;
                text-align: center;
                padding-top: 10%;
                color: #333;
            }}
            .card {{
                display: inline-block;
                padding: 30px;
                border-radius: 15px;
                background: white;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            }}
            h2 {{
                color: #28a745;
            }}
            p {{
                color: #555;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <h2>✅ Payment Successful!</h2>
            <p>You’ll be redirected to Telegram in a few seconds...</p>
            <p>If not, <a href="https://t.me/MegaWinRafflebot">click here</a>.</p>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)



# ---------------------------------------------------------
# STARTUP / SHUTDOWN
# ---------------------------------------------------------
@app.on_event("startup")
async def on_startup():
    await init_db()
    await set_bot_commands()
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_webhook(f"{PUBLIC_URL}{TELEGRAM_WEBHOOK_PATH}",
                              allowed_updates=["message", "callback_query"])
        logger.info("✅ Telegram webhook set")
    except Exception as e:
        logger.error(f"❌ Failed to set webhook: {e}")

@app.on_event("shutdown")
async def on_shutdown():
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass

# ---------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
