import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from datetime import datetime, timedelta

from database import db
from models import UserRole, ReportStatus, AccountStatus
import config
from utils import format_number, truncate_text

logger = logging.getLogger(__name__)

class AdminHandler:
    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show admin panel"""
        try:
            user_id = update.effective_user.id
            
            # Check if user is admin/owner directly from config
            is_admin = (user_id == config.SUPER_ADMIN_ID or 
                       user_id in config.OWNER_IDS or 
                       user_id in config.ADMIN_IDS)
            
            if not is_admin:
                await update.effective_message.reply_text("❌ **Unauthorized Access**\n\nThis area is for admins only.", parse_mode='Markdown')
                return
            
            # Get user role for display (don't use database)
            role = "ADMIN"
            if user_id in config.OWNER_IDS:
                role = "OWNER"
            if user_id == config.SUPER_ADMIN_ID:
                role = "SUPER ADMIN"
            
            # Get quick stats from database with error handling
            try:
                if db and db.db:
                    pending_count = await db.db.reports.count_documents({"status": "pending"})
                    user_count = await db.get_user_count()
                else:
                    pending_count = 0
                    user_count = 0
            except Exception as e:
                logger.error(f"Error getting stats: {e}")
                pending_count = 0
                user_count = 0
            
            message = (
                f"👑 **Admin Control Panel**\n\n"
                f"**Welcome!**\n"
                f"**Your Role:** {role}\n"
                f"**User ID:** `{user_id}`\n\n"
                f"📊 **Quick Stats:**\n"
                f"• Total Users: {user_count}\n"
                f"• Pending Reports: {pending_count}\n\n"
                f"**Select an option below:**"
            )
            
            keyboard = [
                [InlineKeyboardButton("📋 Pending Reports", callback_data="admin_pending")],
                [InlineKeyboardButton("👥 User Management", callback_data="admin_users")],
                [InlineKeyboardButton("💰 Token Management", callback_data="admin_tokens")],
                [InlineKeyboardButton("📈 Statistics", callback_data="admin_stats")],
                [InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings")],
                [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Check if this is a callback query or direct message
            if update.callback_query:
                await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            else:
                await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
                
        except Exception as e:
            logger.error(f"Error in admin_panel: {e}", exc_info=True)
            try:
                await update.effective_message.reply_text(
                    "❌ An error occurred opening admin panel.\n"
                    "Please try again or use /start"
                )
            except:
                pass
    
    async def handle_admin_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle admin panel callbacks"""
        try:
            query = update.callback_query
            await query.answer()
            
            data = query.data
            user_id = update.effective_user.id
            
            logger.info(f"Admin callback: {data} from user {user_id}")
            
            # Verify admin access for all admin callbacks
            is_admin = (user_id == config.SUPER_ADMIN_ID or 
                       user_id in config.OWNER_IDS or 
                       user_id in config.ADMIN_IDS)
            
            if not is_admin:
                await query.edit_message_text("❌ Unauthorized access.")
                return
            
            if data == "admin_pending":
                await self.show_pending_reports(update, context)
            elif data == "admin_users":
                await self.user_management(update, context)
            elif data == "admin_tokens":
                await self.token_management(update, context)
            elif data == "admin_stats":
                await self.show_statistics(update, context)
            elif data == "admin_settings":
                await self.bot_settings(update, context)
            elif data == "admin_back":
                await self.admin_panel(update, context)
            elif data.startswith("review_"):
                await self.review_report(update, context)
            elif data.startswith("resolve_"):
                await self.resolve_report(update, context)
            elif data.startswith("reject_"):
                await self.reject_report(update, context)
            elif data.startswith("user_info_"):
                await self.show_user_info(update, context)
            elif data.startswith("block_user_"):
                await self.block_user(update, context)
            elif data.startswith("unblock_user_"):
                await self.unblock_user(update, context)
            elif data.startswith("add_tokens_"):
                await self.add_tokens_menu(update, context)
            else:
                await query.edit_message_text(f"Unknown action: {data}")
                
        except Exception as e:
            logger.error(f"Error in admin callback: {e}", exc_info=True)
    
    async def show_pending_reports(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show pending reports for review"""
        try:
            query = update.callback_query
            
            # Get pending reports from database
            reports = []
            try:
                if db and db.db:
                    cursor = db.db.reports.find({"status": "pending"}).sort("created_at", -1).limit(10)
                    reports = await cursor.to_list(length=10)
            except Exception as e:
                logger.error(f"Error fetching reports: {e}")
            
            if not reports:
                await query.edit_message_text(
                    "✅ **No Pending Reports**\n\n"
                    "All reports have been reviewed.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back", callback_data="admin_back")
                    ]]),
                    parse_mode='Markdown'
                )
                return
            
            message = "📋 **Pending Reports**\n\n"
            keyboard = []
            
            for i, report in enumerate(reports[:5], 1):
                report_id = report.get('report_id', 'Unknown')[:8]
                report_type = report.get('report_type', 'unknown')
                target = truncate_text(report.get('target', 'unknown'), 30)
                created = report.get('created_at', datetime.now())
                time_str = created.strftime('%H:%M %d/%m') if hasattr(created, 'strftime') else 'Unknown'
                
                message += f"{i}. **ID:** `{report_id}...`\n"
                message += f"   **Type:** {report_type.upper()}\n"
                message += f"   **Target:** {target}\n"
                message += f"   **Time:** {time_str}\n\n"
                
                keyboard.append([
                    InlineKeyboardButton(
                        f"🔍 Review #{report_id}",
                        callback_data=f"review_{report.get('report_id')}"
                    )
                ])
            
            keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data="admin_pending")])
            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_back")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in show_pending_reports: {e}")
    
    async def review_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Review a specific report"""
        try:
            query = update.callback_query
            report_id = query.data.replace("review_", "")
            
            # Get report from database
            report = None
            try:
                if db and db.db:
                    report = await db.db.reports.find_one({"report_id": report_id})
            except Exception as e:
                logger.error(f"Error fetching report: {e}")
            
            if not report:
                await query.edit_message_text("❌ Report not found.")
                return
            
            message = (
                f"📋 **Report Review**\n\n"
                f"**Report ID:** `{report_id}`\n"
                f"**User ID:** `{report.get('user_id', 'Unknown')}`\n"
                f"**Type:** {report.get('report_type', 'Unknown').upper()}\n"
                f"**Target:** `{report.get('target', 'Unknown')}`\n"
                f"**Reason:** {report.get('reason', 'No reason')}\n"
                f"**Details:** {report.get('details', 'No details')}\n"
                f"**Submitted:** {report.get('created_at', 'Unknown')}\n\n"
                f"**Actions:**"
            )
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ Resolve", callback_data=f"resolve_{report_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_{report_id}")
                ],
                [
                    InlineKeyboardButton("👤 User Info", callback_data=f"user_info_{report.get('user_id')}"),
                    InlineKeyboardButton("🔙 Back to List", callback_data="admin_pending")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in review_report: {e}")
    
    async def resolve_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Resolve a report"""
        try:
            query = update.callback_query
            report_id = query.data.replace("resolve_", "")
            admin_id = update.effective_user.id
            
            # Update report status
            try:
                if db and db.db:
                    await db.db.reports.update_one(
                        {"report_id": report_id},
                        {"$set": {"status": "resolved", "reviewed_by": admin_id, "reviewed_at": datetime.now()}}
                    )
            except Exception as e:
                logger.error(f"Error updating report: {e}")
            
            await query.edit_message_text(
                f"✅ **Report Resolved**\n\n"
                f"Report ID: `{report_id}`\n"
                f"Status updated to RESOLVED.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back to Pending", callback_data="admin_pending")
                ]]),
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error in resolve_report: {e}")
    
    async def reject_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Reject a report"""
        try:
            query = update.callback_query
            report_id = query.data.replace("reject_", "")
            admin_id = update.effective_user.id
            
            # Update report status
            try:
                if db and db.db:
                    await db.db.reports.update_one(
                        {"report_id": report_id},
                        {"$set": {"status": "rejected", "reviewed_by": admin_id, "reviewed_at": datetime.now()}}
                    )
            except Exception as e:
                logger.error(f"Error updating report: {e}")
            
            await query.edit_message_text(
                f"❌ **Report Rejected**\n\n"
                f"Report ID: `{report_id}`\n"
                f"Status updated to REJECTED.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back to Pending", callback_data="admin_pending")
                ]]),
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error in reject_report: {e}")
    
    async def user_management(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User management interface"""
        try:
            query = update.callback_query
            
            # Get user stats
            total_users = 0
            active_today = 0
            blocked_users = 0
            
            try:
                if db and db.db:
                    total_users = await db.db.users.count_documents({})
                    active_today = await db.db.users.count_documents({
                        "last_active": {"$gte": datetime.now() - timedelta(days=1)}
                    })
                    blocked_users = await db.db.users.count_documents({"is_blocked": True})
            except Exception as e:
                logger.error(f"Error getting user stats: {e}")
            
            message = (
                f"👥 **User Management**\n\n"
                f"**Total Users:** {total_users}\n"
                f"**Active Today:** {active_today}\n"
                f"**Blocked Users:** {blocked_users}\n\n"
                f"**Options:**"
            )
            
            keyboard = [
                [InlineKeyboardButton("📋 List Users", callback_data="list_users")],
                [InlineKeyboardButton("🔍 Search User", callback_data="search_user")],
                [InlineKeyboardButton("👑 Manage Admins", callback_data="manage_admins")],
                [InlineKeyboardButton("🚫 Blocked Users", callback_data="blocked_users")],
                [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in user_management: {e}")
    
    async def token_management(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Token management interface"""
        try:
            query = update.callback_query
            
            # Get token stats
            total_tokens = 0
            
            try:
                if db and db.db:
                    pipeline = [
                        {"$match": {"status": "completed"}},
                        {"$group": {"_id": None, "total": {"$sum": "$tokens_purchased"}}}
                    ]
                    result = await db.db.transactions.aggregate(pipeline).to_list(1)
                    total_tokens = result[0]['total'] if result else 0
            except Exception as e:
                logger.error(f"Error getting token stats: {e}")
            
            message = (
                f"💰 **Token Management**\n\n"
                f"**Total Tokens Sold:** {total_tokens}\n"
                f"**Token Price:** ⭐{config.TOKEN_PRICE_STARS} / ₹{config.TOKEN_PRICE_INR}\n"
                f"**Report Cost:** {config.REPORT_COST_IN_TOKENS} tokens\n\n"
                f"**Select an option:**"
            )
            
            keyboard = [
                [InlineKeyboardButton("➕ Add Tokens to User", callback_data="add_tokens_menu")],
                [InlineKeyboardButton("📊 Token Packages", callback_data="manage_packages")],
                [InlineKeyboardButton("📈 Transaction History", callback_data="transaction_history")],
                [InlineKeyboardButton("⏳ Pending Payments", callback_data="pending_payments")],
                [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in token_management: {e}")
    
    async def show_statistics(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show bot statistics"""
        try:
            query = update.callback_query
            
            # Get stats from database
            total_users = 0
            total_reports = 0
            pending_reports = 0
            
            try:
                if db and db.db:
                    total_users = await db.db.users.count_documents({})
                    total_reports = await db.db.reports.count_documents({})
                    pending_reports = await db.db.reports.count_documents({"status": "pending"})
            except Exception as e:
                logger.error(f"Error getting stats: {e}")
            
            message = (
                f"📊 **Bot Statistics**\n\n"
                f"**👥 Users**\n"
                f"• Total: {total_users}\n\n"
                f"**📊 Reports**\n"
                f"• Total: {total_reports}\n"
                f"• Pending: {pending_reports}\n\n"
                f"**💰 Financial**\n"
                f"• Coming soon..."
            )
            
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh", callback_data="admin_stats")],
                [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in show_statistics: {e}")
    
    async def bot_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Bot settings interface"""
        try:
            query = update.callback_query
            
            message = (
                f"⚙️ **Bot Settings**\n\n"
                f"**Token System:**\n"
                f"• Token Price: ⭐{config.TOKEN_PRICE_STARS} / ₹{config.TOKEN_PRICE_INR}\n"
                f"• Report Cost: {config.REPORT_COST_IN_TOKENS} tokens\n"
                f"• Free Reports: {config.FREE_REPORTS_FOR_NEW_USERS}\n\n"
                
                f"**Account Settings:**\n"
                f"• Max Accounts/User: {config.MAX_ACCOUNTS_PER_USER}\n"
                f"• Session Timeout: {config.SESSION_TIMEOUT//3600}h\n\n"
                
                f"**Contact Info:**\n"
                f"• Admin: @{config.CONTACT_INFO.get('admin_username', 'admin')}\n"
                f"• Owner: @{config.CONTACT_INFO.get('owner_username', 'owner')}\n"
                f"• Support: {config.CONTACT_INFO.get('support_group', 'N/A')}\n\n"
                
                f"**Configuration** (in environment variables)"
            )
            
            keyboard = [
                [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in bot_settings: {e}")
    
    async def show_user_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user information"""
        try:
            query = update.callback_query
            user_id = int(query.data.replace("user_info_", ""))
            
            # Get user from database
            user_data = None
            try:
                if db and db.db:
                    user_data = await db.db.users.find_one({"user_id": user_id})
            except Exception as e:
                logger.error(f"Error fetching user: {e}")
            
            if not user_data:
                await query.edit_message_text("❌ User not found.")
                return
            
            message = (
                f"👤 **User Information**\n\n"
                f"**User ID:** `{user_id}`\n"
                f"**Username:** @{user_data.get('username', 'None')}\n"
                f"**Name:** {user_data.get('first_name', '')} {user_data.get('last_name', '')}\n"
                f"**Role:** {user_data.get('role', 'normal').upper()}\n"
                f"**Status:** {'🔴 Blocked' if user_data.get('is_blocked') else '🟢 Active'}\n"
                f"**Joined:** {user_data.get('joined_date', 'Unknown')}\n\n"
                
                f"**Statistics:**\n"
                f"• Tokens: {user_data.get('tokens', 0)}\n"
                f"• Reports: {user_data.get('total_reports', 0)}\n"
            )
            
            keyboard = [
                [InlineKeyboardButton("🔙 Back", callback_data="admin_users")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in show_user_info: {e}")
    
    async def block_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Block a user"""
        try:
            query = update.callback_query
            user_id = int(query.data.replace("block_user_", ""))
            
            try:
                if db and db.db:
                    await db.db.users.update_one(
                        {"user_id": user_id},
                        {"$set": {"is_blocked": True}}
                    )
            except Exception as e:
                logger.error(f"Error blocking user: {e}")
            
            await query.edit_message_text(
                f"✅ User `{user_id}` has been blocked.",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error in block_user: {e}")
    
    async def unblock_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Unblock a user"""
        try:
            query = update.callback_query
            user_id = int(query.data.replace("unblock_user_", ""))
            
            try:
                if db and db.db:
                    await db.db.users.update_one(
                        {"user_id": user_id},
                        {"$set": {"is_blocked": False}}
                    )
            except Exception as e:
                logger.error(f"Error unblocking user: {e}")
            
            await query.edit_message_text(
                f"✅ User `{user_id}` has been unblocked.",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error in unblock_user: {e}")
    
    async def add_tokens_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show menu to add tokens to user"""
        try:
            query = update.callback_query
            user_id = int(query.data.replace("add_tokens_", ""))
            
            context.user_data['token_user_id'] = user_id
            
            await query.edit_message_text(
                f"💰 **Add Tokens to User `{user_id}`**\n\n"
                f"Please enter the number of tokens to add:",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error in add_tokens_menu: {e}")