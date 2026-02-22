import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from datetime import datetime
import uuid

from database import db
from models import UserRole, AccountStatus
import config
from utils import encrypt_data

logger = logging.getLogger(__name__)

# Conversation states
(PHONE_NUMBER, ACCOUNT_NAME) = range(5, 7)  # Simplified to just 2 states

class AuthHandler:
    def __init__(self):
        self.temp_data = {}
    
    async def start_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start the login process for adding a Telegram account - SIMPLIFIED VERSION"""
        user_id = update.effective_user.id
        
        # Check if user exists
        user = await db.get_user(user_id)
        if not user:
            user = await db.create_user(
                user_id=user_id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name,
                last_name=update.effective_user.last_name
            )
        
        # Check account limit
        accounts = await db.get_user_accounts(user_id)
        if len(accounts) >= config.MAX_ACCOUNTS_PER_USER and user.role not in [UserRole.ADMIN, UserRole.OWNER, UserRole.SUPER_ADMIN]:
            await update.message.reply_text(
                f"❌ **Account Limit Reached**\n\n"
                f"You've reached the maximum limit of {config.MAX_ACCOUNTS_PER_USER} accounts.\n"
                f"Please remove an existing account or contact support to increase your limit.\n\n"
                f"Use /accounts to manage your accounts.",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        # Ask for phone number (simplified - just for display)
        await update.message.reply_text(
            "📱 **Add Telegram Account**\n\n"
            "Please enter your phone number (this will be stored for reference):\n"
            "Example: `+1234567890`\n\n"
            "⚠️ **Note:** This is a simplified version for testing.\n"
            "Your account will be created without actual Telegram login.",
            parse_mode='Markdown'
        )
        
        return PHONE_NUMBER
    
    async def handle_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle phone number input - SIMPLIFIED"""
        phone = update.message.text.strip()
        user_id = update.effective_user.id
        
        # Simple validation
        if not phone.startswith('+'):
            phone = f"+{phone}"
        
        # Store in context
        context.user_data['login_phone'] = phone
        
        # Ask for account name
        await update.message.reply_text(
            "📝 **Account Name**\n\n"
            "Please enter a name for this account (e.g., 'Personal', 'Work', 'Backup'):\n\n"
            "Or send /skip to use default name.",
            parse_mode='Markdown'
        )
        
        return ACCOUNT_NAME
    
    async def handle_account_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle account name input and complete login"""
        account_name = update.message.text.strip()
        
        if len(account_name) > 50:
            await update.message.reply_text(
                "❌ Name too long. Please use 50 characters or less."
            )
            return ACCOUNT_NAME
        
        context.user_data['account_name'] = account_name
        
        # Complete the login process
        return await self.complete_login(update, context)
    
    async def skip_account_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Skip account name and use default"""
        context.user_data['account_name'] = None
        return await self.complete_login(update, context)
    
    async def complete_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Complete the login process and save account - SIMPLIFIED"""
        user_id = update.effective_user.id
        phone = context.user_data.get('login_phone', '+1234567890')
        account_name = context.user_data.get('account_name')
        
        # Generate default name if not provided
        if not account_name:
            account_name = f"Account {phone[-4:]}"
        
        try:
            # Create a unique session ID
            session_id = str(uuid.uuid4())
            
            # Encrypt session data (simplified)
            encrypted_session = encrypt_data(f"session_{user_id}_{datetime.now().timestamp()}")
            
            # Add account to database
            account = await db.add_telegram_account(
                user_id=user_id,
                phone_number=phone,
                session_string=encrypted_session,
                account_name=account_name,
                twofa_password=None
            )
            
            # Clear temp data
            context.user_data.pop('login_phone', None)
            context.user_data.pop('account_name', None)
            
            # Success message
            success_text = (
                f"✅ **Account Added Successfully!**\n\n"
                f"**Account ID:** `{account.account_id[:8]}...`\n"
                f"**Name:** {account.account_name}\n"
                f"**Phone:** {account.phone_number}\n"
                f"**Status:** Active\n"
                f"**Primary:** {'Yes ⭐' if account.is_primary else 'No'}\n\n"
                f"📱 **What's Next?**\n"
                f"• Use /accounts to manage your accounts\n"
                f"• Use /report to start reporting\n"
                f"• Use /buy to purchase tokens\n\n"
                f"Your account is now ready to use!"
            )
            
            await update.message.reply_text(
                success_text,
                parse_mode='Markdown'
            )
            
            logger.info(f"✅ Account added for user {user_id}: {account_name}")
            
        except Exception as e:
            logger.error(f"Login error: {e}")
            await update.message.reply_text(
                "❌ **Login Failed**\n\n"
                f"Error: {str(e)[:100]}\n\n"
                "Please try again or contact support."
            )
        
        return ConversationHandler.END
    
    async def cancel_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel login process"""
        await update.message.reply_text(
            "❌ **Login Cancelled**\n\n"
            "Use /login to try again."
        )
        
        # Clear temp data
        context.user_data.pop('login_phone', None)
        context.user_data.pop('account_name', None)
            
        return ConversationHandler.END