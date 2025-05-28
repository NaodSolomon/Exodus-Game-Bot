import asyncio
import json
import logging
import os
import aiosqlite
from telegram.ext import Application
from handlers import command_handlers, conv_handler, callback_query_handler, inline_query_handler, error_handler
from database import Database
from utils import setup_logging
from config import BOT_TOKEN
from flask import Flask
import threading

# Logger setup
setup_logging()
logger = logging.getLogger(__name__)

# Flask app for Render Web Service
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Telegram bot is running", 200

async def initialize_database():
    logger.info(f"Current working directory: {os.getcwd()}")
    logger.info(f"Script directory: {os.path.dirname(__file__)}")
    db = Database()
    try:
        await db.initialize()
        products_json_path = os.path.join(os.path.dirname(__file__), 'products.json')
        logger.info(f"Loading products from: {products_json_path}")
        if not os.path.exists(products_json_path):
            raise FileNotFoundError(f"products.json not found at {products_json_path}")
        with open(products_json_path, 'r') as f:
            products = json.load(f)
        async with aiosqlite.connect(db.db_path) as conn:
            valid_products = 0
            for product in products:
                image_path = os.path.join(os.path.dirname(__file__), product['image_url'])
                logger.info(f"Checking image for product {product['id']}: {image_path}")
                if not os.path.exists(image_path):
                    logger.warning(f"Image not found for product {product['id']}: {product['image_url']}, using default")
                    product['image_url'] = 'images/default.jpg'
                platform = json.dumps(product['platform'])
                price = float(product['price']) if isinstance(product['price'], (int, float)) else float(product['price'].lstrip('$').replace(',', ''))
                await conn.execute('''
                    INSERT OR REPLACE INTO products (id, name, platform, price, stock, description, image_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    product['id'],
                    product['name'],
                    platform,
                    price,
                    product['stock'],
                    product['description'],
                    product['image_url']
                ))
                valid_products += 1
            await conn.commit()
        logger.info(f"Populated {valid_products} valid products into the database")
        return db
    except Exception as e:
        logger.error(f"Error populating products: {e}", exc_info=True)
        raise

async def run_bot():
    """Run the Telegram bot."""
    try:
        if not BOT_TOKEN or BOT_TOKEN == 'YOUR_BOT_TOKEN':
            raise ValueError("BOT_TOKEN is not set or invalid")
        telegram_app = Application.builder().token(BOT_TOKEN).build()
        
        telegram_app.bot_data['db'] = await initialize_database()
        
        for handler in command_handlers:
            telegram_app.add_handler(handler)
        telegram_app.add_handler(conv_handler)
        telegram_app.add_handler(callback_query_handler)
        telegram_app.add_handler(inline_query_handler)
        telegram_app.add_handler(error_handler)
        
        logger.info("Starting bot...")
        await telegram_app.initialize()
        await telegram_app.start()
        await telegram_app.updater.start_polling(allowed_updates=['message', 'callback_query', 'inline_query'])
        
        while True:
            await asyncio.sleep(3600)
            
    except Exception as e:
        logger.error(f"Bot crashed: {e}", exc_info=True)
        raise

def start_bot():
    """Start the bot in a separate thread."""
    asyncio.run(run_bot())

if __name__ == '__main__':
    # Start bot in a separate thread
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()
    
    # Get port from environment variable
    port_str = os.getenv('PORT', '8000')
    try:
        port = int(port_str)
        if not (0 < port <= 65535):
            raise ValueError(f"Port {port} is out of valid range (1-65535)")
    except ValueError as e:
        logger.error(f"Invalid PORT value: {port_str}. Using default port 8000. Error: {e}")
        port = 8000
    
    logger.info(f"Starting Flask app on port {port}")
    app.run(host='0.0.0.0', port=port)