# Corrected User/handlers.py for Async Telegram & Sync DB

import logging
import sqlite3 # Use synchronous sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
# Import the synchronous Database class
from .database import Database as UserDatabase
from .config import CATEGORIES
from .utils import format_price, is_valid_ethiopian_phone
import re
import os
import json # For handling platform JSON
from typing import Optional, List, Dict, Any
from datetime import datetime

# Logger setup
logger = logging.getLogger(__name__)

# Conversation states for order process
SELECT_QUANTITY, CONFIRM_ORDER, COLLECT_NAME, COLLECT_EMAIL, COLLECT_PHONE, COLLECT_ADDRESS = range(6)

# --- Database Helper --- 
def get_db(context: ContextTypes.DEFAULT_TYPE) -> Optional[UserDatabase]:
    """Gets the UserDatabase instance from bot_data."""
    db = context.bot_data.get("user_db")
    if not isinstance(db, UserDatabase):
        logger.error("UserDatabase instance not found or invalid in bot_data.")
        return None
    return db

# --- Command Handlers (Must be async) --- 

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    user = update.effective_user
    db = get_db(context)
    if not db:
        await update.message.reply_text("Error: Bot database is not configured.")
        return

    try:
        db.connect() # Sync DB connect
        db.add_user(
            user_id=user.id,
            username=user.username or "N/A",
            first_name=user.first_name or "",
            last_name=user.last_name or ""
        )
        logger.info(f"User {user.id} added/updated.")
    except Exception as e:
        logger.error(f"Failed to add user {user.id} to database: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ An error occurred while initializing your account. Please try again later.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
        )
        return
    finally:
        if db: db.disconnect() # Sync DB disconnect

    keyboard = [
        [InlineKeyboardButton(category, callback_data=f"platform:{category}") for category in CATEGORIES],
        [InlineKeyboardButton("🛒 View Cart", callback_data="view_cart")],
        [InlineKeyboardButton("🔍 Search Games", switch_inline_query_current_chat="")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"Welcome {user.first_name}! Browse games by platform, view your cart, or search.",
        reply_markup=reply_markup
    )

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /search command."""
    await update.message.reply_text(
        "🔍 To search for games, use inline mode: type my username then your query (e.g., `@YourBotName FC 24`) in any chat, or click below.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Start Search Here", switch_inline_query_current_chat="")]
        ])
    )
    logger.info(f"User {update.effective_user.id} triggered /search command")

async def cart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /cart command. Displays cart contents."""
    user_id = update.effective_user.id
    db = get_db(context)
    if not db:
        await update.message.reply_text("Error: Bot database is not configured.")
        return

    cart_items = []
    total_price = 0
    try:
        db.connect() # Sync DB connect
        cart_items = db.get_cart(user_id)
        if cart_items:
            total_price = sum(float(item["price"]) * item["quantity"] for item in cart_items)
    except Exception as e:
        logger.error(f"Error fetching cart for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("❌ Error retrieving your cart.")
        return
    finally:
        if db: db.disconnect() # Sync DB disconnect

    if not cart_items:
        await update.message.reply_text(
            "Your cart is empty. Browse games with /start or search!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
        )
        return

    cart_text = "🛒 **Your Cart:**\n\n"
    keyboard = []
    for item in cart_items:
        try: platform_display = json.loads(item["platform"])[0]
        except: platform_display = item["platform"]
        item_price = float(item["price"])
        item_total = item_price * item["quantity"]
        cart_text += (
            f"🎮 **{item["name"]}** ({platform_display})\n"
            f"   Quantity: {item["quantity"]}\n"
            f"   Price: {format_price(item_price)} each\n"
            f"   Subtotal: {format_price(item_total)}\n\n"
        )
        keyboard.append([InlineKeyboardButton(f"❌ Remove {item["name"]}", callback_data=f"remove_from_cart:{item["product_id"]}")])

    cart_text += f"💰 **Total: {format_price(total_price)}**"
    keyboard.extend([
        [InlineKeyboardButton("✅ Confirm Order", callback_data="confirm_order")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ])
    await update.message.reply_text(cart_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

# --- Callback Query Handler (Must be async) --- 

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Handle callback queries from inline buttons."""
    query = update.callback_query
    await query.answer() # Acknowledge callback

    db = get_db(context)
    if not db:
        # Need await here for the Telegram API call
        await query.edit_message_text("Error: Bot database is not configured.")
        return ConversationHandler.END # End conversation if DB fails

    data = query.data
    user_id = query.from_user.id
    is_inline = bool(query.inline_message_id)
    message = query.message # The message the button was attached to

    logger.info(f"Handling callback for user {user_id}, data: {data}, inline: {is_inline}")

    # --- Helper to Edit Message (Must be async) --- 
    async def edit_message(text: str, reply_markup: Optional[InlineKeyboardMarkup] = None, parse_mode: Optional[str] = None) -> None:
        """Safely edits the original message (inline, photo caption, or regular)."""
        try:
            if is_inline:
                await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
            elif message:
                if message.photo:
                    await message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
                else:
                    await message.edit_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except TelegramError as e:
            if "Message is not modified" not in str(e):
                logger.error(f"Error editing message for user {user_id}: {e}", exc_info=True)

    # --- Callback Logic --- 
    next_state = None # Default to staying in the same state or ending
    try:
        db.connect() # Sync DB connect

        if data == "main_menu":
            keyboard = [
                [InlineKeyboardButton(category, callback_data=f"platform:{category}") for category in CATEGORIES],
                [InlineKeyboardButton("🛒 View Cart", callback_data="view_cart")],
                [InlineKeyboardButton("🔍 Search Games", switch_inline_query_current_chat="")]
            ]
            await edit_message(
                "Browse games by platform, view your cart, or search.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            next_state = ConversationHandler.END

        elif data == "view_cart":
            cart_items = db.get_cart(user_id)
            if not cart_items:
                await edit_message(
                    "Your cart is empty. Browse games or search!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
                )
            else:
                total_price = sum(float(item["price"]) * item["quantity"] for item in cart_items)
                cart_text = "🛒 **Your Cart:**\n\n"
                keyboard = []
                for item in cart_items:
                    try: platform_display = json.loads(item["platform"])[0]
                    except: platform_display = item["platform"]
                    item_price = float(item["price"])
                    item_total = item_price * item["quantity"]
                    cart_text += (
                        f"🎮 **{item["name"]}** ({platform_display})\n"
                        f"   Quantity: {item["quantity"]}\n"
                        f"   Price: {format_price(item_price)} each\n"
                        f"   Subtotal: {format_price(item_total)}\n\n"
                    )
                    keyboard.append([InlineKeyboardButton(f"❌ Remove {item["name"]}", callback_data=f"remove_from_cart:{item["product_id"]}")])
                cart_text += f"💰 **Total: {format_price(total_price)}**"
                keyboard.extend([
                    [InlineKeyboardButton("✅ Confirm Order", callback_data="confirm_order")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                ])
                await edit_message(cart_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

        elif data.startswith("platform:"):
            platform_name = data.split(":", 1)[1]
            products = db.get_products_by_platform(platform_name)
            if not products:
                await edit_message(
                    f"No games found for {platform_name}. Try another platform!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
                )
            else:
                keyboard = [
                    [InlineKeyboardButton(product["name"], callback_data=f"product:{product["id"]}")]
                    for product in products
                ]
                keyboard.append([InlineKeyboardButton("🔙 Back to Platforms", callback_data="main_menu")])
                await edit_message(
                    f"Games for **{platform_name}**:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.MARKDOWN
                )

        elif data.startswith("product:"):
            product_id = int(data.split(":", 1)[1])
            product = db.get_product(product_id)
            if not product:
                await edit_message(
                    "Product not found. It might be out of stock or removed.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
                )
            else:
                try: platform_display = json.loads(product["platform"])[0]
                except: platform_display = product["platform"]
                caption = (
                    f"🎮 **{product["name"]}**\n"
                    f"Platform: {platform_display}\n"
                    f"Price: {format_price(product["price"])}\n"
                    f"Stock: {product["stock"]}\n\n"
                    f"{product["description"] or "No description available."}"
                )
                keyboard = [
                    [InlineKeyboardButton("🛒 Add to Cart", callback_data=f"add_to_cart:{product_id}")],
                    [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                image_path_relative = product.get("image_url", "images/default.jpg")
                image_path_abs = os.path.join(os.path.dirname(__file__), os.pardir, image_path_relative)
                default_image_abs = os.path.join(os.path.dirname(__file__), os.pardir, "images/default.jpg")
                image_to_send = default_image_abs
                if os.path.exists(image_path_abs):
                    image_to_send = image_path_abs
                elif not os.path.exists(default_image_abs):
                    logger.warning(f"Product image {image_path_abs} and default {default_image_abs} not found.")
                    await edit_message(f"{caption}\n\n⚠️ Image not available.", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
                    return next_state
                try:
                    with open(image_to_send, "rb") as photo_file:
                        if message and not message.photo:
                            await message.reply_photo(
                                photo=photo_file,
                                caption=caption,
                                reply_markup=reply_markup,
                                parse_mode=ParseMode.MARKDOWN
                            )
                            try: await message.delete()
                            except TelegramError as e: logger.warning(f"Could not delete old text message: {e}")
                        elif message and message.photo:
                             await message.edit_caption(caption=caption, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
                        else:
                             await context.bot.send_photo(
                                chat_id=user_id,
                                photo=photo_file,
                                caption=caption,
                                reply_markup=reply_markup,
                                parse_mode=ParseMode.MARKDOWN
                            )
                except (FileNotFoundError, TelegramError) as e:
                    logger.error(f"Error sending image {image_to_send} for product {product_id}: {e}", exc_info=True)
                    await edit_message(f"{caption}\n\n⚠️ Image could not be sent.", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

        elif data.startswith("add_to_cart:"):
            product_id = int(data.split(":", 1)[1])
            product = db.get_product(product_id)
            if not product or product["stock"] <= 0:
                await edit_message(
                    "Sorry, this product is out of stock or unavailable.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
                )
            else:
                context.user_data["selected_product_id"] = product_id
                await edit_message(
                    f"Selected **{product["name"]}**. Please reply with the quantity you want to add (1-{product["stock"]}).",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="cancel_op")]])
                )
                next_state = SELECT_QUANTITY

        elif data.startswith("remove_from_cart:"):
            product_id = int(data.split(":", 1)[1])
            success = db.remove_from_cart(user_id, product_id)
            if success:
                await query.answer("Item removed from cart.")
                cart_items = db.get_cart(user_id)
                if not cart_items:
                    await edit_message("Cart is now empty.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]) )
                else:
                    total_price = sum(float(item["price"]) * item["quantity"] for item in cart_items)
                    cart_text = "🛒 **Your Cart:**\n\n"
                    keyboard = []
                    for item in cart_items:
                        try: platform_display = json.loads(item["platform"])[0]
                        except: platform_display = item["platform"]
                        item_price = float(item["price"])
                        item_total = item_price * item["quantity"]
                        cart_text += f"🎮 **{item["name"]}** ({platform_display})\n   Qty: {item["quantity"]} @ {format_price(item_price)} = {format_price(item_total)}\n\n"
                        keyboard.append([InlineKeyboardButton(f"❌ Remove {item["name"]}", callback_data=f"remove_from_cart:{item["product_id"]}")])
                    cart_text += f"💰 **Total: {format_price(total_price)}**"
                    keyboard.extend([
                        [InlineKeyboardButton("✅ Confirm Order", callback_data="confirm_order")],
                        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                    ])
                    await edit_message(cart_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
            else:
                await query.answer("Error removing item.", show_alert=True)

        elif data == "confirm_order":
            cart_items = db.get_cart(user_id)
            if not cart_items:
                await edit_message("Your cart is empty.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]) )
            else:
                stock_ok = True
                for item in cart_items:
                    product = db.get_product(item["product_id"])
                    if not product or product["stock"] < item["quantity"]:
                        stock_ok = False
                        await edit_message(f"⚠️ Insufficient stock for **{item["name"]}**. Available: {product["stock"] if product else 0}. Please remove it or reduce quantity.", parse_mode=ParseMode.MARKDOWN)
                        break
                if stock_ok:
                    total_price = sum(float(item["price"]) * item["quantity"] for item in cart_items)
                    context.user_data["total_price"] = total_price
                    context.user_data["cart_items"] = cart_items
                    await edit_message(
                        "To complete your order, please provide your full name.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel Order", callback_data="cancel_order")]])
                    )
                    next_state = COLLECT_NAME

        elif data == "cancel_order":
            context.user_data.clear()
            await edit_message("Order cancelled.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]) )
            next_state = ConversationHandler.END
            
        elif data == "cancel_op":
            context.user_data.pop("selected_product_id", None)
            await edit_message("Operation cancelled.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]) )
            next_state = ConversationHandler.END

    except Exception as e:
        logger.error(f"Error in handle_callback for user {user_id}, data {data}: {e}", exc_info=True)
        try:
            await edit_message("❌ An unexpected error occurred. Please try again later.")
        except Exception as inner_e:
            logger.error(f"Failed to send error message to user {user_id}: {inner_e}")
        next_state = ConversationHandler.END
    finally:
        if db: db.disconnect() # Sync DB disconnect

    return next_state

# --- Conversation Handlers (Must be async) --- 

async def select_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Handle quantity input during the add-to-cart conversation."""
    user_id = update.effective_user.id
    product_id = context.user_data.get("selected_product_id")
    message = update.message

    if not product_id:
        await message.reply_text("❌ No product selected. Please try adding again.")
        return ConversationHandler.END

    db = get_db(context)
    if not db:
        await message.reply_text("Error: Bot database is not configured.")
        return ConversationHandler.END

    next_state = SELECT_QUANTITY
    try:
        db.connect() # Sync DB connect
        product = db.get_product(product_id)
        if not product:
            await message.reply_text("❌ Product not found.")
            next_state = ConversationHandler.END
        else:
            quantity_text = message.text.strip()
            try:
                quantity = int(quantity_text)
                if quantity <= 0:
                    await message.reply_text("Quantity must be positive. Please enter a valid number.")
                elif quantity > product["stock"]:
                    await message.reply_text(f"Only {product["stock"]} units available. Please enter a lower quantity.")
                else:
                    success = db.add_to_cart(user_id, product_id, quantity)
                    if success:
                        await message.reply_text(
                            f"✅ Added {quantity} unit(s) of **{product["name"]}** to your cart.",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🛒 View Cart", callback_data="view_cart")],
                                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
                            ]),
                            parse_mode=ParseMode.MARKDOWN
                        )
                        context.user_data.pop("selected_product_id", None)
                        next_state = ConversationHandler.END
                    else:
                        await message.reply_text("❌ Error adding item to cart. Please try again.")
                        next_state = ConversationHandler.END
            except ValueError:
                await message.reply_text("Invalid input. Please enter a number.")
            except Exception as e:
                 logger.error(f"Error processing quantity for user {user_id}: {e}", exc_info=True)
                 await message.reply_text("❌ An error occurred.")
                 next_state = ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in select_quantity for user {user_id}: {e}", exc_info=True)
        await message.reply_text("❌ An unexpected error occurred.")
        next_state = ConversationHandler.END
    finally:
        if db: db.disconnect() # Sync DB disconnect

    return next_state

async def collect_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Collect user\s full name for the order."""
    user_id = update.effective_user.id
    cart_items = context.user_data.get("cart_items")
    message = update.message

    if not cart_items:
        logger.warning(f"User {user_id} reached COLLECT_NAME without cart items in context.")
        await message.reply_text("❌ No order in progress. Please view your cart first.")
        return ConversationHandler.END

    name = message.text.strip()
    if not name or len(name) < 3:
        await message.reply_text(
            "❌ Please provide a valid full name.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel Order", callback_data="cancel_order")]])
        )
        return COLLECT_NAME

    context.user_data["user_details"] = {"name": name}
    logger.info(f"Collected name for user {user_id}: {name}")
    await message.reply_text(
        "Please provide your email address.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel Order", callback_data="cancel_order")]])
    )
    return COLLECT_EMAIL

async def collect_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Collect user\s email address."""
    user_id = update.effective_user.id
    user_details = context.user_data.get("user_details")
    message = update.message

    if not user_details or "name" not in user_details:
        logger.warning(f"User {user_id} reached COLLECT_EMAIL without name in context.")
        await message.reply_text("❌ Order process error. Please start again.")
        return ConversationHandler.END

    email = message.text.strip()
    if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$	", email):
        await message.reply_text(
            "❌ Invalid email format. Please provide a valid email address (e.g., user@example.com).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel Order", callback_data="cancel_order")]])
        )
        return COLLECT_EMAIL

    context.user_data["user_details"]["email"] = email
    logger.info(f"Collected email for user {user_id}: {email}")
    await message.reply_text(
        "Please provide your Ethiopian phone number (e.g., 0912345678 or +251912345678).",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel Order", callback_data="cancel_order")]])
    )
    return COLLECT_PHONE

async def collect_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Collect user\s phone number."""
    user_id = update.effective_user.id
    user_details = context.user_data.get("user_details")
    message = update.message

    if not user_details or "email" not in user_details:
        logger.warning(f"User {user_id} reached COLLECT_PHONE without email in context.")
        await message.reply_text("❌ Order process error. Please start again.")
        return ConversationHandler.END

    phone = message.text.strip()
    if not is_valid_ethiopian_phone(phone):
        await message.reply_text(
            "⚠️ Please enter a valid Ethiopian phone number (09... or +2519...).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel Order", callback_data="cancel_order")]])
        )
        return COLLECT_PHONE

    context.user_data["user_details"]["phone_number"] = phone
    logger.info(f"Collected phone for user {user_id}: {phone}")
    await message.reply_text(
        "Finally, please provide your full delivery address (City, Subcity, Woreda, House No./Specific Location).",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel Order", callback_data="cancel_order")]])
    )
    return COLLECT_ADDRESS

async def collect_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Collect address, create order in DB, clear cart, send receipt."""
    user_id = update.effective_user.id
    user_details = context.user_data.get("user_details")
    cart_items = context.user_data.get("cart_items")
    total_price = context.user_data.get("total_price")
    message = update.message

    if not all([user_details, cart_items, total_price is not None]):
        logger.warning(f"User {user_id} reached COLLECT_ADDRESS with incomplete context.")
        await message.reply_text("❌ Order process error. Please start again.")
        return ConversationHandler.END

    address = message.text.strip()
    if not address or len(address) < 10:
        await message.reply_text(
            "❌ Please provide a more detailed delivery address.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel Order", callback_data="cancel_order")]])
        )
        return COLLECT_ADDRESS

    user_details["delivery_address"] = address
    user_details["telegram_username"] = update.effective_user.username or "N/A"

    db = get_db(context)
    if not db:
        await message.reply_text("Error: Bot database is not configured.")
        return ConversationHandler.END

    order_id = None
    try:
        db.connect() # Sync DB connect
        order_id = db.create_order(user_id, total_price, cart_items, user_details)
        if order_id is None:
            await message.reply_text(
                "❌ Failed to create order. This might be due to stock changes. Please check your cart and try again.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 View Cart", callback_data="view_cart")]])
            )
            return ConversationHandler.END
        logger.info(f"Order {order_id} created and finalized for user {user_id}.")
        receipt = (
            f"🧾 **Order Receipt #{order_id}**\n"
            f"Date: {datetime.now().strftime("%Y-%m-%d %H:%M")}\n\n"
            f"**Customer Details:**\n"
            f" Name: {user_details["name"]}\n"
            f" Email: {user_details["email"]}\n"
            f" Phone: {user_details["phone_number"]}\n"
            f" Address: {user_details["delivery_address"]}\n"
            f" Telegram: @{user_details["telegram_username"]}\n\n"
            f"**Items:**\n"
        )
        for item in cart_items:
            try: platform_display = json.loads(item["platform"])[0]
            except: platform_display = item["platform"]
            item_price = float(item["price"])
            item_total = item_price * item["quantity"]
            receipt += (
                f" 🎮 {item["name"]} ({platform_display})\n"
                f"    Qty: {item["quantity"]} @ {format_price(item_price)} = {format_price(item_total)}\n"
            )
        receipt += (
            f"\n💰 **Total: {format_price(total_price)}**\n\n"
            "Thank you for your purchase! Your order is being processed. We will contact you soon."
        )
        await message.reply_text(
            receipt,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
        )
        context.user_data.clear()
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error finalizing order for user {user_id} (Order ID might be {order_id}): {e}", exc_info=True)
        if order_id and db.conn:
            try: db.cancel_order(order_id)
            except: pass
        await message.reply_text(
            "❌ An unexpected error occurred while finalizing your order. Please contact support if issues persist.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
        )
        return ConversationHandler.END
    finally:
        if db: db.disconnect() # Sync DB disconnect

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Generic cancel handler for conversations."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} cancelled conversation.")
    context.user_data.clear()
    reply_target = update.message or update.callback_query.message
    if reply_target:
        await reply_target.reply_text(
            "Operation cancelled.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
        )
    return ConversationHandler.END

# --- Inline Query Handler (Must be async) --- 

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline queries for searching products."""
    query_text = update.inline_query.query
    user_id = update.inline_query.from_user.id
    logger.info(f"Received inline query from user {user_id}: 	{query_text}	")

    if not query_text or len(query_text) < 2:
        await update.inline_query.answer([], cache_time=10, switch_pm_text="Type 2+ chars to search games", switch_pm_parameter="search_help")
        return

    db = get_db(context)
    if not db:
        logger.error("Inline query failed: DB not configured.")
        await update.inline_query.answer([], cache_time=5)
        return

    results = []
    try:
        db.connect() # Sync DB connect
        products = db.search_products(query_text)
        logger.info(f"Found {len(products)} products for inline query 	{query_text}	")
        for product in products:
            try: platform_display = json.loads(product["platform"])[0]
            except: platform_display = product["platform"]
            thumb_url = None # Needs public URL for thumbnail
            results.append(
                InlineQueryResultArticle(
                    id=str(product["id"]),
                    title=f"{product["name"]} ({platform_display})",
                    description=f"{format_price(product["price"])} - Stock: {product["stock"]}\n{product["description"][:50]}...",
                    input_message_content=InputTextMessageContent(
                        f"Check out this game: **{product["name"]}**!",
                        parse_mode=ParseMode.MARKDOWN
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        # Note: Callback data triggers handle_callback
                        [InlineKeyboardButton("🛒 Add to Cart", callback_data=f"add_to_cart:{product["id"]}")],
                        [InlineKeyboardButton("ℹ️ View Details", callback_data=f"product:{product["id"]}")]
                    ]),
                    thumbnail_url=thumb_url,
                )
            )
    except Exception as e:
        logger.error(f"Error processing inline query 	{query_text}	 for user {user_id}: {e}", exc_info=True)
    finally:
        if db: db.disconnect() # Sync DB disconnect

    await update.inline_query.answer(results[:50], cache_time=10)

# --- Error Handler (Must be async) --- 

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log Errors caused by Updates."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    # Add user notification if appropriate and possible
    if isinstance(update, Update) and update.effective_user:
        try:
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text="Sorry, an internal error occurred. Please try again later or contact support."
            )
        except Exception as e:
            logger.error(f"Failed to send error message to user {update.effective_user.id}: {e}")

# --- Handler Definitions --- 
# Ensure all handlers passed to TelegramApplication are async
command_handlers = [
    CommandHandler("start", start),
    CommandHandler("search", search_command),
    CommandHandler("cart", cart_command),
    CommandHandler("cancel", cancel_conversation),
]

callback_query_handler = CallbackQueryHandler(handle_callback)
inline_query_handler = InlineQueryHandler(inline_query)

conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(handle_callback)],
    states={
        SELECT_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_quantity)],
        COLLECT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_name)],
        COLLECT_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_email)],
        COLLECT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_phone)],
        COLLECT_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_address)],
    },
    fallbacks=[
        CallbackQueryHandler(handle_callback),
        CommandHandler("cancel", cancel_conversation),
        CommandHandler("start", start),
    ],
    allow_reentry=True,
)

