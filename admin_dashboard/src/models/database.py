import sqlite3
import os
import json
from datetime import datetime

class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self.connection = None
        self.cursor = None
        
    def connect(self):
        """Connect to the SQLite database."""
        try:
            self.connection = sqlite3.connect(self.db_path)
            self.connection.row_factory = sqlite3.Row
            self.cursor = self.connection.cursor()
            return True
        except sqlite3.Error as e:
            print(f"Database connection error: {e}")
            return False
            
    def disconnect(self):
        """Close the database connection."""
        if self.connection:
            self.connection.close()
            
    def execute_query(self, query, params=None):
        """Execute a query with optional parameters."""
        try:
            if params:
                self.cursor.execute(query, params)
            else:
                self.cursor.execute(query)
            self.connection.commit()
            return True
        except sqlite3.Error as e:
            print(f"Query execution error: {e}")
            return False
            
    def fetch_all(self, query, params=None):
        """Execute a query and fetch all results."""
        try:
            if params:
                self.cursor.execute(query, params)
            else:
                self.cursor.execute(query)
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"Fetch error: {e}")
            return []
            
    def fetch_one(self, query, params=None):
        """Execute a query and fetch one result."""
        try:
            if params:
                self.cursor.execute(query, params)
            else:
                self.cursor.execute(query)
            return self.cursor.fetchone()
        except sqlite3.Error as e:
            print(f"Fetch error: {e}")
            return None
            
    def create_tables(self):
        """Create new tables for admin dashboard if they don't exist."""
        try:
            # Admin users table
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS admin_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    email TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP
                )
            ''')
            
            # Admin logs table
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS admin_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER,
                    action TEXT NOT NULL,
                    details TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(admin_id) REFERENCES admin_users(id)
                )
            ''')
            
            # Discounts table
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS discounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER,
                    discount_percentage REAL NOT NULL,
                    start_date TIMESTAMP,
                    end_date TIMESTAMP,
                    created_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(product_id) REFERENCES products(id),
                    FOREIGN KEY(created_by) REFERENCES admin_users(id)
                )
            ''')
            
            # Categories/Platforms table
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Stock alerts table
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS stock_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER,
                    threshold INTEGER NOT NULL,
                    created_by INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(product_id) REFERENCES products(id),
                    FOREIGN KEY(created_by) REFERENCES admin_users(id)
                )
            ''')
            
            # Broadcast messages table
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS broadcast_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message TEXT NOT NULL,
                    sent_by INTEGER,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    target_group TEXT,
                    FOREIGN KEY(sent_by) REFERENCES admin_users(id)
                )
            ''')
            
            self.connection.commit()
            return True
        except sqlite3.Error as e:
            print(f"Table creation error: {e}")
            return False
            
    def initialize_admin(self, username, password_hash):
        """Initialize the admin user if not exists."""
        try:
            admin = self.fetch_one("SELECT * FROM admin_users WHERE username = ?", (username,))
            if not admin:
                self.execute_query(
                    "INSERT INTO admin_users (username, password_hash) VALUES (?, ?)",
                    (username, password_hash)
                )
                return True
            return False
        except sqlite3.Error as e:
            print(f"Admin initialization error: {e}")
            return False
            
    def log_admin_action(self, admin_id, action, details=None):
        """Log an admin action."""
        try:
            self.execute_query(
                "INSERT INTO admin_logs (admin_id, action, details) VALUES (?, ?, ?)",
                (admin_id, action, details)
            )
            return True
        except sqlite3.Error as e:
            print(f"Admin log error: {e}")
            return False
