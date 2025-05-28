import asyncio
import json
import logging
import os
import aiosqlite
from telegram.ext import Application
from .handlers import command_handlers, conv_handler, callback_query_handler, inline_query_handler, error_handler
from .database import Database
from .utils import setup_logging
from .config import BOT_TOKEN
from admin_dashboard.app import set_telegram_app

# Logger setup
setup_logging()
logger = logging.getLogger(__name__)

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
    """Run the Telegram bot with webhook."""
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
        
        # Set up webhook
        webhook_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/webhook"
        logger.info(f"Setting webhook to: {webhook_url}")
        await telegram_app.bot.set_webhook(webhook_url)
        
        # Pass telegram_app to Flask app for webhook processing
        set_telegram_app(telegram_app)
        
        logger.info("Starting bot...")
        await telegram_app.initialize()
        await telegram_app.start()
        
        # Keep the bot running
        while True:
            await asyncio.sleep(3600)
            
    except Exception as e:
        logger.error(f"Bot crashed: {e}", exc_info=True)
        raise

if __name__ == '__main__':
    asyncio.run(run_bot())