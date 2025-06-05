import logging
import re

def setup_logging():
    logging.basicConfig(
        filename='/tmp/bot.log',
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

def format_price(price: float) -> str:
    """Format a price as a string with dollar sign and two decimal places."""
    try:
        return f"${price:.2f}"
    except (TypeError, ValueError):
        logging.error(f"Invalid price value for formatting: {price}", exc_info=True)
        return "$0.00"
    
def is_valid_ethiopian_phone(phone: str) -> bool:
    """Validate if the phone number matches Ethiopian format: +251(9|7)******** or 0(9|7)********."""
    pattern = r"^(?:\+251[97]\d{8}|0[97]\d{8})$"
    return bool(re.match(pattern, phone))