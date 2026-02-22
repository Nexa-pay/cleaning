import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from datetime import datetime, timedelta
import asyncio

from database import db
from models import UserRole, AccountStatus
import config

logger = logging.getLogger(__name__)

class OwnerHandler:
    async def owner_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show owner panel with exclusive features"""
        user_id = update.effective_user.id
        
        # Verify owner access
        if user_id not in config.OWNER_IDS and user_id != config.SUPER_ADMIN_ID:
            await update.effective_message.reply_text("❌ Owner access only!")
            return
        
        message = (
            f"👑 **Owner Control Panel**\n\n"
            f"Welcome, Owner!\n"
            f"Your ID: `{user_id}`\n\n"
            f"**Exclusive Features:**"
        )
        
        keyboard = [
            [InlineKeyboardButton("📢 Broadcast Message", callback_data="owner_broadcast")],
            [InlineKeyboardButton("🎁 Create Giveaway", callback_data="owner_giveaway")],
            [InlineKeyboardButton("💰 Add Tokens to User", callback_data="owner_add_tokens")],
            [InlineKeyboardButton("📊 System Stats", callback_data="owner_stats")],
            [InlineKeyboardButton("👥 Manage Admins", callback_data="owner_manage_admins")],
            [InlineKeyboardButton("⚙️ Bot Settings", callback_data="owner_settings")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def broadcast_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start broadcast process"""
        query = update.callback_query
        await query.answer()
        
        context.user_data['broadcast_mode'] = True
        await query.edit_message_text(
            "📢 **Broadcast Mode**\n\n"
            "Send me the message you want to broadcast to all users.\n"
            "You can send text, photos, or documents.\n\n"
            "Send /cancel to abort."
        )
    
    async def handle_broadcast_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the broadcast message and send to all users"""
        if not context.user_data.get('broadcast_mode'):
            return
        
        message = update.message
        user_id = update.effective_user.id
        
        # Verify owner
        if user_id not in config.OWNER_IDS and user_id != config.SUPER_ADMIN_ID:
            await message.reply_text("❌ Unauthorized")
            return
        
        status_msg = await message.reply_text("📤 Broadcasting message to all users...")
        
        try:
            # Get all users from database
            all_users = []
            if db and db.db:
                cursor = db.db.users.find({}, {"user_id": 1})
                all_users = await cursor.to_list(length=10000)
            
            if not all_users:
                await status_msg.edit_text("❌ No users found in database.")
                return
            
            success_count = 0
            fail_count = 0
            
            for user_data in all_users:
                try:
                    if message.text:
                        await context.bot.send_message(
                            chat_id=user_data['user_id'],
                            text=f"📢 **Broadcast Message**\n\n{message.text}"
                        )
                    elif message.photo:
                        await context.bot.send_photo(
                            chat_id=user_data['user_id'],
                            photo=message.photo[-1].file_id,
                            caption=f"📢 **Broadcast**\n\n{message.caption or ''}"
                        )
                    success_count += 1
                except Exception as e:
                    fail_count += 1
                    logger.error(f"Failed to send to {user_data['user_id']}: {e}")
                
                # Small delay to avoid flooding
                await asyncio.sleep(0.05)
            
            await status_msg.edit_text(
                f"✅ **Broadcast Complete**\n\n"
                f"Total Users: {len(all_users)}\n"
                f"✅ Success: {success_count}\n"
                f"❌ Failed: {fail_count}"
            )
            
        except Exception as e:
            await status_msg.edit_text(f"❌ Broadcast error: {str(e)}")
        
        context.user_data['broadcast_mode'] = False
    
    async def giveaway_setup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Setup token giveaway"""
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "🎁 **Token Giveaway**\n\n"
            "Enter the amount of tokens for giveaway:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Cancel", callback_data="owner_panel")
            ]])
        )
        context.user_data['giveaway_step'] = 'amount'
    
    async def handle_giveaway_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle giveaway amount input"""
        try:
            amount = int(update.message.text.strip())
            if amount <= 0:
                await update.message.reply_text("❌ Amount must be positive!")
                return
            
            context.user_data['giveaway_amount'] = amount
            context.user_data['giveaway_step'] = 'winners'
            
            await update.message.reply_text(
                f"🎁 Amount: {amount} tokens\n\n"
                "Enter number of winners:"
            )
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number!")
    
    async def handle_giveaway_winners(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle giveaway winners input"""
        try:
            winners = int(update.message.text.strip())
            if winners <= 0:
                await update.message.reply_text("❌ Number of winners must be positive!")
                return
            
            amount = context.user_data['giveaway_amount']
            
            await update.message.reply_text(
                f"🎁 **Giveaway Created**\n\n"
                f"Total Prize: {amount * winners} tokens\n"
                f"Each Winner: {amount} tokens\n"
                f"Winners: {winners}\n\n"
                f"Use /start_giveaway to begin!",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Start Giveaway", callback_data="start_giveaway")
                ]])
            )
            
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid number!")
    
    async def add_tokens_to_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Add tokens to a specific user"""
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "💰 **Add Tokens**\n\n"
            "Enter user ID and token amount (format: `user_id amount`)\n"
            "Example: `123456789 100`",
            parse_mode='Markdown'
        )
        context.user_data['add_tokens'] = True
    
    async def handle_add_tokens(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process token addition"""
        if not context.user_data.get('add_tokens'):
            return
        
        try:
            text = update.message.text.strip()
            parts = text.split()
            if len(parts) != 2:
                await update.message.reply_text("❌ Use format: `user_id amount`")
                return
            
            user_id = int(parts[0])
            amount = int(parts[1])
            
            if amount <= 0:
                await update.message.reply_text("❌ Amount must be positive!")
                return
            
            # Update user tokens
            success = await db.update_user_tokens(user_id, amount)
            
            if success:
                await update.message.reply_text(
                    f"✅ Added {amount} tokens to user {user_id}"
                )
                
                # Notify user
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"💰 You received {amount} tokens!"
                    )
                except:
                    pass
            else:
                await update.message.reply_text("❌ Failed to add tokens. User may not exist.")
            
        except ValueError:
            await update.message.reply_text("❌ Invalid number format!")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")
        
        context.user_data['add_tokens'] = False
    
    async def owner_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show detailed system statistics"""
        query = update.callback_query
        await query.answer()
        
        try:
            # Get stats from database
            user_count = await db.get_user_count() if db and db.db else 0
            account_count = 0
            report_count = 0
            transaction_count = 0
            
            if db and db.db:
                account_count = await db.db.accounts.count_documents({})
                report_count = await db.db.reports.count_documents({})
                transaction_count = await db.db.transactions.count_documents({"status": "completed"})
            
            message = (
                f"📊 **System Statistics**\n\n"
                f"**Users:** {user_count}\n"
                f"**Accounts:** {account_count}\n"
                f"**Reports:** {report_count}\n"
                f"**Transactions:** {transaction_count}\n\n"
                f"**Config:**\n"
                f"• Admins: {len(config.ADMIN_IDS)}\n"
                f"• Owners: {len(config.OWNER_IDS)}\n"
                f"• Token Price: ⭐{config.TOKEN_PRICE_STARS} / ₹{config.TOKEN_PRICE_INR}\n"
            )
            
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Back", callback_data="owner_panel")
                ]]),
                parse_mode='Markdown'
            )
        except Exception as e:
            await query.edit_message_text(f"❌ Error: {str(e)}")

# Global instance
owner_handler = OwnerHandler()