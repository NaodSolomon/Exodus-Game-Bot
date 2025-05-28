import os
import sys
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import bcrypt
from datetime import datetime, timedelta
import json

# Use relative import for Database
from .src.models.database import Database

# Initialize Flask app
app = Flask(__name__, template_folder='src/templates', static_folder='src/static')
app.secret_key = os.environ.get('Secret_Key')  # For session management
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)

# Database paths
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'User', 'data.db')
ADMIN_DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'admin.db')

# Initialize database connections
db = Database(DB_PATH)
admin_db = Database(ADMIN_DB_PATH)

# Custom Jinja2 filter for timestamp conversion
@app.template_filter('timestamp_to_date')
def timestamp_to_date(timestamp):
    try:
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return 'Unknown'

# Ensure user is logged in
def login_required(f):
    def decorated_function(*args, **kwargs):
        if 'admin_id' not in session:
            flash('Please log in to access this page', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

# Routes
@app.route('/')
def index():
    if 'admin_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if not username or not password:
            flash('Please enter both username and password', 'error')
            return render_template('login.html')
        
        # Connect to admin database
        admin_db.connect()
        
        # Check if admin database exists, if not create it and add default admin
        admin_db.create_tables()
        
        # Check if default admin exists, if not create it
        default_admin = admin_db.fetch_one("SELECT * FROM admin_users WHERE username = ?", ('admin',))
        if not default_admin:
            # Hash the default password
            hashed_password = bcrypt.hashpw('securepassword123'.encode('utf-8'), bcrypt.gensalt())
            admin_db.initialize_admin('admin', hashed_password.decode('utf-8'))
            default_admin = admin_db.fetch_one("SELECT * FROM admin_users WHERE username = ?", ('admin',))
        
        # Verify credentials
        admin = admin_db.fetch_one("SELECT * FROM admin_users WHERE username = ?", (username,))
        
        if admin and bcrypt.checkpw(password.encode('utf-8'), admin['password_hash'].encode('utf-8')):
            session['admin_id'] = admin['id']
            session['admin_username'] = admin['username']
            
            # Update last login time
            admin_db.execute_query("UPDATE admin_users SET last_login = ? WHERE id = ?", 
                                  (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), admin['id']))
            admin_db.log_admin_action(admin['id'], 'login', f"Admin {username} logged in")
            
            flash('Login successful!', 'success')
            admin_db.disconnect()
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'error')
            admin_db.disconnect()
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    if 'admin_id' in session:
        admin_id = session['admin_id']
        admin_username = session.get('admin_username', 'Unknown')
        
        # Log the logout action
        admin_db.connect()
        admin_db.log_admin_action(admin_id, 'logout', f"Admin {admin_username} logged out")
        admin_db.disconnect()
        
        # Clear session
        session.pop('admin_id', None)
        session.pop('admin_username', None)
        
    flash('You have been logged out', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    # Connect to database
    db.connect()
    
    # Get dashboard statistics
    total_games = len(db.fetch_all("SELECT * FROM products"))
    total_orders = len(db.fetch_all("SELECT * FROM orders"))
    total_users = len(db.fetch_all("SELECT * FROM users"))
    
    # Calculate total revenue
    orders = db.fetch_all("SELECT total_price FROM orders")
    total_revenue = sum(float(order['total_price']) for order in orders)
    
    # Get recent orders
    recent_orders = db.fetch_all("SELECT * FROM orders ORDER BY id DESC LIMIT 5")
    
    # Get low stock products (less than 5)
    low_stock = db.fetch_all("SELECT * FROM products WHERE stock < 5")
    
    # Get top selling products
    top_products_query = """
    SELECT p.id, p.name, p.platform, SUM(oi.quantity) as total_sold
    FROM products p
    JOIN order_items oi ON p.id = oi.product_id
    GROUP BY p.id
    ORDER BY total_sold DESC
    LIMIT 5
    """
    top_products = db.fetch_all(top_products_query)
    
    # Get platform distribution
    platform_query = """
    SELECT platform, COUNT(*) as count
    FROM products
    GROUP BY platform
    """
    platforms = db.fetch_all(platform_query)
    
    # Get monthly revenue data for chart
    monthly_revenue_query = """
    SELECT strftime('%Y-%m', datetime(rowid, 'unixepoch')) as month, SUM(total_price) as revenue
    FROM orders
    GROUP BY month
    ORDER BY month
    LIMIT 6
    """
    monthly_revenue = db.fetch_all(monthly_revenue_query)
    
    db.disconnect()
    
    return render_template('dashboard.html', 
                          total_games=total_games,
                          total_orders=total_orders,
                          total_users=total_users,
                          total_revenue=total_revenue,
                          recent_orders=recent_orders,
                          low_stock=low_stock,
                          top_products=top_products,
                          platforms=platforms,
                          monthly_revenue=monthly_revenue)

# Game Management Routes
@app.route('/games')
@login_required
def games():
    db.connect()
    games = db.fetch_all("SELECT * FROM products ORDER BY id DESC")
    db.disconnect()
    return render_template('games.html', games=games)

@app.route('/games/add', methods=['GET', 'POST'])
@login_required
def add_game():
    if request.method == 'POST':
        name = request.form.get('name')
        platform = request.form.get('platform')
        price = request.form.get('price')
        stock = request.form.get('stock')
        description = request.form.get('description')
        image_url = request.form.get('image_url')
        
        if not all([name, platform, price, stock, image_url]):
            flash('Please fill all required fields', 'error')
            return render_template('add_game.html')
        
        db.connect()
        result = db.execute_query(
            "INSERT INTO products (name, platform, price, stock, description, image_url) VALUES (?, ?, ?, ?, ?, ?)",
            (name, platform, price, stock, description, image_url)
        )
        
        if result:
            # Log the action
            admin_db.connect()
            admin_db.log_admin_action(
                session['admin_id'], 
                'add_game', 
                f"Added game: {name} ({platform}) at ${price}"
            )
            admin_db.disconnect()
            
            flash('Game added successfully!', 'success')
            db.disconnect()
            return redirect(url_for('games'))
        else:
            flash('Error adding game', 'error')
            db.disconnect()
    
    return render_template('add_game.html')

@app.route('/games/edit/<int:game_id>', methods=['GET', 'POST'])
@login_required
def edit_game(game_id):
    db.connect()
    game = db.fetch_one("SELECT * FROM products WHERE id = ?", (game_id,))
    
    if not game:
        db.disconnect()
        flash('Game not found', 'error')
        return redirect(url_for('games'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        platform = request.form.get('platform')
        price = request.form.get('price')
        stock = request.form.get('stock')
        description = request.form.get('description')
        image_url = request.form.get('image_url')
        
        if not all([name, platform, price, stock, image_url]):
            flash('Please fill all required fields', 'error')
            return render_template('edit_game.html', game=game)
        
        result = db.execute_query(
            "UPDATE products SET name = ?, platform = ?, price = ?, stock = ?, description = ?, image_url = ? WHERE id = ?",
            (name, platform, price, stock, description, image_url, game_id)
        )
        
        if result:
            # Log the action
            admin_db.connect()
            admin_db.log_admin_action(
                session['admin_id'], 
                'edit_game', 
                f"Edited game ID {game_id}: {name} ({platform}) at ${price}"
            )
            admin_db.disconnect()
            
            flash('Game updated successfully!', 'success')
            db.disconnect()
            return redirect(url_for('games'))
        else:
            flash('Error updating game', 'error')
    
    db.disconnect()
    return render_template('edit_game.html', game=game)

@app.route('/games/delete/<int:game_id>', methods=['POST'])
@login_required
def delete_game(game_id):
    db.connect()
    game = db.fetch_one("SELECT * FROM products WHERE id = ?", (game_id,))
    
    if not game:
        db.disconnect()
        flash('Game not found', 'error')
        return redirect(url_for('games'))
    
    # Check if game is in any orders
    order_items = db.fetch_all("SELECT * FROM order_items WHERE product_id = ?", (game_id,))
    if order_items:
        db.disconnect()
        flash('Cannot delete game that has been ordered', 'error')
        return redirect(url_for('games'))
    
    result = db.execute_query("DELETE FROM products WHERE id = ?", (game_id,))
    
    if result:
        # Log the action
        admin_db.connect()
        admin_db.log_admin_action(
            session['admin_id'], 
            'delete_game', 
            f"Deleted game ID {game_id}: {game['name']} ({game['platform']})"
        )
        admin_db.disconnect()
        
        flash('Game deleted successfully!', 'success')
    else:
        flash('Error deleting game', 'error')
    
    db.disconnect()
    return redirect(url_for('games'))

@app.route('/games/restock/<int:game_id>', methods=['GET', 'POST'])
@login_required
def restock_game(game_id):
    db.connect()
    game = db.fetch_one("SELECT * FROM products WHERE id = ?", (game_id,))
    
    if not game:
        db.disconnect()
        flash('Game not found', 'error')
        return redirect(url_for('games'))
    
    if request.method == 'POST':
        stock = request.form.get('stock')
        
        if not stock or not stock.isdigit():
            flash('Please enter a valid stock quantity', 'error')
            return render_template('restock_game.html', game=game)
        
        result = db.execute_query(
            "UPDATE products SET stock = ? WHERE id = ?",
            (stock, game_id)
        )
        
        if result:
            # Log the action
            admin_db.connect()
            admin_db.log_admin_action(
                session['admin_id'], 
                'restock_game', 
                f"Restocked game ID {game_id}: {game['name']} to {stock} units"
            )
            admin_db.disconnect()
            
            flash('Game restocked successfully!', 'success')
            db.disconnect()
            return redirect(url_for('games'))
        else:
            flash('Error restocking game', 'error')
    
    db.disconnect()
    return render_template('restock_game.html', game=game)

# Order Management Routes
@app.route('/orders')
@login_required
def orders():
    db.connect()
    orders = db.fetch_all("SELECT * FROM orders ORDER BY id DESC")
    
    # Get user details for each order
    for order in orders:
        user = db.fetch_one("SELECT * FROM users WHERE id = ?", (order['user_id'],))
        order['user'] = user
    
    db.disconnect()
    return render_template('orders.html', orders=orders)

@app.route('/orders/<int:order_id>')
@login_required
def order_details(order_id):
    db.connect()
    order = db.fetch_one("SELECT * FROM orders WHERE id = ?", (order_id,))
    
    if not order:
        db.disconnect()
        flash('Order not found', 'error')
        return redirect(url_for('orders'))
    
    # Get user details
    user = db.fetch_one("SELECT * FROM users WHERE id = ?", (order['user_id'],))
    order['user'] = user
    
    # Get order items
    items_query = """
    SELECT oi.*, p.name, p.platform, p.image_url
    FROM order_items oi
    JOIN products p ON oi.product_id = p.id
    WHERE oi.order_id = ?
    """
    items = db.fetch_all(items_query, (order_id,))
    
    # Parse user details JSON if available
    user_details = {}
    if order['user_details']:
        try:
            user_details = json.loads(order['user_details'])
        except json.JSONDecodeError:
            user_details = {'error': 'Could not parse user details'}
    
    db.disconnect()
    return render_template('order_details.html', order=order, items=items, user_details=user_details)

@app.route('/orders/update_status/<int:order_id>', methods=['POST'])
@login_required
def update_order_status(order_id):
    status = request.form.get('status')
    
    if not status:
        flash('Please select a status', 'error')
        return redirect(url_for('order_details', order_id=order_id))
    
    db.connect()
    order = db.fetch_one("SELECT * FROM orders WHERE id = ?", (order_id,))
    
    if not order:
        db.disconnect()
        flash('Order not found', 'error')
        return redirect(url_for('orders'))
    
    result = db.execute_query(
        "UPDATE orders SET status = ? WHERE id = ?",
        (status, order_id)
    )
    
    if result:
        # Log the action
        admin_db.connect()
        admin_db.log_admin_action(
            session['admin_id'], 
            'update_order_status', 
            f"Updated order ID {order_id} status to {status}"
        )
        admin_db.disconnect()
        
        flash(f'Order status updated to {status}!', 'success')
    else:
        flash('Error updating order status', 'error')
    
    db.disconnect()
    return redirect(url_for('order_details', order_id=order_id))

# Category Management Routes
@app.route('/categories')
@login_required
def categories():
    # For this application, categories are the platforms
    db.connect()
    platform_query = """
    SELECT platform, COUNT(*) as game_count
    FROM products
    GROUP BY platform
    ORDER BY platform
    """
    platforms = db.fetch_all(platform_query)
    db.disconnect()
    
    return render_template('categories.html', platforms=platforms)

@app.route('/categories/add', methods=['GET', 'POST'])
@login_required
def add_category():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description', '')
        
        if not name:
            flash('Please enter a category name', 'error')
            return render_template('add_category.html')
        
        # Connect to admin database to add the category
        admin_db.connect()
        
        # Check if category exists
        existing = admin_db.fetch_one("SELECT * FROM categories WHERE name = ?", (name,))
        if existing:
            admin_db.disconnect()
            flash('Category already exists', 'error')
            return render_template('add_category.html')
        
        result = admin_db.execute_query(
            "INSERT INTO categories (name, description) VALUES (?, ?)",
            (name, description)
        )
        
        if result:
            admin_db.log_admin_action(
                session['admin_id'], 
                'add_category', 
                f"Added category: {name}"
            )
            admin_db.disconnect()
            
            flash('Category added successfully!', 'success')
            return redirect(url_for('categories'))
        else:
            admin_db.disconnect()
            flash('Error adding category', 'error')
    
    return render_template('add_category.html')

@app.route('/categories/edit/<string:category_name>', methods=['GET', 'POST'])
@login_required
def edit_category(category_name):
    admin_db.connect()
    
    category = admin_db.fetch_one("SELECT * FROM categories WHERE name = ?", (category_name,))
    
    if not category:
        admin_db.disconnect()
        flash('Category not found', 'error')
        return redirect(url_for('categories'))
    
    if request.method == 'POST':
        new_name = request.form.get('name')
        description = request.form.get('description', '')
        
        if not new_name:
            flash('Please enter a category name', 'error')
            return render_template('edit_category.html', category=category)
        
        # Check if new name already exists (if different from current)
        if new_name != category_name:
            existing = admin_db.fetch_one("SELECT * FROM categories WHERE name = ?", (new_name,))
            if existing:
                admin_db.disconnect()
                flash('Category name already exists', 'error')
                return render_template('edit_category.html', category=category)
        
        result = admin_db.execute_query(
            "UPDATE categories SET name = ?, description = ? WHERE name = ?",
            (new_name, description, category_name)
        )
        
        if result:
            # If category name changed, update all products with this platform
            if new_name != category_name:
                db.connect()
                db.execute_query(
                    "UPDATE products SET platform = ? WHERE platform = ?",
                    (new_name, category_name)
                )
                db.disconnect()
            
            admin_db.log_admin_action(
                session['admin_id'], 
                'edit_category', 
                f"Updated category from {category_name} to {new_name}"
            )
            admin_db.disconnect()
            
            flash('Category updated successfully!', 'success')
            return redirect(url_for('categories'))
        else:
            admin_db.disconnect()
            flash('Error updating category', 'error')
    
    admin_db.disconnect()
    return render_template('edit_category.html', category=category)

@app.route('/categories/delete/<string:category_name>', methods=['POST'])
@login_required
def delete_category(category_name):
    # Check if any games use this platform
    db.connect()
    games = db.fetch_all("SELECT * FROM products WHERE platform = ?", (category_name,))
    
    if games:
        db.disconnect()
        flash('Cannot delete category that has games assigned to it', 'error')
        return redirect(url_for('categories'))
    
    db.disconnect()
    
    # Delete from admin database
    admin_db.connect()
    
    result = admin_db.execute_query("DELETE FROM categories WHERE name = ?", (category_name,))
    
    if result:
        admin_db.log_admin_action(
            session['admin_id'], 
            'delete_category', 
            f"Deleted category: {category_name}"
        )
        admin_db.disconnect()
        
        flash('Category deleted successfully!', 'success')
    else:
        admin_db.disconnect()
        flash('Error deleting category', 'error')
    
    return redirect(url_for('categories'))

# Client Management Routes
@app.route('/clients')
@login_required
def clients():
    db.connect()
    clients = db.fetch_all("SELECT * FROM users ORDER BY id DESC")
    
    # Get order count for each client
    for client in clients:
        orders = db.fetch_all("SELECT * FROM orders WHERE user_id = ?", (client['id'],))
        client['order_count'] = len(orders)
        
        # Calculate total spent
        total_spent = sum(float(order['total_price']) for order in orders)
        client['total_spent'] = total_spent
    
    db.disconnect()
    return render_template('clients.html', clients=clients)

@app.route('/clients/<int:client_id>')
@login_required
def client_details(client_id):
    db.connect()
    client = db.fetch_one("SELECT * FROM users WHERE id = ?", (client_id,))
    
    if not client:
        db.disconnect()
        flash('Client not found', 'error')
        return redirect(url_for('clients'))
    
    # Get client orders
    orders = db.fetch_all("SELECT * FROM orders WHERE user_id = ?", (client_id,))
    
    # Get order items for each order
    for order in orders:
        items_query = """
        SELECT oi.*, p.name, p.platform
        FROM order_items oi
        JOIN products p ON oi.product_id = p.id
        WHERE oi.order_id = ?
        """
        items = db.fetch_all(items_query, (order['id'],))
        order['items'] = items
    
    db.disconnect()
    return render_template('client_details.html', client=client, orders=orders)

# Analytics Routes
@app.route('/analytics')
@login_required
def analytics():
    db.connect()
    
    # Total games sold
    total_sold_query = """
    SELECT SUM(quantity) as total
    FROM order_items
    """
    total_sold_result = db.fetch_one(total_sold_query)
    total_sold = total_sold_result['total'] if total_sold_result and total_sold_result['total'] else 0
    
    # Most sold platforms
    platform_sales_query = """
    SELECT p.platform, SUM(oi.quantity) as total
    FROM products p
    JOIN order_items oi ON p.id = oi.product_id
    GROUP BY p.platform
    ORDER BY total DESC
    """
    platform_sales = db.fetch_all(platform_sales_query)
    
    # Most sold games
    game_sales_query = """
    SELECT p.id, p.name, p.platform, SUM(oi.quantity) as total
    FROM products p
    JOIN order_items oi ON p.id = oi.product_id
    GROUP BY p.id
    ORDER BY total DESC
    LIMIT 10
    """
    game_sales = db.fetch_all(game_sales_query)
    
    # Monthly revenue
    current_month = datetime.now().strftime('%Y-%m')
    monthly_revenue_query = """
    SELECT SUM(total_price) as revenue
    FROM orders
    WHERE strftime('%Y-%m', datetime(rowid, 'unixepoch')) = ?
    """
    monthly_revenue_result = db.fetch_one(monthly_revenue_query, (current_month,))
    monthly_revenue = monthly_revenue_result['revenue'] if monthly_revenue_result and monthly_revenue_result['revenue'] else 0
    
    # Revenue by platform
    platform_revenue_query = """
    SELECT p.platform, SUM(oi.quantity * oi.price) as revenue
    FROM products p
    JOIN order_items oi ON p.id = oi.product_id
    GROUP BY p.platform
    ORDER BY revenue DESC
    """
    platform_revenue = db.fetch_all(platform_revenue_query)
    
    # Revenue by game
    game_revenue_query = """
    SELECT p.id, p.name, p.platform, SUM(oi.quantity * oi.price) as revenue
    FROM products p
    JOIN order_items oi ON p.id = oi.product_id
    GROUP BY p.id
    ORDER BY revenue DESC
    LIMIT 10
    """
    game_revenue = db.fetch_all(game_revenue_query)
    
    # Monthly sales trend (last 6 months)
    sales_trend_query = """
    SELECT strftime('%Y-%m', datetime(rowid, 'unixepoch')) as month, 
           COUNT(*) as order_count,
           SUM(total_price) as revenue
    FROM orders
    GROUP BY month
    ORDER BY month DESC
    LIMIT 6
    """
    sales_trend = db.fetch_all(sales_trend_query)
    sales_trend.reverse()  # Show oldest to newest
    
    db.disconnect()
    
    return render_template('analytics.html',
                          total_sold=total_sold,
                          platform_sales=platform_sales,
                          game_sales=game_sales,
                          monthly_revenue=monthly_revenue,
                          platform_revenue=platform_revenue,
                          game_revenue=game_revenue,
                          sales_trend=sales_trend)

# Stock Management Routes
@app.route('/stock')
@login_required
def stock():
    db.connect()
    products = db.fetch_all("SELECT * FROM products ORDER BY stock ASC")
    
    # Get stock alerts
    admin_db.connect()
    alerts = admin_db.fetch_all("SELECT * FROM stock_alerts")
    
    # Create a dictionary of product_id -> threshold
    alert_thresholds = {alert['product_id']: alert['threshold'] for alert in alerts}
    
    # Add alert flag to products
    for product in products:
        threshold = alert_thresholds.get(product['id'], 5)  # Default threshold is 5
        product['is_low'] = product['stock'] < threshold
        product['threshold'] = threshold
    
    admin_db.disconnect()
    db.disconnect()
    
    return render_template('stock.html', products=products)

@app.route('/stock/set_alert/<int:product_id>', methods=['POST'])
@login_required
def set_stock_alert(product_id):
    threshold = request.form.get('threshold')
    
    if not threshold or not threshold.isdigit():
        flash('Please enter a valid threshold', 'error')
        return redirect(url_for('stock'))
    
    db.connect()
    product = db.fetch_one("SELECT * FROM products WHERE id = ?", (product_id,))
    
    if not product:
        db.disconnect()
        flash('Product not found', 'error')
        return redirect(url_for('stock'))
    
    admin_db.connect()
    
    # Check if alert already exists
    existing = admin_db.fetch_one("SELECT * FROM stock_alerts WHERE product_id = ?", (product_id,))
    
    if existing:
        result = admin_db.execute_query(
            "UPDATE stock_alerts SET threshold = ?, created_by = ? WHERE product_id = ?",
            (threshold, session['admin_id'], product_id)
        )
    else:
        result = admin_db.execute_query(
            "INSERT INTO stock_alerts (product_id, threshold, created_by) VALUES (?, ?, ?)",
            (product_id, threshold, session['admin_id'])
        )
    
    if result:
        admin_db.log_admin_action(
            session['admin_id'], 
            'set_stock_alert', 
            f"Set stock alert for {product['name']} to {threshold} units"
        )
        admin_db.disconnect()
        db.disconnect()
        
        flash('Stock alert set successfully!', 'success')
    else:
        admin_db.disconnect()
        db.disconnect()
        flash('Error setting stock alert', 'error')
    
    return redirect(url_for('stock'))

# Discount Management Routes
@app.route('/discounts')
@login_required
def discounts():
    db.connect()
    products = db.fetch_all("SELECT * FROM products ORDER BY name")
    
    admin_db.connect()
    discounts = admin_db.fetch_all("SELECT * FROM discounts")
    
    # Create a dictionary of product_id -> discount
    discount_map = {}
    for discount in discounts:
        discount_map[discount['product_id']] = discount
    
    # Add discount info to products
    for product in products:
        product['discount'] = discount_map.get(product['id'], None)
    
    admin_db.disconnect()
    db.disconnect()
    
    return render_template('discounts.html', products=products)

@app.route('/discounts/add/<int:product_id>', methods=['GET', 'POST'])
@login_required
def add_discount(product_id):
    db.connect()
    product = db.fetch_one("SELECT * FROM products WHERE id = ?", (product_id,))
    
    if not product:
        db.disconnect()
        flash('Product not found', 'error')
        return redirect(url_for('discounts'))
    
    if request.method == 'POST':
        percentage = request.form.get('percentage')
        start_date = request.form.get('start_date')
        end_date = request.form.get('end_date')
        
        if not percentage or not percentage.replace('.', '', 1).isdigit():
            db.disconnect()
            flash('Please enter a valid discount percentage', 'error')
            return render_template('add_discount.html', product=product)
        
        admin_db.connect()
        
        # Check if discount already exists
        existing = admin_db.fetch_one("SELECT * FROM discounts WHERE product_id = ?", (product_id,))
        
        if existing:
            result = admin_db.execute_query(
                "UPDATE discounts SET discount_percentage = ?, start_date = ?, end_date = ?, created_by = ? WHERE product_id = ?",
                (percentage, start_date, end_date, session['admin_id'], product_id)
            )
        else:
            result = admin_db.execute_query(
                "INSERT INTO discounts (product_id, discount_percentage, start_date, end_date, created_by) VALUES (?, ?, ?, ?, ?)",
                (product_id, percentage, start_date, end_date, session['admin_id'])
            )
        
        if result:
            admin_db.log_admin_action(
                session['admin_id'], 
                'add_discount', 
                f"Added {percentage}% discount for {product['name']}"
            )
            admin_db.disconnect()
            db.disconnect()
            
            flash('Discount added successfully!', 'success')
            return redirect(url_for('discounts'))
        else:
            admin_db.disconnect()
            db.disconnect()
            flash('Error adding discount', 'error')
    
    db.disconnect()
    return render_template('add_discount.html', product=product)

@app.route('/discounts/delete/<int:product_id>', methods=['POST'])
@login_required
def delete_discount(product_id):
    db.connect()
    product = db.fetch_one("SELECT * FROM products WHERE id = ?", (product_id,))
    
    if not product:
        db.disconnect()
        flash('Product not found', 'error')
        return redirect(url_for('discounts'))
    
    admin_db.connect()
    
    result = admin_db.execute_query("DELETE FROM discounts WHERE product_id = ?", (product_id,))
    
    if result:
        admin_db.log_admin_action(
            session['admin_id'], 
            'delete_discount', 
            f"Removed discount for {product['name']}"
        )
        admin_db.disconnect()
        db.disconnect()
        
        flash('Discount removed successfully!', 'success')
    else:
        admin_db.disconnect()
        db.disconnect()
        flash('Error removing discount', 'error')
    
    return redirect(url_for('discounts'))

# Broadcast Messages Routes
@app.route('/broadcasts')
@login_required
def broadcasts():
    admin_db.connect()
    
    broadcasts = admin_db.fetch_all("SELECT * FROM broadcast_messages ORDER BY id DESC")
    
    admin_db.disconnect()
    
    return render_template('broadcasts.html', broadcasts=broadcasts)

@app.route('/broadcasts/send', methods=['GET', 'POST'])
@login_required
def send_broadcast():
    if request.method == 'POST':
        message = request.form.get('message')
        target_group = request.form.get('target_group', 'all')
        
        if not message:
            flash('Please enter a message', 'error')
            return render_template('send_broadcast.html')
        
        # TODO: Implement actual Telegram bot integration
        # For now, just log the broadcast
        
        admin_db.connect()
        
        result = admin_db.execute_query(
            "INSERT INTO broadcast_messages (message, sent_by, target_group) VALUES (?, ?, ?)",
            (message, session['admin_id'], target_group)
        )
        
        if result:
            admin_db.log_admin_action(
                session['admin_id'], 
                'send_broadcast', 
                f"Sent broadcast to {target_group}: {message[:50]}..."
            )
            admin_db.disconnect()
            
            flash('Broadcast sent successfully!', 'success')
            return redirect(url_for('broadcasts'))
        else:
            admin_db.disconnect()
            flash('Error sending broadcast', 'error')
    
    return render_template('send_broadcast.html')

# Admin Logs Routes
@app.route('/logs')
@login_required
def logs():
    admin_db.connect()
    
    logs = admin_db.fetch_all("SELECT * FROM admin_logs ORDER BY id DESC LIMIT 100")
    
    # Get admin usernames
    admin_ids = set(log['admin_id'] for log in logs if log['admin_id'])
    admins = {}
    
    for admin_id in admin_ids:
        admin = admin_db.fetch_one("SELECT * FROM admin_users WHERE id = ?", (admin_id,))
        if admin:
            admins[admin_id] = admin['username']
    
    admin_db.disconnect()
    
    return render_template('logs.html', logs=logs, admins=admins)

# Export Data Routes
@app.route('/export/<string:data_type>')
@login_required
def export_data(data_type):
    db.connect()
    
    if data_type == 'orders':
        data = db.fetch_all("SELECT * FROM orders")
        filename = 'orders.csv'
        headers = ['id', 'user_id', 'total_price', 'status', 'user_details']
    elif data_type == 'clients':
        data = db.fetch_all("SELECT * FROM users")
        filename = 'clients.csv'
        headers = ['id', 'username', 'first_name', 'last_name']
    elif data_type == 'products':
        data = db.fetch_all("SELECT * FROM products")
        filename = 'products.csv'
        headers = ['id', 'name', 'platform', 'price', 'stock', 'description', 'image_url']
    else:
        db.disconnect()
        flash('Invalid export type', 'error')
        return redirect(url_for('dashboard'))
    
    db.disconnect()
    
    # Convert to CSV
    csv_data = ','.join(headers) + '\n'
    for row in data:
        csv_data += ','.join(str(row[header]) for header in headers) + '\n'
    
    # Log the export
    admin_db.connect()
    admin_db.log_admin_action(
        session['admin_id'], 
        'export_data', 
        f"Exported {data_type} data"
    )
    admin_db.disconnect()
    
    # Create response
    response = app.response_class(
        response=csv_data,
        status=200,
        mimetype='text/csv'
    )
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response

# API Endpoints for AJAX requests
@app.route('/api/dashboard/stats')
@login_required
def api_dashboard_stats():
    db.connect()
    
    # Get dashboard statistics
    total_games = len(db.fetch_all("SELECT * FROM products"))
    total_orders = len(db.fetch_all("SELECT * FROM orders"))
    total_users = len(db.fetch_all("SELECT * FROM users"))
    
    # Calculate total revenue
    orders = db.fetch_all("SELECT total_price FROM orders")
    total_revenue = sum(float(order['total_price']) for order in orders)
    
    # Get monthly revenue data for chart
    monthly_revenue_query = """
    SELECT strftime('%Y-%m', datetime(rowid, 'unixepoch')) as month, SUM(total_price) as revenue
    FROM orders
    GROUP BY month
    ORDER BY month
    LIMIT 6
    """
    monthly_revenue = db.fetch_all(monthly_revenue_query)
    
    # Format for Chart.js
    months = [item['month'] for item in monthly_revenue]
    revenues = [float(item['revenue']) for item in monthly_revenue]
    
    db.disconnect()
    
    return jsonify({
        'total_games': total_games,
        'total_orders': total_orders,
        'total_users': total_users,
        'total_revenue': total_revenue,
        'chart_data': {
            'labels': months,
            'datasets': [{
                'label': 'Monthly Revenue',
                'data': revenues,
                'backgroundColor': 'rgba(54, 162, 235, 0.2)',
                'borderColor': 'rgba(54, 162, 235, 1)',
                'borderWidth': 1
            }]
        }
    })

if __name__ == '__main__':
    # Initialize admin database
    admin_db.connect()
    admin_db.create_tables()
    admin_db.disconnect()
    
    port = int(os.getenv('PORT', 5000))
    app.run( host='0.0.0.0', port=port)
