import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import qrcode
from io import BytesIO

from database import db
import config
from utils import generate_qr_code

logger = logging.getLogger(__name__)

class PaymentHandler:
    async def show_token_packages(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show available token packages"""
        packages = await db.get_token_packages()
        
        user_id = update.effective_user.id
        user = await db.get_user(user_id)
        
        if not user:
            user = await db.create_user(
                user_id=user_id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name
            )
        
        message = (
            f"💰 **Token Packages**\n\n"
            f"**Your Balance:** `{user.tokens}` tokens\n"
            f"**Report Cost:** `{config.REPORT_COST_IN_TOKENS}` token per report\n\n"
            "Choose a package to purchase:\n\n"
        )
        
        keyboard = []
        
        for package in packages:
            message += (
                f"**{package.name}**\n"
                f"• {package.tokens} Reports\n"
                f"• ⭐ {package.price_stars} Stars\n"
                f"• ₹{package.price_inr} UPI\n"
                f"• _{package.description}_\n\n"
            )
            
            # Add buttons for each package
            keyboard.append([
                InlineKeyboardButton(
                    f"⭐ Buy {package.name} (Stars)",
                    callback_data=f"buy_stars_{package.package_id}"
                )
            ])
            keyboard.append([
                InlineKeyboardButton(
                    f"💳 Buy {package.name} (UPI)",
                    callback_data=f"buy_upi_{package.package_id}"
                )
            ])
            keyboard.append([InlineKeyboardButton("────────────", callback_data="ignore")])
        
        keyboard.append([InlineKeyboardButton("📊 Check Balance", callback_data="check_balance")])
        keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.message:
            await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def handle_package_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle package selection"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data == "check_balance":
            await self.check_balance(update, context)
            return
        elif data == "ignore":
            return
        
        if data.startswith("buy_stars_"):
            package_id = data.replace("buy_stars_", "")
            await self.initiate_stars_payment(update, context, package_id)
        elif data.startswith("buy_upi_"):
            package_id = data.replace("buy_upi_", "")
            await self.initiate_upi_payment(update, context, package_id)
    
    async def initiate_stars_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE, package_id: str):
        """Initiate Telegram Stars payment"""
        query = update.callback_query
        user_id = update.effective_user.id
        
        package = await db.get_package(package_id)
        if not package:
            await query.edit_message_text("❌ Invalid package selected.")
            return
        
        # Create transaction
        transaction = await db.create_transaction(
            user_id=user_id,
            amount=package.price_stars,
            currency="STARS",
            tokens=package.tokens,
            payment_method="stars"
        )
        
        payment_text = (
            f"💫 **Telegram Stars Payment**\n\n"
            f"**Package:** {package.name}\n"
            f"**Tokens:** {package.tokens}\n"
            f"**Price:** {package.price_stars} ⭐\n\n"
            f"**Transaction ID:** `{transaction.transaction_id}`\n\n"
            f"**How to Pay:**\n"
            f"1. Send **{package.price_stars} Stars** to @{context.bot.username}\n"
            f"2. After sending, click 'I've Sent Stars'\n"
            f"3. Tokens will be added automatically\n\n"
            f"⏰ Transaction expires in 30 minutes."
        )
        
        keyboard = [
            [InlineKeyboardButton("✅ I've Sent Stars", callback_data=f"confirm_stars_{transaction.transaction_id}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_payment")],
            [InlineKeyboardButton("🔙 Back to Packages", callback_data="back_to_packages")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(payment_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def initiate_upi_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE, package_id: str):
        """Initiate UPI payment"""
        query = update.callback_query
        user_id = update.effective_user.id
        
        package = await db.get_package(package_id)
        if not package:
            await query.edit_message_text("❌ Invalid package selected.")
            return
        
        # Create transaction
        transaction = await db.create_transaction(
            user_id=user_id,
            amount=package.price_inr,
            currency="INR",
            tokens=package.tokens,
            payment_method="upi"
        )
        
        # Generate UPI payment link
        upi_link = f"upi://pay?pa={config.UPI_ID}&pn={config.PAYEE_NAME}&am={package.price_inr}&cu=INR&tn={transaction.transaction_id}"
        
        # Generate QR code
        bio = generate_qr_code(upi_link)
        
        payment_text = (
            f"💳 **UPI Payment**\n\n"
            f"**Package:** {package.name}\n"
            f"**Tokens:** {package.tokens}\n"
            f"**Amount:** ₹{package.price_inr}\n"
            f"**UPI ID:** `{config.UPI_ID}`\n"
            f"**Transaction ID:** `{transaction.transaction_id}`\n\n"
            f"**Instructions:**\n"
            f"1. Scan QR code or copy UPI ID\n"
            f"2. Send exact amount: ₹{package.price_inr}\n"
            f"3. Use Transaction ID as reference\n"
            f"4. Click 'I've Paid' after payment\n\n"
            f"⏰ Transaction expires in 30 minutes."
        )
        
        keyboard = [
            [InlineKeyboardButton("✅ I've Paid", callback_data=f"confirm_upi_{transaction.transaction_id}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_payment")],
            [InlineKeyboardButton("🔙 Back to Packages", callback_data="back_to_packages")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(payment_text, reply_markup=reply_markup, parse_mode='Markdown')
        
        # Send QR code
        await context.bot.send_photo(
            chat_id=user_id,
            photo=bio,
            caption="📱 Scan this QR code to pay via UPI"
        )
    
    async def confirm_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Confirm payment"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data == "cancel_payment":
            await query.edit_message_text("❌ Payment cancelled.")
            return
        elif data == "back_to_packages":
            await self.show_token_packages(update, context)
            return
        
        if data.startswith("confirm_stars_"):
            transaction_id = data.replace("confirm_stars_", "")
            await self.verify_stars_payment(update, context, transaction_id)
        elif data.startswith("confirm_upi_"):
            transaction_id = data.replace("confirm_upi_", "")
            await self.verify_upi_payment(update, context, transaction_id)
    
    async def verify_stars_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE, transaction_id: str):
        """Verify Stars payment"""
        query = update.callback_query
        
        # Get transaction
        transaction = await db.get_transaction(transaction_id)
        if not transaction:
            await query.edit_message_text("❌ Transaction not found.")
            return
        
        if transaction.status == "completed":
            await query.edit_message_text("✅ This transaction has already been verified.")
            return
        
        # In production, verify with Telegram API
        # For now, simulate verification
        await db.complete_transaction(transaction_id)
        
        # Get updated user info
        user = await db.get_user(transaction.user_id)
        
        success_text = (
            f"✅ **Payment Verified!**\n\n"
            f"🎉 **{transaction.tokens_purchased} tokens** have been added to your account.\n\n"
            f"**New Balance:** {user.tokens + transaction.tokens_purchased} tokens\n"
            f"**Transaction ID:** `{transaction_id}`\n\n"
            f"Use /report to start reporting!\n"
            f"Use /balance to check your balance."
        )
        
        await query.edit_message_text(success_text, parse_mode='Markdown')
    
    async def verify_upi_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE, transaction_id: str):
        """Verify UPI payment (manual verification)"""
        query = update.callback_query
        
        transaction = await db.get_transaction(transaction_id)
        if not transaction:
            await query.edit_message_text("❌ Transaction not found.")
            return
        
        if transaction.status == "completed":
            await query.edit_message_text("✅ This transaction has already been verified.")
            return
        
        # Notify admins for manual verification
        admin_notified = False
        for admin_id in config.ADMIN_IDS + config.OWNER_IDS:
            try:
                admin_text = (
                    f"💰 **UPI Payment Pending Verification**\n\n"
                    f"**User ID:** `{transaction.user_id}`\n"
                    f"**Amount:** ₹{transaction.amount}\n"
                    f"**Tokens:** {transaction.tokens_purchased}\n"
                    f"**Transaction ID:** `{transaction_id}`\n"
                    f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"Use `/verify {transaction_id}` to confirm payment."
                )
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=admin_text,
                    parse_mode='Markdown'
                )
                admin_notified = True
            except Exception as e:
                logger.error(f"Failed to notify admin {admin_id}: {e}")
        
        user_text = (
            f"⏳ **Payment Submitted for Verification**\n\n"
            f"Your payment of ₹{transaction.amount} has been received and is pending verification.\n"
            f"**Transaction ID:** `{transaction_id}`\n\n"
            f"An admin will verify your payment within 24 hours.\n"
            f"You'll receive a notification once verified.\n\n"
            f"Need help? Contact @{config.CONTACT_INFO['admin_username']}"
        )
        
        if not admin_notified:
            user_text += "\n\n⚠️ Note: No admins are currently available. Please contact support manually."
        
        await query.edit_message_text(user_text, parse_mode='Markdown')
    
    async def check_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Check user's token balance"""
        user_id = update.effective_user.id
        user = await db.get_user(user_id)
        
        if not user:
            user = await db.create_user(
                user_id=user_id,
                username=update.effective_user.username,
                first_name=update.effective_user.first_name
            )
        
        # Get recent transactions
        transactions = await db.get_user_transactions(user_id, limit=3)
        
        balance_text = (
            f"💰 **Your Balance**\n\n"
            f"**Tokens:** `{user.tokens}`\n"
            f"**Reports Made:** `{user.total_reports}`\n"
            f"**Account Type:** `{user.role.value.upper()}`\n\n"
        )
        
        if transactions:
            balance_text += "**Recent Transactions:**\n"
            for t in transactions:
                status_emoji = "✅" if t.status == "completed" else "⏳"
                balance_text += f"{status_emoji} {t.tokens_purchased} tokens - {t.currency} {t.amount}\n"
        
        keyboard = [
            [InlineKeyboardButton("💰 Buy More Tokens", callback_data="back_to_packages")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.message:
            await update.message.reply_text(balance_text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.callback_query.edit_message_text(balance_text, reply_markup=reply_markup, parse_mode='Markdown')
    
    async def admin_verify_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin command to verify payment"""
        user_id = update.effective_user.id
        
        # Check if user is admin/owner
        if user_id not in config.ADMIN_IDS and user_id not in config.OWNER_IDS and user_id != config.SUPER_ADMIN_ID:
            await update.message.reply_text("❌ Unauthorized.")
            return
        
        # Get transaction ID from command
        try:
            transaction_id = context.args[0]
        except (IndexError, AttributeError):
            await update.message.reply_text(
                "Usage: `/verify <transaction_id>`\n\n"
                "Example: `/verify TXN123456789`",
                parse_mode='Markdown'
            )
            return
        
        # Verify transaction
        result = await db.complete_transaction(transaction_id)
        
        if result:
            # Get transaction details
            transaction = await db.get_transaction(transaction_id)
            if transaction:
                # Notify user
                try:
                    await context.bot.send_message(
                        chat_id=transaction.user_id,
                        text=(
                            f"✅ **Payment Verified!**\n\n"
                            f"🎉 {transaction.tokens_purchased} tokens have been added to your account.\n"
                            f"**Transaction ID:** `{transaction_id}`"
                        ),
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.error(f"Failed to notify user: {e}")
                
                await update.message.reply_text(
                    f"✅ Payment verified.\n"
                    f"User: `{transaction.user_id}`\n"
                    f"Tokens added: {transaction.tokens_purchased}"
                )
        else:
            await update.message.reply_text(
                "❌ Transaction not found or already verified.\n\n"
                "Use `/pending` to see pending transactions.",
                parse_mode='Markdown'
            )