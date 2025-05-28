from typing import List, Dict
from database import Database

async def get_products_by_platform(platform: str, db: Database) -> List[Dict]:
    """Retrieve products for a specific platform."""
    try:
        products = await db.get_all_products()
        return [product for product in products if platform in product['platform']]
    except Exception as e:
        raise Exception(f"Error retrieving products for platform {platform}: {e}")

async def get_product_by_id(product_id: int, db: Database) -> Dict:
    """Retrieve a product by its ID."""
    try:
        return await db.get_product(product_id) or {}
    except Exception as e:
        raise Exception(f"Error retrieving product {product_id}: {e}")

async def search_products(query: str, db: Database) -> List[Dict]:
    """Search products by name or description."""
    try:
        query = query.lower()
        products = await db.get_all_products()
        return [
            product for product in products
            if query in product['name'].lower() or query in product['description'].lower()
        ]
    except Exception as e:
        raise Exception(f"Error searching products with query {query}: {e}")