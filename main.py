#!/usr/bin/env python3
"""
Telegram Advanced Report Bot - Main Entry Point
Complete solution with multi-account support, token system, admin panel, and owner features
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
from auth import AuthHandler, PHONE_NUMBER, OTP_CODE, TWO_FA_PASSWORD, ACCOUNT_NAME
from payments import PaymentHandler
from report_handler import ReportHandler, SELECT_ACCOUNT, REPORT_TYPE, REPORT_TARGET, REPORT_REASON, REPORT_DETAILS, CONFIRMATION, ADMIN_TARGET, ADMIN_REASON
from admin_handler import AdminHandler
from owner_handler import owner_handler
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

# ========== EMERGENCY TEST COMMAND ==========
async def emergency_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Emergency test command that works without database"""
    try:
        user = update.effective_user
        
        # Check database status safely
        db_status = "❌ Not Connected"
        if db is not None:
            if hasattr(db, 'db') and db.db is not None:
                try:
                    await db.db.command('ping')
                    db_status = "✅ Connected and working"
                except Exception as e:
                    db_status = f"⚠️ Connected but error: {str(e)[:50]}"
            else:
                db_status = "❌ Database object exists but no connection"
                
                if config.MONGODB_URI:
                    db_status += "\n• URI is set but connection failed"
                    if 'Adiantum' in config.MONGODB_URI:
                        db_status += "\n• Password appears correct"
                    else:
                        db_status += "\n• Check your password in URI"
                else:
                    db_status += "\n• MONGODB_URI is not set!"
        else:
            db_status = "❌ Database object is None"
        
        message = (
            f"✅ EMERGENCY TEST PASSED\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Bot is receiving commands!\n\n"
            f"Your ID: {user.id}\n"
            f"Your Name: {user.first_name}\n"
            f"Bot Username: @{context.bot.username}\n\n"
            f"Database Status:\n{db_status}\n\n"
            f"Config Status:\n"
            f"• BOT_TOKEN: {'✅ Set' if config.BOT_TOKEN else '❌ Missing'}\n"
            f"• MONGODB_URI: {'✅ Set' if config.MONGODB_URI else '❌ Missing'}\n\n"
            f"Send /test for more details."
        )
        
        await update.message.reply_text(message)
        
    except Exception as e:
        await update.message.reply_text(f"Emergency test error: {str(e)}")

# ========== TEST COMMANDS ==========
async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Simple ping command"""
    try:
        await update.message.reply_text("🏓 Pong! Bot is working!")
        logger.info(f"Ping command used by user {update.effective_user.id}")
    except Exception as e:
        logger.error(f"Ping command error: {e}")

async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test command to check database connection"""
    try:
        db_status = "❌ Not Connected"
        if db is not None:
            if hasattr(db, 'db') and db.db is not None:
                try:
                    await db.db.command('ping')
                    db_status = "✅ Connected and working"
                except Exception as e:
                    db_status = f"⚠️ Connected but error: {str(e)[:50]}"
            else:
                db_status = "❌ Database object exists but no connection"
        else:
            db_status = "❌ Database object is None"
        
        user = update.effective_user
        is_super = (user.id == config.SUPER_ADMIN_ID)
        is_owner = (user.id in config.OWNER_IDS)
        is_admin = (user.id in config.ADMIN_IDS)
        
        uri_preview = "Not set"
        if config.MONGODB_URI:
            uri_preview = config.MONGODB_URI[:30] + "..."
        
        message = (
            f"🔧 Bot Diagnostic Test\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"User: {user.first_name}\n"
            f"User ID: {user.id}\n"
            f"Database: {db_status}\n"
            f"Bot Token: {'✅ Set' if config.BOT_TOKEN else '❌ Missing'}\n"
            f"MongoDB URI: {uri_preview}\n\n"
            f"Role Checks:\n"
            f"• Super Admin: {'✅ Yes' if is_super else '❌ No'}\n"
            f"• Owner: {'✅ Yes' if is_owner else '❌ No'}\n"
            f"• Admin: {'✅ Yes' if is_admin else '❌ No'}\n\n"
            f"Try sending /start to see the main menu."
        )
        
        await update.message.reply_text(message)
        logger.info(f"Test command used by user {user.id}")
        
    except Exception as e:
        logger.error(f"Test command error: {e}")
        await update.message.reply_text(f"❌ Test error: {str(e)}")

async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Debug command to check bot status"""
    try:
        await update.message.reply_text(
            f"🔍 Debug Info\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Bot Username: @{context.bot.username}\n"
            f"Bot ID: {context.bot.id}\n"
            f"Your ID: {update.effective_user.id}\n"
            f"Chat ID: {update.effective_chat.id}\n"
            f"Message ID: {update.effective_message.message_id}"
        )
    except Exception as e:
        logger.error(f"Debug command error: {e}")

# ========== DATABASE DEBUG COMMANDS ==========
async def checkdb_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check database status"""
    try:
        # Check connection
        is_connected = (db is not None and 
                       hasattr(db, 'db') and 
                       db.db is not None)
        
        if not is_connected:
            await update.message.reply_text("❌ Database is not connected!")
            return
        
        # Get counts
        user_count = await db.get_user_count()
        account_count = 0
        report_count = 0
        transaction_count = 0
        
        if db.db:
            account_count = await db.db.accounts.count_documents({})
            report_count = await db.db.reports.count_documents({})
            transaction_count = await db.db.transactions.count_documents({})
        
        # Get your user
        user_id = update.effective_user.id
        your_user = await db.get_user(user_id)
        
        message = (
            f"📊 **Database Status**\n\n"
            f"**Connection:** ✅ Connected\n"
            f"**Database Name:** {config.DATABASE_NAME}\n\n"
            f"**Collections:**\n"
            f"• Users: {user_count}\n"
            f"• Accounts: {account_count}\n"
            f"• Reports: {report_count}\n"
            f"• Transactions: {transaction_count}\n\n"
        )
        
        if your_user:
            message += f"**Your Record:**\n"
            message += f"• User ID: `{your_user.user_id}`\n"
            message += f"• Role: {your_user.role.value}\n"
            message += f"• Tokens: {your_user.tokens}\n"
        else:
            message += f"**Your Record:** ❌ Not found in database\n"
            message += f"Use /createme to add yourself."
        
        await update.message.reply_text(message, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in checkdb: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def create_me_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create yourself in the database if you don't exist"""
    user_id = update.effective_user.id
    user = update.effective_user
    
    try:
        # Check if user exists
        db_user = await db.get_user(user_id)
        
        if db_user:
            await update.message.reply_text(
                f"✅ You already exist in the database!\n"
                f"User ID: `{user_id}`\n"
                f"Role: {db_user.role.value}\n"
                f"Tokens: {db_user.tokens}",
                parse_mode='Markdown'
            )
        else:
            # Create user
            new_user = await db.create_user(
                user_id=user_id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name
            )
            
            # Give some initial tokens
            await db.update_user_tokens(user_id, 100)
            
            await update.message.reply_text(
                f"✅ **You've been added to the database!**\n\n"
                f"User ID: `{user_id}`\n"
                f"Role: {new_user.role.value}\n"
                f"Tokens: 100 (including bonus)\n\n"
                f"Use /balance to check your balance.",
                parse_mode='Markdown'
            )
    except Exception as e:
        logger.error(f"Error in create_me: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def fixdb_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Diagnose and fix database connection issues"""
    user_id = update.effective_user.id
    
    message = "🔍 **Database Diagnostic**\n\n"
    
    # Check if MONGODB_URI is set
    if not config.MONGODB_URI:
        message += "❌ MONGODB_URI is NOT set in environment variables!\n"
        message += "Please add it to Railway variables.\n"
        await update.message.reply_text(message, parse_mode='Markdown')
        return
    
    message += f"✅ MONGODB_URI is set: `{config.MONGODB_URI[:30]}...`\n"
    
    # Check database object
    if db is None:
        message += "❌ Database object is None\n"
        await update.message.reply_text(message, parse_mode='Markdown')
        return
    
    message += "✅ Database object exists\n"
    
    # Try to connect
    message += "\n🔄 Attempting to connect...\n"
    try:
        connected = await db.connect()
        if connected:
            message += "✅ Connection successful!\n"
            if hasattr(self, '_db_connected'):
                self._db_connected = True
        else:
            message += "❌ Connection failed\n"
    except Exception as e:
        message += f"❌ Connection error: {str(e)[:100]}\n"
    
    # Check if db.db is accessible
    if db.db is not None:
        message += "✅ Database handle is available\n"
        
        # Try to list collections
        try:
            collections = await db.db.list_collection_names()
            message += f"✅ Collections: {', '.join(collections) or 'None'}\n"
        except Exception as e:
            message += f"❌ Cannot list collections: {str(e)[:100]}\n"
    else:
        message += "❌ Database handle is None\n"
    
    # Check if we can ping
    try:
        if db.client:
            await db.client.admin.command('ping')
            message += "✅ MongoDB ping successful\n"
    except Exception as e:
        message += f"❌ Ping failed: {str(e)[:100]}\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def testdb_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Simple database test"""
    try:
        msg = await update.message.reply_text("🔄 Testing database connection...")
        
        # Try to connect
        connected = await db.connect()
        
        if connected:
            await msg.edit_text(
                "✅ **Database Connected!**\n\n"
                "Try using /createme to add yourself to the database.",
                parse_mode='Markdown'
            )
        else:
            await msg.edit_text(
                "❌ **Database Connection Failed**\n\n"
                "Please check your MONGODB_URI in Railway variables.\n"
                "It should look like:\n"
                "`mongodb+srv://username:password@cluster.mongodb.net/dbname`",
                parse_mode='Markdown'
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# ========== EMERGENCY FIX COMMAND ==========
async def emfix_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Emergency fix - add owner to database with 9999 tokens"""
    user_id = update.effective_user.id
    user = update.effective_user
    
    msg = await update.message.reply_text("🔄 Running emergency database fix...")
    
    try:
        # Try to connect manually
        connected = await db.connect()
        
        if not connected:
            await msg.edit_text(
                "❌ **Database Connection Failed**\n\n"
                "Please check your MONGODB_URI in Railway variables.\n"
                f"Current URI: `{config.MONGODB_URI[:50] if config.MONGODB_URI else 'Not set'}...`\n\n"
                "Make sure it's exactly:\n"
                "`mongodb+srv://telegram_bot_user:Adiantum@cluster0.ibwg1jy.mongodb.net/telegram_report_bot?retryWrites=true&w=majority`",
                parse_mode='Markdown'
            )
            return
        
        # Check if we can access the database
        try:
            # Try to create a test collection
            test_collection = db.db.test_connection
            await test_collection.insert_one({"test": "data", "timestamp": datetime.now()})
            await test_collection.delete_many({})
            logger.info("✅ Database write test passed")
        except Exception as e:
            logger.error(f"Database write test failed: {e}")
            await msg.edit_text(f"❌ Database connected but write test failed: {e}")
            return
        
        # Create owner user with 9999 tokens
        owner_id = user_id
        owner = await db.get_user(owner_id)
        
        if owner:
            # Update existing owner
            await db.update_user_tokens(owner_id, 9999)
            await msg.edit_text(
                f"✅ **Owner Updated!**\n\n"
                f"User ID: `{owner_id}`\n"
                f"Added 9999 tokens\n"
                f"New balance: {owner.tokens + 9999}\n\n"
                f"Database is now working!",
                parse_mode='Markdown'
            )
        else:
            # Create new owner
            new_owner = await db.create_user(
                user_id=owner_id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name
            )
            if new_owner:
                await db.update_user_tokens(owner_id, 9999)
                await msg.edit_text(
                    f"✅ **Owner Created!**\n\n"
                    f"User ID: `{owner_id}`\n"
                    f"Tokens: 9999\n\n"
                    f"Database is now working!",
                    parse_mode='Markdown'
                )
            else:
                await msg.edit_text("❌ Failed to create user")
        
        # Create a test user
        test_id = 987654321
        test_user = await db.get_user(test_id)
        if not test_user:
            await db.create_user(
                user_id=test_id,
                username="test_user",
                first_name="Test",
                last_name="User"
            )
            await db.update_user_tokens(test_id, 100)
        
    except Exception as e:
        logger.error(f"Emergency fix error: {e}")
        await msg.edit_text(f"❌ Error: {str(e)}")

# ========== TOKEN COMMANDS ==========
async def give_tokens_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Give tokens to a user (owner only)"""
    user_id = update.effective_user.id
    
    # Check if owner
    if user_id not in config.OWNER_IDS and user_id != config.SUPER_ADMIN_ID:
        await update.message.reply_text("❌ Owner only command.")
        return
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/givetokens <user_id> <amount>`\n"
            "Example: `/givetokens 8289517006 100`\n\n"
            "**Owner Commands:**\n"
            "• `/addtokens @username 100` - Add tokens by username\n"
            "• `/tokenstats` - View token statistics",
            parse_mode='Markdown'
        )
        return
    
    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
        
        if amount <= 0:
            await update.message.reply_text("❌ Amount must be positive.")
            return
        
        if not self.is_db_connected():
            await update.message.reply_text("❌ Database not connected.")
            return
        
        success = await db.update_user_tokens(target_id, amount)
        
        if success:
            await update.message.reply_text(
                f"✅ Added **{amount}** tokens to user `{target_id}`",
                parse_mode='Markdown'
            )
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=f"💰 You received **{amount}** tokens from owner!",
                    parse_mode='Markdown'
                )
            except:
                pass
        else:
            await update.message.reply_text(
                f"❌ Failed to add tokens. User `{target_id}` may not exist.",
                parse_mode='Markdown'
            )
            
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID or amount.")
    except Exception as e:
        logger.error(f"Error: {e}")

# ========== OWNER TOKEN MANAGEMENT COMMANDS ==========
async def owner_add_tokens_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner command to add tokens (usage: /addtokens @username 100)"""
    user_id = update.effective_user.id
    
    # Check if owner
    if user_id not in config.OWNER_IDS and user_id != config.SUPER_ADMIN_ID:
        await update.message.reply_text("❌ Owner only command.")
        return
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/addtokens <username or user_id> <amount>`\n"
            "Examples:\n"
            "• `/addtokens @username 100`\n"
            "• `/addtokens 123456789 100`",
            parse_mode='Markdown'
        )
        return
    
    try:
        target = context.args[0]
        amount = int(context.args[1])
        
        if amount <= 0:
            await update.message.reply_text("❌ Amount must be positive.")
            return
        
        # Find user
        target_id = None
        if target.startswith('@'):
            # Find by username
            user = await db.get_user_by_username(target[1:])
            if user:
                target_id = user.user_id
        else:
            # Find by user ID
            try:
                target_id = int(target)
            except ValueError:
                await update.message.reply_text("❌ Invalid user ID or username.")
                return
        
        if not target_id:
            await update.message.reply_text(f"❌ User {target} not found.")
            return
        
        # Add tokens
        success = await db.update_user_tokens(target_id, amount)
        
        if success:
            await update.message.reply_text(
                f"✅ Added **{amount}** tokens to {target}\n"
                f"User ID: `{target_id}`",
                parse_mode='Markdown'
            )
            
            # Notify user
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=f"💰 **You received {amount} tokens from owner!**",
                    parse_mode='Markdown'
                )
            except:
                pass
        else:
            await update.message.reply_text("❌ Failed to add tokens.")
            
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Use numbers only.")
    except Exception as e:
        logger.error(f"Error in addtokens: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)[:100]}")

async def owner_token_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show token statistics"""
    user_id = update.effective_user.id
    
    if user_id not in config.OWNER_IDS and user_id != config.SUPER_ADMIN_ID:
        await update.message.reply_text("❌ Owner only command.")
        return
    
    try:
        total_users = await db.get_user_count()
        total_tokens = 0
        
        if db and db.db:
            pipeline = [
                {"$match": {"status": "completed"}},
                {"$group": {"_id": None, "total": {"$sum": "$tokens_purchased"}}}
            ]
            result = await db.db.transactions.aggregate(pipeline).to_list(1)
            total_tokens = result[0]['total'] if result else 0
        
        await update.message.reply_text(
            f"📊 **Token Statistics**\n\n"
            f"**Total Users:** {total_users}\n"
            f"**Total Tokens Issued:** {total_tokens}\n\n"
            f"Use `/addtokens` to add tokens to users.",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"Error in token stats: {e}")
        await update.message.reply_text("❌ Error fetching statistics.")

# ========== BULK TOKEN INPUT HANDLER ==========
async def handle_bulk_token_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle bulk token input"""
    if context.user_data.get('awaiting_bulk_tokens'):
        # This would need to be implemented in admin_handler
        await update.message.reply_text("Bulk token processing coming soon...")
    elif context.user_data.get('awaiting_token_input'):
        # This would need to be implemented in admin_handler
        await update.message.reply_text("Token addition processing coming soon...")

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
            logger.error("BOT_TOKEN is not configured!")
            return False
        
        if not config.MONGODB_URI:
            logger.error("MONGODB_URI is not configured!")
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
    
    def is_db_connected(self):
        """Safely check if database is connected"""
        return (db is not None and 
                hasattr(db, 'db') and 
                db.db is not None)
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send welcome message with inline buttons"""
        try:
            user = update.effective_user
            user_id = user.id
            
            logger.info(f"User {user_id} started the bot")
            user_role = await self.get_user_role(user_id)
            
            tokens = 0
            total_reports = 0
            
            try:
                if self.is_db_connected():
                    db_user = await db.get_user(user_id)
                    if db_user:
                        tokens = getattr(db_user, 'tokens', 0)
                        total_reports = getattr(db_user, 'total_reports', 0)
                    else:
                        db_user = await db.create_user(
                            user_id=user_id,
                            username=user.username,
                            first_name=user.first_name,
                            last_name=user.last_name
                        )
                        if db_user:
                            tokens = getattr(db_user, 'tokens', 0)
            except Exception as e:
                logger.warning(f"Database unavailable: {e}")
            
            welcome_text = (
                f"👋 **Welcome {user.first_name}!**\n\n"
                f"🆔 **User ID:** `{user_id}`\n"
                f"💰 **Tokens:** {tokens}\n"
                f"📊 **Reports Made:** {total_reports}\n"
                f"👑 **Role:** {user_role}\n\n"
                "Select an option below:"
            )
            
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
            
            if user_role in ["ADMIN", "OWNER", "SUPER ADMIN"]:
                keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data="menu_admin")])
            
            if user_role in ["OWNER", "SUPER ADMIN"]:
                keyboard.append([InlineKeyboardButton("👑 Owner Panel", callback_data="menu_owner")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                welcome_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error in start: {e}")
    
    async def whoami_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check your role and permissions"""
        try:
            user_id = update.effective_user.id
            
            is_super = (user_id == config.SUPER_ADMIN_ID)
            is_owner = (user_id in config.OWNER_IDS)
            is_admin = (user_id in config.ADMIN_IDS)
            
            if is_super:
                role = "SUPER ADMIN"
            elif is_owner:
                role = "OWNER"
            elif is_admin:
                role = "ADMIN"
            else:
                role = "NORMAL USER"
            
            db_status = "✅ Connected" if self.is_db_connected() else "❌ Disconnected"
            uptime = time.time() - self._start_time
            uptime_str = f"{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m"
            
            message = (
                f"👤 **Your Information**\n\n"
                f"**User ID:** `{user_id}`\n"
                f"**Your Role:** `{role}`\n"
                f"**Bot Uptime:** `{uptime_str}`\n"
                f"**Database:** {db_status}\n\n"
                f"**Permission Checks:**\n"
                f"• Super Admin: {'✅ Yes' if is_super else '❌ No'}\n"
                f"• Owner: {'✅ Yes' if is_owner else '❌ No'}\n"
                f"• Admin: {'✅ Yes' if is_admin else '❌ No'}\n\n"
                f"ADMIN_IDS: `{config.ADMIN_IDS}`\n"
                f"OWNER_IDS: `{config.OWNER_IDS}`\n"
                f"SUPER_ADMIN_ID: `{config.SUPER_ADMIN_ID}`"
            )
            
            await update.message.reply_text(message, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in whoami: {e}")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help information"""
        help_text = (
            "📚 **Bot Commands**\n\n"
            "**User Commands:**\n"
            "/start - Start the bot\n"
            "/help - Show help\n"
            "/whoami - Check your role\n"
            "/ping - Test bot\n"
            "/emergency - Emergency test\n"
            "/test - Diagnostic test\n"
            "/debug - Debug info\n"
            "/checkdb - Check database status\n"
            "/createme - Add yourself to database\n"
            "/fixdb - Diagnose database issues\n"
            "/testdb - Test database connection\n"
            "/emfix - Emergency fix (adds you with 9999 tokens)\n"
            "/login - Add account\n"
            "/accounts - Manage accounts\n"
            "/report - Start report\n"
            "/myreports - View reports\n"
            "/buy - Purchase tokens\n"
            "/balance - Check balance\n"
            "/contact - Contact support\n"
            "/freetokens - Get free test tokens\n\n"
            
            "**Admin Commands:**\n"
            "/admin - Admin panel\n"
            "/stats - Statistics\n"
            "/verify - Verify payments\n\n"
            
            "**Owner Commands:**\n"
            "/givetokens - Give tokens by user ID\n"
            "/addtokens - Add tokens by username/ID\n"
            "/tokenstats - View token statistics\n"
            "• Access Owner Panel for more features"
        )
        
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check user balance"""
        try:
            user_id = update.effective_user.id
            tokens = 0
            total_reports = 0
            role = await self.get_user_role(user_id)
            
            try:
                if self.is_db_connected():
                    user = await db.get_user(user_id)
                    if user:
                        tokens = getattr(user, 'tokens', 0)
                        total_reports = getattr(user, 'total_reports', 0)
            except Exception as e:
                logger.warning(f"Database error: {e}")
            
            balance_text = (
                f"💰 **Your Balance**\n\n"
                f"**Tokens:** `{tokens}`\n"
                f"**Reports Made:** `{total_reports}`\n"
                f"**Account Type:** `{role}`\n\n"
                f"Use /buy to purchase more tokens."
            )
            
            await update.message.reply_text(balance_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in balance: {e}")
    
    async def contact_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show contact information - FIXED VERSION"""
        try:
            contact_text = (
                "📞 **Contact Information**\n\n"
                f"**Admin:** @{config.CONTACT_INFO.get('admin_username', 'admin')}\n"
                f"**Owner:** @{config.CONTACT_INFO.get('owner_username', 'owner')}\n"
                f"**Support Group:** [Join]({config.CONTACT_INFO.get('support_group', 'https://t.me/support')})\n\n"
                "For urgent issues, please contact admin directly."
            )
            
            keyboard = [
                [InlineKeyboardButton("📢 Support Group", url=config.CONTACT_INFO.get('support_group', 'https://t.me/support'))],
                [InlineKeyboardButton("👤 Contact Admin", url=f"https://t.me/{config.CONTACT_INFO.get('admin_username', 'admin')}")],
                [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            if update.message:
                await update.message.reply_text(
                    contact_text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            elif update.callback_query:
                await update.callback_query.edit_message_text(
                    contact_text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            
        except Exception as e:
            logger.error(f"Error in contact command: {e}")
            try:
                error_msg = "❌ Error loading contact info. Please try again."
                if update.message:
                    await update.message.reply_text(error_msg)
                elif update.callback_query:
                    await update.callback_query.edit_message_text(error_msg)
            except:
                pass
    
    async def freetokens_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get free tokens for testing"""
        user_id = update.effective_user.id
        
        if not self.is_db_connected():
            await update.message.reply_text("❌ Database not connected.")
            return
        
        success = await db.update_user_tokens(user_id, 10)
        
        if success:
            await update.message.reply_text(
                f"✅ You received **10 free tokens** for testing!\n\n"
                f"Use /balance to check your balance.\n"
                f"Use /report to start reporting.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("❌ Could not add tokens.")
    
    async def handle_owner_messages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle owner feature messages"""
        if context.user_data.get('broadcast_mode'):
            await owner_handler.handle_broadcast_message(update, context)
        elif context.user_data.get('giveaway_step') == 'amount':
            await owner_handler.handle_giveaway_amount(update, context)
        elif context.user_data.get('giveaway_step') == 'winners':
            await owner_handler.handle_giveaway_winners(update, context)
        elif context.user_data.get('add_tokens'):
            await owner_handler.handle_add_tokens(update, context)
    
    async def menu_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle menu button callbacks - FIXED VERSION"""
        query = update.callback_query
        
        try:
            await query.answer()
            data = query.data
            user_id = update.effective_user.id
            
            logger.info(f"📱 Menu callback: {data} from user {user_id}")
            
            # Owner Panel
            if data == "menu_owner":
                is_owner = (user_id == config.SUPER_ADMIN_ID or user_id in config.OWNER_IDS)
                if not is_owner:
                    await query.edit_message_text("❌ Owner access only.")
                    return
                
                await query.edit_message_text("👑 Loading owner panel...")
                await owner_handler.owner_panel(update, context)
                return
            
            elif data == "owner_panel":
                await query.edit_message_text("👑 Loading owner panel...")
                await owner_handler.owner_panel(update, context)
                return
                
            elif data == "owner_broadcast":
                await query.edit_message_text("📢 Loading broadcast...")
                await owner_handler.broadcast_message(update, context)
                return
                
            elif data == "owner_giveaway":
                await query.edit_message_text("🎁 Loading giveaway...")
                await owner_handler.giveaway_setup(update, context)
                return
                
            elif data == "owner_add_tokens":
                await query.edit_message_text("💰 Loading token adder...")
                await owner_handler.add_tokens_to_user(update, context)
                return
                
            elif data == "owner_stats":
                await query.edit_message_text("📊 Loading stats...")
                await owner_handler.owner_stats(update, context)
                return
            
            # Admin Panel
            elif data == "menu_admin":
                is_admin = (user_id == config.SUPER_ADMIN_ID or 
                           user_id in config.OWNER_IDS or 
                           user_id in config.ADMIN_IDS)
                if not is_admin:
                    await query.edit_message_text("❌ No admin access.")
                    return
                
                await query.edit_message_text("👑 Loading admin panel...")
                await self.admin_handler.admin_panel(update, context)
                return
            
            # Regular buttons
            elif data == "menu_report":
                await query.edit_message_text("📝 Loading report...")
                await self.report_handler.start_report(update, context)
                return
            
            elif data == "menu_buy":
                await query.edit_message_text("💰 Loading packages...")
                await self.payment_handler.show_token_packages(update, context)
                return
            
            elif data == "menu_accounts":
                await query.edit_message_text("📱 Loading accounts...")
                await account_manager.show_accounts(update, context)
                return
            
            elif data == "menu_myreports":
                await query.edit_message_text("📊 Loading reports...")
                await self.report_handler.my_reports(update, context)
                return
            
            elif data == "menu_help":
                await query.edit_message_text("ℹ️ Loading help...")
                await self.help_command(update, context)
                return
            
            elif data == "menu_contact":
                await query.edit_message_text("📞 Loading contact...")
                await self.contact_command(update, context)
                return
            
            elif data == "back_to_main":
                await query.edit_message_text("👋 Returning to main menu...")
                await self.start(update, context)
                return
            
            else:
                logger.warning(f"Unknown callback: {data}")
                await query.edit_message_text("❓ Unknown button. Use /start")
                
        except Exception as e:
            logger.error(f"❌ Error in menu callback: {e}")
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ An error occurred. Please use /start"
                )
            except:
                pass
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors gracefully"""
        error = context.error
        
        if isinstance(error, Conflict):
            logger.debug("Conflict error ignored")
            return
            
        logger.error(f"Update {update} caused error {error}")
        logger.error(traceback.format_exc())
        
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
        
        logger.info(f"ADMIN_IDS: {config.ADMIN_IDS}")
        logger.info(f"OWNER_IDS: {config.OWNER_IDS}")
        logger.info(f"SUPER_ADMIN_ID: {config.SUPER_ADMIN_ID}")
        
        if config.MONGODB_URI:
            logger.info(f"MONGODB_URI: {config.MONGODB_URI[:50]}...")
        
        try:
            health_thread = threading.Thread(target=start_healthcheck_server, daemon=True)
            health_thread.start()
            logger.info("✅ Healthcheck thread started")
        except Exception as e:
            logger.error(f"Healthcheck error: {e}")
        
        # Connect to database
        for attempt in range(3):
            try:
                logger.info(f"DB attempt {attempt + 1}/3")
                connected = await db.connect()
                if connected:
                    self._db_connected = True
                    logger.info("✅ Database connected!")
                    break
            except Exception as e:
                logger.error(f"DB error: {e}")
                if attempt < 2:
                    await asyncio.sleep(3)
        
        logger.info("Bot initialization complete")
    
    async def post_shutdown(self, application: Application):
        """Run before bot shutdown"""
        logger.info("Bot is shutting down...")
        if db and db.client:
            db.client.close()
    
    def setup(self):
        """Setup bot handlers"""
        if not self.check_config():
            sys.exit(1)
        
        builder = Application.builder().token(config.BOT_TOKEN)
        builder.post_init(self.post_init)
        builder.post_shutdown(self.post_shutdown)
        
        self.application = builder.build()
        
        # Emergency command
        self.application.add_handler(CommandHandler("emergency", emergency_test))
        
        # Test commands
        self.application.add_handler(CommandHandler("ping", ping_command))
        self.application.add_handler(CommandHandler("test", test_command))
        self.application.add_handler(CommandHandler("debug", debug_command))
        
        # Database debug commands
        self.application.add_handler(CommandHandler("checkdb", checkdb_command))
        self.application.add_handler(CommandHandler("createme", create_me_command))
        self.application.add_handler(CommandHandler("fixdb", fixdb_command))
        self.application.add_handler(CommandHandler("testdb", testdb_command))
        self.application.add_handler(CommandHandler("emfix", self.emfix_command))
        
        # User commands
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("whoami", self.whoami_command))
        self.application.add_handler(CommandHandler("balance", self.balance_command))
        self.application.add_handler(CommandHandler("contact", self.contact_command))
        self.application.add_handler(CommandHandler("buy", self.payment_handler.show_token_packages))
        self.application.add_handler(CommandHandler("accounts", account_manager.show_accounts))
        self.application.add_handler(CommandHandler("myreports", self.report_handler.my_reports))
        self.application.add_handler(CommandHandler("givetokens", give_tokens_command))
        self.application.add_handler(CommandHandler("freetokens", self.freetokens_command))
        
        # Owner token management commands
        self.application.add_handler(CommandHandler("addtokens", owner_add_tokens_command))
        self.application.add_handler(CommandHandler("tokenstats", owner_token_stats_command))
        
        # Admin commands
        self.application.add_handler(CommandHandler("admin", self.admin_handler.admin_panel))
        self.application.add_handler(CommandHandler("stats", self.admin_handler.show_statistics))
        self.application.add_handler(CommandHandler("verify", self.payment_handler.admin_verify_payment))
        
        # Login conversation
        login_conv = ConversationHandler(
            entry_points=[CommandHandler('login', self.auth_handler.start_login)],
            states={
                PHONE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.auth_handler.handle_phone)],
                OTP_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.auth_handler.handle_otp)],
                TWO_FA_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.auth_handler.handle_2fa_password)],
                ACCOUNT_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.auth_handler.handle_account_name),
                    CommandHandler('skip', self.auth_handler.skip_account_name)
                ],
            },
            fallbacks=[CommandHandler('cancel', self.auth_handler.cancel_login)],
        )
        self.application.add_handler(login_conv)
        
        # Report conversation
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
        
        # Owner message handlers
        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            self.handle_owner_messages
        ))
        
        # Bulk token input handler
        self.application.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            handle_bulk_token_input
        ))
        
        # Callback query handlers - ORDER MATTERS!
        self.application.add_handler(CallbackQueryHandler(account_manager.handle_account_callback, pattern='^(add_account|refresh_accounts|manage_acc_|activate_acc_|deactivate_acc_|set_primary_|rename_acc_|delete_acc_|acc_reports_|confirm_delete_|back_accounts)$'))
        self.application.add_handler(CallbackQueryHandler(self.payment_handler.handle_package_selection, pattern='^(buy_stars_|buy_upi_|check_balance)$'))
        self.application.add_handler(CallbackQueryHandler(self.payment_handler.confirm_payment, pattern='^(confirm_stars_|confirm_upi_|cancel_payment)$'))
        self.application.add_handler(CallbackQueryHandler(self.admin_handler.handle_admin_callback, pattern='^admin_'))
        self.application.add_handler(CallbackQueryHandler(self.menu_callback, pattern='^menu_'))
        self.application.add_handler(CallbackQueryHandler(self.menu_callback, pattern='^owner_'))
        
        # Error handler
        self.application.add_error_handler(self.error_handler)
        
        logger.info("✅ Bot handlers setup complete")
    
    async def run(self):
        """Run the bot"""
        try:
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES,
                poll_interval=1.0,
                timeout=10
            )
            
            logger.info(f"✅ Bot is running. Press Ctrl+C to stop.")
            
            while True:
                await asyncio.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("Stopping bot...")
        except Exception as e:
            logger.error(f"Fatal error: {e}")
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