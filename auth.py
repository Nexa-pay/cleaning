import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
import pyotp
import asyncio

from database import db
from models import UserRole, AccountStatus
import config
from utils import generate_qr_code, generate_2fa_secret, encrypt_data, decrypt_data

logger = logging.getLogger(__name__)

# Conversation states
(PHONE_NUMBER, OTP_CODE, PASSWORD, TWO_FA_SETUP, ACCOUNT_NAME) = range(5, 10)

class AuthHandler:
    def __init__(self):
        self.temp_data = {}
    
    async def start_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start the login process for adding a Telegram account"""
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
        
        # Ask for phone number
        await update.message.reply_text(
            "📱 **Add Telegram Account**\n\n"
            "Please enter your phone number in international format:\n"
            "Example: `+1234567890`\n\n"
            "⚠️ Your credentials will be **encrypted** and stored securely.\n"
            "We never share your information with anyone.",
            parse_mode='Markdown'
        )
        
        return PHONE_NUMBER
    
    async def handle_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle phone number input"""
        phone = update.message.text.strip()
        user_id = update.effective_user.id
        
        # Validate phone number
        if not phone.startswith('+') or not phone[1:].replace(' ', '').isdigit():
            await update.message.reply_text(
                "❌ **Invalid Phone Number**\n\n"
                "Please use international format: `+1234567890`\n"
                "Example: `+919876543210` for India",
                parse_mode='Markdown'
            )
            return PHONE_NUMBER
        
        # Store in context
        context.user_data['login_phone'] = phone
        
        # In a real implementation, you would use Telethon to send OTP
        # For now, we'll simulate it
        await update.message.reply_text(
            "📱 **Verification Code Sent**\n\n"
            "An OTP has been sent to your Telegram app.\n"
            "Please enter the 5-digit code you received:\n\n"
            "If you don't receive the code within 30 seconds, click /cancel and try again.",
            parse_mode='Markdown'
        )
        
        return OTP_CODE
    
    async def handle_otp(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle OTP input"""
        otp = update.message.text.strip()
        
        if not otp.isdigit() or len(otp) != 5:
            await update.message.reply_text(
                "❌ **Invalid OTP**\n\n"
                "Please enter the 5-digit code you received."
            )
            return OTP_CODE
        
        context.user_data['login_otp'] = otp
        
        # Ask about 2FA
        keyboard = [
            [InlineKeyboardButton("✅ No 2FA", callback_data="2fa_no")],
            [InlineKeyboardButton("🔐 I have 2FA", callback_data="2fa_yes")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🔐 **Two-Factor Authentication**\n\n"
            "Does your Telegram account have 2FA (Two-Factor Authentication) enabled?",
            reply_markup=reply_markup
        )
        
        return PASSWORD
    
    async def handle_2fa_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle 2FA choice"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "2fa_no":
            # No 2FA, proceed to account name
            await query.edit_message_text(
                "📝 **Account Name**\n\n"
                "Please enter a name for this account (e.g., 'Personal', 'Work', 'Backup'):"
            )
            return ACCOUNT_NAME
        else:
            await query.edit_message_text(
                "🔐 **2FA Password**\n\n"
                "Please enter your 2FA password:"
            )
            return TWO_FA_SETUP
    
    async def handle_2fa_password(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle 2FA password"""
        password = update.message.text.strip()
        context.user_data['login_2fa'] = password
        
        await update.message.reply_text(
            "📝 **Account Name**\n\n"
            "Please enter a name for this account (e.g., 'Personal', 'Work', 'Backup'):"
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
    
    async def complete_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Complete the login process and save account"""
        user_id = update.effective_user.id
        phone = context.user_data.get('login_phone')
        otp = context.user_data.get('login_otp')
        twofa = context.user_data.get('login_2fa')
        account_name = context.user_data.get('account_name', f"Account {phone[-4:]}")
        
        # Simulate successful login
        # In production, you would use Telethon to create a real session
        session_string = f"session_{phone}_{otp}_{datetime.now().timestamp()}"
        
        try:
            # Add account to database
            account = await db.add_telegram_account(
                user_id=user_id,
                phone_number=phone,
                session_string=session_string,
                account_name=account_name,
                twofa_password=twofa
            )
            
            # Clear temp data
            for key in ['login_phone', 'login_otp', 'login_2fa', 'account_name']:
                context.user_data.pop(key, None)
            
            # Success message with account details
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
            
        except Exception as e:
            logger.error(f"Login error: {e}")
            await update.message.reply_text(
                "❌ **Login Failed**\n\n"
                "Could not add account. Please try again.\n"
                "If the problem persists, contact support."
            )
        
        return ConversationHandler.END
    
    async def cancel_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel login process"""
        await update.message.reply_text(
            "❌ **Login Cancelled**\n\n"
            "Use /login to try again."
        )
        
        # Clear temp data
        for key in ['login_phone', 'login_otp', 'login_2fa', 'account_name']:
            context.user_data.pop(key, None)
            
        return ConversationHandler.END