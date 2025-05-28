import os
from dotenv import load_dotenv

# Load .env file from the User/ subfolder
load_dotenv()

# Telegram bot token from .env
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in .env file")

# Supported platform categories for the game store
CATEGORIES = [
    "PC",
    "PlayStation 4",
    "PlayStation 5",
    "Xbox One",
    "Xbox Series X",
    "Nintendo Switch"
]