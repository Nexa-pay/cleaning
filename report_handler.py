import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from datetime import datetime
import re

from database import db
from models import UserRole, ReportStatus
import config
from utils import validate_target, parse_user_input, truncate_text

logger = logging.getLogger(__name__)

# Conversation states
(SELECT_ACCOUNT, REPORT_TYPE, REPORT_TARGET, REPORT_REASON, 
 REPORT_DETAILS, CONFIRMATION, ADMIN_TARGET, ADMIN_REASON) = range(10, 18)

# Report types
REPORT_TYPES = {
    'user': '👤 User',
    'group': '👥 Group', 
    'channel': '📢 Channel'
}

class ReportHandler:
    def __init__(self):
        self.temp_data = {}
    
    async def start_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start the report process"""
        user_id = update.effective_user.id
        user = await db.get_user(user_id)
        
        if not user:
            user = await db.create_user(
                user_id=user_id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name
            )
        
        # Check if user is blocked
        if user.is_blocked:
            await update.message.reply_text(
                "❌ **Account Blocked**\n\n"
                "Your account has been blocked. Please contact support for assistance.",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        # Check if user is admin/owner (free reporting)
        if user.role in [UserRole.ADMIN, UserRole.OWNER, UserRole.SUPER_ADMIN]:
            return await self.start_admin_report(update, context)
        
        # Check tokens for normal users
        if user.tokens < config.REPORT_COST_IN_TOKENS:
            keyboard = [
                [InlineKeyboardButton("💰 Buy Tokens", callback_data="menu_buy")],
                [InlineKeyboardButton("📞 Contact Support", url=f"https://t.me/{config.CONTACT_INFO['admin_username']}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"❌ **Insufficient Tokens**\n\n"
                f"You need **{config.REPORT_COST_IN_TOKENS} token(s)** to make a report.\n"
                f"Your balance: **{user.tokens} tokens**\n\n"
                f"Each report costs {config.REPORT_COST_IN_TOKENS} token.\n"
                f"Please purchase tokens to continue.",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        # Check if user has any accounts
        accounts = await db.get_user_accounts(user_id)
        active_accounts = [acc for acc in accounts if acc.status.value == "active"]
        
        if not active_accounts:
            keyboard = [
                [InlineKeyboardButton("➕ Add Account", callback_data="add_account")],
                [InlineKeyboardButton("📞 Contact Support", url=f"https://t.me/{config.CONTACT_INFO['admin_username']}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "❌ **No Active Accounts Found**\n\n"
                "You need to add a Telegram account to report.\n"
                "This keeps your main account safe.\n\n"
                "Use /login to add an account.",
                reply_markup=reply_markup
            )
            return ConversationHandler.END
        
        # Ask user to select account
        return await self.show_account_selection(update, context, user_id)
    
    async def show_account_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
        """Show available accounts for reporting"""
        accounts = await db.get_user_accounts(user_id)
        active_accounts = [acc for acc in accounts if acc.status.value == "active"]
        
        message = "📱 **Select Account to Report With**\n\n"
        message += "Choose which account you want to use for this report:\n\n"
        
        keyboard = []
        for acc in active_accounts:
            status = "⭐" if acc.is_primary else "📱"
            message += f"{status} **{acc.account_name}** - {acc.total_reports_used} reports\n"
            keyboard.append([
                InlineKeyboardButton(
                    f"{status} {acc.account_name}",
                    callback_data=f"select_acc_{acc.account_id}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("➕ Add New Account", callback_data="add_account")])
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_report")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.message:
            await update.message.reply_text(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await update.callback_query.edit_message_text(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        
        return SELECT_ACCOUNT
    
    async def handle_account_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle account selection"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data == "add_account":
            await query.edit_message_text(
                "📱 **Add Account**\n\n"
                "Use /login to add a new account.\n"
                "Then start /report again."
            )
            return ConversationHandler.END
        elif data == "cancel_report":
            await query.edit_message_text("❌ Report cancelled.")
            return ConversationHandler.END
        elif data.startswith("select_acc_"):
            account_id = data.replace("select_acc_", "")
            context.user_data['report_account_id'] = account_id
            
            # Show report type selection
            keyboard = [
                [InlineKeyboardButton(REPORT_TYPES['user'], callback_data='report_type_user')],
                [InlineKeyboardButton(REPORT_TYPES['group'], callback_data='report_type_group')],
                [InlineKeyboardButton(REPORT_TYPES['channel'], callback_data='report_type_channel')],
                [InlineKeyboardButton('❌ Cancel', callback_data='cancel_report')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "🔍 **What would you like to report?**\n\n"
                "Select the type of content you want to report:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            return REPORT_TYPE
    
    async def handle_report_type(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle report type selection"""
        query = update.callback_query
        await query.answer()
        
        if query.data == 'cancel_report':
            await query.edit_message_text("❌ Report cancelled.")
            return ConversationHandler.END
        
        report_type = query.data.replace('report_type_', '')
        context.user_data['report_type'] = report_type
        
        examples = {
            'user': "• Username: @username\n• User ID: 123456789\n• Profile link: https://t.me/username",
            'group': "• Group username: @groupname\n• Group link: https://t.me/groupname\n• Invite link: https://t.me/+abc123...",
            'channel': "• Channel username: @channelname\n• Channel link: https://t.me/channelname"
        }
        
        await query.edit_message_text(
            f"📝 **Reporting: {REPORT_TYPES[report_type]}**\n\n"
            f"Please send the username, link, or ID of the {report_type} you want to report.\n\n"
            f"**Examples:**\n{examples[report_type]}",
            parse_mode='Markdown'
        )
        
        return REPORT_TARGET
    
    async def handle_target(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle target input"""
        target = update.message.text.strip()
        
        if not validate_target(target):
            await update.message.reply_text(
                "❌ **Invalid Format**\n\n"
                "Please provide a valid username, link, or ID.\n\n"
                "**Valid formats:**\n"
                "• @username\n"
                "• https://t.me/username\n"
                "• https://t.me/+abc123...\n"
                "• 123456789 (numeric ID)\n\n"
                "Please try again:"
            )
            return REPORT_TARGET
        
        context.user_data['report_target'] = target
        
        # Get templates for reason selection
        templates = await db.get_templates()
        
        keyboard = []
        for template in templates[:5]:  # Show first 5 templates
            keyboard.append([
                InlineKeyboardButton(
                    f"📌 {template.name}",
                    callback_data=f"reason_template_{template.template_id}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("✏️ Custom Reason", callback_data="reason_custom")])
        keyboard.append([InlineKeyboardButton('❌ Cancel', callback_data='cancel_report')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "⚠️ **Select a reason for your report:**\n\n"
            "Choose a template or write your own reason:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        return REPORT_REASON
    
    async def handle_reason(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle reason selection"""
        query = update.callback_query
        await query.answer()
        
        if query.data == 'cancel_report':
            await query.edit_message_text("❌ Report cancelled.")
            return ConversationHandler.END
        
        if query.data == 'reason_custom':
            await query.edit_message_text(
                "✏️ **Custom Reason**\n\n"
                "Please type your reason for reporting:\n"
                f"Maximum {config.MAX_REPORT_LENGTH} characters.",
                parse_mode='Markdown'
            )
            return REPORT_DETAILS
        elif query.data.startswith('reason_template_'):
            template_id = query.data.replace('reason_template_', '')
            template = await db.get_template(template_id)
            if template:
                context.user_data['report_reason'] = template.content
                context.user_data['report_reason_name'] = template.name
            
            await query.edit_message_text(
                "📝 **Additional Details**\n\n"
                "Please provide any additional details or evidence:\n"
                "(Send /skip to continue without details)\n\n"
                f"**Reason template used:** {template.name if template else 'Selected'}"
            )
            return REPORT_DETAILS
    
    async def handle_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle additional details"""
        details = update.message.text.strip()
        
        if len(details) > config.MAX_REPORT_LENGTH:
            await update.message.reply_text(
                f"❌ Details too long. Maximum {config.MAX_REPORT_LENGTH} characters.\n"
                f"Current: {len(details)} characters.\n\n"
                "Please try again or use /skip."
            )
            return REPORT_DETAILS
        
        context.user_data['report_details'] = details
        return await self.confirm_report(update, context)
    
    async def skip_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Skip additional details"""
        context.user_data['report_details'] = "No additional details provided."
        await update.message.reply_text("⏩ Skipped additional details.")
        return await self.confirm_report(update, context)
    
    async def confirm_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show report summary for confirmation"""
        user_data = context.user_data
        user = await db.get_user(update.effective_user.id)
        
        # Get reason text
        reason_text = user_data.get('report_reason_name', 'Custom Reason')
        
        summary = (
            "📋 **Please confirm your report:**\n\n"
            f"**Type:** {REPORT_TYPES[user_data['report_type']]}\n"
            f"**Target:** `{user_data['report_target']}`\n"
            f"**Reason:** {reason_text}\n"
            f"**Details:** {truncate_text(user_data.get('report_details', ''), 200)}\n"
            f"**Cost:** {config.REPORT_COST_IN_TOKENS} token(s)\n"
            f"**Your Balance:** {user.tokens} tokens\n\n"
            f"Once confirmed, tokens will be deducted."
        )
        
        keyboard = [
            [
                InlineKeyboardButton('✅ Confirm', callback_data='confirm_report'),
                InlineKeyboardButton('❌ Cancel', callback_data='cancel_report')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.message:
            await update.message.reply_text(summary, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.callback_query.edit_message_text(summary, reply_markup=reply_markup, parse_mode='Markdown')
        
        return CONFIRMATION
    
    async def submit_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Submit the report"""
        query = update.callback_query
        await query.answer()
        
        if query.data == 'cancel_report':
            await query.edit_message_text("❌ Report cancelled.")
            return ConversationHandler.END
        
        user_id = update.effective_user.id
        user_data = context.user_data
        
        # Get account
        account = await db.get_account(user_data['report_account_id'])
        if not account:
            await query.edit_message_text("❌ Account not found. Please try again.")
            return ConversationHandler.END
        
        # Get reason
        reason = user_data.get('report_reason', 'Custom reason provided by user')
        
        # Get details
        details = user_data.get('report_details', 'No additional details')
        
        # Check tokens again
        user = await db.get_user(user_id)
        if user.role not in [UserRole.ADMIN, UserRole.OWNER, UserRole.SUPER_ADMIN]:
            if user.tokens < config.REPORT_COST_IN_TOKENS:
                await query.edit_message_text(
                    "❌ **Insufficient Tokens**\n\n"
                    "Your token balance changed. Please purchase more tokens.",
                    parse_mode='Markdown'
                )
                return ConversationHandler.END
            
            # Deduct tokens
            await db.update_user_tokens(user_id, -config.REPORT_COST_IN_TOKENS)
        
        # Create report
        report = await db.create_report(
            user_id=user_id,
            account_id=account.account_id,
            report_type=user_data['report_type'],
            target=user_data['report_target'],
            reason=reason,
            details=details,
            tokens_used=config.REPORT_COST_IN_TOKENS if user.role not in [UserRole.ADMIN, UserRole.OWNER, UserRole.SUPER_ADMIN] else 0
        )
        
        # Update user report count
        await db.add_report_count(user_id)
        
        # Send to report channel if configured
        if config.REPORT_CHANNEL_ID:
            try:
                report_text = (
                    f"🚨 **NEW REPORT**\n\n"
                    f"**Report ID:** `{report.report_id}`\n"
                    f"**User:** {update.effective_user.full_name} (ID: `{user_id}`)\n"
                    f"**Account:** {account.account_name}\n"
                    f"**Type:** {REPORT_TYPES[user_data['report_type']]}\n"
                    f"**Target:** `{user_data['report_target']}`\n"
                    f"**Reason:** {truncate_text(reason, 100)}\n"
                    f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                
                await context.bot.send_message(
                    chat_id=config.REPORT_CHANNEL_ID,
                    text=report_text,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Failed to send to report channel: {e}")
        
        # Send confirmation to user
        await query.edit_message_text(
            f"✅ **Report Submitted Successfully!**\n\n"
            f"**Report ID:** `{report.report_id}`\n"
            f"**Tokens Used:** {report.tokens_used}\n"
            f"**Status:** Pending Review\n\n"
            f"Thank you for helping keep Telegram safe.\n\n"
            f"Use /myreports to track your reports.\n"
            f"Need help? Contact @{config.CONTACT_INFO['admin_username']}",
            parse_mode='Markdown'
        )
        
        # Clear user data
        context.user_data.clear()
        
        return ConversationHandler.END
    
    async def start_admin_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin-specific report process (free, can target anything)"""
        await update.message.reply_text(
            "👑 **Admin Report Mode**\n\n"
            "You can report any user, group, or channel for free.\n\n"
            "Please send the username, link, or ID of the target:",
            parse_mode='Markdown'
        )
        
        return ADMIN_TARGET
    
    async def handle_admin_target(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle admin target input"""
        target = update.message.text.strip()
        
        if not validate_target(target):
            await update.message.reply_text(
                "❌ Invalid format. Please provide a valid username, link, or ID."
            )
            return ADMIN_TARGET
        
        context.user_data['admin_target'] = target
        
        await update.message.reply_text(
            "⚠️ **Enter report reason:**\n\n"
            "Please explain why you're reporting this target:",
            parse_mode='Markdown'
        )
        
        return ADMIN_REASON
    
    async def handle_admin_reason(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle admin reason input"""
        reason = update.message.text.strip()
        
        if len(reason) > config.MAX_REPORT_LENGTH:
            await update.message.reply_text(
                f"❌ Reason too long. Maximum {config.MAX_REPORT_LENGTH} characters."
            )
            return ADMIN_REASON
        
        user_id = update.effective_user.id
        target = context.user_data['admin_target']
        
        # Create admin report
        report = await db.create_report(
            user_id=user_id,
            account_id="admin",
            report_type="admin",
            target=target,
            reason=reason,
            details="Admin Report",
            tokens_used=0
        )
        
        # Send to report channel
        if config.REPORT_CHANNEL_ID:
            report_text = (
                f"👑 **ADMIN REPORT**\n\n"
                f"**Admin:** {update.effective_user.full_name}\n"
                f"**Target:** {target}\n"
                f"**Reason:** {reason}\n"
                f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            
            await context.bot.send_message(
                chat_id=config.REPORT_CHANNEL_ID,
                text=report_text,
                parse_mode='Markdown'
            )
        
        await update.message.reply_text(
            f"✅ **Admin Report Submitted**\n\n"
            f"Target: {target}\n"
            f"Report ID: `{report.report_id}`",
            parse_mode='Markdown'
        )
        
        context.user_data.clear()
        return ConversationHandler.END
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel the conversation"""
        await update.message.reply_text(
            "❌ Operation cancelled. Use /report to start over."
        )
        context.user_data.clear()
        return ConversationHandler.END
    
    async def my_reports(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user's reports"""
        user_id = update.effective_user.id
        page = 1
        
        if context.args and context.args[0].isdigit():
            page = int(context.args[0])
        
        reports = await db.get_user_reports(user_id, page)
        
        if not reports:
            keyboard = [[InlineKeyboardButton("📝 New Report", callback_data="menu_report")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "📊 **No Reports Found**\n\n"
                "You haven't made any reports yet.\n"
                "Use /report to get started!",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        
        message = f"📊 **Your Reports (Page {page})**\n\n"
        
        for report in reports:
            status_emoji = {
                ReportStatus.PENDING: "⏳",
                ReportStatus.REVIEWED: "👀",
                ReportStatus.RESOLVED: "✅",
                ReportStatus.REJECTED: "❌"
            }.get(report.status, "📝")
            
            date_str = report.created_at.strftime('%Y-%m-%d %H:%M')
            message += f"{status_emoji} **{report.report_type.upper()}** - {truncate_text(report.target, 30)}\n"
            message += f"   ID: `{report.report_id[:8]}...` | Status: {report.status.value}\n"
            message += f"   Time: {date_str}\n\n"
        
        # Add navigation buttons
        keyboard = []
        nav_buttons = []
        
        if page > 1:
            nav_buttons.append(InlineKeyboardButton("◀️ Previous", callback_data=f"reports_page_{page-1}"))
        nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"reports_page_{page+1}"))
        
        keyboard.append(nav_buttons)
        keyboard.append([InlineKeyboardButton("🆕 New Report", callback_data="menu_report")])
        keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')