import sys
import asyncio
import logging
import os
import json
import re
import uuid
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent, InputFile
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    InlineQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters
)
from Game_Catalog import CATEGORIES, get_products_by_platform, get_product_by_id, search_products
from Database_helper import Database
import sqlite3


# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set")

# Conversation states
ASK_NAME, ASK_USERNAME, ASK_PHONE, ASK_ADDRESS, CONFIRM_DETAILS, ASK_QUANTITY = range(6)

# Initialize database
db = Database()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def log_interaction(action: str, user_id: int, details: str = ""):
    """Log user interactions with timestamp and details."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"[{timestamp}] User {user_id} - {action} {details}")

def populate_database():
    """Populate the database with initial products from products.json if empty."""
    try:
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM products")
            if cursor.fetchone()[0] == 0:
                try:
                    with open('products.json', 'r') as f:
                        initial_products = json.load(f)
                        logger.info(f"Found {len(initial_products)} products to add")
                        
                    for product in initial_products:
                        try:
                            # Ensure price is properly formatted
                            if isinstance(product['price'], str):
                                product['price'] = float(product['price'].replace('$', ''))
                            db.add_product(product)
                            logger.info(f"Added product {product['id']}: {product['name']}")
                        except (ValueError, sqlite3.Error) as e:
                            logger.error(f"Failed to add product {product.get('id')}: {e}")
                            continue
                    
                    conn.commit()
                    logger.info("Database population completed successfully")
                    
                    # Debug: Log all products in the database
                    cursor.execute("SELECT product_id, name, platform, stock FROM products")
                    rows = cursor.fetchall()
                    logger.info("Products in database after population:")
                    for row in rows:
                        logger.info(f"ID: {row['product_id']}, Name: {row['name']}, Platform: {row['platform']}, Stock: {row['stock']}")
                except FileNotFoundError:
                    logger.error("products.json not found")
                    raise
                except json.JSONDecodeError:
                    logger.error("Invalid JSON in products.json")
                    raise
    except sqlite3.Error as e:
        logger.error(f"Database population failed: {e}")
        raise

# Populate database on startup
populate_database()

async def send_error_message(update: Update, context: ContextTypes.DEFAULT_TYPE, message: str):
    """Send an error message with a main menu button."""
    keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        if update.callback_query:
            await update.callback_query.message.reply_text(message, reply_markup=reply_markup)
        elif update.message:
            await update.message.reply_text(message, reply_markup=reply_markup)
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=message,
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"Error sending error message: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message,
            reply_markup=reply_markup
        )

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display the main menu."""
    user_id = update.effective_user.id
    log_interaction("Menu accessed", user_id)
    
    context.user_data.clear()
    
    keyboard = [
        [InlineKeyboardButton("📚 Catalog", callback_data="show_catalog")],
        [InlineKeyboardButton("🛒 View Cart", callback_data="view_cart")],
        [InlineKeyboardButton("📦 My Orders", callback_data="view_orders")],
        [InlineKeyboardButton("🔍 Search Games", callback_data="prompt_search")],
        [InlineKeyboardButton("❓ Help", callback_data="show_help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "Welcome to Exodus Game Store! Choose an option:"
    
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Menu display error for user {user_id}: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    
    return ConversationHandler.END

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /start command."""
    await menu(update, context)

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display available commands."""
    user_id = update.effective_user.id
    log_interaction("Help accessed", user_id)
    
    keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Available commands:\n/start - Welcome message\n/menu - Main menu\n/catalog - Browse games by category\n/cart - View cart\n/search - Search games\n/orders - View order history\n/help - Show this help",
        reply_markup=reply_markup
    )

async def catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display game categories."""
    user_id = update.effective_user.id
    log_interaction("Catalog accessed", user_id)
    
    keyboard = [
        [InlineKeyboardButton(category, callback_data=f"category:{category}")]
        for category in CATEGORIES
    ]
    keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Choose a game category:", reply_markup=reply_markup)

async def prompt_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt user to enter a search keyword."""
    user_id = update.effective_user.id
    log_interaction("Search prompted", user_id)
    
    keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Please enter a keyword to search (e.g., /search fifa):", reply_markup=reply_markup)

async def cancel_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the checkout or quantity input process."""
    user_id = update.effective_user.id
    log_interaction("Checkout/Quantity input canceled", user_id)
    
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")],
        [InlineKeyboardButton("🛒 View Cart", callback_data="view_cart")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        try:
            await update.callback_query.message.delete()
            await update.callback_query.message.reply_text("Action canceled.", reply_markup=reply_markup)
        except Exception:
            await update.callback_query.message.reply_text("Action canceled.", reply_markup=reply_markup)
    else:
        await update.message.reply_text("Action canceled.", reply_markup=reply_markup)
    
    return ConversationHandler.END

async def checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the checkout process."""
    user_id = update.effective_user.id
    log_interaction("Checkout started", user_id)
    
    try:
        cart_items = db.get_cart_items(user_id)
    except sqlite3.Error as e:
        logger.error(f"Failed to get cart for user {user_id}: {e}")
        await send_error_message(update, context, "❌ Error loading cart.")
        return ConversationHandler.END
    
    if not cart_items:
        keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("🛒 Your cart is empty.", reply_markup=reply_markup)
        return ConversationHandler.END
    
    keyboard = [
        [InlineKeyboardButton("🔙 Back to Cart", callback_data="view_cart")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🧾 Please enter your full name:", reply_markup=reply_markup)
    return ASK_NAME

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries from inline keyboards."""
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    
    log_interaction("Button pressed", user_id, f"'{data}'")
    
    try:
        if data == "main_menu":
            return await menu(update, context)
        
        elif data == "show_catalog":
            keyboard = [
                [InlineKeyboardButton(category, callback_data=f"category:{category}")]
                for category in CATEGORIES
            ]
            keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.delete()
            await query.message.reply_text("Choose a game category:", reply_markup=reply_markup)
        
        elif data == "show_help":
            keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.delete()
            await query.message.reply_text(
                "Available commands:\n/start - Welcome message\n/menu - Main menu\n/catalog - Browse games by category\n/cart - View cart\n/search - Search games\n/orders - View order history\n/help - Show this help",
                reply_markup=reply_markup
            )
        
        elif data == "prompt_search":
            keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.delete()
            await query.message.reply_text("Please enter a keyword to search (e.g., /search fifa):", reply_markup=reply_markup)
        
        elif data.startswith("category:"):
            platform = data.split("category:")[1]
            products = get_products_by_platform(platform)
            if products:
                keyboard = []
                for p in products:
                    try:
                        if p['stock'] <= 0:
                            continue
                        price = p['price'] if isinstance(p['price'], str) else str(p['price'])
                        if not price.startswith('$'):
                            try:
                                price = f"${float(price):.2f}"
                            except (ValueError, TypeError):
                                logger.error(f"Invalid price format for product {p.get('id')}: {price}")
                                continue
                        button_text = f"{p['name']} - {price} (Stock: {p['stock']})"
                        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"product:{p['id']}")])
                    except Exception as e:
                        logger.error(f"Error formatting product {p.get('id')} for user {user_id}: {e}, product data: {p}")
                        continue
                if not keyboard:
                    keyboard = [
                        [InlineKeyboardButton("🔙 Back to Catalog", callback_data="show_catalog")],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                    ]
                    await query.message.delete()
                    await query.message.reply_text("No games available in this category.", reply_markup=InlineKeyboardMarkup(keyboard))
                    return
                keyboard.append([InlineKeyboardButton("🔙 Back to Catalog", callback_data="show_catalog")])
                keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.delete()
                await query.message.reply_text(f"Games for *{platform}*:", reply_markup=reply_markup, parse_mode="Markdown")
            else:
                keyboard = [
                    [InlineKeyboardButton("🔙 Back to Catalog", callback_data="show_catalog")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.delete()
                await query.message.reply_text("No games available in this category.", reply_markup=reply_markup)
        
        elif data.startswith("product:"):
            try:
                product_id = int(data.split("product:")[1])
                product = db.get_product(product_id)
                if not product:
                    raise ValueError("Product not found")
                
                image_path = product['image_url']
                keyboard = []
                if product['stock'] > 0:
                    keyboard.append([InlineKeyboardButton("🛒 Add to Cart", callback_data=f"add_to_cart:{product['id']}")])
                keyboard.extend([
                    [InlineKeyboardButton("🔙 Back to Category", callback_data=f"category:{product['platform'][0] if product['platform'] else 'PC'}")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                ])
                caption = (
                    f"*{product['name']}*\n"
                    f"Price: {product['price']}\n"
                    f"Platform: {', '.join(product['platform']) if product['platform'] else 'N/A'}\n"
                    f"Description: {product['description'] or 'No description available'}\n"
                    f"Stock: {product['stock']}"
                )
                try:
                    with open(image_path, 'rb') as img:
                        await query.message.delete()
                        await query.message.reply_photo(
                            photo=InputFile(img),
                            caption=caption,
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                except FileNotFoundError:
                    logger.error(f"Image not found for product {product_id}")
                    await query.message.delete()
                    await query.message.reply_text(
                        f"{caption}\n\n❌ Product image not available.",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
            except (ValueError, sqlite3.Error) as e:
                logger.error(f"Product view error for user {user_id}, product {product_id}: {e}")
                await send_error_message(update, context, "❌ Product not found.")
        
        elif data.startswith("add_to_cart:"):
            try:
                product_id = int(data.split(":")[1])
                product = db.get_product(product_id)
                if not product:
                    raise ValueError("Product not found")
                if product['stock'] <= 0:
                    await query.answer(f"❌ {product['name']} is out of stock.")
                    return
        
                context.user_data['current_product_id'] = product_id
                context.user_data['__CONVERSATION_STATE__'] = 'ASK_QUANTITY'
                logger.info(f"Set current_product_id to {product_id} and state to ASK_QUANTITY for user {user_id}")
                keyboard = [
                    [InlineKeyboardButton("🔙 Back to Product", callback_data=f"product:{product_id}")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.delete()
                await query.message.reply_text(
                    f"How many copies of *{product['name']}* would you like to add? (Enter a number, max {product['stock']}):",
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
                return ASK_QUANTITY
            except (ValueError, sqlite3.Error) as e:
                logger.error(f"Add to cart prompt error for user {user_id}, product {product_id}: {e}")
                await query.answer("❌ Error preparing to add to cart.")
        
        elif data.startswith("remove_from_cart:"):
            try:
                product_id = int(data.split(":")[1])
                db.remove_from_cart(user_id, product_id)
                await query.answer("🗑 Item removed from cart.")
                await view_cart(update, context)
            except sqlite3.Error as e:
                logger.error(f"Remove from cart error for user {user_id}, product {product_id}: {e}")
                await query.answer("❌ Error removing from cart.")
        
        elif data == "view_cart":
            await view_cart(update, context)
        
        elif data == "confirm_checkout":
            keyboard = [
                [InlineKeyboardButton("🔙 Back to Cart", callback_data="view_cart")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.delete()
            await query.message.reply_text("📝 Please enter your full name:", reply_markup=reply_markup)
            return ASK_NAME
        
        elif data == "confirm_details":
            try:
                cart_items = db.get_cart_items(user_id)
                if not cart_items:
                    await send_error_message(update, context, "❌ Your cart is empty.")
                    return ConversationHandler.END
                
                total = sum(float(item['price'].strip('$')) * item['quantity'] for item in cart_items)
                receipt = "🧾 *Please confirm your details:*\n\n"
                receipt += f"*Full Name:* {context.user_data['full_name']}\n"
                receipt += f"*Username:* {context.user_data['username']}\n"
                receipt += f"*Phone:* {context.user_data['phone']}\n"
                receipt += f"*Address:* {context.user_data['address']}\n\n"
                receipt += "*Cart:*\n"
                for i, item in enumerate(cart_items, 1):
                    receipt += f"{i}. {item['name']} - {item['price']} (x{item['quantity']}, Stock: {item['stock']})\n"
                receipt += f"\n*Total:* ${total:.2f}"
                
                keyboard = [
                    [InlineKeyboardButton("✅ Confirm", callback_data="finalize_checkout")],
                    [InlineKeyboardButton("✏️ Edit Details", callback_data="edit_details")],
                    [InlineKeyboardButton("🔙 Back to Cart", callback_data="view_cart")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.delete()
                await query.message.reply_text(receipt, parse_mode="Markdown", reply_markup=reply_markup)
                return CONFIRM_DETAILS
            except sqlite3.Error as e:
                logger.error(f"Confirm details error for user {user_id}: {e}")
                await send_error_message(update, context, "❌ Error loading cart.")
                return ConversationHandler.END
        
        elif data == "finalize_checkout":
            try:
                cart_items = db.get_cart_items(user_id)
                if not cart_items:
                    await send_error_message(update, context, "❌ Your cart is empty.")
                    return ConversationHandler.END
                
                # Save user details
                db.add_or_update_user(
                    user_id=user_id,
                    username=context.user_data['username'],
                    full_name=context.user_data['full_name'],
                    phone=context.user_data['phone'],
                    address=context.user_data['address']
                )
                
                # Create order
                order_id = db.create_order(user_id, cart_items)
                
                total = sum(float(item['price'].strip('$')) * item['quantity'] for item in cart_items)
                receipt = "🧾 *Receipt Summary*\n\n"
                for i, item in enumerate(cart_items, 1):
                    receipt += f"{i}. {item['name']} - {item['price']} (x{item['quantity']})\n"
                receipt += (
                    f"\n*Total:* ${total:.2f}\n"
                    f"*Order ID:* {order_id}\n"
                    f"*Full Name:* {context.user_data['full_name']}\n"
                    f"*Username:* {context.user_data['username']}\n"
                    f"*Phone:* {context.user_data['phone']}\n"
                    f"*Address:* {context.user_data['address']}"
                )
                keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.delete()
                await query.message.reply_text(receipt, parse_mode="Markdown", reply_markup=reply_markup)
                return ConversationHandler.END
            except (ValueError, sqlite3.Error) as e:
                logger.error(f"Finalize checkout error for user {user_id}: {e}")
                await send_error_message(update, context, f"❌ {str(e)}")
                return ConversationHandler.END
        
        elif data == "edit_details":
            keyboard = [
                [InlineKeyboardButton("🔙 Back to Cart", callback_data="view_cart")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.delete()
            await query.message.reply_text("📝 Please enter your full name again:", reply_markup=reply_markup)
            return ASK_NAME
        
        elif data == "view_orders":
            await order_history(update, context)
    
    except Exception as e:
        logger.error(f"Callback error for user {user_id}: {e}")
        await send_error_message(update, context, "❌ An error occurred. Please try again.")
        return ConversationHandler.END

async def ask_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Process user input
    quantity_text = update.message.text
    user_id = update.effective_user.id

    try:
        quantity = int(quantity_text)
        if quantity <= 0:
            raise ValueError("Quantity must be positive.")
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid positive number.")
        return ASK_QUANTITY

    # Store quantity
    context.user_data["quantity"] = quantity
    context.user_data["__CONVERSATION_STATE__"] = "ASK_NAME"

    # Ask for name
    await update.message.reply_text("📝 Please enter your full name:")
    return ASK_NAME
             
async def ask_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle full name input during checkout."""
    user_id = update.effective_user.id
    full_name = update.message.text.strip()
    log_interaction("Full name entered", user_id, f"'{full_name}'")
    
    context.user_data["full_name"] = full_name
    keyboard = [
        [InlineKeyboardButton("🔙 Back to Cart", callback_data="view_cart")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"✅ Full name saved: {full_name}\nPlease enter your Telegram username:",
        reply_markup=reply_markup
    )
    return ASK_USERNAME

async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle username input during checkout."""
    user_id = update.effective_user.id
    username = update.message.text.strip()
    log_interaction("Username entered", user_id, f"'{username}'")
    
    context.user_data["username"] = username
    keyboard = [
        [InlineKeyboardButton("🔙 Back to Cart", callback_data="view_cart")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"✅ Username saved: {username}\nPlease enter your phone number (e.g., +251912345678 or 0912345678):",
        reply_markup=reply_markup
    )
    return ASK_PHONE

async def ask_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle phone number input during checkout."""
    user_id = update.effective_user.id
    phone = update.message.text.strip()
    log_interaction("Phone entered", user_id, f"'{phone}'")
    
    context.user_data["phone"] = phone
    keyboard = [
        [InlineKeyboardButton("🔙 Back to Cart", callback_data="view_cart")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"✅ Phone number saved: {phone}\nPlease enter your delivery address:",
        reply_markup=reply_markup
    )
    return ASK_ADDRESS

async def confirm_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm checkout details."""
    user_id = update.effective_user.id
    address = update.message.text.strip()
    log_interaction("Address entered", user_id, f"'{address}'")
    
    context.user_data["address"] = address
    
    try:
        cart_items = db.get_cart_items(user_id)
        if not cart_items:
            await send_error_message(update, context, "❌ Your cart is empty.")
            return ConversationHandler.END
        
        total = sum(float(item['price'].strip('$')) * item['quantity'] for item in cart_items)
        receipt = "🧾 *Please confirm your details:*\n\n"
        receipt += f"*Full Name:* {context.user_data['full_name']}\n"
        receipt += f"*Username:* {context.user_data['username']}\n"
        receipt += f"*Phone:* {context.user_data['phone']}\n"
        receipt += f"*Address:* {context.user_data['address']}\n\n"
        receipt += "*Cart:*\n"
        for i, item in enumerate(cart_items, 1):
            receipt += f"{i}. {item['name']} - {item['price']} (x{item['quantity']}, Stock: {item['stock']})\n"
        receipt += f"\n*Total:* ${total:.2f}"
        
        keyboard = [
            [InlineKeyboardButton("✅ Confirm", callback_data="finalize_checkout")],
            [InlineKeyboardButton("✏️ Edit Details", callback_data="edit_details")],
            [InlineKeyboardButton("🔙 Back to Cart", callback_data="view_cart")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(receipt, parse_mode="Markdown", reply_markup=reply_markup)
        return CONFIRM_DETAILS
    except sqlite3.Error as e:
        logger.error(f"Confirm details error for user {user_id}: {e}")
        await send_error_message(update, context, "❌ Error loading cart.")
        return ConversationHandler.END

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search for games by keyword."""
    user_id = update.effective_user.id
    log_interaction("Search initiated", user_id)
    
    if not context.args:
        await prompt_search(update, context)
        return
    
    keyword = " ".join(context.args).strip()
    if len(keyword) > 100:
        await update.message.reply_text("❌ Search query too long. Please use a shorter query.")
        return
    
    matches = search_products(keyword)
    if matches:
        keyboard = []
        for p in matches:
            try:
                if p['stock'] <= 0:
                    continue
                price = p['price'] if isinstance(p['price'], str) else str(p['price'])
                if not price.startswith('$'):
                    try:
                        price = f"${float(price):.2f}"
                    except (ValueError, TypeError):
                        logger.error(f"Invalid price format for product {p.get('id')} in search: {price}")
                        continue
                button_text = f"{p['name']} - {price} (Stock: {p['stock']})"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"product:{p['id']}")])
            except Exception as e:
                logger.error(f"Error formatting search result for product {p.get('id')} for user {user_id}: {e}, product data: {p}")
                continue
        if not keyboard:
            keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]
            await update.message.reply_text("No matching games found.", reply_markup=InlineKeyboardMarkup(keyboard))
            return
        keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"Results for *{keyword}*", reply_markup=reply_markup, parse_mode="Markdown")
    else:
        keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("No matching games found.", reply_markup=reply_markup)

async def inline_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline search queries."""
    query = update.inline_query.query
    if not query:
        return
    
    results = []
    matches = search_products(query)
    
    for product in matches:
        if product['stock'] <= 0:
            continue
        try:
            price = product['price'] if isinstance(product['price'], str) else str(product['price'])
            if not price.startswith('$'):
                try:
                    price = f"${float(price):.2f}"
                except (ValueError, TypeError):
                    logger.error(f"Invalid price format for product {product.get('id')} in inline search: {price}")
                    continue
            message = (
                f"*{product['name']}*\n"
                f"Price: {price}\n"
                f"Platform: {', '.join(product['platform']) if product['platform'] else 'N/A'}\n"
                f"Description: {product['description'] or 'No description available'}\n"
                f"Stock: {product['stock']}"
            )
            results.append(
                InlineQueryResultArticle(
                    id=str(uuid.uuid4()),
                    title=f"{product['name']} - {price} (Stock: {product['stock']})",
                    input_message_content=InputTextMessageContent(message, parse_mode="Markdown"),
                    description=product["description"] or "No description available",
                    thumb_url=product["image_url"] or ""
                )
            )
        except Exception as e:
            logger.error(f"Error formatting inline search result for product {product.get('id')}: {e}, product data: {product}")
            continue
    
    await update.inline_query.answer(results, cache_time=1)

async def view_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display the user's cart contents."""
    user_id = update.effective_user.id
    log_interaction("View cart", user_id)
    
    try:
        cart_items = db.get_cart_items(user_id)
    except sqlite3.Error as e:
        logger.error(f"Failed to get cart for user {user_id}: {e}")
        await send_error_message(update, context, "❌ Error loading cart.")
        return
    
    if not cart_items:
        keyboard = [
            [InlineKeyboardButton("📚 Catalog", callback_data="show_catalog")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = "🛒 Your cart is empty."
    else:
        message = "*Your Cart:*\n\n"
        total = 0.0
        keyboard = []
        for i, item in enumerate(cart_items, 1):
            try:
                price = item['price'] if isinstance(item['price'], str) else str(item['price'])
                if not price.startswith('$'):
                    try:
                        price = f"${float(price):.2f}"
                    except (ValueError, TypeError):
                        logger.error(f"Invalid price format for cart item {item.get('id')} for user {user_id}: {price}")
                        continue
                price_value = float(price.strip('$')) * item['quantity']
                total += price_value
                message += f"{i}. {item['name']} - {price} (Qty: {item['quantity']}, Stock: {item['stock']})\n"
                keyboard.append([
                    InlineKeyboardButton(f"❌ Remove {item['name']}", callback_data=f"remove_from_cart:{item['id']}")
                ])
            except Exception as e:
                logger.error(f"Error formatting cart item {item.get('id')} for user {user_id}: {e}, item data: {item}")
                continue
        message += f"\n*Total:* ${total:.2f}"
        keyboard.append([InlineKeyboardButton("✅ Checkout", callback_data="confirm_checkout")])
        keyboard.append([InlineKeyboardButton("📚 Catalog", callback_data="show_catalog")])
        keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.message.edit_text(
            message,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            message,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )

async def order_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display the user's order history."""
    user_id = update.effective_user.id
    log_interaction("View orders", user_id)
    
    try:
        orders = db.get_user_orders(user_id)
    except sqlite3.Error as e:
        logger.error(f"Failed to get orders for user {user_id}: {e}")
        await send_error_message(update, context, "❌ Error loading orders.")
        return
    
    if not orders:
        keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            if update.callback_query:
                await update.callback_query.message.delete()
                await update.callback_query.message.reply_text(
                    "📦 You don't have any orders yet.",
                    reply_markup=reply_markup
                )
            else:
                await update.message.reply_text(
                    "📦 You don't have any orders yet.",
                    reply_markup=reply_markup
                )
        except Exception as e:
            logger.error(f"Error displaying empty order history for user {user_id}: {e}")
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="📦 You don't have any orders yet.",
                reply_markup=reply_markup
            )
        return
    
    message = "📦 *Your Order History:*\n\n"
    for order in orders:
        try:
            message += (
                f"🆔 *Order ID:* {order['order_id']}\n"
                f"📅 *Date:* {order['order_date']}\n"
                f"💰 *Total:* ${order['total_amount']:.2f}\n"
                f"📦 *Items:*\n"
            )
            if not order['items']:
                message += "  No items in this order.\n"
            else:
                for item in order['items']:
                    price = item['price'] if isinstance(item['price'], str) else str(item['price'])
                    if not price.startswith('$'):
                        try:
                            price = f"${float(price):.2f}"
                        except (ValueError, TypeError):
                            logger.error(f"Invalid price format in order history for item {item.get('name')} for user {user_id}: {price}")
                            price = "$0.00"
                    message += f"  - {item['name']} - {price} (x{item['quantity']})\n"
            message += f"📌 *Status:* {order['status']}\n\n"
        except Exception as e:
            logger.error(f"Error formatting order {order.get('order_id')} for user {user_id}: {e}, order data: {order}")
            continue
    
    keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        if update.callback_query:
            await update.callback_query.message.delete()
            await update.callback_query.message.reply_text(
                message,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                message,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"Error displaying order history for user {user_id}: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors during bot operation."""
    error = str(context.error)
    user_id = update.effective_user.id if update.effective_user else None
    
    logger.error(f"Error for user {user_id}: {error}")
    await send_error_message(update, context, "❌ An error occurred. Please try again or return to /menu.")

async def debug_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text
    state = context.user_data.get('__CONVERSATION_STATE__', 'None')
    logger.info(f"Global message received from user {user_id}: '{message_text}', state: {state}")
    if state == 'ASK_QUANTITY' and not message_text.startswith('/'):
        logger.error(f"Message '{message_text}' not handled by ASK_QUANTITY handler for user {user_id}")
        await update.message.reply_text(
            "❌ Input not processed. Please try again or use /cancel.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Product", callback_data=f"product:{context.user_data.get('current_product_id', 'unknown')}")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ])
        )
        context.user_data.pop('current_product_id', None)
        context.user_data.pop('__CONVERSATION_STATE__', None)
        return ConversationHandler.END
    
async def debug_state(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = context.user_data.get('__CONVERSATION_STATE__', 'None')
    product_id = context.user_data.get('current_product_id', 'None')
    logger.info(f"Debug state for user {user_id}: state={state}, product_id={product_id}")
    await update.message.reply_text(f"Current state: {state}, Product ID: {product_id}")

async def handle_quantity_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message_text = update.message.text
    state = context.user_data.get('__CONVERSATION_STATE__', 'None')
    logger.info(f"Global fallback handler received from user {user_id}: '{message_text}', state: {state}")
    if state == 'ASK_QUANTITY':
        logger.info(f"Processing ASK_QUANTITY input '{message_text}' for user {user_id} via global fallback")
        await ask_quantity(update, context)
    else:
        logger.info(f"Ignoring message '{message_text}' for user {user_id} in state {state}")

async def shutdown(application):
    """Close database connection on shutdown."""
    db.close()
    logger.info("Bot shutting down...")

from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
import asyncio

async def main():
    """Run the bot."""
    # Initialize application with BOT_TOKEN
    application = Application.builder().token(BOT_TOKEN).build()

    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CommandHandler("catalog", catalog))
    application.add_handler(CommandHandler("cart", view_cart))
    application.add_handler(CommandHandler("checkout", checkout))
    application.add_handler(CommandHandler("cancel", cancel_checkout))
    application.add_handler(CommandHandler("debug_state", debug_state))
    application.add_handler(CommandHandler("help", help))
    application.add_handler(CommandHandler("search", search))
    application.add_handler(CommandHandler("orders", order_history))
    
    # Add callback query handler
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # Add inline query handler
    application.add_handler(InlineQueryHandler(inline_search))
    
    # Add error handler
    application.add_error_handler(error_handler)

    # Conversation handler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("checkout", checkout),
            CallbackQueryHandler(handle_callback, pattern="^confirm_checkout$"),
            CallbackQueryHandler(handle_callback, pattern="^add_to_cart:")
        ],
        states={
            ASK_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_quantity)],
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_username)],
            ASK_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_address)],
            ASK_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_details)],
            CONFIRM_DETAILS: [CallbackQueryHandler(handle_callback)]
        },
        fallbacks=[
            CommandHandler("cancel", cancel_checkout),
            CallbackQueryHandler(handle_callback, pattern="^main_menu$")
        ],
        per_chat=True,
        per_user=True,
        per_message=False
    )
    application.add_handler(conv_handler)

    # Run the bot until the user presses Ctrl-C
    await application.run_polling()

if __name__ == "__main__":
    # Configure Windows event loop policy first
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Critical error: {str(e)}")
    finally:
        # Clean up resources
        db.close()