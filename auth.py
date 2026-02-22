import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from datetime import datetime
import uuid
import asyncio

from database import db
from models import UserRole, AccountStatus
import config
from utils import encrypt_data
from telegram_client import tg_client_manager

logger = logging.getLogger(__name__)

# Conversation states
(PHONE_NUMBER, OTP_CODE, TWO_FA_PASSWORD, ACCOUNT_NAME) = range(10, 14)

class AuthHandler:
    def __init__(self):
        self.temp_data = {}
        self.login_sessions = {}  # Store temporary login sessions
    
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
                f"Please remove an existing account or contact support.\n\n"
                f"Use /accounts to manage your accounts.",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        # Ask for phone number
        await update.message.reply_text(
            "📱 **Add Telegram Account**\n\n"
            "Please enter your phone number in international format:\n"
            "Example: `+1234567890`\n\n"
            "⚠️ This will send a real OTP to your Telegram app.",
            parse_mode='Markdown'
        )
        
        return PHONE_NUMBER
    
    async def handle_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle phone number input and send OTP"""
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
        
        # Send OTP via Telethon
        status_msg = await update.message.reply_text("📤 Sending OTP...")
        
        try:
            result = await tg_client_manager.start_login(phone)
            
            if result['success']:
                # Store client for this user
                self.login_sessions[user_id] = {
                    'phone': phone,
                    'client': result['client']
                }
                
                await status_msg.edit_text(
                    "📱 **OTP Sent!**\n\n"
                    "Please enter the 5-digit code you received in Telegram.\n\n"
                    "If you don't receive it within 30 seconds, try again.",
                    parse_mode='Markdown'
                )
                return OTP_CODE
            else:
                await status_msg.edit_text(
                    f"❌ **Login Failed**\n\n"
                    f"Error: {result.get('error', 'Unknown error')}",
                    parse_mode='Markdown'
                )
                return ConversationHandler.END
                
        except Exception as e:
            logger.error(f"OTP send error: {e}")
            await status_msg.edit_text(
                "❌ Failed to send OTP. Please try again later.",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
    
    async def handle_otp(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle OTP input"""
        otp = update.message.text.strip()
        user_id = update.effective_user.id
        
        if not otp.isdigit() or (len(otp) != 5 and len(otp) != 6):
            await update.message.reply_text(
                "❌ **Invalid OTP**\n\n"
                "Please enter the 5 or 6-digit code you received."
            )
            return OTP_CODE
        
        # Get stored session
        session = self.login_sessions.get(user_id)
        if not session:
            await update.message.reply_text(
                "❌ Session expired. Please start over with /login"
            )
            return ConversationHandler.END
        
        status_msg = await update.message.reply_text("🔄 Verifying OTP...")
        
        try:
            result = await tg_client_manager.verify_otp(
                session['client'],
                session['phone'],
                otp
            )
            
            if result['success']:
                # Store session string for later use
                context.user_data['session_string'] = result['session_string']
                
                await status_msg.edit_text(
                    "✅ **Login Successful!**\n\n"
                    "Now, please enter a name for this account (e.g., 'Personal', 'Work'):\n\n"
                    "Send /skip to use default name.",
                    parse_mode='Markdown'
                )
                return ACCOUNT_NAME
                
            elif result.get('step') == '2fa_required':
                # 2FA required
                await status_msg.edit_text(
                    "🔐 **Two-Factor Authentication Required**\n\n"
                    "Please enter your 2FA password:",
                    parse_mode='Markdown'
                )
                return TWO_FA_PASSWORD
            else:
                await status_msg.edit_text(
                    f"❌ **Verification Failed**\n\n"
                    f"Error: {result.get('error', 'Invalid OTP')}",
                    parse_mode='Markdown'
                )
                return ConversationHandler.END
                
        except Exception as e:
            logger.error(f"OTP verify error: {e}")
            await status_msg.edit_text(
                "❌ Verification failed. Please try again.",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
    
    async def handle_2fa_password(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle 2FA password"""
        password = update.message.text.strip()
        user_id = update.effective_user.id
        
        session = self.login_sessions.get(user_id)
        if not session:
            await update.message.reply_text(
                "❌ Session expired. Please start over with /login"
            )
            return ConversationHandler.END
        
        status_msg = await update.message.reply_text("🔄 Verifying 2FA...")
        
        try:
            result = await tg_client_manager.verify_otp(
                session['client'],
                session['phone'],
                None,
                password
            )
            
            if result['success']:
                context.user_data['session_string'] = result['session_string']
                
                await status_msg.edit_text(
                    "✅ **2FA Verified!**\n\n"
                    "Now, please enter a name for this account (e.g., 'Personal', 'Work'):\n\n"
                    "Send /skip to use default name.",
                    parse_mode='Markdown'
                )
                return ACCOUNT_NAME
            else:
                await status_msg.edit_text(
                    f"❌ **2FA Failed**\n\n"
                    f"Error: {result.get('error', 'Invalid password')}",
                    parse_mode='Markdown'
                )
                return TWO_FA_PASSWORD
                
        except Exception as e:
            logger.error(f"2FA error: {e}")
            await status_msg.edit_text(
                "❌ Verification failed. Please try again."
            )
            return TWO_FA_PASSWORD
    
    async def handle_account_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle account name input and complete login"""
        account_name = update.message.text.strip()
        user_id = update.effective_user.id
        
        if len(account_name) > 50:
            await update.message.reply_text(
                "❌ Name too long. Please use 50 characters or less."
            )
            return ACCOUNT_NAME
        
        context.user_data['account_name'] = account_name
        
        # Complete login
        return await self.complete_login(update, context)
    
    async def skip_account_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Skip account name and use default"""
        context.user_data['account_name'] = None
        return await self.complete_login(update, context)
    
    async def complete_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Complete the login process and save account"""
        user_id = update.effective_user.id
        session = self.login_sessions.get(user_id)
        
        if not session:
            await update.message.reply_text(
                "❌ Session expired. Please start over with /login"
            )
            return ConversationHandler.END
        
        phone = session['phone']
        session_string = context.user_data.get('session_string')
        account_name = context.user_data.get('account_name', f"Account {phone[-4:]}")
        
        try:
            # Encrypt session string
            encrypted_session = encrypt_data(session_string)
            
            # Add account to database
            account = await db.add_telegram_account(
                user_id=user_id,
                phone_number=phone,
                session_string=encrypted_session,
                account_name=account_name,
                twofa_password=None
            )
            
            # Clean up
            del self.login_sessions[user_id]
            context.user_data.pop('session_string', None)
            context.user_data.pop('account_name', None)
            
            # Get user info from Telegram to confirm
            try:
                user_info = await tg_client_manager.get_me(session_string)
                if user_info['success']:
                    extra_info = f"\n**Telegram ID:** `{user_info['user_id']}`\n**Username:** @{user_info['username'] or 'None'}"
                else:
                    extra_info = ""
            except:
                extra_info = ""
            
            success_text = (
                f"✅ **Account Added Successfully!**\n\n"
                f"**Account ID:** `{account.account_id[:8]}...`\n"
                f"**Name:** {account.account_name}\n"
                f"**Phone:** {account.phone_number}{extra_info}\n"
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
            
            logger.info(f"✅ Real Telegram account added for user {user_id}: {phone}")
            
        except Exception as e:
            logger.error(f"Login completion error: {e}")
            await update.message.reply_text(
                "❌ **Login Failed**\n\n"
                f"Error: {str(e)[:100]}\n\n"
                "Please try again or contact support."
            )
        
        return ConversationHandler.END
    
    async def cancel_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel login process"""
        user_id = update.effective_user.id
        
        # Clean up
        if user_id in self.login_sessions:
            try:
                await self.login_sessions[user_id]['client'].disconnect()
            except:
                pass
            del self.login_sessions[user_id]
        
        await update.message.reply_text(
            "❌ **Login Cancelled**\n\n"
            "Use /login to try again."
        )
        
        # Clear temp data
        context.user_data.pop('session_string', None)
        context.user_data.pop('account_name', None)
            
        return ConversationHandler.END