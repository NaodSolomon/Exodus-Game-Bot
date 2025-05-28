import logging
import aiosqlite
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
from telegram.error import TelegramError
from database import Database
from catalog import get_products_by_platform, get_product_by_id, search_products
from config import CATEGORIES
from utils import format_price, is_valid_ethiopian_phone
import re
import os
from typing import Optional

# Logger setup
logger = logging.getLogger(__name__)

# Conversation states
SELECT_QUANTITY, CONFIRM_ORDER, COLLECT_NAME, COLLECT_EMAIL, COLLECT_PHONE, COLLECT_ADDRESS = range(6)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    db = context.bot_data.get('db')
    if not db:
        db = Database()
        context.bot_data['db'] = db
    
    user = update.effective_user
    try:
        await db.add_user(
            user_id=user.id,
            username=user.username or "N/A",
            first_name=user.first_name or "",
            last_name=user.last_name or ""
        )
    except Exception as e:
        logger.error(f"Failed to add user {user.id} to database: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ An error occurred while initializing your account. Please try again later.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
        )
        return
    
    keyboard = [
        [InlineKeyboardButton(category, callback_data=f"platform:{category}") for category in CATEGORIES],
        [InlineKeyboardButton("🛒 View Cart", callback_data="view_cart")],
        [InlineKeyboardButton("🔍 Search Games", switch_inline_query_current_chat="")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Welcome to Exodus Game Store! Browse games by platform, view your cart, or search for games.",
        reply_markup=reply_markup
    )

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /search command."""
    await update.message.reply_text(
        "🔍 To search for games, use inline mode by typing '@BotName <game>' (e.g., '@BotName FC 25') "
        "in any chat, or click below to start a search.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Start Search", switch_inline_query_current_chat="")]
        ])
    )
    logger.info(f"User {update.effective_user.id} triggered /search command")

async def cart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /cart command."""
    db = context.bot_data.get('db')
    if not db:
        db = Database()
        context.bot_data['db'] = db
    
    user_id = update.effective_user.id
    cart_items = await db.get_cart(user_id)
    
    if not cart_items:
        await update.message.reply_text(
            "Your cart is empty. Browse games with /start or search with /search!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
        )
        return
    
    total_price = 0
    cart_text = "🛒 Your Cart:\n\n"
    keyboard = []
    for item in cart_items:
        item_price = float(item['price'])
        item_total = item_price * item['quantity']
        total_price += item_total
        cart_text += (
            f"🎮 {item['name']} ({', '.join(item['platform'])})\n"
            f"Quantity: {item['quantity']}\n"
            f"Price: {format_price(item_price)} each\n"
            f"Subtotal: {format_price(item_total)}\n\n"
        )
        keyboard.append([InlineKeyboardButton(f"❌ Remove {item['name']}", callback_data=f"remove_from_cart:{item['product_id']}")])
    
    cart_text += f"💰 Total: {format_price(total_price)}"
    keyboard.extend([
        [InlineKeyboardButton("✅ Confirm Order", callback_data="confirm_order")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ])
    await update.message.reply_text(cart_text, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Handle callback queries."""
    query = update.callback_query
    await query.answer()
    
    db = context.bot_data.get('db')
    if not db:
        db = Database()
        context.bot_data['db'] = db
    
    data = query.data
    user_id = query.from_user.id
    is_inline = bool(query.inline_message_id)
    is_photo = query.message.photo if query.message else False
    logger.info(f"Handling callback for user {user_id}, data: {data}, inline: {is_inline}, is_photo: {is_photo}")
    
    async def edit_or_reply(text: str, reply_markup: Optional[InlineKeyboardMarkup] = None) -> None:
        """Helper to edit inline message, photo caption, or reply in chat."""
        try:
            if is_inline:
                await query.edit_message_text(text=text, reply_markup=reply_markup)
            elif is_photo:
                await query.message.edit_caption(caption=text, reply_markup=reply_markup)
            elif query.message:
                await query.message.edit_text(text=text, reply_markup=reply_markup)
            else:
                await context.bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup)
        except TelegramError as e:
            logger.error(f"Error editing/replying for user {user_id}: {e}", exc_info=True)
            raise
    
    if data == "main_menu":
        keyboard = [
            [InlineKeyboardButton(category, callback_data=f"platform:{category}") for category in CATEGORIES],
            [InlineKeyboardButton("🛒 View Cart", callback_data="view_cart")],
            [InlineKeyboardButton("🔍 Search Games", switch_inline_query_current_chat="")]
        ]
        await edit_or_reply(
            "Browse games by platform, view your cart, or search for games.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return None
    
    elif data == "view_cart":
        cart_items = await db.get_cart(user_id)
        
        if not cart_items:
            await edit_or_reply(
                "Your cart is empty. Browse games or search!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
            )
            return None
        
        total_price = 0
        cart_text = "🛒 Your Cart:\n\n"
        keyboard = []
        for item in cart_items:
            item_price = float(item['price'])
            item_total = item_price * item['quantity']
            total_price += item_total
            cart_text += (
                f"🎮 {item['name']} ({', '.join(item['platform'])})\n"
                f"Quantity: {item['quantity']}\n"
                f"Price: {format_price(item_price)} each\n"
                f"Subtotal: {format_price(item_total)}\n\n"
            )
            keyboard.append([InlineKeyboardButton(f"❌ Remove {item['name']}", callback_data=f"remove_from_cart:{item['product_id']}")])
        
        cart_text += f"💰 Total: {format_price(total_price)}"
        keyboard.extend([
            [InlineKeyboardButton("✅ Confirm Order", callback_data="confirm_order")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
        ])
        await edit_or_reply(cart_text, reply_markup=InlineKeyboardMarkup(keyboard))
        return CONFIRM_ORDER
    
    elif data.startswith("platform:"):
        platform = data.split(":", 1)[1]
        products = await get_products_by_platform(platform, db)
        
        if not products:
            await edit_or_reply(
                f"No games found for {platform}. Try another platform!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
            )
            return None
        
        keyboard = [
            [InlineKeyboardButton(product['name'], callback_data=f"product:{product['id']}")]
            for product in products
        ]
        keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])
        await edit_or_reply(
            f"Games for {platform}:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return None
    
    elif data.startswith("product:"):
        product_id = int(data.split(":", 1)[1])
        product = await get_product_by_id(product_id, db)
        
        if not product:
            await edit_or_reply(
                "Product not found. Try browsing again!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
            )
            return None
        
        caption = (
            f"🎮 {product['name']}\n"
            f"Platform: {', '.join(product['platform'])}\n"
            f"Price: {format_price(product['price'])}\n"
            f"Stock: {product['stock']}\n"
            f"Description: {product['description']}"
        )
        keyboard = [
            [InlineKeyboardButton("🛒 Add to Cart", callback_data=f"add_to_cart:{product_id}")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
        ]
        
        try:
            image_path = os.path.join(os.path.dirname(__file__), product['image_url'])
            logger.info(f"Attempting to load image for product {product_id} at: {image_path}")
            if not os.path.exists(image_path):
                logger.warning(f"Image not found for product {product_id}: {image_path}")
                image_path = os.path.join(os.path.dirname(__file__), 'images/default.jpg')

            with open(image_path, 'rb') as photo:
                if is_inline:
                    await query.edit_message_media(
                        media=InputFile(photo, filename=f"{product['name']}.jpg"),
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    await query.edit_message_caption(caption=caption, reply_markup=InlineKeyboardMarkup(keyboard))
                else:
                    if query.message:
                        await query.message.reply_photo(
                            photo=InputFile(photo),
                            caption=caption,
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
                        try:
                            await query.message.delete()
                        except TelegramError as e:
                            logger.warning(f"Failed to delete message for product {product_id}: {e}")
                    else:
                        await context.bot.send_photo(
                            chat_id=user_id,
                            photo=InputFile(photo),
                            caption=caption,
                            reply_markup=InlineKeyboardMarkup(keyboard)
                        )
        except (FileNotFoundError, TelegramError) as e:
            logger.error(f"Error sending image for product {product_id}: {e}", exc_info=True)
            await edit_or_reply(
                f"{caption}\n⚠️ Image not available.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        return None
    
    elif data.startswith("add_to_cart:"):
        product_id = int(data.split(":", 1)[1])
        context.user_data['selected_product_id'] = product_id
        product = await get_product_by_id(product_id, db)
        
        if not product:
            await edit_or_reply(
                "Product not found. Try browsing again!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
            )
            return None
        
        if is_inline or is_photo:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"How many units of {product['name']} would you like to add to your cart? (Available: {product['stock']})",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="main_menu")]])
            )
            if is_inline:
                await query.edit_message_text(
                    f"✅ Please check your chat with the bot to select quantity for {product['name']}.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
                )
            elif is_photo:
                await query.message.edit_caption(
                    caption=f"✅ Please check your chat to select quantity for {product['name']}.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            return SELECT_QUANTITY
        else:
            await edit_or_reply(
                f"How many units of {product['name']} would you like to add to your cart? (Available: {product['stock']})",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="main_menu")]])
            )
            return SELECT_QUANTITY
    
    elif data.startswith("remove_from_cart:"):
        product_id = int(data.split(":", 1)[1])
        try:
            await db.remove_from_cart(user_id, product_id)
            cart_items = await db.get_cart(user_id)
            
            if not cart_items:
                await edit_or_reply(
                    "Your cart is empty. Browse games or search!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
                )
                return None
            
            total_price = 0
            cart_text = "🛒 Your Cart:\n\n"
            keyboard = []
            for item in cart_items:
                item_price = float(item['price'])
                item_total = item_price * item['quantity']
                total_price += item_total
                cart_text += (
                    f"🎮 {item['name']} ({', '.join(item['platform'])})\n"
                    f"Quantity: {item['quantity']}\n"
                    f"Price: {format_price(item_price)} each\n"
                    f"Subtotal: {format_price(item_total)}\n\n"
                )
                keyboard.append([InlineKeyboardButton(f"❌ Remove {item['name']}", callback_data=f"remove_from_cart:{item['product_id']}")])
            
            cart_text += f"💰 Total: {format_price(total_price)}"
            keyboard.extend([
                [InlineKeyboardButton("✅ Confirm Order", callback_data="confirm_order")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ])
            await edit_or_reply(cart_text, reply_markup=InlineKeyboardMarkup(keyboard))
            return CONFIRM_ORDER
        except Exception as e:
            logger.error(f"Error removing product {product_id} from cart for user {user_id}: {e}", exc_info=True)
            await edit_or_reply(
                "❌ Error removing item. Please try again.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
            )
            return None
    
    elif data == "confirm_order":
        cart_items = await db.get_cart(user_id)
        
        if not cart_items:
            await edit_or_reply(
                "Your cart is empty. Add some games first!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
            )
            return None
        
        total_price = 0
        for item in cart_items:
            item_price = float(item['price'])
            item_total = item_price * item['quantity']
            total_price += item_total
        
        try:
            logger.info(f"Creating order for user {user_id} with {len(cart_items)} items, total: {total_price}")
            order_id = await db.create_order(user_id, total_price, cart_items)
            context.user_data['order_id'] = order_id
            context.user_data['total_price'] = total_price
            context.user_data['cart_items'] = cart_items
            logger.info(f"Created order {order_id} for user {user_id}")
            await edit_or_reply(
                "✅ Order created! Please provide your full name.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Cancel Order", callback_data="cancel_order")]
                ])
            )
            return COLLECT_NAME
        except ValueError as e:
            logger.error(f"Order creation failed for user {user_id}: {e}", exc_info=True)
            await edit_or_reply(
                f"❌ Order failed: {e}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
            )
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating order for user {user_id}: {e}", exc_info=True)
            await edit_or_reply(
                "❌ An error occurred while creating the order. Please try again.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
            )
            return None
    
    elif data == "cancel_order":
        order_id = context.user_data.get('order_id')
        if order_id:
            try:
                await db.cancel_order(order_id)
                context.user_data.clear()
                await edit_or_reply(
                    "✅ Order cancelled.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
                )
            except Exception as e:
                logger.error(f"Error cancelling order {order_id} for user {user_id}: {e}", exc_info=True)
                await edit_or_reply(
                    "❌ Error cancelling order. Please try again.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
                )
        else:
            await edit_or_reply(
                "❌ No order to cancel.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
            )
        return None

async def select_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Handle quantity input for adding to cart."""
    user_id = update.effective_user.id
    product_id = context.user_data.get('selected_product_id')
    
    if not product_id:
        await update.message.reply_text(
            "❌ No product selected. Please try again.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
        )
        return ConversationHandler.END
    
    db = context.bot_data.get('db')
    if not db:
        db = Database()
        context.bot_data['db'] = db
    
    product = await db.get_product(product_id)
    
    if not product:
        await update.message.reply_text(
            "❌ Product not found. Please try again.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
        )
        return ConversationHandler.END
    
    quantity_text = update.message.text.strip()
    try:
        quantity = int(quantity_text)
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        if quantity > product['stock']:
            raise ValueError(f"Only {product['stock']} units available")
        
        await db.add_to_cart(user_id, product_id, quantity)
        await update.message.reply_text(
            f"✅ Added {quantity} unit(s) of {product['name']} to your cart.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 View Cart", callback_data="view_cart")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ])
        )
        return ConversationHandler.END
    except ValueError as e:
        logger.error(f"Invalid quantity input by user {user_id}: {quantity_text} - {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ Invalid input: {e}. Please enter a valid number (e.g., 1, 2).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="main_menu")]])
        )
        return SELECT_QUANTITY
    except Exception as e:
        logger.error(f"Error adding to cart for user {user_id}, product {product_id}: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ An error occurred. Please try again.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
        )
        return ConversationHandler.END

async def collect_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Collect user's full name."""
    user_id = update.effective_user.id
    order_id = context.user_data.get('order_id')
    
    if not order_id:
        logger.error(f"No order_id found for user {user_id} in COLLECT_NAME")
        await update.message.reply_text(
            "❌ No order found. Please start a new order.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
        )
        return ConversationHandler.END
    
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text(
            "❌ Please provide a valid name.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel Order", callback_data="cancel_order")]])
        )
        return COLLECT_NAME
    
    context.user_data['user_details'] = {'name': text}
    logger.info(f"Collected name for user {user_id}, order {order_id}: {text}")
    await update.message.reply_text(
        "Please provide your email address.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel Order", callback_data="cancel_order")]])
    )
    return COLLECT_EMAIL

async def collect_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Collect user's email address."""
    user_id = update.effective_user.id
    order_id = context.user_data.get('order_id')
    
    if not order_id:
        logger.error(f"No order_id found for user {user_id} in COLLECT_EMAIL")
        await update.message.reply_text(
            "❌ No order found. Please start a new order.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
        )
        return ConversationHandler.END
    
    text = update.message.text.strip()
    if not re.match(r"[^@]+@[^@]+\.[^@]+", text):
        await update.message.reply_text(
            "❌ Invalid email format. Please provide a valid email address.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel Order", callback_data="cancel_order")]])
        )
        return COLLECT_EMAIL
    
    context.user_data['user_details']['email'] = text
    logger.info(f"Collected email for user {user_id}, order {order_id}: {text}")
    await update.message.reply_text(
        "Please provide your phone number (e.g., +251912345678 or 0912345678).",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel Order", callback_data="cancel_order")]])
    )
    return COLLECT_PHONE

async def collect_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Collect user's phone number."""
    user_id = update.effective_user.id
    order_id = context.user_data.get('order_id')
    phone = update.message.text.strip()
    
    if not order_id:
        logger.error(f"No order_id found for user {user_id} in COLLECT_PHONE")
        await update.message.reply_text(
            "❌ No order found. Please start a new order.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
        )
        return ConversationHandler.END
    
    if not is_valid_ethiopian_phone(phone):
        await update.message.reply_text(
            "⚠️ Please enter a valid Ethiopian phone number in the format +251912345678 or 0912345678.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel Order", callback_data="cancel_order")]])
        )
        return COLLECT_PHONE
        
    context.user_data['user_details']['phone_number'] = phone
    logger.info(f"Collected phone for user {user_id}, order {order_id}: {phone}")
    await update.message.reply_text(
        "Please provide your delivery address.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel Order", callback_data="cancel_order")]])
    )
    return COLLECT_ADDRESS

async def collect_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Collect user's delivery address, deduct stock, and finalize order."""
    user_id = update.effective_user.id
    order_id = context.user_data.get('order_id')
    total_price = context.user_data.get('total_price')
    cart_items = context.user_data.get('cart_items')
    
    if not order_id:
        logger.error(f"No order_id found for user {user_id} in COLLECT_ADDRESS")
        await update.message.reply_text(
            "❌ No order found. Please start a new order.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
        )
        return ConversationHandler.END
    
    text = update.message.text.strip()
    if not text:
        await update.message.reply_text(
            "❌ Please provide a valid delivery address.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel Order", callback_data="cancel_order")]])
        )
        return COLLECT_ADDRESS
    
    db = context.bot_data.get('db')
    if not db:
        db = Database()
        context.bot_data['db'] = db
    
    # Deduct stock for each item
    for item in cart_items:
        product_id = item['product_id']
        quantity = item['quantity']
        success = await db.deduct_stock(product_id, quantity)
        if not success:
            await update.message.reply_text(
                f"⚠️ Insufficient stock for {item['name']}. Please adjust your cart and try again.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
            )
            return ConversationHandler.END
    
    # Clear cart
    await db.clear_cart(user_id)
    
    # Update order details
    details = context.user_data['user_details']
    details['delivery_address'] = text
    details['username'] = update.effective_user.username or "N/A"
    
    try:
        await db.update_order_details(order_id, details)
        
        # Generate receipt
        from datetime import datetime
        receipt = (
            f"🧾 Order Receipt #{order_id}\n"
            f"Date: {datetime.now().strftime('%Y-%m-%d')}\n\n"
            f"Customer Details:\n"
            f"Name: {details['name']}\n"
            f"Email: {details['email']}\n"
            f"Phone: {details['phone_number']}\n"
            f"Address: {details['delivery_address']}\n"
            f"Username: {details['username']}\n\n"
            f"Items:\n"
        )
        for item in cart_items:
            item_price = float(item['price'])
            item_total = item_price * item['quantity']
            receipt += (
                f"🎮 {item['name']} ({', '.join(item['platform'])})\n"
                f"Quantity: {item['quantity']}\n"
                f"Price: {format_price(item_price)} each\n"
                f"Subtotal: {format_price(item_total)}\n\n"
            )
        receipt += (
            f"💰 Total: {format_price(total_price)}\n\n"
            "Thank you for your purchase! Your order will be processed soon."
        )
        
        await update.message.reply_text(
            receipt,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
        )
        logger.info(f"Order {order_id} finalized for user {user_id}: {details}")
        context.user_data.clear()
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error finalizing order {order_id} for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Error finalizing order. Please try again.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel Order", callback_data="cancel_order")]])
        )
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the current operation or order."""
    user_id = update.effective_user.id
    order_id = context.user_data.get('order_id')
    
    db = context.bot_data.get('db')
    if not db:
        db = Database()
        context.bot_data['db'] = db
    
    if order_id:
        try:
            await db.cancel_order(order_id)
            await update.message.reply_text(
                "✅ Order cancelled.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
            )
        except Exception as e:
            logger.error(f"Error cancelling order {order_id} for user {user_id}: {e}", exc_info=True)
            await update.message.reply_text(
                "❌ Error cancelling order. Please try again.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
            )
    else:
        await update.message.reply_text(
            "✅ Operation cancelled.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
        )
    
    context.user_data.clear()
    return ConversationHandler.END

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline queries for game search."""
    query = update.inline_query.query.strip()
    user_id = update.inline_query.from_user.id
    logger.info(f"Inline query by user {user_id}: '{query}'")
    
    if not query:
        await update.inline_query.answer([], cache_time=10)
        logger.info(f"Empty inline query by user {user_id}")
        return
    
    try:
        db = context.bot_data.get('db')
        if not db:
            db = Database()
            context.bot_data['db'] = db
        products = await search_products(query, db)
        results = []
        for product in products[:50]:
            description = (
                f"Price: {format_price(product['price'])}\n"
                f"Platform: {', '.join(product['platform'])}\n"
                f"Stock: {product['stock']}"
            )
            results.append(
                InlineQueryResultArticle(
                    id=str(product['id']),
                    title=product['name'],
                    description=description,
                    input_message_content=InputTextMessageContent(
                        f"🎮 {product['name']}\n{description}\nDescription: {product['description']}"
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🛒 Add to Cart", callback_data=f"add_to_cart:{product['id']}")]
                    ])
                )
            )
        await update.inline_query.answer(results, cache_time=10)
        logger.info(f"Inline query by user {user_id}: '{query}' returned {len(results)} results")
    except Exception as e:
        logger.error(f"Error in inline query '{query}' by user_id {user_id}: {e}", exc_info=True)
        await update.inline_query.answer([], cache_time=10)

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors."""
    logger.error(f"Update {update} caused error: {context.error}", exc_info=True)
    if update and (update.message or update.callback_query):
        try:
            if update.callback_query:
                await update.callback_query.answer()
                query = update.callback_query
                is_inline = bool(query.inline_message_id)
                is_photo = query.message.photo if query.message else False
                text = "❌ An error occurred. Please try again."
                reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
                if is_inline:
                    await query.edit_message_text(text=text, reply_markup=reply_markup)
                elif is_photo:
                    await query.message.edit_caption(caption=text, reply_markup=reply_markup)
                elif query.message:
                    await query.message.edit_text(text=text, reply_markup=reply_markup)
                else:
                    await context.bot.send_message(
                        chat_id=query.from_user.id,
                        text=text,
                        reply_markup=reply_markup
                    )
            elif update.message:
                await update.message.reply_text(
                    text="❌ An error occurred! Please try again.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
                )
        except TelegramError as e:
            logger.error(f"Error sending error message: {e}", exc_info=True)

# Define command handlers
command_handlers = [
    CommandHandler("start", start),
    CommandHandler("search", search_command),
    CommandHandler("cart", cart_command),
    CommandHandler("cancel", cancel),
]

# Define conversation handler
conv_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(handle_callback, pattern="^add_to_cart:.*$"),
        CallbackQueryHandler(handle_callback, pattern="^confirm_order$"),
    ],
    states={
        SELECT_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_quantity)],
        CONFIRM_ORDER: [CallbackQueryHandler(handle_callback, pattern="^(confirm_order|main_menu|remove_from_cart:.*)$")],
        COLLECT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_name)],
        COLLECT_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_email)],
        COLLECT_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_phone)],
        COLLECT_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_address)],
    },
    fallbacks=[
        CommandHandler("cancel", cancel),
        CallbackQueryHandler(handle_callback, pattern="^cancel_order$"),
        CallbackQueryHandler(handle_callback, pattern="^main_menu$"),
    ],
    per_message=False
)

# Define callback query handler
callback_query_handler = CallbackQueryHandler(handle_callback)

# Define inline query handler
inline_query_handler = InlineQueryHandler(inline_query)