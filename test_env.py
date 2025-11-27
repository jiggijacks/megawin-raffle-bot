import os
from dotenv import load_dotenv

dotenv_path = r"C:\Users\USER\Desktop\clean-raffle-bot\.env"
print(f"Loading .env from: {dotenv_path}")

if not os.path.exists(dotenv_path):
    print("❌ .env file not found at that location!")
else:
    load_dotenv(dotenv_path=dotenv_path)
    print("✅ .env file loaded!")

print("Loaded BOT_TOKEN:", os.getenv("BOT_TOKEN"))
