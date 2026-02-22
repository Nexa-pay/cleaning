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
        """Show admin panel - FIXED VERSION"""
        try:
            user_id = update.effective_user.id
            
            # Check if user is admin/owner directly from config
            is_admin = (user_id == config.SUPER_ADMIN_ID or 
                       user_id in config.OWNER_IDS or 
                       user_id in config.ADMIN_IDS)
            
            if not is_admin:
                if update.callback_query:
                    await update.callback_query.edit_message_text("❌ **Unauthorized Access**\n\nThis area is for admins only.", parse_mode='Markdown')
                else:
                    await update.message.reply_text("❌ **Unauthorized Access**\n\nThis area is for admins only.", parse_mode='Markdown')
                return
            
            # Get user role for display
            role = "ADMIN"
            if user_id in config.OWNER_IDS:
                role = "OWNER"
            if user_id == config.SUPER_ADMIN_ID:
                role = "SUPER ADMIN"
            
            # Get quick stats from database with error handling
            pending_count = 0
            user_count = 0
            
            try:
                if db and db.db is not None:
                    pending_count = await db.db.reports.count_documents({"status": "pending"})
                    user_count = await db.get_user_count()
            except Exception as e:
                logger.error(f"Error getting stats: {e}")
            
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
            
            # Handle both callback queries and direct messages
            if update.callback_query:
                try:
                    await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
                except Exception as e:
                    logger.error(f"Error editing message: {e}")
                    # If edit fails, send new message
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=message,
                        reply_markup=reply_markup,
                        parse_mode='Markdown'
                    )
            else:
                await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
                
        except Exception as e:
            logger.error(f"Error in admin_panel: {e}", exc_info=True)
            try:
                error_msg = "❌ An error occurred opening admin panel.\nPlease try again or use /start"
                if update.callback_query:
                    await update.callback_query.edit_message_text(error_msg)
                else:
                    await update.message.reply_text(error_msg)
            except:
                pass
    
    async def handle_admin_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle admin panel callbacks - FIXED VERSION"""
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
            
            # Show loading message
            await query.edit_message_text("⏳ Loading...")
            
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
            elif data == "bulk_add_tokens":
                await self.bulk_add_tokens(update, context)
            elif data == "token_stats":
                await self.token_stats(update, context)
            elif data == "token_transactions":
                await self.token_transactions(update, context)
            elif data == "pending_payments":
                await self.pending_payments(update, context)
            elif data == "manage_packages":
                await self.manage_packages(update, context)
            else:
                await query.edit_message_text(f"❓ Unknown action: {data}")
                
        except Exception as e:
            logger.error(f"Error in admin callback: {e}", exc_info=True)
            try:
                await update.callback_query.edit_message_text(
                    "❌ An error occurred. Please try again."
                )
            except:
                pass
    
    async def show_pending_reports(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show pending reports for review"""
        try:
            query = update.callback_query
            
            # Get pending reports from database
            reports = []
            try:
                if db and db.db is not None:
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
            await query.edit_message_text("❌ Error loading reports. Please try again.")
    
    async def review_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Review a specific report"""
        try:
            query = update.callback_query
            report_id = query.data.replace("review_", "")
            
            # Get report from database
            report = None
            try:
                if db and db.db is not None:
                    report = await db.db.reports.find_one({"report_id": report_id})
            except Exception as e:
                logger.error(f"Error fetching report: {e}")
            
            if not report:
                await query.edit_message_text("❌ Report not found.")
                return
            
            # Get user info
            user_id = report.get('user_id', 'Unknown')
            username = "Unknown"
            try:
                if db and db.db is not None:
                    user = await db.db.users.find_one({"user_id": user_id})
                    if user:
                        username = user.get('username', 'Unknown') or 'Unknown'
            except:
                pass
            
            message = (
                f"📋 **Report Review**\n\n"
                f"**Report ID:** `{report_id}`\n"
                f"**User:** {username} (ID: `{user_id}`)\n"
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
                    InlineKeyboardButton("👤 User Info", callback_data=f"user_info_{user_id}"),
                    InlineKeyboardButton("🔙 Back", callback_data="admin_pending")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in review_report: {e}")
            await query.edit_message_text("❌ Error loading report. Please try again.")
    
    async def resolve_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Resolve a report"""
        try:
            query = update.callback_query
            report_id = query.data.replace("resolve_", "")
            admin_id = update.effective_user.id
            
            # Update report status
            success = False
            try:
                if db and db.db is not None:
                    result = await db.db.reports.update_one(
                        {"report_id": report_id},
                        {"$set": {"status": "resolved", "reviewed_by": admin_id, "reviewed_at": datetime.now()}}
                    )
                    success = result.modified_count > 0
            except Exception as e:
                logger.error(f"Error updating report: {e}")
            
            if success:
                await query.edit_message_text(
                    f"✅ **Report Resolved**\n\n"
                    f"Report ID: `{report_id}`\n"
                    f"Status updated to RESOLVED.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back to Pending", callback_data="admin_pending")
                    ]]),
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text(
                    f"❌ Failed to resolve report.\n"
                    f"Report ID: `{report_id}`",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back", callback_data="admin_pending")
                    ]]),
                    parse_mode='Markdown'
                )
        except Exception as e:
            logger.error(f"Error in resolve_report: {e}")
            await query.edit_message_text("❌ Error resolving report.")
    
    async def reject_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Reject a report"""
        try:
            query = update.callback_query
            report_id = query.data.replace("reject_", "")
            admin_id = update.effective_user.id
            
            # Update report status
            success = False
            try:
                if db and db.db is not None:
                    result = await db.db.reports.update_one(
                        {"report_id": report_id},
                        {"$set": {"status": "rejected", "reviewed_by": admin_id, "reviewed_at": datetime.now()}}
                    )
                    success = result.modified_count > 0
            except Exception as e:
                logger.error(f"Error updating report: {e}")
            
            if success:
                await query.edit_message_text(
                    f"❌ **Report Rejected**\n\n"
                    f"Report ID: `{report_id}`\n"
                    f"Status updated to REJECTED.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back to Pending", callback_data="admin_pending")
                    ]]),
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text(
                    f"❌ Failed to reject report.\n"
                    f"Report ID: `{report_id}`",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back", callback_data="admin_pending")
                    ]]),
                    parse_mode='Markdown'
                )
        except Exception as e:
            logger.error(f"Error in reject_report: {e}")
            await query.edit_message_text("❌ Error rejecting report.")
    
    async def user_management(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """User management interface"""
        try:
            query = update.callback_query
            
            # Get user stats
            total_users = 0
            active_today = 0
            blocked_users = 0
            
            try:
                if db and db.db is not None:
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
            await query.edit_message_text("❌ Error loading user management.")
    
    # ========== TOKEN MANAGEMENT METHODS ==========
    
    async def token_management(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Enhanced token management interface"""
        try:
            query = update.callback_query
            
            # Get token stats
            total_tokens = 0
            pending_count = 0
            total_transactions = 0
            
            try:
                if db and db.db is not None:
                    pipeline = [
                        {"$match": {"status": "completed"}},
                        {"$group": {"_id": None, "total": {"$sum": "$tokens_purchased"}}}
                    ]
                    result = await db.db.transactions.aggregate(pipeline).to_list(1)
                    total_tokens = result[0]['total'] if result else 0
                    
                    pending_count = await db.db.transactions.count_documents({"status": "pending"})
                    total_transactions = await db.db.transactions.count_documents({})
            except Exception as e:
                logger.error(f"Error getting token stats: {e}")
            
            message = (
                f"💰 **Token Management**\n\n"
                f"**Total Tokens Issued:** {total_tokens}\n"
                f"**Pending Payments:** {pending_count}\n"
                f"**Total Transactions:** {total_transactions}\n"
                f"**Token Price:** ⭐{config.TOKEN_PRICE_STARS} / ₹{config.TOKEN_PRICE_INR}\n"
                f"**Report Cost:** {config.REPORT_COST_IN_TOKENS} tokens\n\n"
                f"**Select an option:**"
            )
            
            keyboard = [
                [InlineKeyboardButton("➕ Add Tokens to User", callback_data="add_tokens_menu")],
                [InlineKeyboardButton("📊 Bulk Add Tokens", callback_data="bulk_add_tokens")],
                [InlineKeyboardButton("📈 Token Statistics", callback_data="token_stats")],
                [InlineKeyboardButton("📋 Transaction History", callback_data="token_transactions")],
                [InlineKeyboardButton("⏳ Pending Payments", callback_data="pending_payments")],
                [InlineKeyboardButton("📦 Manage Packages", callback_data="manage_packages")],
                [InlineKeyboardButton("🔙 Back", callback_data="admin_back")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error in token_management: {e}")
            await query.edit_message_text("❌ Error loading token management.")
    
    async def add_tokens_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show menu to add tokens to user"""
        try:
            query = update.callback_query
            await query.answer()
            
            # Check if this is called from user info or main menu
            if query.data.startswith("add_tokens_"):
                user_id = int(query.data.replace("add_tokens_", ""))
                context.user_data['token_user_id'] = user_id
                
                await query.edit_message_text(
                    f"💰 **Add Tokens to User `{user_id}`**\n\n"
                    f"Please enter the number of tokens to add:\n"
                    f"Format: `<amount>`\n"
                    f"Example: `100`",
                    parse_mode='Markdown'
                )
            else:
                # General add tokens menu
                await query.edit_message_text(
                    "💰 **Add Tokens to User**\n\n"
                    "Please enter the user ID and amount in this format:\n"
                    "`<user_id> <amount>`\n\n"
                    "Examples:\n"
                    "• `123456789 100`\n"
                    "• `8289517006 50`\n\n"
                    "Or click below for advanced options:",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("➕ Add to Current User", callback_data="add_to_current")],
                        [InlineKeyboardButton("📊 Bulk Add", callback_data="bulk_add_tokens")],
                        [InlineKeyboardButton("🔙 Back", callback_data="admin_tokens")]
                    ]),
                    parse_mode='Markdown'
                )
            
            context.user_data['awaiting_token_input'] = True
            
        except Exception as e:
            logger.error(f"Error in add_tokens_menu: {e}")
            await query.edit_message_text("❌ Error loading token menu.")
    
    async def process_token_addition(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process token addition from text input"""
        if not context.user_data.get('awaiting_token_input'):
            return
        
        try:
            text = update.message.text.strip()
            user_id = update.effective_user.id
            
            # Check if we have a specific user ID from context
            target_user_id = context.user_data.get('token_user_id')
            
            if target_user_id:
                # Simple format: just amount
                try:
                    amount = int(text)
                    if amount <= 0:
                        await update.message.reply_text("❌ Amount must be positive.")
                        return
                    
                    target_id = target_user_id
                except ValueError:
                    await update.message.reply_text("❌ Please enter a valid number.")
                    return
            else:
                # Format: user_id amount
                parts = text.split()
                if len(parts) != 2:
                    await update.message.reply_text(
                        "❌ Invalid format. Please use: `<user_id> <amount>`\n"
                        "Example: `123456789 100`"
                    )
                    return
                
                try:
                    target_id = int(parts[0])
                    amount = int(parts[1])
                    
                    if amount <= 0:
                        await update.message.reply_text("❌ Amount must be positive.")
                        return
                except ValueError:
                    await update.message.reply_text("❌ Invalid numbers. Use integers only.")
                    return
            
            # Check if user exists
            user = await db.get_user(target_id)
            if not user:
                # Create user if doesn't exist
                user = await db.create_user(
                    user_id=target_id,
                    username="unknown",
                    first_name=f"User {target_id}"
                )
            
            # Add tokens
            success = await db.update_user_tokens(target_id, amount)
            
            if success:
                await update.message.reply_text(
                    f"✅ **Successfully Added Tokens**\n\n"
                    f"**User ID:** `{target_id}`\n"
                    f"**Amount:** `{amount}` tokens\n"
                    f"**New Balance:** `{user.tokens + amount}` tokens",
                    parse_mode='Markdown'
                )
                
                # Try to notify user
                try:
                    await context.bot.send_message(
                        chat_id=target_id,
                        text=f"💰 **You received {amount} tokens!**\n\n"
                             f"Your new balance: {user.tokens + amount} tokens",
                        parse_mode='Markdown'
                    )
                except:
                    pass
            else:
                await update.message.reply_text("❌ Failed to add tokens.")
            
            # Clear context data
            context.user_data['awaiting_token_input'] = False
            context.user_data.pop('token_user_id', None)
            
        except Exception as e:
            logger.error(f"Error processing token addition: {e}")
            await update.message.reply_text("❌ An error occurred.")
    
    async def bulk_add_tokens(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Bulk add tokens to multiple users"""
        try:
            query = update.callback_query
            await query.answer()
            
            await query.edit_message_text(
                "📊 **Bulk Token Addition**\n\n"
                "Send a list of user IDs and amounts in this format:\n"
                "`user_id1 amount1`\n"
                "`user_id2 amount2`\n"
                "`user_id3 amount3`\n\n"
                "Example:\n"
                "`123456789 50`\n"
                "`987654321 100`\n"
                "`555555555 25`\n\n"
                "**Maximum 20 users at a time.**\n\n"
                "Send /cancel to abort.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back", callback_data="admin_tokens")
                ]]),
                parse_mode='Markdown'
            )
            context.user_data['awaiting_bulk_token'] = True
            
        except Exception as e:
            logger.error(f"Error in bulk_add_tokens: {e}")
            await query.edit_message_text("❌ Error loading bulk token menu.")
    
    async def process_bulk_tokens(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process bulk token addition"""
        if not context.user_data.get('awaiting_bulk_token'):
            return
        
        try:
            text = update.message.text.strip()
            lines = text.split('\n')
            
            if len(lines) > 20:
                await update.message.reply_text("❌ Too many entries. Maximum 20.")
                return
            
            results = []
            success_count = 0
            fail_count = 0
            total_tokens = 0
            
            for i, line in enumerate(lines, 1):
                try:
                    line = line.strip()
                    if not line:
                        continue
                        
                    parts = line.split()
                    if len(parts) != 2:
                        results.append(f"{i}. ❌ Invalid format: {line}")
                        fail_count += 1
                        continue
                    
                    user_id = int(parts[0])
                    amount = int(parts[1])
                    
                    if amount <= 0:
                        results.append(f"{i}. ❌ User {user_id}: Amount must be positive")
                        fail_count += 1
                        continue
                    
                    # Check if user exists
                    user = await db.get_user(user_id)
                    if not user:
                        user = await db.create_user(
                            user_id=user_id,
                            username="unknown",
                            first_name=f"User {user_id}"
                        )
                    
                    # Add tokens
                    success = await db.update_user_tokens(user_id, amount)
                    
                    if success:
                        results.append(f"{i}. ✅ User {user_id}: +{amount} tokens")
                        success_count += 1
                        total_tokens += amount
                        
                        # Try to notify user
                        try:
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=f"💰 **You received {amount} tokens!**",
                                parse_mode='Markdown'
                            )
                        except:
                            pass
                    else:
                        results.append(f"{i}. ❌ User {user_id}: Failed to add tokens")
                        fail_count += 1
                        
                except ValueError:
                    results.append(f"{i}. ❌ Invalid numbers: {line}")
                    fail_count += 1
                except Exception as e:
                    results.append(f"{i}. ❌ Error: {line} - {str(e)[:50]}")
                    fail_count += 1
            
            # Send results
            result_text = (
                f"📊 **Bulk Token Addition Results**\n\n"
                f"✅ Successful: {success_count}\n"
                f"❌ Failed: {fail_count}\n"
                f"💰 Total Tokens Added: {total_tokens}\n\n"
            )
            
            # Add first 15 results
            for r in results[:15]:
                result_text += f"{r}\n"
            
            if len(results) > 15:
                result_text += f"... and {len(results) - 15} more"
            
            await update.message.reply_text(result_text, parse_mode='Markdown')
            
            context.user_data['awaiting_bulk_token'] = False
            
        except Exception as e:
            logger.error(f"Error in bulk token processing: {e}")
            await update.message.reply_text("❌ Error processing bulk tokens.")
    
    async def token_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show token statistics"""
        try:
            query = update.callback_query
            await query.answer()
            
            # Get token stats
            total_users = await db.get_user_count()
            total_tokens_issued = 0
            total_tokens_used = 0
            top_users = []
            
            try:
                if db and db.db:
                    # Total tokens issued
                    pipeline = [
                        {"$match": {"status": "completed"}},
                        {"$group": {"_id": None, "total": {"$sum": "$tokens_purchased"}}}
                    ]
                    result = await db.db.transactions.aggregate(pipeline).to_list(1)
                    total_tokens_issued = result[0]['total'] if result else 0
                    
                    # Total tokens used (from reports)
                    report_pipeline = [
                        {"$group": {"_id": None, "total": {"$sum": "$tokens_used"}}}
                    ]
                    report_result = await db.db.reports.aggregate(report_pipeline).to_list(1)
                    total_tokens_used = report_result[0]['total'] if report_result else 0
                    
                    # Get top users by tokens
                    cursor = db.db.users.find().sort("tokens", -1).limit(10)
                    top_users = await cursor.to_list(length=10)
            except Exception as e:
                logger.error(f"Error getting token stats: {e}")
            
            message = (
                f"📊 **Token Statistics**\n\n"
                f"**Total Users:** {total_users}\n"
                f"**Total Tokens Issued:** {total_tokens_issued}\n"
                f"**Total Tokens Used:** {total_tokens_used}\n"
                f"**Active Tokens:** {total_tokens_issued - total_tokens_used}\n\n"
                f"**Top Users by Tokens:**\n"
            )
            
            for i, user in enumerate(top_users[:5], 1):
                username = user.get('username', 'Unknown')
                tokens = user.get('tokens', 0)
                message += f"{i}. `{username}`: {tokens} tokens\n"
            
            keyboard = [
                [InlineKeyboardButton("➕ Add Tokens", callback_data="add_tokens_menu")],
                [InlineKeyboardButton("📋 Transactions", callback_data="token_transactions")],
                [InlineKeyboardButton("🔙 Back", callback_data="admin_tokens")]
            ]
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error in token_stats: {e}")
            await query.edit_message_text("❌ Error loading token statistics.")
    
    async def token_transactions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """View token transaction history"""
        try:
            query = update.callback_query
            await query.answer()
            
            # Get recent token transactions
            transactions = []
            try:
                if db and db.db:
                    cursor = db.db.transactions.find().sort("created_at", -1).limit(20)
                    transactions = await cursor.to_list(length=20)
            except Exception as e:
                logger.error(f"Error getting transactions: {e}")
            
            if not transactions:
                await query.edit_message_text(
                    "📊 **No Token Transactions Found**",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back", callback_data="admin_tokens")
                    ]]),
                    parse_mode='Markdown'
                )
                return
            
            message = "📊 **Recent Token Transactions**\n\n"
            
            for t in transactions[:10]:
                date_str = t.get('created_at', datetime.now())
                if hasattr(date_str, 'strftime'):
                    date_str = date_str.strftime('%Y-%m-%d %H:%M')
                else:
                    date_str = 'Unknown'
                    
                status_emoji = "✅" if t.get('status') == "completed" else "⏳"
                message += (
                    f"{status_emoji} **User:** `{t.get('user_id')}`\n"
                    f"   **Amount:** `{t.get('tokens_purchased')}` tokens\n"
                    f"   **Method:** {t.get('payment_method', 'Unknown')}\n"
                    f"   **Date:** {date_str}\n\n"
                )
            
            if len(transactions) > 10:
                message += f"... and {len(transactions) - 10} more"
            
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh", callback_data="token_transactions")],
                [InlineKeyboardButton("🔙 Back", callback_data="admin_tokens")]
            ]
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error in token_transactions: {e}")
            await query.edit_message_text("❌ Error loading transactions.")
    
    async def pending_payments(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show pending payments"""
        try:
            query = update.callback_query
            await query.answer()
            
            # Get pending transactions
            transactions = []
            try:
                if db and db.db:
                    cursor = db.db.transactions.find({"status": "pending"}).sort("created_at", -1).limit(20)
                    transactions = await cursor.to_list(length=20)
            except Exception as e:
                logger.error(f"Error getting pending payments: {e}")
            
            if not transactions:
                await query.edit_message_text(
                    "✅ **No Pending Payments**\n\n"
                    "All payments have been processed.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔙 Back", callback_data="admin_tokens")
                    ]]),
                    parse_mode='Markdown'
                )
                return
            
            message = "⏳ **Pending Payments**\n\n"
            keyboard = []
            
            for t in transactions[:5]:
                txn_id = t.get('transaction_id', 'Unknown')[:8]
                amount = t.get('amount', 0)
                method = t.get('payment_method', 'Unknown')
                user_id = t.get('user_id', 'Unknown')
                
                message += (
                    f"**ID:** `{txn_id}...`\n"
                    f"**User:** `{user_id}`\n"
                    f"**Amount:** ₹{amount}\n"
                    f"**Method:** {method}\n\n"
                )
                
                keyboard.append([
                    InlineKeyboardButton(
                        f"✅ Verify {txn_id}",
                        callback_data=f"verify_payment_{t.get('transaction_id')}"
                    )
                ])
            
            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_tokens")])
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error in pending_payments: {e}")
            await query.edit_message_text("❌ Error loading pending payments.")
    
    async def manage_packages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Manage token packages"""
        try:
            query = update.callback_query
            await query.answer()
            
            # Get packages
            packages = await db.get_token_packages()
            
            message = "📦 **Token Packages**\n\n"
            
            for p in packages:
                message += (
                    f"**{p.name}**\n"
                    f"• Tokens: {p.tokens}\n"
                    f"• Stars: ⭐{p.price_stars}\n"
                    f"• UPI: ₹{p.price_inr}\n"
                    f"• {p.description}\n\n"
                )
            
            message += "Package settings can be configured in environment variables."
            
            keyboard = [
                [InlineKeyboardButton("🔙 Back", callback_data="admin_tokens")]
            ]
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error in manage_packages: {e}")
            await query.edit_message_text("❌ Error loading packages.")
    
    # ========== END TOKEN MANAGEMENT METHODS ==========
    
    async def show_statistics(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show bot statistics"""
        try:
            query = update.callback_query
            
            # Get stats from database
            total_users = 0
            total_reports = 0
            pending_reports = 0
            resolved_reports = 0
            total_accounts = 0
            
            try:
                if db and db.db is not None:
                    total_users = await db.db.users.count_documents({})
                    total_reports = await db.db.reports.count_documents({})
                    pending_reports = await db.db.reports.count_documents({"status": "pending"})
                    resolved_reports = await db.db.reports.count_documents({"status": "resolved"})
                    total_accounts = await db.db.accounts.count_documents({})
            except Exception as e:
                logger.error(f"Error getting stats: {e}")
            
            message = (
                f"📊 **Bot Statistics**\n\n"
                f"**👥 Users**\n"
                f"• Total Users: {total_users}\n"
                f"• Total Accounts: {total_accounts}\n\n"
                f"**📊 Reports**\n"
                f"• Total Reports: {total_reports}\n"
                f"• Pending: {pending_reports}\n"
                f"• Resolved: {resolved_reports}\n\n"
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
            await query.edit_message_text("❌ Error loading statistics.")
    
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
            await query.edit_message_text("❌ Error loading settings.")
    
    async def show_user_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show user information"""
        try:
            query = update.callback_query
            user_id = int(query.data.replace("user_info_", ""))
            
            # Get user from database
            user_data = None
            try:
                if db and db.db is not None:
                    user_data = await db.db.users.find_one({"user_id": user_id})
            except Exception as e:
                logger.error(f"Error fetching user: {e}")
            
            if not user_data:
                await query.edit_message_text("❌ User not found.")
                return
            
            # Get user stats
            account_count = 0
            report_count = 0
            try:
                if db and db.db is not None:
                    account_count = await db.db.accounts.count_documents({"user_id": user_id})
                    report_count = await db.db.reports.count_documents({"user_id": user_id})
            except:
                pass
            
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
                f"• Reports: {report_count}\n"
                f"• Accounts: {account_count}\n"
            )
            
            # Add action buttons
            keyboard = []
            if user_data.get('is_blocked'):
                keyboard.append([InlineKeyboardButton("🔓 Unblock User", callback_data=f"unblock_user_{user_id}")])
            else:
                keyboard.append([InlineKeyboardButton("🔒 Block User", callback_data=f"block_user_{user_id}")])
            
            keyboard.append([InlineKeyboardButton("💰 Add Tokens", callback_data=f"add_tokens_{user_id}")])
            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_users")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in show_user_info: {e}")
            await query.edit_message_text("❌ Error loading user info.")
    
    async def block_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Block a user"""
        try:
            query = update.callback_query
            user_id = int(query.data.replace("block_user_", ""))
            
            success = False
            try:
                if db and db.db is not None:
                    result = await db.db.users.update_one(
                        {"user_id": user_id},
                        {"$set": {"is_blocked": True}}
                    )
                    success = result.modified_count > 0
            except Exception as e:
                logger.error(f"Error blocking user: {e}")
            
            if success:
                await query.edit_message_text(
                    f"✅ User `{user_id}` has been blocked.",
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text(
                    f"❌ Failed to block user `{user_id}`.",
                    parse_mode='Markdown'
                )
        except Exception as e:
            logger.error(f"Error in block_user: {e}")
            await query.edit_message_text("❌ Error blocking user.")
    
    async def unblock_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Unblock a user"""
        try:
            query = update.callback_query
            user_id = int(query.data.replace("unblock_user_", ""))
            
            success = False
            try:
                if db and db.db is not None:
                    result = await db.db.users.update_one(
                        {"user_id": user_id},
                        {"$set": {"is_blocked": False}}
                    )
                    success = result.modified_count > 0
            except Exception as e:
                logger.error(f"Error unblocking user: {e}")
            
            if success:
                await query.edit_message_text(
                    f"✅ User `{user_id}` has been unblocked.",
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text(
                    f"❌ Failed to unblock user `{user_id}`.",
                    parse_mode='Markdown'
                )
        except Exception as e:
            logger.error(f"Error in unblock_user: {e}")
            await query.edit_message_text("❌ Error unblocking user.")