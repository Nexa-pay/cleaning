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
            
            # Log the user ID for debugging
            logger.info(f"User {user_id} started the bot")
            
            # Determine user role
            user_role = await self.get_user_role(user_id)
            
            # Get or create user in database with error handling
            tokens = 0
            total_reports = 0
            
            try:
                # Ensure database connection
                if not self._db_connected:
                    await db.ensure_connection()
                    
                db_user = await db.get_user(user_id)
                if not db_user:
                    db_user = await db.create_user(
                        user_id=user_id,
                        username=user.username,
                        first_name=user.first_name,
                        last_name=user.last_name
                    )
                
                if db_user:
                    tokens = getattr(db_user, 'tokens', 0)
                    total_reports = getattr(db_user, 'total_reports', 0)
                    
            except Exception as e:
                logger.error(f"Database error in start: {e}")
                # Fallback values if database fails
            
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
            
            # Add admin button for admins/owners/super admin
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
            try:
                await update.message.reply_text(
                    "👋 Welcome! The bot is starting up. Please try again in a few seconds.\n\n"
                    f"If this persists, contact @{config.CONTACT_INFO.get('admin_username', 'admin')}"
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
            db_status = "✅ Connected" if self._db_connected else "❌ Disconnected"
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
            
            # Ensure database connection
            if not self._db_connected:
                await db.ensure_connection()
            
            user = await db.get_user(user_id)
            
            if not user:
                user = await db.create_user(
                    user_id=user_id,
                    username=update.effective_user.username,
                    first_name=update.effective_user.first_name
                )
            
            balance_text = (
                f"💰 **Your Balance**\n\n"
                f"**Tokens:** `{getattr(user, 'tokens', 0)}`\n"
                f"**Reports Made:** `{getattr(user, 'total_reports', 0)}`\n"
                f"**Account Type:** `{await self.get_user_role(user_id)}`\n\n"
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
    
    async def menu_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle menu button callbacks"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = update.effective_user.id
        
        logger.info(f"Menu callback: {data} from user {user_id}")
        
        try:
            # Check admin access for admin panel
            if data == "menu_admin":
                # Check if user has admin privileges directly from config
                is_admin = (user_id == config.SUPER_ADMIN_ID or 
                           user_id in config.OWNER_IDS or 
                           user_id in config.ADMIN_IDS)
                
                if not is_admin:
                    await query.message.reply_text("❌ You don't have admin access.")
                    return
                
                await query.message.delete()
                await self.admin_handler.admin_panel(update, context)
                return
            
            # Handle other menu options
            if data == "menu_report":
                await query.message.delete()
                context.user_data['from_menu'] = True
                await self.report_handler.start_report(update, context)
                
            elif data == "menu_buy":
                await query.message.delete()
                await self.payment_handler.show_token_packages(update, context)
                
            elif data == "menu_accounts":
                await query.message.delete()
                await account_manager.show_accounts(update, context)
                
            elif data == "menu_myreports":
                await query.message.delete()
                await self.report_handler.my_reports(update, context)
                
            elif data == "menu_help":
                await query.message.delete()
                await self.help_command(update, context)
                
            elif data == "menu_contact":
                await query.message.delete()
                await self.contact_command(update, context)
                
            elif data == "back_to_main":
                await query.message.delete()
                await self.start(update, context)
                
        except Exception as e:
            logger.error(f"Error in menu callback: {e}", exc_info=True)
            try:
                await query.message.reply_text(
                    "❌ An error occurred. Please try again or use /start"
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
                        await asyncio.sleep(3)  # Wait 3 seconds before retry
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
        if db.client:
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
        
        # Basic command handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("whoami", self.whoami_command))
        self.application.add_handler(CommandHandler("balance", self.balance_command))
        self.application.add_handler(CommandHandler("contact", self.contact_command))
        self.application.add_handler(CommandHandler("buy", self.payment_handler.show_token_packages))
        self.application.add_handler(CommandHandler("accounts", account_manager.show_accounts))
        self.application.add_handler(CommandHandler("myreports", self.report_handler.my_reports))
        
        # Admin commands
        self.application.add_handler(CommandHandler("admin", self.admin_handler.admin_panel))
        self.application.add_handler(CommandHandler("stats", self.admin_handler.show_statistics))
        self.application.add_handler(CommandHandler("verify", self.payment_handler.admin_verify_payment))
        
        # Login conversation handler
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
        
        # Report conversation handler
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
        
        # Callback query handlers
        self.application.add_handler(CallbackQueryHandler(self.menu_callback, pattern='^menu_'))
        self.application.add_handler(CallbackQueryHandler(account_manager.handle_account_callback, pattern='^(add_account|refresh_accounts|manage_acc_|activate_acc_|deactivate_acc_|set_primary_|rename_acc_|delete_acc_|acc_reports_|confirm_delete_|back_accounts)$'))
        self.application.add_handler(CallbackQueryHandler(self.payment_handler.handle_package_selection, pattern='^(buy_stars_|buy_upi_|check_balance)$'))
        self.application.add_handler(CallbackQueryHandler(self.payment_handler.confirm_payment, pattern='^(confirm_stars_|confirm_upi_|cancel_payment)$'))
        self.application.add_handler(CallbackQueryHandler(self.admin_handler.handle_admin_callback, pattern='^admin_'))
        
        # Error handler
        self.application.add_error_handler(self.error_handler)
        
        logger.info("Bot handlers setup complete")
    
    async def run(self):
        """Run the bot"""
        try:
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES
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