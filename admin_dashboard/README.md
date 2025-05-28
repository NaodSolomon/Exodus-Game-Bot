# Exodus Game Store Admin Dashboard - README

## Overview
This admin dashboard provides a comprehensive web interface for managing the Exodus Game Store Telegram bot. It enables administrators to manage games, track orders, view analytics, manage clients, and perform various administrative tasks through an intuitive and professional user interface.

## Features
- **Game Management**: Add, edit, delete, and restock games
- **Category Management**: Manage platform categories
- **Order Management**: View and update order status
- **Client Management**: View client information and order history
- **Analytics**: Track sales, revenue, and platform distribution
- **Stock Management**: Monitor inventory and set stock alerts
- **Discount Management**: Create and manage special offers
- **Broadcast Messages**: Send announcements to users via Telegram
- **Admin Logs**: Track all administrative actions
- **Data Export**: Export orders, clients, and product data

## Technology Stack
- **Backend**: Python with Flask
- **Database**: SQLite (data.db for game store data, admin.db for admin-specific data)
- **Frontend**: HTML, CSS, JavaScript with Tailwind CSS
- **Charts**: Chart.js for analytics visualization

## Setup Instructions

### Prerequisites
- Python 3.8 or higher
- pip (Python package installer)

### Installation
1. Clone the repository or extract the provided files
2. Navigate to the project directory
```
cd admin_dashboard
```

3. Create and activate a virtual environment
```
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

4. Install required packages
```
pip install -r requirements.txt
```

5. Run the setup script to initialize the admin database and copy static assets
```
chmod +x setup.sh
./setup.sh
```

6. Start the application
```
python app.py
```

7. Access the dashboard at http://localhost:8000

### Default Admin Credentials
- Username: admin
- Password: securepassword123

## Database Structure
The dashboard uses two SQLite databases:
- **data.db**: Contains game store data (games, orders, users)
- **admin.db**: Contains admin-specific data (admin users, logs, discounts, stock alerts)

### Main Tables in data.db
- **users**: Store customers
- **products**: Game catalog
- **orders**: Customer orders
- **order_items**: Items in each order
- **cart**: User shopping carts

### Main Tables in admin.db
- **admin_users**: Dashboard administrators
- **admin_logs**: Admin activity logs
- **discounts**: Game discounts
- **categories**: Platform categories
- **stock_alerts**: Low stock thresholds
- **broadcast_messages**: Messages sent to users

## Usage Guide

### Game Management
- View all games in the catalog
- Add new games with details (name, platform, price, stock, description, image URL)
- Edit existing game information
- Delete games (if not in any orders)
- Restock games with new inventory

### Order Management
- View all orders with customer information
- See detailed order information including items
- Update order status (pending, processing, shipped, delivered, cancelled)

### Analytics
- View key metrics (total games sold, monthly revenue, top platform, top game)
- See sales trends over time
- View revenue by platform and game
- Track top-selling games

### Client Management
- View all clients and their order history
- See detailed client information
- Track client spending and order frequency

### Stock Management
- Monitor inventory levels
- Set stock alerts for low inventory
- Quickly identify products that need restocking

### Discount Management
- Create discounts for specific games
- Set discount percentage and validity period
- Remove discounts when no longer needed

### Broadcast Messages
- Send announcements to all users or specific groups
- Track message history

## Security Features
- Password hashing with bcrypt
- Session-based authentication
- Admin action logging for accountability
- Input sanitization to prevent SQL injection

## Integration with Telegram Bot
The dashboard integrates with the existing Exodus Game Store Telegram bot, allowing:
- Access to the same database for consistent data
- Sending broadcast messages to users
- Viewing and managing orders placed through the bot

## Troubleshooting
- If you encounter database connection issues, ensure the database paths in app.py are correct
- For authentication issues, check that the admin user exists in the admin.db database
- If static assets are not loading, run the setup script again to copy them
