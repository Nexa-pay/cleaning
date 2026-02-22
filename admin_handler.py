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
        user_id = update.effective_user.id
        user = await db.get_user(user_id)
        
        # Check if user is admin/owner
        if user.role not in [UserRole.ADMIN, UserRole.OWNER, UserRole.SUPER_ADMIN]:
            await update.message.reply_text("❌ **Unauthorized Access**\n\nThis area is for admins only.", parse_mode='Markdown')
            return
        
        # Get quick stats
        pending_count = await db.db.reports.count_documents({"status": ReportStatus.PENDING.value})
        user_count = await db.get_user_count()
        
        message = (
            f"👑 **Admin Control Panel**\n\n"
            f"**Welcome, {user.first_name}!**\n"
            f"**Your Role:** {user.role.value.upper()}\n\n"
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
            [InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings")]
        ]
        
        if user.role == UserRole.SUPER_ADMIN:
            keyboard.append([InlineKeyboardButton("👑 Super Admin", callback_data="admin_super")])
        
        keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.message:
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def handle_admin_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle admin panel callbacks"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
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
        elif data == "admin_super":
            await self.super_admin_panel(update, context)
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
        elif data == "admin_back":
            await self.admin_panel(update, context)
    
    async def show_pending_reports(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show pending reports for review"""
        query = update.callback_query
        
        reports = await db.get_pending_reports(limit=10)
        
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
            user = await db.get_user(report.user_id)
            username = user.username if user and user.username else f"User {report.user_id}"
            
            message += f"{i}. **ID:** `{report.report_id[:8]}...`\n"
            message += f"   **Type:** {report.report_type.upper()}\n"
            message += f"   **Target:** {truncate_text(report.target, 30)}\n"
            message += f"   **From:** {username}\n"
            message += f"   **Time:** {report.created_at.strftime('%H:%M %d/%m')}\n\n"
            
            keyboard.append([
                InlineKeyboardButton(
                    f"🔍 Review #{report.report_id[:8]}",
                    callback_data=f"review_{report.report_id}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data="admin_pending")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_back")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def review_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Review a specific report"""
        query = update.callback_query
        report_id = query.data.replace("review_", "")
        
        report = await db.get_report(report_id)
        if not report:
            await query.edit_message_text("❌ Report not found.")
            return
        
        user = await db.get_user(report.user_id)
        username = user.username if user and user.username else f"User {report.user_id}"
        
        message = (
            f"📋 **Report Review**\n\n"
            f"**Report ID:** `{report.report_id}`\n"
            f"**User:** {username} (ID: `{report.user_id}`)\n"
            f"**Account:** {report.account_id}\n"
            f"**Type:** {report.report_type.upper()}\n"
            f"**Target:** `{report.target}`\n"
            f"**Reason:** {report.reason}\n"
            f"**Details:** {report.details}\n"
            f"**Submitted:** {report.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"**Tokens Used:** {report.tokens_used}\n\n"
            f"**Actions:**"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Resolve", callback_data=f"resolve_{report_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{report_id}")
            ],
            [
                InlineKeyboardButton("👤 User Info", callback_data=f"user_info_{report.user_id}"),
                InlineKeyboardButton("🔙 Back to List", callback_data="admin_pending")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def resolve_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Resolve a report"""
        query = update.callback_query
        report_id = query.data.replace("resolve_", "")
        admin_id = update.effective_user.id
        
        await db.update_report_status(report_id, ReportStatus.RESOLVED, admin_id, "Report resolved by admin")
        
        # Notify user
        report = await db.get_report(report_id)
        if report:
            try:
                await context.bot.send_message(
                    chat_id=report.user_id,
                    text=(
                        f"✅ **Report Resolved**\n\n"
                        f"Your report (ID: `{report_id}`) has been resolved.\n"
                        f"Thank you for helping keep Telegram safe!"
                    ),
                    parse_mode='Markdown'
                )
            except:
                pass
        
        await query.edit_message_text(
            f"✅ **Report Resolved**\n\n"
            f"Report ID: `{report_id}`\n"
            f"Status updated to RESOLVED.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back to Pending", callback_data="admin_pending")
            ]]),
            parse_mode='Markdown'
        )
    
    async def reject_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Reject a report"""
        query = update.callback_query
        report_id = query.data.replace("reject_", "")
        admin_id = update.effective_user.id
        
        await db.update_report_status(report_id, ReportStatus.REJECTED, admin_id, "Report rejected by admin")
        
        # Notify user
        report = await db.get_report(report_id)
        if report:
            try:
                await context.bot.send_message(
                    chat_id=report.user_id,
                    text=(
                        f"❌ **Report Rejected**\n\n"
                        f"Your report (ID: `{report_id}`) has been reviewed and rejected.\n"
                        f"If you believe this is a mistake, please contact support."
                    ),
                    parse_mode='Markdown'
                )
            except:
                pass
        
        await query.edit_message_text(
            f"❌ **Report Rejected**\n\n"
            f"Report ID: `{report_id}`\n"
            f"Status updated to REJECTED.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back to Pending", callback_data="admin_pending")
            ]]),
            parse_mode='Markdown'
        )
    
    async def user_management(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User management interface"""
        query = update.callback_query
        
        # Get user stats
        total_users = await db.get_user_count()
        active_today = await db.db.users.count_documents({
            "last_active": {"$gte": datetime.now() - timedelta(days=1)}
        })
        blocked_users = await db.db.users.count_documents({"is_blocked": True})
        
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
    
    async def token_management(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Token management interface"""
        query = update.callback_query
        
        # Get token stats
        pipeline = [
            {"$match": {"status": "completed"}},
            {"$group": {"_id": None, "total": {"$sum": "$tokens_purchased"}}}
        ]
        result = await db.db.transactions.aggregate(pipeline).to_list(1)
        total_tokens = result[0]['total'] if result else 0
        
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
    
    async def show_statistics(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show bot statistics"""
        query = update.callback_query
        
        stats = await db.get_bot_stats()
        
        message = (
            f"📊 **Bot Statistics**\n\n"
            f"**👥 Users**\n"
            f"• Total: {stats['users']}\n"
            f"• With Accounts: {stats['accounts']['users_with_accounts']}\n\n"
            
            f"**📊 Reports**\n"
            f"• Total: {stats['reports']['total']}\n"
            f"• Pending: {stats['reports']['pending']}\n"
            f"• Resolved: {stats['reports']['resolved']}\n"
            f"• Today: {stats['reports']['today']}\n\n"
            
            f"**📱 Accounts**\n"
            f"• Total: {stats['accounts']['total']}\n"
            f"• Active: {stats['accounts']['active']}\n\n"
            
            f"**💰 Financial**\n"
            f"• Tokens Sold: {stats['total_tokens_sold']}\n"
            f"• Revenue: ₹{stats['total_revenue']}\n\n"
        )
        
        # Reports by type
        if stats['reports']['by_type']:
            message += "**Reports by Type:**\n"
            for type_name, count in stats['reports']['by_type'].items():
                message += f"• {type_name}: {count}\n"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data="admin_stats")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def bot_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Bot settings interface"""
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
            f"• Admin: @{config.CONTACT_INFO['admin_username']}\n"
            f"• Owner: @{config.CONTACT_INFO['owner_username']}\n"
            f"• Support: {config.CONTACT_INFO['support_group']}\n"
            f"• Channel: {config.CONTACT_INFO['channel']}\n\n"
            
            f"**Configuration** (in environment variables)"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def super_admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Super admin only panel"""
        query = update.callback_query
        user_id = update.effective_user.id
        
        if user_id != config.SUPER_ADMIN_ID:
            await query.edit_message_text("❌ **Super Admin Only**\n\nThis area is restricted to super admin.", parse_mode='Markdown')
            return
        
        message = "👑 **Super Admin Panel**\n\nExtra privileges:"
        
        keyboard = [
            [InlineKeyboardButton("👥 Manage Admins", callback_data="super_admins")],
            [InlineKeyboardButton("💰 System Balance", callback_data="super_balance")],
            [InlineKeyboardButton("📊 Full Analytics", callback_data="super_analytics")],
            [InlineKeyboardButton("⚙️ System Config", callback_data="super_config")],
            [InlineKeyboardButton("📝 View Logs", callback_data="super_logs")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def show_user_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show detailed user information"""
        query = update.callback_query
        user_id = int(query.data.replace("user_info_", ""))
        
        user = await db.get_user(user_id)
        if not user:
            await query.edit_message_text("❌ User not found.")
            return
        
        # Get user stats
        report_count = await db.db.reports.count_documents({"user_id": user_id})
        account_count = await db.db.accounts.count_documents({"user_id": user_id})
        transaction_count = await db.db.transactions.count_documents({"user_id": user_id, "status": "completed"})
        
        # Get last active
        last_active = user.last_active.strftime('%Y-%m-%d %H:%M') if user.last_active else "Never"
        
        message = (
            f"👤 **User Information**\n\n"
            f"**User ID:** `{user.user_id}`\n"
            f"**Username:** @{user.username if user.username else 'None'}\n"
            f"**Name:** {user.first_name} {user.last_name or ''}\n"
            f"**Role:** {user.role.value.upper()}\n"
            f"**Status:** {'🔴 Blocked' if user.is_blocked else '🟢 Active'}\n"
            f"**Joined:** {user.joined_date.strftime('%Y-%m-%d')}\n"
            f"**Last Active:** {last_active}\n\n"
            
            f"**Statistics:**\n"
            f"• Tokens: {user.tokens}\n"
            f"• Reports Made: {user.total_reports}\n"
            f"• Total Reports: {report_count}\n"
            f"• Accounts: {account_count}\n"
            f"• Transactions: {transaction_count}\n\n"
        )
        
        keyboard = []
        if user.is_blocked:
            keyboard.append([InlineKeyboardButton("🔓 Unblock User", callback_data=f"unblock_user_{user_id}")])
        else:
            keyboard.append([InlineKeyboardButton("🔒 Block User", callback_data=f"block_user_{user_id}")])
        
        keyboard.append([InlineKeyboardButton("➕ Add Tokens", callback_data=f"add_tokens_{user_id}")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_users")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def block_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Block a user"""
        query = update.callback_query
        user_id = int(query.data.replace("block_user_", ""))
        
        await db.block_user(user_id)
        
        await query.edit_message_text(
            f"✅ User `{user_id}` has been blocked.",
            parse_mode='Markdown'
        )
    
    async def unblock_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Unblock a user"""
        query = update.callback_query
        user_id = int(query.data.replace("unblock_user_", ""))
        
        await db.unblock_user(user_id)
        
        await query.edit_message_text(
            f"✅ User `{user_id}` has been unblocked.",
            parse_mode='Markdown'
        )
    
    async def add_tokens_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show menu to add tokens to user"""
        query = update.callback_query
        user_id = int(query.data.replace("add_tokens_", ""))
        
        context.user_data['token_user_id'] = user_id
        
        await query.edit_message_text(
            f"💰 **Add Tokens to User `{user_id}`**\n\n"
            f"Please enter the number of tokens to add:",
            parse_mode='Markdown'
        )
        
        # This would need a conversation handler in main bot