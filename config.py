import os
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot Configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    logger.error("CRITICAL: BOT_TOKEN environment variable is not set!")

# Admin IDs (full access - can report anything for free)
admin_ids_str = os.environ.get('ADMIN_IDS', '')
ADMIN_IDS = []
if admin_ids_str:
    try:
        ADMIN_IDS = [int(id.strip()) for id in admin_ids_str.split(',') if id.strip()]
    except ValueError as e:
        logger.error(f"Error parsing ADMIN_IDS: {e}")

# Owner IDs (can manage tokens, view all reports, manage accounts)
owner_ids_str = os.environ.get('OWNER_IDS', '')
OWNER_IDS = []
if owner_ids_str:
    try:
        OWNER_IDS = [int(id.strip()) for id in owner_ids_str.split(',') if id.strip()]
    except ValueError:
        logger.error(f"Invalid OWNER_IDS: {owner_ids_str}")

# Super Admin (can do everything including managing other admins)
SUPER_ADMIN_ID = int(os.environ.get('SUPER_ADMIN_ID', 0))

# Report channel ID
REPORT_CHANNEL_ID = os.environ.get('REPORT_CHANNEL_ID')
if REPORT_CHANNEL_ID:
    try:
        REPORT_CHANNEL_ID = int(REPORT_CHANNEL_ID)
    except ValueError:
        logger.error(f"Invalid REPORT_CHANNEL_ID: {REPORT_CHANNEL_ID}")
        REPORT_CHANNEL_ID = None

# MongoDB Configuration
MONGODB_URI = os.environ.get('MONGODB_URI')
DATABASE_NAME = os.environ.get('DATABASE_NAME', 'telegram_report_bot')

# Token System Settings
TOKEN_PRICE_STARS = int(os.environ.get('TOKEN_PRICE_STARS', 50))
TOKEN_PRICE_INR = int(os.environ.get('TOKEN_PRICE_INR', 50))
REPORT_COST_IN_TOKENS = int(os.environ.get('REPORT_COST_IN_TOKENS', 1))
FREE_REPORTS_FOR_NEW_USERS = int(os.environ.get('FREE_REPORTS_FOR_NEW_USERS', 0))

# UPI Payment Details
UPI_ID = os.environ.get('UPI_ID', 'your-upi-id@okhdfcbank')
PAYEE_NAME = os.environ.get('PAYEE_NAME', 'Your Name/Business')

# Encryption Key for sensitive data
ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY')
if not ENCRYPTION_KEY:
    logger.warning("ENCRYPTION_KEY not set. Generating temporary key.")
    import base64
    import os as os_random
    ENCRYPTION_KEY = base64.urlsafe_b64encode(os_random.urandom(32)).decode()

# Contact Information
CONTACT_INFO = {
    'admin_username': os.environ.get('ADMIN_USERNAME', 'admin'),
    'owner_username': os.environ.get('OWNER_USERNAME', 'owner'),
    'support_group': os.environ.get('SUPPORT_GROUP', 'https://t.me/support_group'),
    'email': os.environ.get('CONTACT_EMAIL', 'support@example.com'),
    'channel': os.environ.get('CHANNEL_LINK', 'https://t.me/your_channel')
}

# Account Management Settings
MAX_ACCOUNTS_PER_USER = int(os.environ.get('MAX_ACCOUNTS_PER_USER', 5))
SESSION_TIMEOUT = int(os.environ.get('SESSION_TIMEOUT', 3600))  # 1 hour

# Bot Settings
MAX_REPORT_LENGTH = 1000
REPORT_COOLDOWN = 30
REPORTS_PER_PAGE = 10

# Log configuration status
logger.info("=" * 50)
logger.info("Configuration loaded:")
logger.info(f"BOT_TOKEN set: {'Yes' if BOT_TOKEN else 'No'}")
logger.info(f"ADMIN_IDS: {ADMIN_IDS}")
logger.info(f"OWNER_IDS: {OWNER_IDS}")
logger.info(f"SUPER_ADMIN: {SUPER_ADMIN_ID}")
logger.info(f"MONGODB_URI set: {'Yes' if MONGODB_URI else 'No'}")
logger.info(f"Token Price: {TOKEN_PRICE_STARS} Stars / ₹{TOKEN_PRICE_INR}")
logger.info("=" * 50) 