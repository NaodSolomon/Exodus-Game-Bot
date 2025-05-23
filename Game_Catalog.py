import logging
from Database_helper import Database
from typing import List, Dict, Optional

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

CATEGORIES = ["PC", "PlayStation 4", "PlayStation 5", "Xbox One", "Xbox Series X", "Nintendo"]

db = Database()

def get_products_by_platform(platform: str) -> List[Dict]:
    """Retrieve products by platform."""
    try:
        with db._get_connection() as conn:
            cursor = conn.cursor()
            # Use a more precise LIKE pattern to match platform names
            cursor.execute('''
                SELECT product_id, name, price, platform, description, image_url, stock 
                FROM products 
                WHERE (',' || platform || ',') LIKE ? AND stock > 0
                ORDER BY name
            ''', (f'%,{platform},%',))
            
            products = []
            for row in cursor.fetchall():
                products.append({
                    'id': row['product_id'],
                    'name': row['name'],
                    'price': f"${row['price']:.2f}",
                    'platform': row['platform'].split(',') if row['platform'] else [],
                    'description': row['description'],
                    'image_url': row['image_url'],
                    'stock': row['stock']
                })
            
            logger.info(f"Found {len(products)} products for platform {platform}")
            return products
            
    except Exception as e:
        logger.error(f"Error fetching products for platform {platform}: {e}")
        return []
def get_product_by_id(product_id: int) -> Optional[Dict]:
    """Retrieve a product by ID."""
    try:
        product = db.get_product(product_id)
        if product:
            logger.info(f"Fetched product {product_id}: price={product['price']}, type={type(product['price'])}")
        return product
    except Exception as e:
        logger.error(f"Error fetching product {product_id}: {e}")
        return None

def search_products(keyword: str) -> List[Dict]:
    """Search products by keyword."""
    keyword = keyword.lower().strip()
    products = []
    try:
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT product_id FROM products WHERE lower(name) LIKE ?', (f'%{keyword}%',))
            for row in cursor.fetchall():
                product = db.get_product(row['product_id'])
                if product:
                    logger.info(f"Search hit for product {product['id']}: price={product['price']}, type={type(product['price'])}")
                    products.append(product)
        return products
    except Exception as e:
        logger.error(f"Error searching products with keyword {keyword}: {e}")
        return []