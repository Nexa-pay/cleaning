import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
import uuid

from database import db
from models import AccountStatus, UserRole
from utils import decrypt_data, encrypt_data, format_datetime, time_ago
import config

logger = logging.getLogger(__name__)

# Conversation states
(EDIT_NAME, CONFIRM_DELETE, ADD_NOTE) = range(20, 23)

class AccountManager:
    def __init__(self):
        self.temp_data = {}
    
    async def show_accounts(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Display all accounts for the user"""
        user_id = update.effective_user.id
        user = await db.get_user(user_id)
        
        if not user:
            user = await db.create_user(
                user_id=user_id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name
            )
        
        accounts = await db.get_user_accounts(user_id)
        
        if not accounts:
            keyboard = [
                [InlineKeyboardButton("➕ Add Account", callback_data="add_account")],
                [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = (
                "📱 **No Accounts Found**\n\n"
                "You haven't added any Telegram accounts yet.\n"
                "Add an account to start reporting!\n\n"
                "**Why add accounts?**\n"
                "• Keep your main account safe\n"
                "• Report multiple times\n"
                "• Switch between accounts easily"
            )
            
            if update.message:
                await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            else:
                await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            return
        
        # Create account list message
        message = f"📱 **Your Accounts**\n\n"
        message += f"Total: {len(accounts)}/{config.MAX_ACCOUNTS_PER_USER}\n\n"
        
        keyboard = []
        
        for i, acc in enumerate(accounts, 1):
            # Status emoji
            status_emoji = {
                AccountStatus.ACTIVE: "✅",
                AccountStatus.INACTIVE: "⭕",
                AccountStatus.SUSPENDED: "⚠️",
                AccountStatus.BANNED: "🚫"
            }.get(acc.status, "❓")
            
            # Primary indicator
            primary_star = "⭐ " if acc.is_primary else ""
            
            # Format phone number (hide middle digits)
            phone = acc.phone_number
            if len(phone) > 8:
                hidden_phone = phone[:4] + "****" + phone[-4:]
            else:
                hidden_phone = phone
            
            # Last used
            last_used = time_ago(acc.last_used) if acc.last_used else "Never"
            
            message += f"{i}. {status_emoji} {primary_star}**{acc.account_name}**\n"
            message += f"   📞 `{hidden_phone}`\n"
            message += f"   📊 Reports: {acc.total_reports_used} | Last: {last_used}\n\n"
            
            # Add button for this account
            keyboard.append([
                InlineKeyboardButton(
                    f"🔧 Manage {acc.account_name}",
                    callback_data=f"manage_acc_{acc.account_id}"
                )
            ])
        
        # Add global buttons
        keyboard.append([
            InlineKeyboardButton("➕ Add Account", callback_data="add_account"),
            InlineKeyboardButton("🔄 Refresh", callback_data="refresh_accounts")
        ])
        keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.message:
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def handle_account_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle account management callbacks"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data == "add_account":
            await query.edit_message_text(
                "📱 **Add New Account**\n\n"
                "To add a new Telegram account:\n"
                "1. Use /login command\n"
                "2. Follow the verification steps\n"
                "3. Your account will be added securely\n\n"
                "Your credentials are encrypted for safety.\n\n"
                "Click below to start:",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔐 Start Login", callback_data="start_login")
                ]])
            )
            return
        
        elif data == "start_login":
            await query.message.delete()
            context.user_data['from_accounts'] = True
            # This would trigger the login flow - in main bot, this is handled by the command
        
        elif data == "refresh_accounts":
            await self.show_accounts(update, context)
            return
        
        elif data.startswith("manage_acc_"):
            account_id = data.replace("manage_acc_", "")
            await self.show_account_details(update, context, account_id)
            return
    
    async def show_account_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE, account_id: str):
        """Show detailed account information"""
        query = update.callback_query
        
        account = await db.get_account(account_id)
        if not account:
            await query.edit_message_text("❌ Account not found.")
            return
        
        # Get user info
        user = await db.get_user(account.user_id)
        
        # Get recent reports from this account
        recent_reports = await db.db.reports.find(
            {"account_id": account_id}
        ).sort("created_at", -1).limit(3).to_list(length=3)
        
        # Format phone with full display
        phone = account.phone_number
        
        # Status color
        status_colors = {
            AccountStatus.ACTIVE: "🟢",
            AccountStatus.INACTIVE: "⚪",
            AccountStatus.SUSPENDED: "🟡",
            AccountStatus.BANNED: "🔴"
        }
        status_color = status_colors.get(account.status, "⚪")
        
        message = (
            f"📱 **Account Details**\n\n"
            f"**Name:** {account.account_name}\n"
            f"**Phone:** `{phone}`\n"
            f"**Status:** {status_color} {account.status.value.upper()}\n"
            f"**Primary:** {'Yes ⭐' if account.is_primary else 'No'}\n"
            f"**Added:** {format_datetime(account.added_date)}\n"
            f"**Last Used:** {format_datetime(account.last_used)}\n"
            f"**Total Reports:** {account.total_reports_used}\n"
            f"**Owner:** {user.first_name} (ID: `{user.user_id}`)\n\n"
        )
        
        if recent_reports:
            message += "**Recent Reports:**\n"
            for report in recent_reports[:3]:
                date_str = report['created_at'].strftime('%Y-%m-%d %H:%M')
                message += f"• {date_str}: {report['target'][:30]}... ({report['status']})\n"
        else:
            message += "**Recent Reports:** None\n"
        
        # Action buttons
        keyboard = []
        
        if account.status == AccountStatus.ACTIVE:
            keyboard.append([
                InlineKeyboardButton("⏸️ Deactivate", callback_data=f"deactivate_acc_{account_id}"),
                InlineKeyboardButton("⭐ Set Primary", callback_data=f"set_primary_{account_id}")
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("▶️ Activate", callback_data=f"activate_acc_{account_id}")
            ])
        
        keyboard.append([
            InlineKeyboardButton("✏️ Rename", callback_data=f"rename_acc_{account_id}"),
            InlineKeyboardButton("📊 Reports", callback_data=f"acc_reports_{account_id}")
        ])
        
        keyboard.append([
            InlineKeyboardButton("❌ Remove", callback_data=f"delete_acc_{account_id}"),
            InlineKeyboardButton("🔙 Back", callback_data="refresh_accounts")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def handle_account_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle account actions"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data.startswith("activate_acc_"):
            account_id = data.replace("activate_acc_", "")
            await db.update_account_status(account_id, AccountStatus.ACTIVE)
            await query.edit_message_text("✅ Account activated successfully!")
            await self.show_account_details(update, context, account_id)
        
        elif data.startswith("deactivate_acc_"):
            account_id = data.replace("deactivate_acc_", "")
            await db.update_account_status(account_id, AccountStatus.INACTIVE)
            await query.edit_message_text("⏸️ Account deactivated. It won't be used for reporting.")
            await self.show_account_details(update, context, account_id)
        
        elif data.startswith("set_primary_"):
            account_id = data.replace("set_primary_", "")
            user_id = update.effective_user.id
            await db.set_primary_account(user_id, account_id)
            await query.edit_message_text("⭐ Account set as primary! This account will be used by default.")
            await self.show_account_details(update, context, account_id)
        
        elif data.startswith("rename_acc_"):
            account_id = data.replace("rename_acc_", "")
            context.user_data['renaming_account'] = account_id
            await query.edit_message_text(
                "✏️ **Rename Account**\n\n"
                "Please enter a new name for this account (max 50 characters):",
                parse_mode='Markdown'
            )
            return EDIT_NAME
        
        elif data.startswith("delete_acc_"):
            account_id = data.replace("delete_acc_", "")
            context.user_data['deleting_account'] = account_id
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ Yes, Delete", callback_data=f"confirm_delete_{account_id}"),
                    InlineKeyboardButton("❌ No, Keep", callback_data=f"manage_acc_{account_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "⚠️ **Are you sure?**\n\n"
                "This will permanently remove this account.\n"
                "All associated data and session will be lost.\n\n"
                "This action cannot be undone!",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return CONFIRM_DELETE
        
        elif data.startswith("acc_reports_"):
            account_id = data.replace("acc_reports_", "")
            await self.show_account_reports(update, context, account_id)
    
    async def handle_rename(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle account renaming"""
        new_name = update.message.text.strip()
        account_id = context.user_data.get('renaming_account')
        
        if not account_id:
            await update.message.reply_text("❌ Session expired. Please try again.")
            return ConversationHandler.END
        
        if len(new_name) > 50:
            await update.message.reply_text("❌ Name too long. Maximum 50 characters.")
            return EDIT_NAME
        
        if len(new_name) < 3:
            await update.message.reply_text("❌ Name too short. Minimum 3 characters.")
            return EDIT_NAME
        
        # Update account name
        await db.db.accounts.update_one(
            {"account_id": account_id},
            {"$set": {"account_name": new_name}}
        )
        
        context.user_data.pop('renaming_account', None)
        
        await update.message.reply_text(f"✅ Account renamed to: **{new_name}**", parse_mode='Markdown')
        
        # Show updated account
        await self.show_account_details(update, context, account_id)
        return ConversationHandler.END
    
    async def handle_delete_confirmation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle account deletion confirmation"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data.startswith("confirm_delete_"):
            account_id = data.replace("confirm_delete_", "")
            
            # Delete account
            await db.db.accounts.delete_one({"account_id": account_id})
            
            # Delete associated sessions
            await db.db.sessions.delete_many({"account_id": account_id})
            
            await query.edit_message_text("✅ Account permanently deleted.")
            
            # Show remaining accounts
            await self.show_accounts(update, context)
        
        return ConversationHandler.END
    
    async def show_account_reports(self, update: Update, context: ContextTypes.DEFAULT_TYPE, account_id: str):
        """Show reports made with this account"""
        query = update.callback_query
        
        # Get account
        account = await db.get_account(account_id)
        if not account:
            await query.edit_message_text("❌ Account not found.")
            return
        
        # Get reports
        cursor = db.db.reports.find({"account_id": account_id}).sort("created_at", -1).limit(10)
        reports = await cursor.to_list(length=10)
        
        if not reports:
            message = f"📊 **Reports from {account.account_name}**\n\nNo reports found with this account."
        else:
            message = f"📊 **Recent Reports from {account.account_name}**\n\n"
            
            for report in reports:
                status_emoji = {
                    "pending": "⏳",
                    "reviewed": "👀",
                    "resolved": "✅",
                    "rejected": "❌"
                }.get(report['status'], "📝")
                
                date_str = report['created_at'].strftime('%Y-%m-%d %H:%M')
                message += f"{status_emoji} **{report['report_type'].upper()}**\n"
                message += f"   Target: {report['target'][:50]}\n"
                message += f"   Time: {date_str}\n"
                message += f"   ID: `{report['report_id'][:8]}...`\n\n"
        
        keyboard = [
            [InlineKeyboardButton("🔙 Back to Account", callback_data=f"manage_acc_{account_id}")],
            [InlineKeyboardButton("📋 All Accounts", callback_data="refresh_accounts")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def account_status_check(self, user_id: int) -> bool:
        """Check if user has active accounts"""
        accounts = await db.get_user_accounts(user_id)
        active_accounts = [acc for acc in accounts if acc.status == AccountStatus.ACTIVE]
        return len(active_accounts) > 0
    
    async def get_active_account(self, user_id: int):
        """Get primary or first active account"""
        accounts = await db.get_user_accounts(user_id)
        
        # Return primary account first
        for acc in accounts:
            if acc.is_primary and acc.status == AccountStatus.ACTIVE:
                return acc
        
        # Return first active account
        for acc in accounts:
            if acc.status == AccountStatus.ACTIVE:
                return acc
        
        return None
    
    async def account_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show account statistics (admin only)"""
        user_id = update.effective_user.id
        user = await db.get_user(user_id)
        
        if user.role not in [UserRole.ADMIN, UserRole.OWNER, UserRole.SUPER_ADMIN]:
            await update.message.reply_text("❌ Unauthorized.")
            return
        
        # Get stats
        stats = await db.get_account_stats()
        
        # Get top users by accounts
        pipeline = [
            {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 5}
        ]
        top_users = await db.db.accounts.aggregate(pipeline).to_list(length=5)
        
        message = (
            f"📊 **Account Statistics**\n\n"
            f"**Total Accounts:** {stats['total']}\n"
            f"**Active Accounts:** {stats['active']}\n"
            f"**Users with Accounts:** {stats['users_with_accounts']}\n\n"
            f"**Top Users:**\n"
        )
        
        for i, user_stat in enumerate(top_users, 1):
            user_info = await db.get_user(user_stat['_id'])
            username = user_info.username if user_info and user_info.username else f"User {user_stat['_id']}"
            message += f"{i}. {username}: {user_stat['count']} accounts\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')

# Global account manager instance
account_manager = AccountManager()