#!/usr/bin/env python3
"""
Telegram Advanced Report Bot - Main Entry Point
Complete solution with multi-account support, token system, and admin panel
"""

import logging
import asyncio
import os
import sys
import threading
import time
import traceback
from datetime import datetime
from aiohttp import web

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes
)
from telegram.error import InvalidToken, Conflict

# Import configuration
import config

# Import handlers
from database import db
from auth import AuthHandler, PHONE_NUMBER, OTP_CODE, PASSWORD, TWO_FA_SETUP
from payments import PaymentHandler
from report_handler import ReportHandler, SELECT_ACCOUNT, REPORT_TYPE, REPORT_TARGET, REPORT_REASON, REPORT_DETAILS, CONFIRMATION, ADMIN_TARGET, ADMIN_REASON
from admin_handler import AdminHandler
from account_manager import account_manager
from models import UserRole

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Healthcheck server
async def handle_health(request):
    """Handle healthcheck requests"""
    return web.Response(text="OK", status=200)

async def run_web_server():
    """Run the healthcheck web server"""
    app = web.Application()
    app.router.add_get('/', handle_health)
    app.router.add_get('/health', handle_health)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    logger.info("✅ Healthcheck server running on port 8080")
    
    # Keep the server running
    await asyncio.Event().wait()

def start_healthcheck_server():
    """Start healthcheck server in a separate thread"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_web_server())
    except Exception as e:
        logger.error(f"Healthcheck server error: {e}")
    finally:
        loop.close()

# ========== TEST COMMANDS ==========

async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Simple ping command to test if bot is responding"""
    try:
        await update.message.reply_text("🏓 **Pong! Bot is working!**", parse_mode='Markdown')
        logger.info(f"Ping command used by user {update.effective_user.id}")
    except Exception as e:
        logger.error(f"Ping command error: {e}")

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test command to check database connection"""
    try:
        # Check database
        db_status = "✅ Connected" if db and db.db else "❌ Not Connected"
        
        # Get user info
        user = update.effective_user
        
        # Check if user is in config
        is_super = (user.id == config.SUPER_ADMIN_ID)
        is_owner = (user.id in config.OWNER_IDS)
        is_admin = (user.id in config.ADMIN_IDS)
        
        message = (
            f"🔧 **Bot Diagnostic Test**\n\n"
            f"**User:** {user.first_name}\n"
            f"**User ID:** `{user.id}`\n"
            f"**Database:** {db_status}\n"
            f"**Bot Token:** {'✅ Set' if config.BOT_TOKEN else '❌ Missing'}\n"
            f"**MongoDB URI:** {'✅ Set' if config.MONGODB_URI else '❌ Missing'}\n\n"
            f"**Role Checks:**\n"
            f"• Super Admin: {'✅ Yes' if is_super else '❌ No'}\n"
            f"• Owner: {'✅ Yes' if is_owner else '❌ No'}\n"
            f"• Admin: {'✅ Yes' if is_admin else '❌ No'}\n\n"
            f"Try sending /start to see the main menu."
        )
        
        await update.message.reply_text(message, parse_mode='Markdown')
        logger.info(f"Test command used by user {user.id}")
        
    except Exception as e:
        logger.error(f"Test command error: {e}")
        await update.message.reply_text(f"❌ Test error: {str(e)}")

async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug command to check bot status"""
    try:
        await update.message.reply_text(
            f"🔍 **Debug Info**\n\n"
            f"Bot Username: @{context.bot.username}\n"
            f"Bot ID: `{context.bot.id}`\n"
            f"Your ID: `{update.effective_user.id}`\n"
            f"Chat ID: `{update.effective_chat.id}`\n"
            f"Message ID: `{update.effective_message.message_id}`",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Debug command error: {e}")

# ========== MAIN BOT CLASS ==========

class TelegramReportBot:
    def __init__(self):
        self.application = None
        self.auth_handler = AuthHandler()
        self.payment_handler = PaymentHandler()
        self.report_handler = ReportHandler()
        self.admin_handler = AdminHandler()
        self._db_connected = False
        self._start_time = time.time()
        
    def check_config(self):
        """Check if required configuration is present"""
        if not config.BOT_TOKEN:
            logger.error("=" * 50)
            logger.error("BOT_TOKEN is not configured!")
            logger.error("Please set the BOT_TOKEN environment variable")
            logger.error("=" * 50)
            return False
        
        if not config.MONGODB_URI:
            logger.error("=" * 50)
            logger.error("MONGODB_URI is not configured!")
            logger.error("Please set the MONGODB_URI environment variable")
            logger.error("=" * 50)
            return False
            
        return True
    
    async def get_user_role(self, user_id: int) -> str:
        """Determine user role based on config"""
        if user_id == config.SUPER_ADMIN_ID:
            return "SUPER ADMIN"
        elif user_id in config.OWNER_IDS:
            return "OWNER"
        elif user_id in config.ADMIN_IDS:
            return "ADMIN"
        else:
            return "NORMAL USER"
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send welcome message with inline buttons"""
        try:
            user = update.effective_user
            user_id = user.id
            
            logger.info(f"User {user_id} started the bot")
            
            # Determine user role from config
            user_role = await self.get_user_role(user_id)
            
            # Try to get from database, but don't fail if it doesn't work
            tokens = 0
            total_reports = 0
            
            try:
                # Only try database if we think it might be connected
                if db and db.db:
                    db_user = await db.get_user(user_id)
                    if db_user:
                        tokens = getattr(db_user, 'tokens', 0)
                        total_reports = getattr(db_user, 'total_reports', 0)
                    else:
                        # Create user if not exists
                        db_user = await db.create_user(
                            user_id=user_id,
                            username=user.username,
                            first_name=user.first_name,
                            last_name=user.last_name
                        )
                        if db_user:
                            tokens = getattr(db_user, 'tokens', 0)
            except Exception as e:
                logger.warning(f"Database unavailable for user {user_id}: {e}")
            
            # Create welcome message
            welcome_text = (
                f"👋 **Welcome {user.first_name}!**\n\n"
                f"🆔 **User ID:** `{user_id}`\n"
                f"💰 **Tokens:** {tokens}\n"
                f"📊 **Reports Made:** {total_reports}\n"
                f"👑 **Role:** {user_role}\n\n"
                "I'm a comprehensive reporting bot that helps you report:\n"
                "• 👤 Suspicious users\n"
                "• 👥 Problematic groups\n"
                "• 📢 Violating channels\n\n"
                "**Select an option below:**"
            )
            
            # Create inline keyboard
            keyboard = [
                [
                    InlineKeyboardButton("📝 Report", callback_data="menu_report"),
                    InlineKeyboardButton("💰 Buy Tokens", callback_data="menu_buy")
                ],
                [
                    InlineKeyboardButton("📱 Accounts", callback_data="menu_accounts"),
                    InlineKeyboardButton("📊 My Reports", callback_data="menu_myreports")
                ],
                [
                    InlineKeyboardButton("ℹ️ Help", callback_data="menu_help"),
                    InlineKeyboardButton("📞 Contact", callback_data="menu_contact")
                ]
            ]
            
            # Add admin button for privileged users
            if user_role in ["ADMIN", "OWNER", "SUPER ADMIN"]:
                keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="menu_admin")])
                logger.info(f"✅ Admin panel button added for user {user_id}")
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                welcome_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error in start command: {e}", exc_info=True)
            # Ultimate fallback
            try:
                await update.message.reply_text(
                    "👋 Welcome! The bot is starting up.\n"
                    "Please try again in a few seconds."
                )
            except:
                pass
    
    async def whoami_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check your role and permissions"""
        try:
            user_id = update.effective_user.id
            
            # Check roles directly from config
            is_super = (user_id == config.SUPER_ADMIN_ID)
            is_owner = (user_id in config.OWNER_IDS)
            is_admin = (user_id in config.ADMIN_IDS)
            
            # Determine primary role
            if is_super:
                role = "SUPER ADMIN"
            elif is_owner:
                role = "OWNER"
            elif is_admin:
                role = "ADMIN"
            else:
                role = "NORMAL USER"
            
            # Get database status
            db_status = "✅ Connected" if (db and db.db) else "❌ Disconnected"
            uptime = time.time() - self._start_time
            uptime_str = f"{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m"
            
            message = (
                f"👤 **Your Information**\n\n"
                f"**User ID:** `{user_id}`\n"
                f"**Your Role:** `{role}`\n"
                f"**Bot Uptime:** `{uptime_str}`\n"
                f"**Database:** {db_status}\n\n"
                f"**Permission Checks:**\n"
                f"• Is Super Admin: {'✅ Yes' if is_super else '❌ No'}\n"
                f"• Is Owner: {'✅ Yes' if is_owner else '❌ No'}\n"
                f"• Is Admin: {'✅ Yes' if is_admin else '❌ No'}\n\n"
                f"**Config Values:**\n"
                f"ADMIN_IDS: `{config.ADMIN_IDS}`\n"
                f"OWNER_IDS: `{config.OWNER_IDS}`\n"
                f"SUPER_ADMIN_ID: `{config.SUPER_ADMIN_ID}`"
            )
            
            await update.message.reply_text(message, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in whoami command: {e}")
            await update.message.reply_text("❌ Error checking your information.")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help information"""
        help_text = (
            "📚 **Bot Commands**\n\n"
            "**User Commands:**\n"
            "/start - Start the bot\n"
            "/help - Show this help\n"
            "/whoami - Check your role\n"
            "/ping - Test if bot is working\n"
            "/test - Run diagnostic test\n"
            "/debug - Debug information\n"
            "/login - Add Telegram account\n"
            "/accounts - Manage accounts\n"
            "/report - Start reporting\n"
            "/myreports - View your reports\n"
            "/buy - Purchase tokens\n"
            "/balance - Check token balance\n"
            "/contact - Contact support\n\n"
            
            "**Admin Commands:**\n"
            "/admin - Open admin panel\n"
            "/stats - View statistics\n"
            "/users - Manage users\n"
            "/reports - View all reports\n"
            "/verify - Verify payments\n\n"
            
            "**How to Report:**\n"
            "1. Add an account using /login\n"
            "2. Buy tokens with /buy\n"
            "3. Start report with /report\n"
            "4. Select target and reason\n"
            "5. Confirm and submit\n\n"
            
            f"**Support:** @{config.CONTACT_INFO.get('admin_username', 'admin')}"
        )
        
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check user balance"""
        try:
            user_id = update.effective_user.id
            
            # Try to get from database
            tokens = 0
            total_reports = 0
            role = await self.get_user_role(user_id)
            
            try:
                if db and db.db:
                    user = await db.get_user(user_id)
                    if user:
                        tokens = getattr(user, 'tokens', 0)
                        total_reports = getattr(user, 'total_reports', 0)
            except Exception as e:
                logger.warning(f"Database error in balance: {e}")
            
            balance_text = (
                f"💰 **Your Balance**\n\n"
                f"**Tokens:** `{tokens}`\n"
                f"**Reports Made:** `{total_reports}`\n"
                f"**Account Type:** `{role}`\n\n"
                f"Use /buy to purchase more tokens."
            )
            
            await update.message.reply_text(balance_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in balance command: {e}")
            await update.message.reply_text(
                "❌ Error checking balance. Please try again later."
            )
    
    async def contact_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show contact information"""
        contact_text = (
            "📞 **Contact Information**\n\n"
            f"**Admin:** @{config.CONTACT_INFO.get('admin_username', 'admin')}\n"
            f"**Owner:** @{config.CONTACT_INFO.get('owner_username', 'owner')}\n"
            f"**Support Group:** [Join here]({config.CONTACT_INFO.get('support_group', 'https://t.me/support')})\n"
            f"**Channel:** [Follow updates]({config.CONTACT_INFO.get('channel', 'https://t.me/channel')})\n"
            f"**Email:** `{config.CONTACT_INFO.get('email', 'support@example.com')}`\n\n"
            "Feel free to reach out for any issues or questions!"
        )
        
        keyboard = [
            [InlineKeyboardButton("📢 Support Group", url=config.CONTACT_INFO.get('support_group', 'https://t.me/support'))],
            [InlineKeyboardButton("📱 Channel", url=config.CONTACT_INFO.get('channel', 'https://t.me/channel'))]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            contact_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    # ========== IMPROVED BUTTON HANDLER ==========
    async def menu_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle menu button callbacks - IMPROVED VERSION with better error handling"""
        query = update.callback_query
        
        try:
            # Always answer the callback query first
            await query.answer()
            
            data = query.data
            user_id = update.effective_user.id
            
            logger.info(f"📱 Menu callback received: {data} from user {user_id}")
            
            # Show typing indicator
            await query.message.chat.send_action(action="typing")
            
            # ===== HANDLE EACH BUTTON TYPE =====
            
            # Admin Panel Button
            if data == "menu_admin":
                # Check if user has admin privileges
                is_admin = (user_id == config.SUPER_ADMIN_ID or 
                           user_id in config.OWNER_IDS or 
                           user_id in config.ADMIN_IDS)
                
                if not is_admin:
                    await query.edit_message_text("❌ You don't have admin access.")
                    return
                
                await query.message.delete()
                await self.admin_handler.admin_panel(update, context)
                return
            
            # Report Button
            elif data == "menu_report":
                await query.message.delete()
                context.user_data['from_menu'] = True
                result = await self.report_handler.start_report(update, context)
                if result is None:
                    # If start_report doesn't return a state, send a message
                    await query.message.reply_text("📝 Starting report process... Use /report to begin.")
                return
            
            # Buy Tokens Button
            elif data == "menu_buy":
                await query.message.delete()
                await self.payment_handler.show_token_packages(update, context)
                return
            
            # Accounts Button
            elif data == "menu_accounts":
                await query.message.delete()
                await account_manager.show_accounts(update, context)
                return
            
            # My Reports Button
            elif data == "menu_myreports":
                await query.message.delete()
                await self.report_handler.my_reports(update, context)
                return
            
            # Help Button
            elif data == "menu_help":
                await query.message.delete()
                await self.help_command(update, context)
                return
            
            # Contact Button
            elif data == "menu_contact":
                await query.message.delete()
                await self.contact_command(update, context)
                return
            
            # Back to Main Menu Button
            elif data == "back_to_main":
                await query.message.delete()
                await self.start(update, context)
                return
            
            # Unknown Button
            else:
                logger.warning(f"Unknown callback data: {data}")
                await query.edit_message_text(
                    f"❓ Unknown button: `{data}`\n\nPlease use /start to restart.",
                    parse_mode='Markdown'
                )
                
        except Exception as e:
            logger.error(f"❌ Error in menu callback: {e}", exc_info=True)
            
            # Try to send error message to user
            try:
                error_message = (
                    "❌ **An error occurred while processing your request.**\n\n"
                    f"Error: `{str(e)[:100]}`\n\n"
                    "Please try again or use /start"
                )
                
                # Try to edit the original message
                await query.edit_message_text(error_message, parse_mode='Markdown')
            except:
                try:
                    # If edit fails, try to send a new message
                    await query.message.reply_text(
                        "❌ An error occurred. Please use /start to restart."
                    )
                except:
                    pass
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors gracefully"""
        error = context.error
        
        # Ignore Conflict errors (multiple instances)
        if isinstance(error, Conflict):
            logger.debug("Conflict error ignored (multiple bot instances)")
            return
            
        logger.error(f"Update {update} caused error {error}")
        logger.error(traceback.format_exc())
        
        try:
            if update and update.effective_message:
                await update.effective_message.reply_text(
                    "❌ An error occurred. Our team has been notified.\n"
                    "Please try again later or contact support."
                )
        except:
            pass
    
    async def post_init(self, application: Application):
        """Run after bot initialization"""
        logger.info("Bot is starting up...")
        
        # Log configuration for debugging
        logger.info(f"ADMIN_IDS: {config.ADMIN_IDS}")
        logger.info(f"OWNER_IDS: {config.OWNER_IDS}")
        logger.info(f"SUPER_ADMIN_ID: {config.SUPER_ADMIN_ID}")
        if config.MONGODB_URI:
            logger.info(f"MONGODB_URI: {config.MONGODB_URI[:30]}...")
        
        # Start healthcheck server in a background thread
        try:
            health_thread = threading.Thread(target=start_healthcheck_server, daemon=True)
            health_thread.start()
            logger.info("✅ Healthcheck thread started")
        except Exception as e:
            logger.error(f"Failed to start healthcheck server: {e}")
        
        # Connect to database with retry
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.info(f"Database connection attempt {attempt + 1}/{max_retries}")
                connected = await db.connect()
                if connected:
                    self._db_connected = True
                    logger.info("✅ Database connected successfully!")
                    break
                else:
                    logger.warning(f"Database connection attempt {attempt + 1} failed")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"Database connection error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(3)
        
        if not self._db_connected:
            logger.warning("⚠️ Bot running in limited mode without database")
        
        logger.info("Bot started successfully!")
    
    async def post_shutdown(self, application: Application):
        """Run before bot shutdown"""
        logger.info("Bot is shutting down...")
        
        # Close database connection
        if db and db.client:
            db.client.close()
            logger.info("Database connection closed.")
    
    def setup(self):
        """Setup bot handlers"""
        if not self.check_config():
            sys.exit(1)
        
        # Create application with custom settings
        builder = Application.builder().token(config.BOT_TOKEN)
        
        # Add post init/shutdown
        builder.post_init(self.post_init)
        builder.post_shutdown(self.post_shutdown)
        
        # Build application
        self.application = builder.build()
        
        # ========== TEST COMMANDS ==========
        self.application.add_handler(CommandHandler("ping", ping_command))
        self.application.add_handler(CommandHandler("test", test_command))
        self.application.add_handler(CommandHandler("debug", debug_command))
        
        # ========== USER COMMANDS ==========
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("whoami", self.whoami_command))
        self.application.add_handler(CommandHandler("balance", self.balance_command))
        self.application.add_handler(CommandHandler("contact", self.contact_command))
        self.application.add_handler(CommandHandler("buy", self.payment_handler.show_token_packages))
        self.application.add_handler(CommandHandler("accounts", account_manager.show_accounts))
        self.application.add_handler(CommandHandler("myreports", self.report_handler.my_reports))
        
        # ========== ADMIN COMMANDS ==========
        self.application.add_handler(CommandHandler("admin", self.admin_handler.admin_panel))
        self.application.add_handler(CommandHandler("stats", self.admin_handler.show_statistics))
        self.application.add_handler(CommandHandler("verify", self.payment_handler.admin_verify_payment))
        
        # ========== LOGIN CONVERSATION ==========
        login_conv = ConversationHandler(
            entry_points=[CommandHandler('login', self.auth_handler.start_login)],
            states={
                PHONE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.auth_handler.handle_phone)],
                OTP_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.auth_handler.handle_otp)],
                PASSWORD: [CallbackQueryHandler(self.auth_handler.handle_2fa_choice, pattern='^2fa_')],
                TWO_FA_SETUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.auth_handler.handle_2fa_password)],
            },
            fallbacks=[CommandHandler('cancel', self.auth_handler.cancel_login)],
        )
        self.application.add_handler(login_conv)
        
        # ========== REPORT CONVERSATION ==========
        report_conv = ConversationHandler(
            entry_points=[
                CommandHandler('report', self.report_handler.start_report),
                CallbackQueryHandler(self.report_handler.start_report, pattern='^menu_report$')
            ],
            states={
                SELECT_ACCOUNT: [CallbackQueryHandler(self.report_handler.handle_account_selection, pattern='^(select_acc_|add_account|cancel_report)$')],
                REPORT_TYPE: [CallbackQueryHandler(self.report_handler.handle_report_type, pattern='^(report_type_|cancel_report)$')],
                REPORT_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.report_handler.handle_target)],
                REPORT_REASON: [CallbackQueryHandler(self.report_handler.handle_reason, pattern='^(reason_template_|reason_custom|cancel_report)$')],
                REPORT_DETAILS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.report_handler.handle_details),
                    CommandHandler('skip', self.report_handler.skip_details)
                ],
                CONFIRMATION: [CallbackQueryHandler(self.report_handler.submit_report, pattern='^(confirm_report|cancel_report)$')],
                ADMIN_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.report_handler.handle_admin_target)],
                ADMIN_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.report_handler.handle_admin_reason)],
            },
            fallbacks=[CommandHandler('cancel', self.report_handler.cancel)],
        )
        self.application.add_handler(report_conv)
        
        # ========== CALLBACK QUERY HANDLERS ==========
        # Main menu buttons
        self.application.add_handler(CallbackQueryHandler(self.menu_callback, pattern='^menu_'))
        
        # Account management buttons
        self.application.add_handler(CallbackQueryHandler(account_manager.handle_account_callback, pattern='^(add_account|refresh_accounts|manage_acc_|activate_acc_|deactivate_acc_|set_primary_|rename_acc_|delete_acc_|acc_reports_|confirm_delete_|back_accounts)$'))
        
        # Payment buttons
        self.application.add_handler(CallbackQueryHandler(self.payment_handler.handle_package_selection, pattern='^(buy_stars_|buy_upi_|check_balance)$'))
        self.application.add_handler(CallbackQueryHandler(self.payment_handler.confirm_payment, pattern='^(confirm_stars_|confirm_upi_|cancel_payment)$'))
        
        # Admin panel buttons
        self.application.add_handler(CallbackQueryHandler(self.admin_handler.handle_admin_callback, pattern='^admin_'))
        
        # ========== ERROR HANDLER ==========
        self.application.add_error_handler(self.error_handler)
        
        logger.info("✅ Bot handlers setup complete")
    
    async def run(self):
        """Run the bot"""
        try:
            await self.application.initialize()
            await self.application.start()
            
            # Start polling with error handling for conflicts
            await self.application.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES,
                poll_interval=1.0,
                timeout=10
            )
            
            logger.info(f"✅ Bot is running. Press Ctrl+C to stop.")
            
            # Keep running
            while True:
                await asyncio.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("Stopping bot...")
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the bot gracefully"""
        try:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
            logger.info("Bot stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping bot: {e}")

def main():
    """Main entry point"""
    bot = TelegramReportBot()
    bot.setup()
    
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()