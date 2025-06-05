# Refactored User/database.py for Synchronous SQLite

import sqlite3
import json
import logging
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class Database:
    """Synchronous wrapper for User SQLite database operations."""
    def __init__(self, db_path: str = None):
        # Default to ./instance/data.db relative to project root if not provided
        # This assumes wsgi.py is in the root, adjust if needed.
        if db_path is None:
            instance_dir = Path("instance")
            instance_dir.mkdir(exist_ok=True)
            db_path = str(instance_dir / "data.db")
        self.db_path = db_path
        self.conn = None
        logger.info(f"User Database path set to: {self.db_path}")

    def connect(self):
        """Establishes a database connection."""
        if self.conn is None:
            try:
                self.conn = sqlite3.connect(self.db_path)
                self.conn.row_factory = sqlite3.Row
                self.conn.execute("PRAGMA foreign_keys = ON")
                logger.debug("User database connected")
            except sqlite3.Error as e:
                logger.error(f"User database connection error: {e}", exc_info=True)
                raise

    def disconnect(self):
        """Closes the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
            logger.debug("User database disconnected")

    def execute_query(self, query: str, params: tuple = ()) -> bool:
        """Executes a query (INSERT, UPDATE, DELETE) and returns success status."""
        if not self.conn:
            logger.error("Cannot execute query: User database not connected.")
            # Attempt to reconnect? Or rely on per-request connection.
            # For now, assume connection is managed externally (e.g., Flask request context)
            return False
        cursor = None
        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            self.conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"User DB Query execution error: {e}", exc_info=True)
            if self.conn: self.conn.rollback()
            return False
        finally:
            if cursor:
                cursor.close()

    def execute_query_get_count(self, query: str, params: tuple = ()) -> int:
        """Executes a query (typically UPDATE/DELETE) and returns the row count."""
        if not self.conn:
            logger.error("Cannot execute query: User database not connected.")
            return 0
        cursor = None
        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            count = cursor.rowcount
            self.conn.commit()
            return count
        except sqlite3.Error as e:
            logger.error(f"User DB Query execution error: {e}", exc_info=True)
            if self.conn: self.conn.rollback()
            return 0
        finally:
            if cursor:
                cursor.close()

    def fetch_one(self, query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        """Fetches a single row from the database."""
        if not self.conn:
            logger.error("Cannot fetch one: User database not connected.")
            return None
        cursor = None
        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            row = cursor.fetchone()
            return dict(row) if row else None
        except sqlite3.Error as e:
            logger.error(f"User DB Fetch one error: {e}", exc_info=True)
            return None
        finally:
            if cursor:
                cursor.close()

    def fetch_all(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Fetches all rows matching the query."""
        if not self.conn:
            logger.error("Cannot fetch all: User database not connected.")
            return []
        cursor = None
        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as e:
            logger.error(f"User DB Fetch all error: {e}", exc_info=True)
            return []
        finally:
            if cursor:
                cursor.close()

    def initialize(self):
        """Initialize the database and create tables if they don\t exist."""
        queries = [
            # Users table
            """CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            # Products table (using image_url consistently)
            """CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                platform TEXT NOT NULL, -- Storing as JSON list string e.g., '["PC"]'
                price REAL NOT NULL,
                stock INTEGER NOT NULL,
                description TEXT,
                image_url TEXT -- Store the primary image URL
            )""",
            # Cart table
            """CREATE TABLE IF NOT EXISTS cart (
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, product_id),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
            )""",
            # Orders table
            """CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                total_price REAL NOT NULL,
                status TEXT NOT NULL, -- e.g., Pending, Processing, Shipped, Delivered, Cancelled
                user_details TEXT, -- JSON string of user info at time of order
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )""",
            # Order items table
            """CREATE TABLE IF NOT EXISTS order_items (
                order_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                price REAL NOT NULL, -- Price at the time of order
                PRIMARY KEY (order_id, product_id),
                FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
                FOREIGN KEY(product_id) REFERENCES products(id) -- Don't cascade delete products with orders
            )""",
            # Favorites table
            """CREATE TABLE IF NOT EXISTS favorites (
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, product_id),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
            )"""
        ]
        try:
            self.connect()
            for query in queries:
                self.execute_query(query)
            logger.info(f"User database tables checked/created successfully at {self.db_path}")
        except Exception as e:
            logger.error(f"User database table creation error: {e}", exc_info=True)
        finally:
            self.disconnect()

    def populate_products(self, products_data: List[Dict[str, Any]], base_image_path: str):
        """Populates the products table from a list of dictionaries."""
        logger.info(f"Populating products. Received {len(products_data)} items.")
        populated_count = 0
        skipped_count = 0
        try:
            self.connect()
            for product in products_data:
                try:
                    # Validate required fields
                    if not all(k in product for k in ["id", "name", "platform", "price", "stock"]):
                        logger.warning(f"Skipping product due to missing required fields: {product.get("id", "N/A")}")
                        skipped_count += 1
                        continue

                    # Normalize platform to JSON list string
                    platform = product["platform"]
                    if isinstance(platform, str):
                        platform_json = json.dumps([platform])
                    elif isinstance(platform, list):
                        platform_json = json.dumps(platform)
                    else:
                        logger.warning(f"Skipping product {product["id"]} due to invalid platform type: {type(platform)}")
                        skipped_count += 1
                        continue
                        
                    # Normalize price
                    price_str = str(product["price"]).lstrip("$").replace(",", "")
                    price = float(price_str)
                    
                    # Normalize stock
                    stock = int(product["stock"])

                    # Handle image URL (use default if missing or file doesn't exist)
                    image_url = product.get("image_url", "images/default.jpg")
                    # Check relative path based on provided base path
                    full_image_path = os.path.join(base_image_path, image_url)
                    if not os.path.exists(full_image_path):
                        logger.warning(f"Image not found for product {product["id"]}: {full_image_path}. Using default.")
                        image_url = "images/default.jpg" # Assuming default exists relative to static path

                    # Use INSERT OR REPLACE (or INSERT OR IGNORE based on desired behavior)
                    # Using REPLACE will update existing products with the same ID.
                    success = self.execute_query(
                        "INSERT OR REPLACE INTO products (id, name, platform, price, stock, description, image_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            product["id"],
                            product["name"],
                            platform_json,
                            price,
                            stock,
                            product.get("description", ""),
                            image_url
                        )
                    )
                    if success:
                        populated_count += 1
                    else:
                        skipped_count += 1
                        logger.warning(f"Failed to insert/replace product ID: {product["id"]}")
                        
                except (ValueError, TypeError, json.JSONDecodeError) as e:
                    logger.warning(f"Skipping product {product.get("id", "N/A")} due to data error: {e}")
                    skipped_count += 1
                except Exception as e:
                    logger.error(f"Unexpected error processing product {product.get("id", "N/A")}: {e}", exc_info=True)
                    skipped_count += 1

            logger.info(f"Finished populating products. Populated: {populated_count}, Skipped: {skipped_count}")
        except Exception as e:
            logger.error(f"Error during product population: {e}", exc_info=True)
        finally:
            self.disconnect()

    # --- User Management --- (Synchronous)
    def add_user(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None) -> bool:
        return self.execute_query(
            "INSERT OR REPLACE INTO users (id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
            (user_id, username, first_name, last_name)
        )

    def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        return self.fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))

    def update_user(self, user_id: int, username: str = None, first_name: str = None, last_name: str = None) -> bool:
        # Be careful with REPLACE INTO, it deletes and inserts. UPDATE is safer.
        user = self.get_user(user_id)
        if not user:
            return False # Or call add_user?
        
        # Only update provided fields
        updates = []
        params = []
        if username is not None: 
            updates.append("username = ?")
            params.append(username)
        if first_name is not None:
            updates.append("first_name = ?")
            params.append(first_name)
        if last_name is not None:
            updates.append("last_name = ?")
            params.append(last_name)
            
        if not updates:
            return True # Nothing to update
            
        params.append(user_id)
        query = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
        return self.execute_query(query, tuple(params))

    # --- Product Management --- (Synchronous)
    def get_product(self, product_id: int) -> Optional[Dict[str, Any]]:
        product = self.fetch_one(
            "SELECT id, name, platform, price, stock, description, image_url FROM products WHERE id = ?",
            (product_id,)
        )
        # No need to parse platform JSON here, do it in the route/handler if needed
        return product

    def get_products_by_platform(self, platform_name: str) -> List[Dict[str, Any]]:
        # Search within the JSON string
        platform_json_like = f'%"{platform_name}"%'
        return self.fetch_all(
            "SELECT id, name, platform, price, stock, description, image_url FROM products WHERE platform LIKE ? AND stock > 0",
            (platform_json_like,)
        )

    def search_products(self, query: str) -> List[Dict[str, Any]]:
        return self.fetch_all(
            "SELECT id, name, platform, price, stock, description, image_url FROM products WHERE name LIKE ? AND stock > 0",
            (f"%{query}%",)
        )

    def get_all_products(self) -> List[Dict[str, Any]]:
        return self.fetch_all(
            "SELECT id, name, platform, price, stock, description, image_url FROM products WHERE stock > 0"
        )
        
    def update_product_stock(self, product_id: int, quantity_change: int) -> bool:
        """Updates stock for a product (e.g., quantity_change is negative for sale)."""
        # Important: Check stock before calling this or handle constraint violation
        return self.execute_query(
            "UPDATE products SET stock = stock + ? WHERE id = ? AND stock + ? >= 0",
            (quantity_change, product_id, quantity_change)
        )

    # --- Cart Operations --- (Synchronous)
    def add_to_cart(self, user_id: int, product_id: int, quantity: int = 1) -> bool:
        product = self.get_product(product_id)
        if not product or product["stock"] < quantity:
            logger.warning(f"Cannot add to cart: product {product_id} not found or insufficient stock ({product['stock'] if product else 'N/A'} available, {quantity} requested)")
            return False

        existing = self.fetch_one(
            "SELECT quantity FROM cart WHERE user_id = ? AND product_id = ?",
            (user_id, product_id)
        )
        
        if existing:
            # Check if adding quantity exceeds stock
            new_quantity = existing["quantity"] + quantity
            if product["stock"] < new_quantity:
                 logger.warning(f"Cannot update cart: insufficient stock for product {product_id} ({product['stock']} available, {new_quantity} requested)")
                 return False
            return self.execute_query(
                "UPDATE cart SET quantity = ? WHERE user_id = ? AND product_id = ?",
                (new_quantity, user_id, product_id)
            )
        else:
            # Check stock before inserting
            if product["stock"] < quantity:
                 logger.warning(f"Cannot add to cart: insufficient stock for product {product_id} ({product['stock']} available, {quantity} requested)")
                 return False
            return self.execute_query(
                "INSERT INTO cart (user_id, product_id, quantity) VALUES (?, ?, ?)",
                (user_id, product_id, quantity)
            )

    def get_cart(self, user_id: int) -> List[Dict[str, Any]]:
        # Join with products to get details
        return self.fetch_all(
            """SELECT c.user_id, c.product_id, c.quantity,
                p.name, p.platform, p.price, p.stock, p.image_url
               FROM cart c JOIN products p ON c.product_id = p.id
               WHERE c.user_id = ?""",
            (user_id,)
        )

    def remove_from_cart(self, user_id: int, product_id: int) -> bool:
        return self.execute_query(
            "DELETE FROM cart WHERE user_id = ? AND product_id = ?",
            (user_id, product_id)
        )

    def clear_cart(self, user_id: int) -> bool:
        return self.execute_query(
            "DELETE FROM cart WHERE user_id = ?",
            (user_id,)
        )

    # --- Order Processing --- (Synchronous)
    def create_order(self, user_id: int, total_price: float, cart_items: List[Dict[str, Any]], user_details: Dict[str, Any]) -> Optional[int]:
        """Creates an order, order items, updates stock, and clears cart within a transaction."""
        if not self.conn:
            logger.error("Cannot create order: Database not connected.")
            return None
            
        cursor = None
        try:
            cursor = self.conn.cursor()
            # Start transaction
            cursor.execute("BEGIN TRANSACTION")

            # 1. Check stock for all items
            for item in cart_items:
                cursor.execute("SELECT stock FROM products WHERE id = ?", (item["product_id"],))
                stock_row = cursor.fetchone()
                if not stock_row or stock_row["stock"] < item["quantity"]:
                    logger.warning(f"Order creation failed: Insufficient stock for product {item['product_id']}")
                    cursor.execute("ROLLBACK")
                    return None # Indicate failure due to stock

            # 2. Insert order
            cursor.execute(
                "INSERT INTO orders (user_id, total_price, status, user_details) VALUES (?, ?, ?, ?)",
                (user_id, total_price, "Processing", json.dumps(user_details))
            )
            order_id = cursor.lastrowid
            if not order_id:
                raise sqlite3.Error("Failed to get last row ID for order.")

            # 3. Insert order items and update stock
            for item in cart_items:
                # Insert item
                cursor.execute(
                    "INSERT INTO order_items (order_id, product_id, quantity, price) VALUES (?, ?, ?, ?)",
                    (order_id, item["product_id"], item["quantity"], item["price"]) # Use price from cart item
                )
                # Update stock
                cursor.execute(
                    "UPDATE products SET stock = stock - ? WHERE id = ?",
                    (item["quantity"], item["product_id"])
                )

            # 4. Clear cart
            cursor.execute("DELETE FROM cart WHERE user_id = ?", (user_id,))

            # Commit transaction
            self.conn.commit()
            logger.info(f"Order {order_id} created successfully for user {user_id}.")
            return order_id

        except sqlite3.Error as e:
            logger.error(f"Error creating order for user {user_id}: {e}", exc_info=True)
            if self.conn: self.conn.rollback()
            return None
        finally:
            if cursor:
                cursor.close()

    def update_order_status(self, order_id: int, status: str) -> bool:
        """Updates the status of an order."""
        # Add validation for allowed statuses if needed
        return self.execute_query(
            "UPDATE orders SET status = ? WHERE id = ?",
            (status, order_id)
        )

    def cancel_order(self, order_id: int) -> bool:
        """Cancels an order and potentially restores stock (complex logic)."""
        # Simple status update for now. Restoring stock requires transaction.
        logger.warning("Cancelling order - stock restoration not implemented yet.")
        return self.update_order_status(order_id, "Cancelled")

    def get_user_orders(self, user_id: int) -> List[Dict[str, Any]]:
        orders = self.fetch_all(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        )
        for order in orders:
            # Parse user_details JSON
            try: order["user_details_parsed"] = json.loads(order["user_details"])
            except: order["user_details_parsed"] = {"error": "Invalid JSON"}
            
            # Get items for this order
            items = self.fetch_all(
                """SELECT oi.*, p.name, p.platform
                   FROM order_items oi JOIN products p ON oi.product_id = p.id
                   WHERE oi.order_id = ?""",
                (order["id"],)
            )
            order["items"] = items
        return orders

    # --- Favorites --- (Synchronous)
    def add_favorite(self, user_id: int, product_id: int) -> bool:
        return self.execute_query(
            "INSERT OR IGNORE INTO favorites (user_id, product_id) VALUES (?, ?)",
            (user_id, product_id)
        )

    def remove_favorite(self, user_id: int, product_id: int) -> bool:
        return self.execute_query(
            "DELETE FROM favorites WHERE user_id = ? AND product_id = ?",
            (user_id, product_id)
        )

    def get_favorites(self, user_id: int) -> List[Dict[str, Any]]:
        return self.fetch_all(
            """SELECT f.product_id, p.name, p.platform, p.price, p.image_url
               FROM favorites f JOIN products p ON f.product_id = p.id
               WHERE f.user_id = ?""",
            (user_id,)
        )

# Example usage (for testing)
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Ensure instance folder exists for testing
    if not os.path.exists("instance"):
        os.makedirs("instance")
    db = Database(db_path="instance/test_user_data.db")
    db.initialize()
    print(f"User DB initialized at {db.db_path}")
    # Add a test user
    db.connect()
    db.add_user(123, "testuser", "Test", "User")
    user = db.get_user(123)
    print("Test User:", user)
    # Example product data
    products = [
        {"id": 1, "name": "Test Game 1", "platform": ["PC"], "price": 59.99, "stock": 10, "description": "Desc 1", "image_url": "images/game1.jpg"},
        {"id": 2, "name": "Test Game 2", "platform": ["PS5"], "price": 69.99, "stock": 5, "description": "Desc 2", "image_url": "images/game2.jpg"}
    ]
    # Assume images folder exists relative to this script for testing
    script_dir = os.path.dirname(__file__)
    db.populate_products(products, script_dir)
    print("Products Populated.")
    all_prods = db.get_all_products()
    print("All Products:", all_prods)
    db.disconnect()

