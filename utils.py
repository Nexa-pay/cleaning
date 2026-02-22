import logging
import base64
import os
import re
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
import qrcode
from io import BytesIO
import pyotp
from datetime import datetime, timedelta

import config

logger = logging.getLogger(__name__)

# Initialize encryption
try:
    cipher_suite = Fernet(config.ENCRYPTION_KEY.encode() if isinstance(config.ENCRYPTION_KEY, str) else config.ENCRYPTION_KEY)
except Exception as e:
    logger.error(f"Failed to initialize encryption: {e}")
    # Generate a fallback key (not recommended for production)
    fallback_key = base64.urlsafe_b64encode(os.urandom(32))
    cipher_suite = Fernet(fallback_key)
    logger.warning("Using fallback encryption key. Set ENCRYPTION_KEY in environment!")

def encrypt_data(data: str) -> str:
    """Encrypt sensitive data"""
    if not data:
        return None
    try:
        encrypted = cipher_suite.encrypt(data.encode())
        return encrypted.decode()
    except Exception as e:
        logger.error(f"Encryption error: {e}")
        return None

def decrypt_data(encrypted_data: str) -> str:
    """Decrypt sensitive data"""
    if not encrypted_data:
        return None
    try:
        decrypted = cipher_suite.decrypt(encrypted_data.encode())
        return decrypted.decode()
    except Exception as e:
        logger.error(f"Decryption error: {e}")
        return None

def generate_qr_code(data: str) -> BytesIO:
    """Generate QR code for UPI payments"""
    qr = qrcode.QRCode(
        version=1,
        box_size=10,
        border=5,
        error_correction=qrcode.constants.ERROR_CORRECT_L
    )
    qr.add_data(data)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    bio = BytesIO()
    img.save(bio, 'PNG')
    bio.seek(0)
    return bio

def generate_2fa_secret() -> str:
    """Generate 2FA secret"""
    return pyotp.random_base32()

def get_2fa_uri(secret: str, email: str) -> str:
    """Get 2FA URI for QR code"""
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=email,
        issuer_name="Telegram Report Bot"
    )

def verify_2fa(secret: str, token: str) -> bool:
    """Verify 2FA token"""
    totp = pyotp.TOTP(secret)
    return totp.verify(token)

def validate_target(target: str) -> bool:
    """Validate report target format"""
    patterns = [
        r'^@\w{5,32}$',  # Username
        r'^https?://t\.me/[\w\+]+/?$',  # Telegram link
        r'^https?://t\.me/\+[\w]+$',  # Private group invite
        r'^\d+$',  # User ID
    ]
    return any(re.match(pattern, target) for pattern in patterns)

def format_number(num: int) -> str:
    """Format large numbers"""
    if num < 1000:
        return str(num)
    elif num < 1000000:
        return f"{num/1000:.1f}K"
    else:
        return f"{num/1000000:.1f}M"

def escape_markdown(text: str) -> str:
    """Escape Markdown special characters"""
    if not text:
        return ""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

def format_datetime(dt: datetime) -> str:
    """Format datetime for display"""
    if not dt:
        return "Never"
    return dt.strftime("%Y-%m-%d %H:%M")

def time_ago(dt: datetime) -> str:
    """Get time ago string"""
    if not dt:
        return "Never"
    
    now = datetime.now()
    diff = now - dt
    
    if diff.days > 365:
        years = diff.days // 365
        return f"{years} year{'s' if years > 1 else ''} ago"
    elif diff.days > 30:
        months = diff.days // 30
        return f"{months} month{'s' if months > 1 else ''} ago"
    elif diff.days > 0:
        return f"{diff.days} day{'s' if diff.days > 1 else ''} ago"
    elif diff.seconds > 3600:
        hours = diff.seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    elif diff.seconds > 60:
        minutes = diff.seconds // 60
        return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
    else:
        return "Just now"

def generate_transaction_id() -> str:
    """Generate unique transaction ID"""
    import uuid
    return str(uuid.uuid4()).replace('-', '')[:16].upper()

def generate_report_id() -> str:
    """Generate unique report ID"""
    import uuid
    return str(uuid.uuid4()).replace('-', '')[:12].upper()

def truncate_text(text: str, max_length: int = 100) -> str:
    """Truncate text to max length"""
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."

def validate_email(email: str) -> bool:
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_phone(phone: str) -> bool:
    """Validate phone number format"""
    pattern = r'^\+\d{10,15}$'
    return re.match(pattern, phone) is not None

def parse_user_input(text: str) -> dict:
    """Parse user input for targets"""
    text = text.strip()
    
    # Check if it's a username
    if text.startswith('@'):
        return {'type': 'username', 'value': text}
    
    # Check if it's a link
    if text.startswith('http'):
        if 't.me/+' in text:
            return {'type': 'private_group', 'value': text}
        elif 't.me/' in text:
            return {'type': 'public_link', 'value': text}
    
    # Check if it's a user ID
    if text.isdigit():
        return {'type': 'user_id', 'value': int(text)}
    
    return {'type': 'unknown', 'value': text}