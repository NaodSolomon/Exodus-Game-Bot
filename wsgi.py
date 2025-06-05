# Refactored wsgi.py for Synchronous Flask, Gunicorn, and Render deployment

import os
import logging
import json
import bcrypt
import threading
import asyncio
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, request, session, redirect, url_for, flash, render_template, jsonify, g
from flask_session import Session # For server-side sessions
from whitenoise import WhiteNoise # For serving static files in production
from telegram import Update
from telegram.ext import Application as TelegramApplication

# Import necessary components from the project
# Assuming User.config contains BOT_TOKEN and other settings
from User.config import BOT_TOKEN, load_env_vars
from User.handlers import command_handlers, conv_handler, callback_query_handler, inline_query_handler, error_handler
from User.database import Database as UserDatabase # Renamed to avoid conflict
from admin_dashboard.src.models.database import Database as AdminDatabase

# Load environment variables
load_env_vars()

# --- Logging Setup ---
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=log_level,
    format="%(asctime)s|%(levelname)s|%(name)s|%(message)s",
    handlers=[
        logging.StreamHandler() # Log to console, Render captures this
    ]
)
logger = logging.getLogger("Flask_App")

# --- Flask App Initialization ---
app = Flask(__name__, template_folder= 'admin_dashboard/src/templates', static_folder='admin_dashboard/src/static')

# --- Configuration ---
# Secret Key: Essential for sessions and security. Use environment variable.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "default-insecure-secret-key-replace-me")
if app.config["SECRET_KEY"] == "default-insecure-secret-key-replace-me":
    logger.warning("Using default SECRET_KEY. Set a strong SECRET_KEY environment variable for production!")

# Session Configuration: Using Flask-Session with filesystem (Render ephemeral) or Redis (recommended)
# For Render, set SESSION_TYPE=redis and provide SESSION_REDIS URL
app.config["SESSION_TYPE"] = os.environ.get("SESSION_TYPE", "filesystem") # Default to filesystem
app.config["SESSION_PERMANENT"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=int(os.environ.get("SESSION_LIFETIME_HOURS", "2")))
app.config["SESSION_FILE_DIR"] = os.environ.get("SESSION_FILE_DIR", "./instance/flask_session") # Store session files locally
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FLASK_ENV", "development") == "production"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# # Configure Redis if specified
# if app.config["SESSION_TYPE"] == "redis":
#     import redis
#     redis_url = os.environ.get("SESSION_REDIS")
#     if not redis_url:
#         logger.error("SESSION_TYPE is redis, but SESSION_REDIS environment variable is not set.")
#         # Fallback or raise error - falling back to filesystem
#         app.config["SESSION_TYPE"] = "filesystem"
#         logger.warning("Falling back to filesystem session storage.")
#     else:
#         app.config["SESSION_REDIS"] = redis.from_url(redis_url)
#         logger.info("Using Redis for session storage.")
# else:
#     # Ensure the filesystem session directory exists
#     session_dir = app.config["SESSION_FILE_DIR"]
#     if not os.path.exists(session_dir):
#         os.makedirs(session_dir)
#     logger.info(f"Using filesystem for session storage at {session_dir}")

Session(app)

# --- Static Files Handling (WhiteNoise) ---
# Serve static files efficiently in production using WhiteNoise
# It wraps the Flask app and handles static file requests
app.wsgi_app = WhiteNoise(app.wsgi_app, root=app.static_folder,
                          prefix="/static/", index_file=False)
logger.info(f"WhiteNoise configured to serve static files from {app.static_folder}")

# --- Database Initialization ---
# Use relative paths within the project or absolute paths via env vars
# Defaulting to an `instance` folder for databases
INSTANCE_FOLDER = os.path.join(app.root_path, "instance")
if not os.path.exists(INSTANCE_FOLDER):
    os.makedirs(INSTANCE_FOLDER)

DB_PATH = os.environ.get("DB_PATH", os.path.join(INSTANCE_FOLDER, "data.db"))
ADMIN_DB_PATH = os.environ.get("ADMIN_DB_PATH", os.path.join(INSTANCE_FOLDER, "admin.db"))

# Initialize database connections (will be managed per request)
user_db = UserDatabase(DB_PATH)
admin_db = AdminDatabase(ADMIN_DB_PATH)

# --- Telegram Bot Setup ---
# Check for BOT_TOKEN
if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN":
    logger.error("BOT_TOKEN is not set or is invalid. Please set the BOT_TOKEN environment variable.")
    # Depending on requirements, you might exit or disable bot features
    telegram_app = None
else:
    # Initialize Telegram Application (using python-telegram-bot v20+)
    telegram_app = TelegramApplication.builder().token(BOT_TOKEN).build()

    # Add handlers
    for handler in command_handlers:
        telegram_app.add_handler(handler)
    telegram_app.add_handler(conv_handler)
    telegram_app.add_handler(callback_query_handler)
    telegram_app.add_handler(inline_query_handler)
    telegram_app.add_handler(error_handler)

    # Store database instances in bot_data (accessible in handlers)
    # Note: Direct async DB access from sync Flask needs care (e.g., run_in_executor)
    # For simplicity, handlers might need refactoring or use sync DB access if possible.
    # Or, run the bot in a separate process/thread.
    telegram_app.bot_data["user_db"] = user_db
    telegram_app.bot_data["admin_db"] = admin_db

# --- Database Connection Management (Per Request) ---
@app.before_request
def before_request():
    """Connect to databases before each request."""
    try:
        g.user_db = UserDatabase(DB_PATH)
        g.user_db.connect()
        g.admin_db = AdminDatabase(ADMIN_DB_PATH)
        g.admin_db.connect()
        logger.debug("DB connections opened for request.")
    except Exception as e:
        logger.error(f"Failed to connect to databases: {e}", exc_info=True)
        # Optionally, return an error page or response
        g.user_db = None
        g.admin_db = None

@app.teardown_request
def teardown_request(exception=None):
    """Disconnect databases after each request."""
    user_db_conn = g.pop("user_db", None)
    if user_db_conn is not None:
        user_db_conn.disconnect()
    admin_db_conn = g.pop("admin_db", None)
    if admin_db_conn is not None:
        admin_db_conn.disconnect()
    logger.debug("DB connections closed for request.")

# --- Initialization Logic (Run Once at Startup) ---
def initialize_app():
    """Perform initial setup like creating DB tables and setting webhook."""
    logger.info("Starting application initialization...")
    try:
        # Initialize Admin DB (create tables, default admin)
        admin_db.create_tables()
        admin_default_password = os.environ.get("ADMIN_DEFAULT_PASSWORD", "admin")
        if admin_default_password == "admin":
            logger.warning("Using default ADMIN_DEFAULT_PASSWORD. Set a strong password environment variable!")
        hashed_password = bcrypt.hashpw(admin_default_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        admin_db.initialize_admin("admin", hashed_password)

        # Initialize User DB (create tables, populate initial data if needed)
        # Assuming UserDatabase has an initialize method similar to AdminDatabase
        user_db.initialize() # Create tables
        # Populate products from JSON (moved from User/main.py)
        products_json_path = os.path.join(os.path.dirname(__file__), "User", "products.json")
        if os.path.exists(products_json_path):
            logger.info(f"Loading products from: {products_json_path}")
            try:
                with open(products_json_path, "r") as f:
                    products_data = json.load(f)
                user_db.populate_products(products_data, os.path.join(os.path.dirname(__file__), "User"))
            except Exception as e:
                logger.error(f"Error populating products from JSON: {e}", exc_info=True)
        else:
            logger.warning(f"products.json not found at {products_json_path}. Skipping initial product population.")

        logger.info("Databases initialized successfully.")

        # --- Telegram Webhook Setup (Async in Background Thread) ---
        if telegram_app:
            webhook_url_base = os.environ.get("RENDER_EXTERNAL_URL")
            if not webhook_url_base:
                logger.warning("RENDER_EXTERNAL_URL not set. Cannot set webhook automatically. Set it manually or provide the variable.")
            else:
                webhook_path = "/webhook"
                webhook_url = f"{webhook_url_base.rstrip("/")}{webhook_path}"
                
                async def setup_telegram_async():
                    try:
                        logger.info(f"Attempting to set Telegram webhook to: {webhook_url}")
                        await telegram_app.initialize() # Initializes bot internals
                        # Check current webhook
                        current_webhook_info = await telegram_app.bot.get_webhook_info()
                        if current_webhook_info.url != webhook_url:
                            logger.info(f"Current webhook is 	{current_webhook_info.url}	. Setting new webhook...")
                            await telegram_app.bot.set_webhook(url=webhook_url, allowed_updates=Update.ALL_TYPES)
                            logger.info(f"Telegram webhook set successfully to: {webhook_url}")
                        else:
                            logger.info("Telegram webhook is already set correctly.")
                        # Start the application components (like job queue, persistence)
                        # await telegram_app.start() # Don\'t start polling if using webhook
                    except Exception as e:
                        logger.error(f"Failed to set Telegram webhook: {e}", exc_info=True)
                
                # Run the async setup in a separate thread to avoid blocking Flask startup
                def run_async_setup():
                    asyncio.run(setup_telegram_async())
                
                thread = threading.Thread(target=run_async_setup)
                thread.start()
        else:
            logger.warning("Telegram bot application not initialized (likely missing BOT_TOKEN). Skipping webhook setup.")

    except Exception as e:
        logger.critical(f"Application initialization failed: {e}", exc_info=True)
        # Depending on severity, you might want to exit
        # raise SystemExit(f"Initialization failed: {e}")

# Run initialization once when the app starts
# Use Flask\'s app context or run before first request
with app.app_context():
    initialize_app()

# --- Webhook Endpoint ---
@app.route("/webhook", methods=["POST"])
def webhook():
    """Endpoint to receive updates from Telegram."""
    if not telegram_app:
        logger.error("Received webhook call, but Telegram app is not initialized.")
        return jsonify({"status": "error", "message": "Bot not configured"}), 500
    
    # Process update asynchronously in a separate thread to avoid blocking
    # the Flask worker and Telegram\'s retry mechanism.
    update_data = request.get_json()
    
    async def process_update_async(data):
        try:
            update = Update.de_json(data, telegram_app.bot)
            logger.debug(f"Processing update ID: {update.update_id}")
            # Make DB instances available within the async context if needed
            # This requires careful handling or using a sync interface within handlers
            await telegram_app.process_update(update)
            logger.debug(f"Finished processing update ID: {update.update_id}")
        except Exception as e:
            logger.error(f"Error processing webhook update: {e}", exc_info=True)

    def run_async_processing():
        asyncio.run(process_update_async(update_data))

    thread = threading.Thread(target=run_async_processing)
    thread.start()
    
    # Return immediately to Telegram
    return jsonify({"status": "ok"}), 200

# --- Authentication Decorator ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "admin_id" not in session:
            flash("Please log in to access this page", "warning")
            return redirect(url_for("login", next=request.url))
        # Optionally, re-verify admin existence in DB here
        return f(*args, **kwargs)
    return decorated_function

# --- Routes (Converted to Sync) ---
@app.route("/")
def index():
    if "admin_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if "admin_id" in session:
        return redirect(url_for("dashboard")) # Already logged in

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if not username or not password:
            flash("Please enter both username and password", "error")
            return render_template("login.html")
        
        admin = g.admin_db.fetch_one("SELECT * FROM admin_users WHERE username = ?", (username,))
        
        if admin and bcrypt.checkpw(password.encode("utf-8"), admin["password_hash"].encode("utf-8")):
            session["admin_id"] = admin["id"]
            session["admin_username"] = admin["username"]
            session.permanent = True # Use PERMANENT_SESSION_LIFETIME
            
            # Log login time and action
            g.admin_db.execute_query("UPDATE admin_users SET last_login = ? WHERE id = ?", 
                                     (datetime.now().isoformat(), admin["id"]))
            g.admin_db.log_admin_action(admin["id"], "login", f"Admin {username} logged in from {request.remote_addr}")
            
            flash("Login successful!", "success")
            next_url = request.args.get("next")
            return redirect(next_url or url_for("dashboard"))
        else:
            flash("Invalid username or password", "error")
            # Optionally log failed login attempt
            g.admin_db.log_admin_action(None, "login_failed", f"Failed login attempt for user 	{username}	 from {request.remote_addr}")
            
    return render_template("login.html")

@app.route("/logout")
def logout():
    if "admin_id" in session:
        admin_id = session["admin_id"]
        admin_username = session.get("admin_username", "Unknown")
        g.admin_db.log_admin_action(admin_id, "logout", f"Admin {admin_username} logged out")
        session.clear() # Clear all session data
        flash("You have been logged out.", "info")
    return redirect(url_for("login"))

# --- Dashboard Routes (Sync) ---
@app.route("/dashboard")
@login_required
def dashboard():
    # Fetch data using g.user_db and g.admin_db
    total_games = (g.user_db.fetch_one("SELECT COUNT(*) as count FROM products"))["count"]
    total_orders = (g.user_db.fetch_one("SELECT COUNT(*) as count FROM orders"))["count"]
    total_users = (g.user_db.fetch_one("SELECT COUNT(*) as count FROM users"))["count"]
    total_revenue = (g.user_db.fetch_one("SELECT SUM(total_price) as sum FROM orders"))["sum"] or 0
    recent_orders = g.user_db.fetch_all("SELECT * FROM orders ORDER BY id DESC LIMIT 5")
    low_stock_threshold = 5 # Example threshold
    low_stock = g.user_db.fetch_all("SELECT * FROM products WHERE stock < ?", (low_stock_threshold,))
    top_products = g.user_db.fetch_all("""
        SELECT p.id, p.name, p.platform, SUM(oi.quantity) as total_sold
        FROM products p JOIN order_items oi ON p.id = oi.product_id
        GROUP BY p.id ORDER BY total_sold DESC LIMIT 5
    """)
    platforms = g.user_db.fetch_all("SELECT platform, COUNT(*) as count FROM products GROUP BY platform")
    # Correcting platform JSON parsing if needed
    parsed_platforms = []
    for p in platforms:
        try:
            platform_name = json.loads(p["platform"])[0] if p["platform"].startswith("[") else p["platform"]
            parsed_platforms.append({"platform": platform_name, "count": p["count"]})
        except (json.JSONDecodeError, IndexError):
             parsed_platforms.append({"platform": p["platform"], "count": p["count"]}) # Keep original if parse fails

    monthly_revenue = g.user_db.fetch_all("""
        SELECT strftime("%Y-%m", created_at) as month, SUM(total_price) as revenue
        FROM orders GROUP BY month ORDER BY month DESC LIMIT 6
    """)
    monthly_revenue.reverse() # Ensure chronological order for charts

    return render_template("dashboard.html", 
                          total_games=total_games, total_orders=total_orders,
                          total_users=total_users, total_revenue=f"{total_revenue:.2f}",
                          recent_orders=recent_orders, low_stock=low_stock,
                          top_products=top_products, platforms=parsed_platforms,
                          monthly_revenue=monthly_revenue)

@app.route("/games")
@login_required
def games():
    games_data = g.user_db.fetch_all("SELECT * FROM products ORDER BY id DESC")
    # Parse platform JSON if needed
    for game in games_data:
        try:
            game["platform_display"] = json.loads(game["platform"])[0] if game["platform"].startswith("[") else game["platform"]
        except (json.JSONDecodeError, IndexError):
            game["platform_display"] = game["platform"]
    return render_template("games.html", games=games_data)

@app.route("/games/add", methods=["GET", "POST"])
@login_required
def add_game():
    categories = g.admin_db.fetch_all("SELECT name FROM categories")
    platforms = [c["name"] for c in categories]

    if request.method == "POST":
        name = request.form.get("name")
        platform = request.form.get("platform")
        price = request.form.get("price")
        stock = request.form.get("stock")
        description = request.form.get("description", "")
        image_url = request.form.get("image_url") # Assuming single image URL for now
        
        # Basic Validation
        errors = []
        if not name: errors.append("Name is required.")
        if not platform or platform not in platforms: errors.append("Valid platform is required.")
        if not price: errors.append("Price is required.")
        else: 
            try: price = float(price)
            except ValueError: errors.append("Price must be a number.")
        if not stock: errors.append("Stock is required.")
        else:
            try: stock = int(stock)
            except ValueError: errors.append("Stock must be an integer.")
        if not image_url: errors.append("Image URL is required.") # Or handle file upload

        if errors:
            for error in errors: flash(error, "error")
            return render_template("add_game.html", platforms=platforms, form_data=request.form)

        # Store platform as JSON list for consistency, even if single
        platform_json = json.dumps([platform])
        # Use consistent column name (e.g., image_url)
        result = g.user_db.execute_query(
            "INSERT INTO products (name, platform, price, stock, description, image_url) VALUES (?, ?, ?, ?, ?, ?)",
            (name, platform_json, price, stock, description, image_url)
        )
        
        if result:
            g.admin_db.log_admin_action(
                session["admin_id"], "add_game", 
                f"Added game: {name} ({platform}) at ${price:.2f}"
            )
            flash("Game added successfully!", "success")
            return redirect(url_for("games"))
        else:
            flash("Error adding game to database.", "error")
            
    return render_template("add_game.html", platforms=platforms)

@app.route("/games/edit/<int:game_id>", methods=["GET", "POST"])
@login_required
def edit_game(game_id):
    game = g.user_db.fetch_one("SELECT * FROM products WHERE id = ?", (game_id,))
    if not game:
        flash("Game not found", "error")
        return redirect(url_for("games"))

    categories = g.admin_db.fetch_all("SELECT name FROM categories")
    platforms = [c["name"] for c in categories]
    
    # Pre-populate form data (handle platform JSON)
    try:
        game_platform = json.loads(game["platform"])[0] if game["platform"].startswith("[") else game["platform"]
    except (json.JSONDecodeError, IndexError):
        game_platform = game["platform"]
    game_dict = dict(game) # Convert Row to dict for modification
    game_dict["platform"] = game_platform

    if request.method == "POST":
        name = request.form.get("name")
        platform = request.form.get("platform")
        price = request.form.get("price")
        stock = request.form.get("stock")
        description = request.form.get("description", "")
        image_url = request.form.get("image_url")

        # Basic Validation (similar to add_game)
        errors = []
        if not name: errors.append("Name is required.")
        if not platform or platform not in platforms: errors.append("Valid platform is required.")
        if not price: errors.append("Price is required.")
        else: 
            try: price = float(price)
            except ValueError: errors.append("Price must be a number.")
        if not stock: errors.append("Stock is required.")
        else:
            try: stock = int(stock)
            except ValueError: errors.append("Stock must be an integer.")
        if not image_url: errors.append("Image URL is required.")

        if errors:
            for error in errors: flash(error, "error")
            # Pass current form data back to template
            form_data = dict(request.form)
            form_data["id"] = game_id # Ensure ID is present
            return render_template("edit_game.html", game=form_data, platforms=platforms)

        platform_json = json.dumps([platform])
        result = g.user_db.execute_query(
            "UPDATE products SET name = ?, platform = ?, price = ?, stock = ?, description = ?, image_url = ? WHERE id = ?",
            (name, platform_json, price, stock, description, image_url, game_id)
        )
        
        if result:
            g.admin_db.log_admin_action(
                session["admin_id"], "edit_game", 
                f"Edited game ID {game_id}: {name} ({platform}) at ${price:.2f}"
            )
            flash("Game updated successfully!", "success")
            return redirect(url_for("games"))
        else:
            flash("Error updating game in database.", "error")
            # Pass current form data back
            form_data = dict(request.form)
            form_data["id"] = game_id
            return render_template("edit_game.html", game=form_data, platforms=platforms)

    # GET request: Populate form with existing data
    return render_template("edit_game.html", game=game_dict, platforms=platforms)

@app.route("/games/delete/<int:game_id>", methods=["POST"])
@login_required
def delete_game(game_id):
    # Check if game exists
    game = g.user_db.fetch_one("SELECT name, platform FROM products WHERE id = ?", (game_id,))
    if not game:
        flash("Game not found", "error")
        return redirect(url_for("games"))

    # Check if game is in any orders (optional, based on requirements)
    order_items = g.user_db.fetch_one("SELECT COUNT(*) as count FROM order_items WHERE product_id = ?", (game_id,))
    if order_items and order_items["count"] > 0:
        flash(f"Cannot delete game 	{game['name']}	 as it exists in {order_items['count']} order(s). Consider disabling it instead.", "error")
        return redirect(url_for("games"))

    # Proceed with deletion
    result = g.user_db.execute_query("DELETE FROM products WHERE id = ?", (game_id,))
    if result:
        g.admin_db.log_admin_action(
            session["admin_id"], "delete_game", 
            f"Deleted game ID {game_id}: {game["name"]}"
        )
        flash("Game deleted successfully!", "success")
    else:
        flash("Error deleting game from database.", "error")
        
    return redirect(url_for("games"))

# --- Other Routes (Categories, Clients, Orders, etc. - Need similar sync conversion) ---
# Placeholder: Convert remaining routes similarly, using g.user_db and g.admin_db

@app.route("/categories")
@login_required
def categories():
    # Fetch categories from admin DB
    categories = g.admin_db.fetch_all("SELECT id, name, description FROM categories ORDER BY name")
    # Fetch game counts for each category from user DB
    platform_counts = g.user_db.fetch_all("SELECT platform, COUNT(*) as count FROM products GROUP BY platform")
    
    # Create a map for easy lookup
    count_map = {}
    for pc in platform_counts:
        try:
            # Handle JSON platform string
            platform_name = json.loads(pc["platform"])[0] if pc["platform"].startswith("[") else pc["platform"]
            count_map[platform_name] = pc["count"]
        except (json.JSONDecodeError, IndexError):
            count_map[pc["platform"]] = pc["count"] # Fallback

    # Add counts to categories
    for category in categories:
        category["game_count"] = count_map.get(category["name"], 0)
        
    return render_template("categories.html", categories=categories)

@app.route("/categories/add", methods=["GET", "POST"])
@login_required
def add_category():
    if request.method == "POST":
        name = request.form.get("name")
        description = request.form.get("description", "")
        if not name:
            flash("Category name is required.", "error")
            return render_template("add_category.html", form_data=request.form)
        
        # Check if exists
        existing = g.admin_db.fetch_one("SELECT id FROM categories WHERE name = ?", (name,))
        if existing:
            flash(f"Category 	{name}	 already exists.", "error")
            return render_template("add_category.html", form_data=request.form)
            
        result = g.admin_db.execute_query(
            "INSERT INTO categories (name, description) VALUES (?, ?)",
            (name, description)
        )
        if result:
            g.admin_db.log_admin_action(session["admin_id"], "add_category", f"Added category: {name}")
            flash("Category added successfully!", "success")
            return redirect(url_for("categories"))
        else:
            flash("Error adding category to database.", "error")
            
    return render_template("add_category.html")

@app.route("/categories/edit/<int:category_id>", methods=["GET", "POST"])
@login_required
def edit_category(category_id):
    category = g.admin_db.fetch_one("SELECT * FROM categories WHERE id = ?", (category_id,))
    if not category:
        flash("Category not found.", "error")
        return redirect(url_for("categories"))

    if request.method == "POST":
        new_name = request.form.get("name")
        description = request.form.get("description", "")
        original_name = category["name"]

        if not new_name:
            flash("Category name is required.", "error")
            return render_template("edit_category.html", category=category, form_data=request.form)

        # Check if new name conflicts with another existing category
        if new_name != original_name:
            existing = g.admin_db.fetch_one("SELECT id FROM categories WHERE name = ? AND id != ?", (new_name, category_id))
            if existing:
                flash(f"Category name 	{new_name}	 already exists.", "error")
                return render_template("edit_category.html", category=category, form_data=request.form)

        # Update category in admin DB
        result = g.admin_db.execute_query(
            "UPDATE categories SET name = ?, description = ? WHERE id = ?",
            (new_name, description, category_id)
        )

        if result:
            # If name changed, update products in user DB (handle JSON platform)
            if new_name != original_name:
                logger.info(f"Category name changed from 	{original_name}	 to 	{new_name}	. Updating products...")
                # Find products with the old platform name (might be JSON list)
                old_platform_json = json.dumps([original_name])
                new_platform_json = json.dumps([new_name])
                # Update products using the JSON representation
                update_count = g.user_db.execute_query_get_count(
                    "UPDATE products SET platform = ? WHERE platform = ?",
                    (new_platform_json, old_platform_json)
                )
                # Also update products where platform might be stored as plain string (legacy?)
                update_count += g.user_db.execute_query_get_count(
                    "UPDATE products SET platform = ? WHERE platform = ?",
                    (new_platform_json, original_name)
                )
                logger.info(f"Updated platform for {update_count} products.")

            g.admin_db.log_admin_action(session["admin_id"], "edit_category", f"Updated category ID {category_id} from 	{original_name}	 to 	{new_name}	")
            flash("Category updated successfully!", "success")
            return redirect(url_for("categories"))
        else:
            flash("Error updating category in database.", "error")
            # Return with form data if update failed
            return render_template("edit_category.html", category=category, form_data=request.form)

    # GET request
    return render_template("edit_category.html", category=category)

@app.route("/categories/delete/<int:category_id>", methods=["POST"])
@login_required
def delete_category(category_id):
    category = g.admin_db.fetch_one("SELECT name FROM categories WHERE id = ?", (category_id,))
    if not category:
        flash("Category not found.", "error")
        return redirect(url_for("categories"))

    category_name = category["name"]
    platform_json = json.dumps([category_name])

    # Check if any products use this category (check JSON and plain string)
    product_count = g.user_db.fetch_one(
        "SELECT COUNT(*) as count FROM products WHERE platform = ? OR platform = ?",
        (platform_json, category_name)
    )["count"]

    if product_count > 0:
        flash(f"Cannot delete category 	{category_name}	 as it is assigned to {product_count} game(s).", "error")
        return redirect(url_for("categories"))

    # Delete from admin DB
    result = g.admin_db.execute_query("DELETE FROM categories WHERE id = ?", (category_id,))
    if result:
        g.admin_db.log_admin_action(session["admin_id"], "delete_category", f"Deleted category: {category_name} (ID: {category_id})")
        flash("Category deleted successfully!", "success")
    else:
        flash("Error deleting category from database.", "error")
        
    return redirect(url_for("categories"))


# --- Clients Route ---
@app.route("/clients")
@login_required
def clients():
    clients_data = g.user_db.fetch_all("SELECT * FROM users ORDER BY id DESC")
    # Enhance client data with order info
    for client in clients_data:
        orders = g.user_db.fetch_all("SELECT total_price FROM orders WHERE user_id = ?", (client["id"],))
        client["order_count"] = len(orders)
        client["total_spent"] = sum(float(order["total_price"]) for order in orders if order["total_price"])
    return render_template("clients.html", clients=clients_data)

@app.route("/clients/<int:client_id>")
@login_required
def client_details(client_id):
    client = g.user_db.fetch_one("SELECT * FROM users WHERE id = ?", (client_id,))
    if not client:
        flash("Client not found", "error")
        return redirect(url_for("clients"))
    
    orders = g.user_db.fetch_all("SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC", (client_id,))
    for order in orders:
        items = g.user_db.fetch_all("""
            SELECT oi.*, p.name, p.platform
            FROM order_items oi JOIN products p ON oi.product_id = p.id
            WHERE oi.order_id = ?
        """, (order["id"],))
        # Parse platform JSON
        for item in items:
             try: item["platform_display"] = json.loads(item["platform"])[0]
             except: item["platform_display"] = item["platform"]
        order["items"] = items
        # Parse user_details JSON
        try: order["user_details_parsed"] = json.loads(order["user_details"])
        except: order["user_details_parsed"] = {"error": "Invalid JSON"}
        
    return render_template("client_details.html", client=client, orders=orders)

# --- Orders Route ---
@app.route("/orders")
@login_required
def orders():
    orders_data = g.user_db.fetch_all("SELECT o.*, u.username, u.first_name, u.last_name FROM orders o JOIN users u ON o.user_id = u.id ORDER BY o.id DESC")
    return render_template("orders.html", orders=orders_data)

@app.route("/orders/<int:order_id>")
@login_required
def order_details(order_id):
    order = g.user_db.fetch_one("SELECT o.*, u.username, u.first_name, u.last_name FROM orders o JOIN users u ON o.user_id = u.id WHERE o.id = ?", (order_id,))
    if not order:
        flash("Order not found", "error")
        return redirect(url_for("orders"))
        
    items = g.user_db.fetch_all("""
        SELECT oi.*, p.name, p.platform, p.image_url 
        FROM order_items oi JOIN products p ON oi.product_id = p.id 
        WHERE oi.order_id = ?
    """, (order_id,))
    # Parse platform JSON
    for item in items:
         try: item["platform_display"] = json.loads(item["platform"])[0]
         except: item["platform_display"] = item["platform"]
         
    user_details = {}
    if order["user_details"]:
        try:
            user_details = json.loads(order["user_details"])
        except json.JSONDecodeError:
            user_details = {"error": "Could not parse user details JSON"}
            
    return render_template("order_details.html", order=order, items=items, user_details=user_details)

@app.route("/orders/update_status/<int:order_id>", methods=["POST"])
@login_required
def update_order_status(order_id):
    status = request.form.get("status")
    valid_statuses = ["Pending", "Processing", "Shipped", "Delivered", "Cancelled", "Refunded"] # Example statuses
    if not status or status not in valid_statuses:
        flash(f"Please select a valid status ({', '.join(valid_statuses)})", "error")
        return redirect(url_for("order_details", order_id=order_id))

    result = g.user_db.execute_query(
        "UPDATE orders SET status = ? WHERE id = ?",
        (status, order_id)
    )
    if result:
        g.admin_db.log_admin_action(
            session["admin_id"], "update_order_status", 
            f"Updated order ID {order_id} status to {status}"
        )
        flash(f"Order status updated to 	{status}	!", "success")
        # Optionally, notify the user via Telegram bot
        # bot_notify_user_order_update(order_id, status)
    else:
        flash("Error updating order status in database.", "error")
        
    return redirect(url_for("order_details", order_id=order_id))

# --- API Routes (Example) ---
@app.route("/api/dashboard/stats")
@login_required
def api_dashboard_stats():
    # Fetch necessary data synchronously
    total_games = (g.user_db.fetch_one("SELECT COUNT(*) as count FROM products"))["count"]
    total_orders = (g.user_db.fetch_one("SELECT COUNT(*) as count FROM orders"))["count"]
    total_users = (g.user_db.fetch_one("SELECT COUNT(*) as count FROM users"))["count"]
    total_revenue = (g.user_db.fetch_one("SELECT SUM(total_price) as sum FROM orders"))["sum"] or 0
    monthly_revenue_data = g.user_db.fetch_all("""
        SELECT strftime("%Y-%m", created_at) as month, SUM(total_price) as revenue
        FROM orders GROUP BY month ORDER BY month DESC LIMIT 6
    """)
    monthly_revenue_data.reverse()
    
    months = [item["month"] for item in monthly_revenue_data]
    revenues = [float(item["revenue"]) if item["revenue"] else 0 for item in monthly_revenue_data]
    
    return jsonify({
        "total_games": total_games,
        "total_orders": total_orders,
        "total_users": total_users,
        "total_revenue": f"{total_revenue:.2f}",
        "chart_data": {
            "labels": months,
            "datasets": [{
                "label": "Monthly Revenue ($)",
                "data": revenues,
                "backgroundColor": "rgba(54, 162, 235, 0.2)",
                "borderColor": "rgba(54, 162, 235, 1)",
                "borderWidth": 1
            }]
        }
    })

# --- Health Check Endpoint ---
@app.route("/health")
def health_check():
    # Basic health check, can be expanded to check DB connection, etc.
    return jsonify({"status": "ok"}), 200

# --- Main Execution (for Gunicorn) ---
# Gunicorn will import and run `app` directly.
# The `if __name__ == "__main__":` block is typically used for local development.
if __name__ == "__main__":
    # Use Flask\'s built-in server for development
    # Host 0.0.0.0 makes it accessible on the network
    # Debug=True enables auto-reloading and debugger (DO NOT use in production)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)

