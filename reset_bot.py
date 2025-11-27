import asyncio
from aiogram import Bot

BOT_TOKEN = "8313769861:AAF9leKJIvTezaLvf8qq_NosYQZhM0MiJxc"   # paste it directly here for now

async def reset_webhook():
    bot = Bot(token=BOT_TOKEN)
    info = await bot.get_webhook_info()
    if info.url:
        print(f"Removing old webhook: {info.url}")
        await bot.delete_webhook(drop_pending_updates=True)
    else:
        print("No webhook found.")
    print("✅ Webhook cleared.")
    await bot.session.close()

if __name__ == "__main__":
    asyncio.run(reset_webhook())
