import sqlite3
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

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

class Database:
    def __init__(self, db_name: str = 'exodus_games.db'):
        """Initialize the SQLite database, create tables, and migrate schema."""
        self.db_name = db_name
        self.create_tables()
        self.migrate_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Return a new SQLite connection with row factory set."""
        conn = sqlite3.connect(self.db_name)
        conn.row_factory = sqlite3.Row
        return conn

    def migrate_schema(self):
        """Migrate the database schema to ensure required columns and indexes exist."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Check if stock column exists in products table
                cursor.execute("PRAGMA table_info(products)")
                columns = [col['name'] for col in cursor.fetchall()]
                
                if 'stock' not in columns:
                    logger.info("Adding stock column to products table")
                    cursor.execute('ALTER TABLE products ADD COLUMN stock INTEGER NOT NULL DEFAULT 0')
                    
                    # Set default stock values for existing products
                    cursor.execute('UPDATE products SET stock = 10 WHERE product_id = 1')
                    cursor.execute('UPDATE products SET stock = 15 WHERE product_id = 2')
                    cursor.execute('UPDATE products SET stock = 8 WHERE product_id = 3')
                    cursor.execute('UPDATE products SET stock = 12 WHERE product_id = 4')
                    cursor.execute('UPDATE products SET stock = 20 WHERE product_id = 5')
                
                # Ensure stock index exists
                cursor.execute("PRAGMA index_list(products)")
                indexes = [index['name'] for index in cursor.fetchall()]
                if 'idx_products_stock' not in indexes:
                    logger.info("Creating idx_products_stock index")
                    cursor.execute('CREATE INDEX idx_products_stock ON products (stock)')
                
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Schema migration failed: {e}")
            raise

    def create_tables(self):
        """Create database tables and indexes if they don't exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Users table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                phone TEXT,
                address TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''')

            # Products table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                product_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                platform TEXT,
                description TEXT,
                image_url TEXT,
                stock INTEGER NOT NULL DEFAULT 0
            )
            ''')

            # Orders table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending',
                total_amount REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
            ''')

            # Order items table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS order_items (
                item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                product_id INTEGER,
                quantity INTEGER DEFAULT 1,
                price_at_purchase REAL NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders (order_id),
                FOREIGN KEY (product_id) REFERENCES products (product_id)
            )
            ''')

            # Carts table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS carts (
                cart_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
            ''')

            # Cart items table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS cart_items (
                cart_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                cart_id INTEGER,
                product_id INTEGER,
                quantity INTEGER DEFAULT 1,
                FOREIGN KEY (cart_id) REFERENCES carts (cart_id),
                FOREIGN KEY (product_id) REFERENCES products (product_id),
                UNIQUE (cart_id, product_id)
            )
            ''')

            # Create indexes
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_carts_user_id ON carts (user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_cart_items_cart_id ON cart_items (cart_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_cart_items_product_id ON cart_items (product_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders (user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items (order_id)')
            # idx_products_stock is created in migrate_schema to ensure stock column exists

            conn.commit()

    def add_or_update_user(self, user_id: int, username: str, full_name: str, phone: str, address: str) -> None:
        """
        Add or update a user in the users table.
        """
        if not full_name or len(full_name.strip()) < 3:
            raise ValueError("Full name must be at least 3 characters")
        if not username or not username.startswith('@') or len(username.strip()) < 4:
            raise ValueError("Username must start with '@' and be at least 4 characters")
        if not phone or not re.match(r"^(?:\+251|0)(9|7)[0-9]{8}$", phone.strip()):
            raise ValueError("Invalid Ethiopian phone number. Format: +251XXXXXXXXX or 09XXXXXXXX")
        if not address or len(address.strip()) < 10:
            raise ValueError("Address must be at least 10 characters")

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                INSERT OR REPLACE INTO users (user_id, username, full_name, phone, address)
                VALUES (?, ?, ?, ?, ?)
                ''', (user_id, username.strip(), full_name.strip(), phone.strip(), address.strip()))
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to add/update user {user_id}: {e}")
            raise

    def get_user(self, user_id: int) -> Optional[Dict]:
        """
        Retrieve a user by ID.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
                row = cursor.fetchone()
                if row:
                    return {
                        'user_id': row['user_id'],
                        'username': row['username'],
                        'full_name': row['full_name'],
                        'phone': row['phone'],
                        'address': row['address'],
                        'created_at': row['created_at']
                    }
                return None
        except sqlite3.Error as e:
            logger.error(f"Failed to get user {user_id}: {e}")
            raise

    def add_product(self, product: Dict) -> None:
        """
        Add a product to the products table if it doesn't exist.
        """
        required_keys = ['id', 'name', 'price', 'platform', 'description', 'image_url', 'stock']
        if not all(key in product for key in required_keys):
            raise ValueError(f"Product dictionary missing required keys: {required_keys}")
        if not product['name'].strip():
            raise ValueError("Product name cannot be empty")
        
        try:
            price = float(product['price'].strip('$')) if isinstance(product['price'], str) else float(product['price'])
            if price <= 0:
                raise ValueError("Price must be positive")
        except (ValueError, TypeError):
            raise ValueError("Invalid price format")
        
        if not isinstance(product['stock'], int) or product['stock'] < 0:
            raise ValueError("Stock must be a non-negative integer")

        platform = ','.join(product['platform']) if isinstance(product['platform'], list) else product['platform']
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                INSERT OR IGNORE INTO products (product_id, name, price, platform, description, image_url, stock)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    product['id'],
                    product['name'].strip(),
                    price,
                    platform,
                    product['description'].strip() if product['description'] else '',
                    product['image_url'].strip() if product['image_url'] else '',
                    product['stock']
                ))
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to add product {product.get('id')}: {e}")
            raise

    def get_product(self, product_id: int) -> Optional[Dict]:
        """
        Retrieve a product by ID.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM products WHERE product_id = ?', (product_id,))
                row = cursor.fetchone()
                if row:
                    return {
                        'id': row['product_id'],
                        'name': row['name'],
                        'price': f"${row['price']:.2f}",
                        'platform': row['platform'].split(',') if row['platform'] else [],
                        'description': row['description'],
                        'image_url': row['image_url'],
                        'stock': row['stock']
                    }
                return None
        except sqlite3.Error as e:
            logger.error(f"Failed to get product {product_id}: {e}")
            raise

    def get_or_create_cart(self, user_id: int) -> int:
        """
        Get or create a cart for a user.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT cart_id FROM carts WHERE user_id = ?', (user_id,))
                cart = cursor.fetchone()
                if not cart:
                    cursor.execute('INSERT INTO carts (user_id) VALUES (?)', (user_id,))
                    conn.commit()
                    cursor.execute('SELECT cart_id FROM carts WHERE user_id = ?', (user_id,))
                    cart = cursor.fetchone()
                return cart['cart_id']
        except sqlite3.Error as e:
            logger.error(f"Failed to get/create cart for user {user_id}: {e}")
            raise

    def add_to_cart(self, user_id: int, product_id: int, quantity: int = 1) -> None:
        """
        Add a specified quantity of a product to the user's cart, checking stock.
        """
        if not isinstance(quantity, int) or quantity < 1:
            raise ValueError("Quantity must be a positive integer")

        product = self.get_product(product_id)
        if not product:
            raise ValueError(f"Product {product_id} does not exist")
        if product['stock'] <= 0:
            raise ValueError(f"Product {product['name']} is out of stock")
        if quantity > product['stock']:
            raise ValueError(f"Cannot add {quantity} of {product['name']}: only {product['stock']} in stock")

        cart_id = self.get_or_create_cart(user_id)
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                SELECT cart_item_id, quantity FROM cart_items 
                WHERE cart_id = ? AND product_id = ?
                ''', (cart_id, product_id))
                item = cursor.fetchone()
                
                new_quantity = (item['quantity'] + quantity) if item else quantity
                if new_quantity > product['stock']:
                    raise ValueError(f"Cannot add {new_quantity} of {product['name']}: only {product['stock']} in stock")
                
                if item:
                    cursor.execute('''
                    UPDATE cart_items SET quantity = ? 
                    WHERE cart_item_id = ?
                    ''', (new_quantity, item['cart_item_id']))
                else:
                    cursor.execute('''
                    INSERT INTO cart_items (cart_id, product_id, quantity) 
                    VALUES (?, ?, ?)
                    ''', (cart_id, product_id, quantity))
                
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to add product {product_id} (quantity {quantity}) to cart for user {user_id}: {e}")
            raise

    def remove_from_cart(self, user_id: int, product_id: int) -> None:
        """
        Remove a product from the user's cart.
        """
        cart_id = self.get_or_create_cart(user_id)
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                DELETE FROM cart_items 
                WHERE cart_id = ? AND product_id = ?
                ''', (cart_id, product_id))
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to remove product {product_id} from cart for user {user_id}: {e}")
            raise

    def get_cart_items(self, user_id: int) -> List[Dict]:
        """
        Retrieve all items in the user's cart.
        """
        cart_id = self.get_or_create_cart(user_id)
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                SELECT p.product_id, p.name, p.price, p.platform, p.description, p.image_url, p.stock, ci.quantity
                FROM cart_items ci
                JOIN products p ON ci.product_id = p.product_id
                WHERE ci.cart_id = ?
                ''', (cart_id,))
                
                items = []
                for row in cursor.fetchall():
                    items.append({
                        'id': row['product_id'],
                        'name': row['name'],
                        'price': f"${row['price']:.2f}",
                        'platform': row['platform'].split(',') if row['platform'] else [],
                        'description': row['description'],
                        'image_url': row['image_url'],
                        'stock': row['stock'],
                        'quantity': row['quantity']
                    })
                return items
        except sqlite3.Error as e:
            logger.error(f"Failed to get cart items for user {user_id}: {e}")
            raise

    def clear_cart(self, user_id: int) -> None:
        """
        Clear all items from the user's cart.
        """
        cart_id = self.get_or_create_cart(user_id)
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM cart_items WHERE cart_id = ?', (cart_id,))
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to clear cart for user {user_id}: {e}")
            raise

    def create_order(self, user_id: int, cart_items: List[Dict]) -> int:
        """
        Create an order from the user's cart items, decrease stock, and clear the cart.
        """
        if not cart_items:
            raise ValueError("Cannot create order with empty cart")

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Verify stock for all items
                for item in cart_items:
                    cursor.execute('SELECT stock, name FROM products WHERE product_id = ?', (item['id'],))
                    product = cursor.fetchone()
                    if not product:
                        raise ValueError(f"Product {item['id']} does not exist")
                    if product['stock'] < item['quantity']:
                        raise ValueError(f"Cannot order {product['name']}: only {product['stock']} in stock")
                
                # Calculate total
                total = sum(float(item['price'].strip('$')) * item['quantity'] for item in cart_items)
                
                # Create order
                cursor.execute('''
                INSERT INTO orders (user_id, total_amount)
                VALUES (?, ?)
                ''', (user_id, total))
                order_id = cursor.lastrowid
                
                # Add order items and decrease stock
                for item in cart_items:
                    price = float(item['price'].strip('$'))
                    cursor.execute('''
                    INSERT INTO order_items (order_id, product_id, quantity, price_at_purchase)
                    VALUES (?, ?, ?, ?)
                    ''', (order_id, item['id'], item['quantity'], price))
                    
                    cursor.execute('''
                    UPDATE products SET stock = stock - ? WHERE product_id = ?
                    ''', (item['quantity'], item['id']))
                
                # Clear cart
                self.clear_cart(user_id)
                
                conn.commit()
                return order_id
        except sqlite3.Error as e:
            logger.error(f"Failed to create order for user {user_id}: {e}")
            raise
        except ValueError as ve:
            logger.error(f"Invalid cart item data for user {user_id}: {ve}")
            raise

    def get_user_orders(self, user_id: int) -> List[Dict]:
        """
        Retrieve all orders for a user.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                SELECT o.order_id, o.order_date, o.total_amount, o.status,
                       p.name, oi.quantity, oi.price_at_purchase
                FROM orders o
                LEFT JOIN order_items oi ON o.order_id = oi.order_id
                LEFT JOIN products p ON oi.product_id = p.product_id
                WHERE o.user_id = ?
                ORDER BY o.order_date DESC
                ''', (user_id,))
                
                orders = {}
                for row in cursor.fetchall():
                    order_id = row['order_id']
                    if order_id not in orders:
                        orders[order_id] = {
                            'order_id': order_id,
                            'order_date': row['order_date'],
                            'total_amount': row['total_amount'],
                            'status': row['status'],
                            'items': []
                        }
                    if row['name']:
                        orders[order_id]['items'].append({
                            'name': row['name'],
                            'quantity': row['quantity'],
                            'price': f"${row['price_at_purchase']:.2f}"
                        })
                
                return list(orders.values())
        except sqlite3.Error as e:
            logger.error(f"Failed to get orders for user {user_id}: {e}")
            raise

    def close(self):
        """Close the database connection (not typically used with context managers)."""
        pass