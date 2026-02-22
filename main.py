import asyncio
from aiohttp import web
import threading

# Simple web server for Railway healthcheck
async def handle_health(request):
    return web.Response(text="OK", status=200)

async def run_web_server():
    app = web.Application()
    app.router.add_get('/', handle_health)
    app.router.add_get('/health', handle_health)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    print("✅ Healthcheck server running on port 8080")

# Add this function to your TelegramReportBot class
def start_healthcheck_server(self):
    """Start healthcheck server in a separate thread"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_web_server())
    loop.run_forever()
#!/usr/bin/env python3
"""
Telegram Advanced Report Bot - Main Entry Point
Complete solution with multi-account support, token system, and admin panel
"""

import logging
import asyncio
import os
import sys
from datetime import datetime

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
from telegram.error import InvalidToken

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

class TelegramReportBot:
    def __init__(self):
        self.application = None
        self.auth_handler = AuthHandler()
        self.payment_handler = PaymentHandler()
        self.report_handler = ReportHandler()
        self.admin_handler = AdminHandler()
        
    def check_config(self):
        """Check if required configuration is present"""
        if not config.BOT_TOKEN:
            logger.error("=" * 50)
            logger.error("BOT_TOKEN is not configured!")
            logger.error("Please set the BOT_TOKEN environment variable")
            logger.error("=" * 50)
            return False
        return True
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send welcome message with inline buttons"""
        user = update.effective_user
        user_id = user.id
        
        # Get or create user in database
        db_user = await db.get_user(user_id)
        if not db_user:
            db_user = await db.create_user(
                user_id=user_id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name
            )
        
        # Create welcome message
        welcome_text = (
            f"👋 **Welcome {user.first_name}!**\n\n"
            f"🆔 **User ID:** `{user_id}`\n"
            f"💰 **Tokens:** {db_user.tokens}\n"
            f"📊 **Reports Made:** {db_user.total_reports}\n"
            f"👑 **Role:** {db_user.role.value.upper()}\n\n"
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
        
        # Add admin button for admins
        if db_user.role in [UserRole.ADMIN, UserRole.OWNER, UserRole.SUPER_ADMIN]:
            keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="menu_admin")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            welcome_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help information"""
        help_text = (
            "📚 **Bot Commands**\n\n"
            "**User Commands:**\n"
            "/start - Start the bot\n"
            "/help - Show this help\n"
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
            
            f"**Support:** @{config.CONTACT_INFO['admin_username']}"
        )
        
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check user balance"""
        user_id = update.effective_user.id
        user = await db.get_user(user_id)
        
        if not user:
            user = await db.create_user(
                user_id=user_id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name
            )
        
        await update.message.reply_text(
            f"💰 **Your Balance**\n\n"
            f"**Tokens:** `{user.tokens}`\n"
            f"**Reports Made:** `{user.total_reports}`\n"
            f"**Account Type:** `{user.role.value.upper()}`\n\n"
            f"Use /buy to purchase more tokens.",
            parse_mode='Markdown'
        )
    
    async def contact_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show contact information"""
        contact_text = (
            "📞 **Contact Information**\n\n"
            f"**Admin:** @{config.CONTACT_INFO['admin_username']}\n"
            f"**Owner:** @{config.CONTACT_INFO['owner_username']}\n"
            f"**Support Group:** [Join here]({config.CONTACT_INFO['support_group']})\n"
            f"**Channel:** [Follow updates]({config.CONTACT_INFO['channel']})\n"
            f"**Email:** `{config.CONTACT_INFO['email']}`\n\n"
            "Feel free to reach out for any issues or questions!"
        )
        
        keyboard = [
            [InlineKeyboardButton("📢 Support Group", url=config.CONTACT_INFO['support_group'])],
            [InlineKeyboardButton("📱 Channel", url=config.CONTACT_INFO['channel'])]
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
            
        elif data == "menu_admin":
            await query.message.delete()
            await self.admin_handler.admin_panel(update, context)
            
        elif data == "back_to_main":
            await query.message.delete()
            await self.start(update, context)
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors"""
        logger.error(f"Update {update} caused error {context.error}")
        
        try:
            if update and update.effective_message:
                await update.effective_message.reply_text(
                    "❌ An error occurred. Please try again later."
                )
        except:
            pass
    
    async def post_init(self, application: Application):
        """Run after bot initialization"""
        logger.info("Bot is starting up...")
        
        # Connect to database
        connected = await db.connect()
        if not connected:
            logger.error("Failed to connect to database!")
            return
        
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
        
        # Create application
        self.application = Application.builder()\
            .token(config.BOT_TOKEN)\
            .post_init(self.post_init)\
            .post_shutdown(self.post_shutdown)\
            .build()
        
        # Basic command handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help_command))
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
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        logger.info(f"Bot is running. Press Ctrl+C to stop.")
        
        # Keep running
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Stopping bot...")
        finally:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()

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