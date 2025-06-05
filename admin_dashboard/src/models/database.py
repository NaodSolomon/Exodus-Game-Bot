# Refactored to use synchronous sqlite3
import sqlite3
import logging
import os

logger = logging.getLogger(__name__)

class Database:
    """Synchronous wrapper for SQLite database operations."""
    def __init__(self, db_path: str = None):
        # Determine DB path, default to ./instance/admin.db for better practice
        self.db_path = db_path or os.environ.get("ADMIN_DB_PATH", "instance/admin.db")
        # Ensure the instance directory exists
        instance_dir = os.path.dirname(self.db_path)
        if instance_dir and not os.path.exists(instance_dir):
            os.makedirs(instance_dir)
            logger.info(f"Created instance directory: {instance_dir}")
        self.conn = None
        logger.info(f"Database path set to: {self.db_path}")

    def connect(self):
        """Establishes a database connection."""
        if self.conn is None:
            try:
                # Removed check_same_thread=False, as it's not needed for sync usage
                # and Flask manages requests in separate threads/processes.
                self.conn = sqlite3.connect(self.db_path)
                self.conn.row_factory = sqlite3.Row
                logger.debug("Database connected")
            except sqlite3.Error as e:
                logger.error(f"Database connection error: {e}", exc_info=True)
                raise

    def disconnect(self):
        """Closes the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None
            logger.debug("Database disconnected")

    def execute_query(self, query: str, params: tuple = ()) -> bool:
        """Executes a query (INSERT, UPDATE, DELETE) and returns success status."""
        if not self.conn:
            logger.error("Cannot execute query: Database not connected.")
            return False
        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            self.conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Query execution error: {e}", exc_info=True)
            self.conn.rollback() # Rollback on error
            return False
        finally:
            if cursor:
                cursor.close()

    def fetch_one(self, query: str, params: tuple = ()) -> dict | None:
        """Fetches a single row from the database."""
        if not self.conn:
            logger.error("Cannot fetch one: Database not connected.")
            return None
        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            row = cursor.fetchone()
            return dict(row) if row else None
        except sqlite3.Error as e:
            logger.error(f"Fetch one error: {e}", exc_info=True)
            return None
        finally:
            if cursor:
                cursor.close()

    def fetch_all(self, query: str, params: tuple = ()) -> list:
        """Fetches all rows matching the query."""
        if not self.conn:
            logger.error("Cannot fetch all: Database not connected.")
            return []
        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as e:
            logger.error(f"Fetch all error: {e}", exc_info=True)
            return []
        finally:
            if cursor:
                cursor.close()

    def create_tables(self):
        """Creates necessary tables if they don't exist."""
        # Note: References to products(id) assume the main DB has this table.
        # This class should ideally only manage admin-specific tables.
        queries = [
            """CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                email TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT NOT NULL,
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(admin_id) REFERENCES admin_users(id)
            )""",
            """CREATE TABLE IF NOT EXISTS discounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL, -- Assuming product_id comes from the main DB
                discount_percentage REAL NOT NULL,
                start_date TIMESTAMP,
                end_date TIMESTAMP,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                -- FOREIGN KEY(product_id) REFERENCES products(id), -- Cannot enforce FK across DBs
                FOREIGN KEY(created_by) REFERENCES admin_users(id)
            )""",
            """CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS stock_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL, -- Assuming product_id comes from the main DB
                threshold INTEGER NOT NULL,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                -- FOREIGN KEY(product_id) REFERENCES products(id), -- Cannot enforce FK across DBs
                FOREIGN KEY(created_by) REFERENCES admin_users(id)
            )""",
            """CREATE TABLE IF NOT EXISTS broadcast_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                sent_by INTEGER,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                target_group TEXT,
                FOREIGN KEY(sent_by) REFERENCES admin_users(id)
            )"""
        ]
        try:
            self.connect()
            for query in queries:
                self.execute_query(query)
            logger.info("Admin database tables checked/created successfully.")
        except Exception as e:
            logger.error(f"Admin table creation error: {e}", exc_info=True)
        finally:
            self.disconnect()

    def initialize_admin(self, username: str, password_hash: str):
        """Initializes the default admin user if not present."""
        try:
            self.connect()
            # Check if admin exists first
            existing_admin = self.fetch_one("SELECT id FROM admin_users WHERE username = ?", (username,))
            if not existing_admin:
                success = self.execute_query(
                    "INSERT INTO admin_users (username, password_hash) VALUES (?, ?)",
                    (username, password_hash)
                )
                if success:
                    logger.info(f"Default admin user '{username}' created.")
                else:
                    logger.error(f"Failed to create default admin user '{username}'.")
            else:
                logger.info(f"Admin user '{username}' already exists.")
        except Exception as e:
            logger.error(f"Admin initialization error: {e}", exc_info=True)
        finally:
            self.disconnect()

    def log_admin_action(self, admin_id: int, action: str, details: str = None):
        """Logs an action performed by an admin user."""
        try:
            self.connect()
            success = self.execute_query(
                "INSERT INTO admin_logs (admin_id, action, details) VALUES (?, ?, ?)",
                (admin_id, action, details)
            )
            if success:
                logger.debug(f"Logged admin action: {action}")
            else:
                logger.error(f"Failed to log admin action: {action}")
        except Exception as e:
            logger.error(f"Log admin action error: {e}", exc_info=True)
        finally:
            self.disconnect()

# Example usage (for testing, typically called elsewhere)
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    admin_db = Database()
    admin_db.create_tables()
    # Example: Initialize admin (use a secure hash)
    import bcrypt
    password = 'adminpassword'
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    admin_db.initialize_admin('admin', hashed)
    # Example: Log action
    admin_user = admin_db.fetch_one("SELECT id FROM admin_users WHERE username = ?", ('admin',))
    if admin_user:
        admin_db.log_admin_action(admin_user['id'], 'test_action', 'Testing logging')
    print("Admin DB operations tested.")

