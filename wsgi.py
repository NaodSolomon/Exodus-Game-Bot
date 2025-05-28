import asyncio
import threading
from admin_dashboard.app import app, set_telegram_app
from User.main import run_bot, BOT_TOKEN
from telegram.ext import Application

if __name__ == "__main__":
    # Initialize Telegram app
    telegram_app = Application.builder().token(BOT_TOKEN).build()
    set_telegram_app(telegram_app)
    
    # Start bot in a separate thread
    bot_thread = threading.Thread(target=lambda: asyncio.run(run_bot()), daemon=True)
    bot_thread.start()
    
    # Run Flask app
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8000)))