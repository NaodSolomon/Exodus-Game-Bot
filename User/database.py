import aiosqlite
import json
import logging
import os
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path: str = None):
        if db_path is None:
            # Set db_path to User directory, where database.py resides
            base_dir = Path(os.path.dirname(__file__))
            db_path = str(base_dir / "data.db")  # Creates User\data.db
            # Ensure the directory exists
            base_dir.mkdir(exist_ok=True)
        self.db_path = db_path
        logger.info(f"Database path set to: {self.db_path}")
    
    async def initialize(self):
        """Initialize the database and create tables."""
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                await conn.execute("PRAGMA foreign_keys = ON")
                # Users table
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        last_name TEXT
                    )
                ''')
                # Products table
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS products (
                        id INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        platform TEXT,
                        price REAL NOT NULL,
                        stock INTEGER NOT NULL,
                        description TEXT,
                        image_url TEXT NOT NULL
                    )
                ''')
                # Cart table
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS cart (
                        user_id INTEGER NOT NULL,
                        product_id INTEGER NOT NULL,
                        quantity INTEGER NOT NULL,
                        PRIMARY KEY (user_id, product_id),
                        FOREIGN KEY(user_id) REFERENCES users(id),
                        FOREIGN KEY(product_id) REFERENCES products(id)
                    )
                ''')
                # Orders table
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS orders (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        total_price REAL NOT NULL,
                        status TEXT NOT NULL,
                        user_details TEXT,
                        FOREIGN KEY(user_id) REFERENCES users(id)
                    )
                ''')
                # Order items table
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS order_items (
                        order_id INTEGER NOT NULL,
                        product_id INTEGER NOT NULL,
                        quantity INTEGER NOT NULL,
                        price TEXT NOT NULL,
                        PRIMARY KEY (order_id, product_id),
                        FOREIGN KEY(order_id) REFERENCES orders(id),
                        FOREIGN KEY(product_id) REFERENCES products(id)
                    )
                ''')
                await conn.commit()
            logger.info(f"Database initialized at {self.db_path}")
        except aiosqlite.OperationalError as e:
            logger.error(f"Database error: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected error initializing database: {e}", exc_info=True)
            raise
    
    async def add_to_cart(self, user_id: int, product_id: int, quantity: int) -> None:
        """Add or update a product in the user's cart."""
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                # Check if the product is already in the cart
                cursor = await conn.execute('''
                    SELECT quantity FROM cart
                    WHERE user_id = ? AND product_id = ?
                ''', (user_id, product_id))
                row = await cursor.fetchone()
                if row:
                    new_quantity = row[0] + quantity
                    await conn.execute('''
                        UPDATE cart
                        SET quantity = ?
                        WHERE user_id = ? AND product_id = ?
                    ''', (new_quantity, user_id, product_id))
                else:
                    await conn.execute('''
                        INSERT INTO cart (user_id, product_id, quantity)
                        VALUES (?, ?, ?)
                    ''', (user_id, product_id, quantity))
                await conn.commit()
        except aiosqlite.OperationalError as e:
            logger.error(f"Database error adding to cart for user {user_id}: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Error adding to cart for user {user_id}: {e}", exc_info=True)
            raise

    # database.py (add to the Database class, e.g., after the initialize method)
    async def get_all_products(self) -> List[Dict[str, Any]]:
        """Retrieve all products from the database."""
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute('''
                    SELECT id, name, platform, price, stock, description, image_url
                    FROM products
                ''')
                rows = await cursor.fetchall()
                return [
                    {
                        'id': row['id'],
                        'name': row['name'],
                        'platform': json.loads(row['platform']),
                        'price': float(row['price']),
                        'stock': row['stock'],
                        'description': row['description'],
                        'image_url': row['image_url']
                    } for row in rows
                ]
        except aiosqlite.OperationalError as e:
            logger.error(f"Database error retrieving products: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Error retrieving all products: {e}", exc_info=True)
            raise

    async def add_user(self, user_id: int, username: str, first_name: str, last_name: str) -> None:
            """Add or update a user."""
            try:
                async with aiosqlite.connect(self.db_path) as conn:
                    await conn.execute('''
                        INSERT OR REPLACE INTO users (id, username, first_name, last_name)
                        VALUES (?, ?, ?, ?)
                    ''', (user_id, username, first_name, last_name))
                    await conn.commit()
                logger.info(f"Added/updated user {user_id}")
            except Exception as e:
                logger.error(f"Error adding user {user_id}: {e}", exc_info=True)
                raise

    async def get_product(self, product_id: int) -> Dict[str, Any]:
            """Retrieve a product by ID."""
            try:
                async with aiosqlite.connect(self.db_path) as conn:
                    cursor = await conn.execute('''
                        SELECT id, name, platform, price, stock, description, image_url
                        FROM products WHERE id = ?
                    ''', (product_id,))
                    row = await cursor.fetchone()
                    if row:
                        return {
                            'id': row[0],
                            'name': row[1],
                            'platform': json.loads(row[2]),
                            'price': row[3],  # e.g., "$59.99"
                            'stock': row[4],
                            'description': row[5],
                            'image_url': row[6]
                        }
                    return None
            except Exception as e:
                logger.error(f"Error retrieving product {product_id}: {e}", exc_info=True)
                raise

    async def get_cart(self, user_id: int) -> List[Dict[str, Any]]:
        """Retrieve all items in the user's cart."""
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute('''
                    SELECT c.user_id, c.product_id, c.quantity,
                        p.id, p.name, p.platform, p.price, p.stock, p.description, p.image_url
                    FROM cart c
                    JOIN products p ON c.product_id = p.id
                    WHERE c.user_id = ?
                ''', (user_id,))
                rows = await cursor.fetchall()
                return [
                    {
                        'user_id': row['user_id'],
                        'product_id': row['product_id'],
                        'quantity': row['quantity'],
                        'id': row['id'],
                        'name': row['name'],
                        'platform': json.loads(row['platform']),
                        'price': row['price'],
                        'stock': row['stock'],
                        'description': row['description'],
                        'image_url': row['image_url']
                    } for row in rows
                ]
        except aiosqlite.OperationalError as e:
            logger.error(f"Database error retrieving cart for user {user_id}: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Error retrieving cart for user {user_id}: {e}", exc_info=True)
            raise

    async def remove_from_cart(self, user_id: int, product_id: int) -> None:
            """Remove product from user's cart."""
            try:
                async with aiosqlite.connect(self.db_path) as conn:
                    await conn.execute('''
                        DELETE FROM cart
                        WHERE user_id = ? AND product_id = ?
                    ''', (user_id, product_id))
                    await conn.commit()
                logger.info(f"Removed product {product_id} from cart for user {user_id}")
            except Exception as e:
                logger.error(f"Error removing product {product_id} from cart for user {user_id}: {e}", exc_info=True)
                raise

    async def clear_cart(self, user_id: int) -> None:
            """Clear user's cart."""
            try:
                async with aiosqlite.connect(self.db_path) as conn:
                    await conn.execute('''
                        DELETE FROM cart
                        WHERE user_id = ?
                    ''', (user_id,))
                    await conn.commit()
                logger.info(f"Cleared cart for user {user_id}")
            except Exception as e:
                logger.error(f"Error clearing cart for user {user_id}: {e}", exc_info=True)
                raise

    async def create_order(self, user_id: int, total_price: float, cart_items: List[Dict[str, Any]]) -> int:
            """Create an order from cart items."""
            try:
                async with aiosqlite.connect(self.db_path) as conn:
                    # Insert order
                    cursor = await conn.execute('''
                        INSERT INTO orders (user_id, total_price, status)
                        VALUES (?, ?, ?)
                    ''', (user_id, total_price, 'pending'))
                    order_id = cursor.lastrowid
                    
                    # Insert order items
                    for item in cart_items:
                        await conn.execute('''
                            INSERT INTO order_items (order_id, product_id, quantity, price)
                            VALUES (?, ?, ?, ?)
                        ''', (order_id, item['product_id'], item['quantity'], item['price']))
                    
                    await conn.commit()
                logger.info(f"Created order {order_id} for user {user_id}")
                return order_id
            except Exception as e:
                logger.error(f"Error creating order for user {user_id}: {e}", exc_info=True)
                raise

    async def update_order_details(self, order_id: int, details: Dict[str, Any]) -> None:
            """Update order with user details."""
            try:
                async with aiosqlite.connect(self.db_path) as conn:
                    await conn.execute('''
                        UPDATE orders
                        SET user_details = ?, status = 'completed'
                        WHERE id = ?
                    ''', (json.dumps(details), order_id))
                    await conn.commit()
                logger.info(f"Updated order {order_id} with user details")
            except Exception as e:
                logger.error(f"Error updating order {order_id} details: {e}", exc_info=True)
                raise

    async def cancel_order(self, order_id: int) -> None:
            """Cancel an order."""
            try:
                async with aiosqlite.connect(self.db_path) as conn:
                    await conn.execute('''
                        UPDATE orders
                        SET status = 'cancelled'
                        WHERE id = ?
                    ''', (order_id,))
                    await conn.commit()
                logger.info(f"Cancelled order {order_id}")
            except Exception as e:
                logger.error(f"Error cancelling order {order_id}: {e}", exc_info=True)
                raise

    async def deduct_stock(self, product_id: int, quantity: int) -> bool:
        """Deduct the specified quantity from the product's stock."""
        try:
            async with aiosqlite.connect(self.db_path) as conn:
                # Check current stock
                cursor = await conn.execute('''
                    SELECT stock FROM products
                    WHERE id = ?
                ''', (product_id,))
                row = await cursor.fetchone()
                if not row:
                    logger.error(f"Product {product_id} not found for stock deduction")
                    return False

                current_stock = row[0]
                if current_stock < quantity:
                    logger.warning(f"Insufficient stock for product {product_id}: {current_stock} available, {quantity} requested")
                    return False

                # Deduct stock
                new_stock = current_stock - quantity
                await conn.execute('''
                    UPDATE products
                    SET stock = ?
                    WHERE id = ?
                ''', (new_stock, product_id))
                await conn.commit()
                logger.info(f"Deducted {quantity} from stock of product {product_id}. New stock: {new_stock}")
                return True
        except aiosqlite.OperationalError as e:
            logger.error(f"Database error deducting stock for product {product_id}: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Error deducting stock for product {product_id}: {e}", exc_info=True)
            raise
