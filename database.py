import motor.motor_asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import logging
import uuid
import asyncio
import socket
import dns.resolver

from models import *
import config
from utils import encrypt_data, decrypt_data

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.client = None
        self.db = None
        self._connection_attempts = 0
        
    async def connect(self):
        """Connect to MongoDB with improved error handling and diagnostics"""
        try:
            if not config.MONGODB_URI:
                logger.error("❌ MONGODB_URI not set in environment variables!")
                return False
            
            # Log URI safely (hide password)
            safe_uri = self._mask_uri(config.MONGODB_URI)
            logger.info(f"🔄 Attempting to connect to MongoDB...")
            logger.info(f"🔗 URI (masked): {safe_uri}")
            
            # Check if URI has the correct format
            if 'mongodb+srv://' not in config.MONGODB_URI:
                logger.error("❌ URI should start with mongodb+srv://")
                return False
            
            if '<password>' in config.MONGODB_URI:
                logger.error("❌ You forgot to replace <password> with your actual password!")
                return False
            
            # Test DNS resolution first
            logger.info("🔍 Testing DNS resolution...")
            try:
                # Extract hostname from URI
                hostname = config.MONGODB_URI.split('@')[1].split('/')[0]
                logger.info(f"   Hostname: {hostname}")
                
                # Try to resolve
                answers = dns.resolver.resolve(hostname, 'A')
                logger.info(f"✅ DNS resolution successful: {answers[0].address}")
            except Exception as dns_error:
                logger.error(f"❌ DNS resolution failed: {dns_error}")
                logger.error("   This usually means the cluster name is wrong or network is blocked")
            
            # Connect with increased timeouts
            logger.info("🔄 Creating MongoDB client...")
            self.client = motor.motor_asyncio.AsyncIOMotorClient(
                config.MONGODB_URI,
                serverSelectionTimeoutMS=15000,  # Increased timeout
                connectTimeoutMS=15000,
                socketTimeoutMS=15000,
                retryWrites=True,
                retryReads=True
            )
            
            # Test connection with ping
            logger.info("🔄 Pinging MongoDB...")
            await self.client.admin.command('ping')
            logger.info("✅ MongoDB ping successful!")
            
            # Get database
            self.db = self.client[config.DATABASE_NAME]
            logger.info(f"✅ Using database: {config.DATABASE_NAME}")
            
            # List collections to verify access
            try:
                collections = await self.db.list_collection_names()
                logger.info(f"✅ Available collections: {collections}")
            except Exception as e:
                logger.warning(f"⚠️ Could not list collections: {e}")
            
            # Initialize default data
            await self._init_default_data()
            
            # Create indexes
            try:
                await self._create_indexes()
                logger.info("✅ Database indexes created successfully!")
            except Exception as e:
                logger.warning(f"⚠️ Index creation warning: {e}")
            
            logger.info("✅ Database connected successfully")
            return True
            
        except motor.motor_asyncio.AsyncIOMotorClientError as e:
            logger.error(f"❌ Motor client error: {e}")
            self._log_connection_help(e)
            self.client = None
            self.db = None
            return False
        except Exception as e:
            logger.error(f"❌ Database connection failed: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            self._log_connection_help(e)
            self.client = None
            self.db = None
            return False
    
    def _mask_uri(self, uri: str) -> str:
        """Mask password in URI for logging"""
        try:
            # Find password part between : and @
            start = uri.find('://') + 3
            at_pos = uri.find('@')
            if start > 0 and at_pos > start:
                user_pass = uri[start:at_pos]
                if ':' in user_pass:
                    user, password = user_pass.split(':', 1)
                    return uri[:start] + f"{user}:****" + uri[at_pos:]
            return uri[:30] + "..."  # Fallback truncation
        except:
            return uri[:30] + "..."
    
    def _log_connection_help(self, error: Exception):
        """Log helpful suggestions based on error"""
        error_str = str(error).lower()
        
        if 'authentication failed' in error_str or 'auth failed' in error_str:
            logger.error("💡 Suggestion: Check your username and password in MONGODB_URI")
            logger.error("   Make sure password doesn't contain special characters that need encoding")
        elif 'getaddrinfo' in error_str or 'dns' in error_str:
            logger.error("💡 Suggestion: Check your cluster name in MONGODB_URI")
            logger.error("   It should look like: cluster0.abc12.mongodb.net")
        elif 'timed out' in error_str or 'timeout' in error_str:
            logger.error("💡 Suggestion: Check network access in MongoDB Atlas")
            logger.error("   Add IP 0.0.0.0/0 to allow access from anywhere")
        elif 'ssl' in error_str:
            logger.error("💡 Suggestion: Make sure you're using mongodb+srv:// not mongodb://")
    
    async def _create_indexes(self):
        """Create database indexes"""
        if not self.db:
            return
            
        # Users collection indexes
        await self.db.users.create_index("user_id", unique=True)
        await self.db.users.create_index("username")  # For username searches
        
        # Accounts collection indexes
        await self.db.accounts.create_index([("user_id", 1), ("account_id", 1)], unique=True)
        
        # Sessions collection indexes
        await self.db.sessions.create_index("session_id", unique=True)
        await self.db.sessions.create_index("expires_at", expireAfterSeconds=0)
        
        # Transactions collection indexes
        await self.db.transactions.create_index("transaction_id", unique=True)
        await self.db.transactions.create_index("created_at", -1)  # For sorting
        
        # Reports collection indexes
        await self.db.reports.create_index("report_id", unique=True)
        await self.db.reports.create_index([("user_id", 1), ("created_at", -1)])
        await self.db.reports.create_index([("status", 1), ("created_at", -1)])
        
        # Token packages indexes
        await self.db.token_packages.create_index("package_id", unique=True)
        
        # Report templates indexes
        await self.db.report_templates.create_index("template_id", unique=True)
    
    async def _init_default_data(self):
        """Initialize default data in database with expanded templates"""
        if not self.db:
            return
            
        # Initialize token packages if not exist
        packages = self._get_default_packages()
        for package in packages:
            existing = await self.db.token_packages.find_one({"package_id": package.package_id})
            if not existing:
                await self.db.token_packages.insert_one(package.__dict__)
        
        # Initialize expanded report templates with all categories
        templates = [
            {
                "template_id": "abuse",
                "name": "🚫 Abuse/Harassment",
                "category": "abuse",
                "content": "This user is engaging in harassment, bullying, or abusive behavior.",
                "created_by": 0,
                "is_public": True
            },
            {
                "template_id": "pron",
                "name": "🔞 Adult Content/Pron",
                "category": "pron",
                "content": "This account is sharing adult content or pornography.",
                "created_by": 0,
                "is_public": True
            },
            {
                "template_id": "information",
                "name": "📋 Personal Information Leak",
                "category": "information",
                "content": "This user is sharing personal information without consent.",
                "created_by": 0,
                "is_public": True
            },
            {
                "template_id": "data_leak",
                "name": "💾 Data Leak/Private Info",
                "category": "data_leak",
                "content": "This account is leaking private data or confidential information.",
                "created_by": 0,
                "is_public": True
            },
            {
                "template_id": "sticker_pron",
                "name": "🎭 Sticker - Adult Content",
                "category": "sticker_pron",
                "content": "This sticker contains adult or explicit content.",
                "created_by": 0,
                "is_public": True
            },
            {
                "template_id": "harassing",
                "name": "⚠️ Harassing Behavior",
                "category": "harassing",
                "content": "This user is engaging in targeted harassment.",
                "created_by": 0,
                "is_public": True
            },
            {
                "template_id": "personal_data",
                "name": "🔐 Personal Data Exposure",
                "category": "personal_data",
                "content": "This account is exposing personal data without permission.",
                "created_by": 0,
                "is_public": True
            },
            {
                "template_id": "spam",
                "name": "📧 Spam",
                "category": "spam",
                "content": "This account is sending spam messages.",
                "created_by": 0,
                "is_public": True
            },
            {
                "template_id": "scam",
                "name": "💰 Scam/Fraud",
                "category": "scam",
                "content": "This account is attempting to scam users.",
                "created_by": 0,
                "is_public": True
            },
            {
                "template_id": "impersonation",
                "name": "👤 Impersonation",
                "category": "impersonation",
                "content": "This account is impersonating someone else.",
                "created_by": 0,
                "is_public": True
            },
            {
                "template_id": "illegal",
                "name": "⚖️ Illegal Content",
                "category": "illegal",
                "content": "This account is sharing illegal content.",
                "created_by": 0,
                "is_public": True
            },
            {
                "template_id": "other",
                "name": "📌 Other",
                "category": "other",
                "content": "Other violation not listed above.",
                "created_by": 0,
                "is_public": True
            }
        ]
        
        for template in templates:
            existing = await self.db.report_templates.find_one({"template_id": template["template_id"]})
            if not existing:
                await self.db.report_templates.insert_one(template)
                logger.info(f"✅ Created template: {template['name']}")
    
    async def ensure_connection(self):
        """Ensure database is connected, attempt reconnection if needed"""
        if not self.db or not self.client:
            logger.warning("⚠️ Database not connected, attempting reconnection...")
            return await self.connect()
        
        # Test if connection is still alive
        try:
            await self.client.admin.command('ping')
            return True
        except:
            logger.warning("⚠️ Connection lost, reconnecting...")
            return await self.connect()
    
    # ========== User Methods ==========
    
    async def get_user(self, user_id: int) -> Optional[User]:
        """Get user by ID"""
        if not await self.ensure_connection():
            return None
            
        try:
            user_data = await self.db.users.find_one({"user_id": user_id})
            if user_data:
                return User.from_dict(user_data)
            return None
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None
    
    async def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username"""
        if not await self.ensure_connection():
            return None
        
        try:
            # Remove @ if present
            if username.startswith('@'):
                username = username[1:]
            
            user_data = await self.db.users.find_one({"username": username})
            if user_data:
                return User.from_dict(user_data)
            return None
        except Exception as e:
            logger.error(f"Error getting user by username {username}: {e}")
            return None
    
    async def create_user(self, user_id: int, username: str, first_name: str, 
                         last_name: str = None, referred_by: int = None) -> Optional[User]:
        """Create new user"""
        if not await self.ensure_connection():
            # Return a temporary user object even if database fails
            return User(
                user_id=user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                role=UserRole.NORMAL,
                tokens=0
            )
        
        try:
            # Determine role
            role = UserRole.NORMAL
            if user_id in config.OWNER_IDS:
                role = UserRole.OWNER
            elif user_id in config.ADMIN_IDS:
                role = UserRole.ADMIN
            elif user_id == config.SUPER_ADMIN_ID:
                role = UserRole.SUPER_ADMIN
                
            user = User(
                user_id=user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                role=role,
                tokens=config.FREE_REPORTS_FOR_NEW_USERS,
                referred_by=referred_by
            )
            
            await self.db.users.insert_one(user.to_dict())
            logger.info(f"✅ New user created: {user_id} ({username})")
            return user
        except Exception as e:
            logger.error(f"Error creating user {user_id}: {e}")
            # Return temporary user
            return User(
                user_id=user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                role=UserRole.NORMAL,
                tokens=0
            )
    
    async def update_user(self, user_id: int, updates: dict) -> bool:
        """Update user information"""
        if not await self.ensure_connection():
            return False
            
        try:
            result = await self.db.users.update_one(
                {"user_id": user_id},
                {"$set": updates}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error updating user {user_id}: {e}")
            return False
    
    async def update_user_tokens(self, user_id: int, tokens_change: int) -> bool:
        """Update user tokens (positive for add, negative for deduct)"""
        if not await self.ensure_connection():
            return False
            
        try:
            result = await self.db.users.update_one(
                {"user_id": user_id},
                {"$inc": {"tokens": tokens_change}}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error updating tokens for {user_id}: {e}")
            return False
    
    async def add_report_count(self, user_id: int):
        """Increment user's report count"""
        if not await self.ensure_connection():
            return
            
        try:
            await self.db.users.update_one(
                {"user_id": user_id},
                {
                    "$inc": {"total_reports": 1},
                    "$set": {"last_active": datetime.now()}
                }
            )
        except Exception as e:
            logger.error(f"Error adding report count for {user_id}: {e}")
    
    async def get_user_count(self) -> int:
        """Get total user count"""
        if not await self.ensure_connection():
            return 0
            
        try:
            return await self.db.users.count_documents({})
        except Exception as e:
            logger.error(f"Error getting user count: {e}")
            return 0
    
    async def block_user(self, user_id: int) -> bool:
        """Block a user"""
        if not await self.ensure_connection():
            return False
            
        try:
            result = await self.db.users.update_one(
                {"user_id": user_id},
                {"$set": {"is_blocked": True}}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error blocking user {user_id}: {e}")
            return False
    
    async def unblock_user(self, user_id: int) -> bool:
        """Unblock a user"""
        if not await self.ensure_connection():
            return False
            
        try:
            result = await self.db.users.update_one(
                {"user_id": user_id},
                {"$set": {"is_blocked": False}}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error unblocking user {user_id}: {e}")
            return False
    
    # ========== Account Methods ==========
    
    async def add_telegram_account(self, user_id: int, phone_number: str, 
                                  session_string: str, account_name: str,
                                  twofa_password: str = None) -> Optional[TelegramAccount]:
        """Add a new Telegram account for reporting"""
        if not await self.ensure_connection():
            # Return a temporary account
            return TelegramAccount(
                account_id=str(uuid.uuid4()),
                user_id=user_id,
                phone_number=phone_number,
                session_string=session_string,
                account_name=account_name,
                twofa_password=twofa_password,
                is_primary=False,
                status=AccountStatus.ACTIVE
            )
        
        try:
            # Check account limit
            account_count = await self.db.accounts.count_documents({"user_id": user_id})
            
            # Encrypt sensitive data
            encrypted_session = encrypt_data(session_string)
            encrypted_2fa = encrypt_data(twofa_password) if twofa_password else None
            
            account = TelegramAccount(
                account_id=str(uuid.uuid4()),
                user_id=user_id,
                phone_number=phone_number,
                session_string=encrypted_session,
                account_name=account_name,
                twofa_password=encrypted_2fa,
                is_primary=(account_count == 0),  # First account is primary
                status=AccountStatus.ACTIVE
            )
            
            await self.db.accounts.insert_one(account.to_dict())
            logger.info(f"✅ New account added for user {user_id}: {account_name}")
            return account
        except Exception as e:
            logger.error(f"Error adding account: {e}")
            return None
    
    async def get_user_accounts(self, user_id: int) -> List[TelegramAccount]:
        """Get all accounts for a user"""
        if not await self.ensure_connection():
            return []
            
        try:
            cursor = self.db.accounts.find({"user_id": user_id})
            accounts = []
            async for doc in cursor:
                accounts.append(TelegramAccount.from_dict(doc))
            return accounts
        except Exception as e:
            logger.error(f"Error getting accounts for {user_id}: {e}")
            return []
    
    async def get_account(self, account_id: str) -> Optional[TelegramAccount]:
        """Get account by ID"""
        if not await self.ensure_connection():
            return None
            
        try:
            account_data = await self.db.accounts.find_one({"account_id": account_id})
            if account_data:
                return TelegramAccount.from_dict(account_data)
            return None
        except Exception as e:
            logger.error(f"Error getting account {account_id}: {e}")
            return None
    
    async def update_account_status(self, account_id: str, status: AccountStatus) -> bool:
        """Update account status"""
        if not await self.ensure_connection():
            return False
            
        try:
            result = await self.db.accounts.update_one(
                {"account_id": account_id},
                {"$set": {"status": status.value}}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error updating account {account_id}: {e}")
            return False
    
    async def set_primary_account(self, user_id: int, account_id: str) -> bool:
        """Set an account as primary"""
        if not await self.ensure_connection():
            return False
            
        try:
            # Remove primary from all accounts
            await self.db.accounts.update_many(
                {"user_id": user_id},
                {"$set": {"is_primary": False}}
            )
            
            # Set new primary
            result = await self.db.accounts.update_one(
                {"account_id": account_id, "user_id": user_id},
                {"$set": {"is_primary": True}}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error setting primary account: {e}")
            return False
    
    async def update_account_last_used(self, account_id: str):
        """Update account's last used timestamp"""
        if not await self.ensure_connection():
            return
            
        try:
            await self.db.accounts.update_one(
                {"account_id": account_id},
                {
                    "$set": {"last_used": datetime.now()},
                    "$inc": {"total_reports_used": 1}
                }
            )
        except Exception as e:
            logger.error(f"Error updating account last used: {e}")
    
    async def delete_account(self, account_id: str) -> bool:
        """Delete an account"""
        if not await self.ensure_connection():
            return False
            
        try:
            result = await self.db.accounts.delete_one({"account_id": account_id})
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"Error deleting account: {e}")
            return False
    
    # ========== Report Methods ==========
    
    async def create_report(self, user_id: int, account_id: str, report_type: str,
                          target: str, reason: str, details: str,
                          tokens_used: int = 1, evidence: List[str] = None) -> Optional[Report]:
        """Create a new report"""
        if not await self.ensure_connection():
            # Return a temporary report
            return Report(
                report_id=str(uuid.uuid4()).replace('-', '')[:12].upper(),
                user_id=user_id,
                account_id=account_id,
                report_type=report_type,
                target=target,
                reason=reason,
                details=details,
                status=ReportStatus.PENDING,
                tokens_used=tokens_used,
                evidence=evidence or []
            )
            
        try:
            report = Report(
                report_id=str(uuid.uuid4()).replace('-', '')[:12].upper(),
                user_id=user_id,
                account_id=account_id,
                report_type=report_type,
                target=target,
                reason=reason,
                details=details,
                status=ReportStatus.PENDING,
                tokens_used=tokens_used,
                evidence=evidence or []
            )
            
            await self.db.reports.insert_one(report.to_dict())
            
            # Update account last used
            await self.update_account_last_used(account_id)
            
            logger.info(f"✅ New report created: {report.report_id}")
            return report
        except Exception as e:
            logger.error(f"Error creating report: {e}")
            return None
    
    async def get_user_reports(self, user_id: int, page: int = 1) -> List[Report]:
        """Get user's reports with pagination"""
        if not await self.ensure_connection():
            return []
            
        try:
            skip = (page - 1) * config.REPORTS_PER_PAGE
            cursor = self.db.reports.find({"user_id": user_id})\
                                   .sort("created_at", -1)\
                                   .skip(skip)\
                                   .limit(config.REPORTS_PER_PAGE)
            
            reports = []
            async for doc in cursor:
                reports.append(Report.from_dict(doc))
            return reports
        except Exception as e:
            logger.error(f"Error getting reports for {user_id}: {e}")
            return []
    
    async def get_pending_reports(self, limit: int = 50) -> List[Report]:
        """Get pending reports for admin"""
        if not await self.ensure_connection():
            return []
            
        try:
            cursor = self.db.reports.find({"status": ReportStatus.PENDING.value})\
                                   .sort("created_at", 1)\
                                   .limit(limit)
            
            reports = []
            async for doc in cursor:
                reports.append(Report.from_dict(doc))
            return reports
        except Exception as e:
            logger.error(f"Error getting pending reports: {e}")
            return []
    
    async def update_report_status(self, report_id: str, status: ReportStatus,
                                  reviewed_by: int, result: str = None) -> bool:
        """Update report status"""
        if not await self.ensure_connection():
            return False
            
        try:
            update_data = {
                "$set": {
                    "status": status.value,
                    "reviewed_by": reviewed_by,
                    "reviewed_at": datetime.now()
                }
            }
            if result:
                update_data["$set"]["result"] = result
                
            result = await self.db.reports.update_one(
                {"report_id": report_id},
                update_data
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error updating report {report_id}: {e}")
            return False
    
    # ========== Transaction Methods ==========
    
    async def create_transaction(self, user_id: int, amount: float, currency: str,
                                tokens: int, payment_method: str) -> Optional[Transaction]:
        """Create a new transaction"""
        if not await self.ensure_connection():
            return Transaction(
                transaction_id=str(uuid.uuid4()).replace('-', '')[:16].upper(),
                user_id=user_id,
                amount=amount,
                currency=currency,
                tokens_purchased=tokens,
                payment_method=payment_method,
                status="pending"
            )
            
        try:
            transaction = Transaction(
                transaction_id=str(uuid.uuid4()).replace('-', '')[:16].upper(),
                user_id=user_id,
                amount=amount,
                currency=currency,
                tokens_purchased=tokens,
                payment_method=payment_method,
                status="pending"
            )
            await self.db.transactions.insert_one(transaction.__dict__)
            return transaction
        except Exception as e:
            logger.error(f"Error creating transaction: {e}")
            return None
    
    async def get_transaction(self, transaction_id: str) -> Optional[Transaction]:
        """Get transaction by ID"""
        if not await self.ensure_connection():
            return None
            
        try:
            transaction_data = await self.db.transactions.find_one({"transaction_id": transaction_id})
            if transaction_data:
                return Transaction(**transaction_data)
            return None
        except Exception as e:
            logger.error(f"Error getting transaction {transaction_id}: {e}")
            return None
    
    async def complete_transaction(self, transaction_id: str, payment_details: Dict = None) -> bool:
        """Mark transaction as completed"""
        if not await self.ensure_connection():
            return False
            
        try:
            update_data = {
                "$set": {
                    "status": "completed",
                    "completed_at": datetime.now()
                }
            }
            if payment_details:
                update_data["$set"]["payment_details"] = payment_details
                
            result = await self.db.transactions.update_one(
                {"transaction_id": transaction_id},
                update_data
            )
            
            if result.modified_count > 0:
                # Get transaction to add tokens to user
                transaction = await self.get_transaction(transaction_id)
                if transaction:
                    await self.update_user_tokens(transaction.user_id, transaction.tokens_purchased)
                    logger.info(f"✅ Transaction {transaction_id} completed")
            
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Error completing transaction {transaction_id}: {e}")
            return False
    
    async def get_user_transactions(self, user_id: int, limit: int = 10) -> List[Transaction]:
        """Get user's transactions"""
        if not await self.ensure_connection():
            return []
            
        try:
            cursor = self.db.transactions.find({"user_id": user_id})\
                                        .sort("created_at", -1)\
                                        .limit(limit)
            transactions = []
            async for doc in cursor:
                transactions.append(Transaction(**doc))
            return transactions
        except Exception as e:
            logger.error(f"Error getting transactions for {user_id}: {e}")
            return []
    
    # ========== Recent Transactions Method ==========
    async def get_recent_transactions(self, limit: int = 20) -> List[Transaction]:
        """Get recent transactions across all users"""
        if not await self.ensure_connection():
            return []
        
        try:
            cursor = self.db.transactions.find().sort("created_at", -1).limit(limit)
            transactions = []
            async for doc in cursor:
                transactions.append(Transaction(**doc))
            return transactions
        except Exception as e:
            logger.error(f"Error getting recent transactions: {e}")
            return []
    
    # ========== Token Packages Methods ==========
    
    async def get_token_packages(self) -> List[TokenPackage]:
        """Get all active token packages"""
        if not await self.ensure_connection():
            # Return default packages if database not connected
            return self._get_default_packages()
            
        try:
            cursor = self.db.token_packages.find({"is_active": True}).sort("tokens", 1)
            packages = []
            async for doc in cursor:
                packages.append(TokenPackage(**doc))
            return packages if packages else self._get_default_packages()
        except Exception as e:
            logger.error(f"Error getting token packages: {e}")
            return self._get_default_packages()
    
    async def get_package(self, package_id: str) -> Optional[TokenPackage]:
        """Get package by ID"""
        if not await self.ensure_connection():
            return None
            
        try:
            package_data = await self.db.token_packages.find_one({"package_id": package_id})
            if package_data:
                return TokenPackage(**package_data)
            return None
        except Exception as e:
            logger.error(f"Error getting package {package_id}: {e}")
            return None
    
    def _get_default_packages(self):
        """Return default token packages"""
        return [
            TokenPackage(
                package_id="basic",
                name="Basic Pack",
                tokens=5,
                price_stars=50,
                price_inr=50,
                description="5 reports - Perfect for testing"
            ),
            TokenPackage(
                package_id="standard",
                name="Standard Pack",
                tokens=15,
                price_stars=120,
                price_inr=120,
                description="15 reports - Most popular choice"
            ),
            TokenPackage(
                package_id="premium",
                name="Premium Pack",
                tokens=30,
                price_stars=200,
                price_inr=200,
                description="30 reports - Great value"
            ),
            TokenPackage(
                package_id="pro",
                name="Pro Pack",
                tokens=100,
                price_stars=500,
                price_inr=500,
                description="100 reports - For power users"
            )
        ]
    
    # ========== Template Methods ==========
    
    async def get_templates(self, category: str = None) -> List[ReportTemplate]:
        """Get report templates"""
        if not await self.ensure_connection():
            return []
            
        try:
            query = {"is_public": True}
            if category:
                query["category"] = category
                
            cursor = self.db.report_templates.find(query).sort("name", 1)
            templates = []
            async for doc in cursor:
                templates.append(ReportTemplate(**doc))
            return templates
        except Exception as e:
            logger.error(f"Error getting templates: {e}")
            return []
    
    async def get_template(self, template_id: str) -> Optional[ReportTemplate]:
        """Get template by ID"""
        if not await self.ensure_connection():
            return None
            
        try:
            template_data = await self.db.report_templates.find_one({"template_id": template_id})
            if template_data:
                return ReportTemplate(**template_data)
            return None
        except Exception as e:
            logger.error(f"Error getting template {template_id}: {e}")
            return None
    
    # ========== Statistics Methods ==========
    
    async def get_account_stats(self) -> dict:
        """Get account statistics"""
        if not await self.ensure_connection():
            return {"total": 0, "active": 0, "users_with_accounts": 0}
            
        try:
            total = await self.db.accounts.count_documents({})
            active = await self.db.accounts.count_documents({"status": AccountStatus.ACTIVE.value})
            users_with_accounts = len(await self.db.accounts.distinct("user_id"))
            
            return {
                "total": total,
                "active": active,
                "users_with_accounts": users_with_accounts
            }
        except Exception as e:
            logger.error(f"Error getting account stats: {e}")
            return {"total": 0, "active": 0, "users_with_accounts": 0}
    
    async def get_report_stats(self) -> dict:
        """Get report statistics"""
        if not await self.ensure_connection():
            return {"total": 0, "pending": 0, "reviewed": 0, "resolved": 0, "rejected": 0, "today": 0, "by_type": {}}
            
        try:
            total = await self.db.reports.count_documents({})
            pending = await self.db.reports.count_documents({"status": ReportStatus.PENDING.value})
            reviewed = await self.db.reports.count_documents({"status": ReportStatus.REVIEWED.value})
            resolved = await self.db.reports.count_documents({"status": ReportStatus.RESOLVED.value})
            rejected = await self.db.reports.count_documents({"status": ReportStatus.REJECTED.value})
            
            # Today's reports
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            today = await self.db.reports.count_documents({"created_at": {"$gte": today_start}})
            
            # Reports by type
            pipeline = [
                {"$group": {"_id": "$report_type", "count": {"$sum": 1}}}
            ]
            by_type = {}
            async for doc in self.db.reports.aggregate(pipeline):
                by_type[doc["_id"]] = doc["count"]
            
            return {
                "total": total,
                "pending": pending,
                "reviewed": reviewed,
                "resolved": resolved,
                "rejected": rejected,
                "today": today,
                "by_type": by_type
            }
        except Exception as e:
            logger.error(f"Error getting report stats: {e}")
            return {"total": 0, "pending": 0, "reviewed": 0, "resolved": 0, "rejected": 0, "today": 0, "by_type": {}}
    
    async def get_bot_stats(self) -> dict:
        """Get comprehensive bot statistics"""
        user_count = await self.get_user_count()
        report_stats = await self.get_report_stats()
        account_stats = await self.get_account_stats()
        
        # Transaction stats
        try:
            total_revenue_pipeline = [
                {"$match": {"status": "completed"}},
                {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
            ]
            total_revenue_result = await self.db.transactions.aggregate(total_revenue_pipeline).to_list(1)
            total_revenue = total_revenue_result[0]['total'] if total_revenue_result else 0
            
            total_tokens_pipeline = [
                {"$match": {"status": "completed"}},
                {"$group": {"_id": None, "total": {"$sum": "$tokens_purchased"}}}
            ]
            total_tokens_result = await self.db.transactions.aggregate(total_tokens_pipeline).to_list(1)
            total_tokens = total_tokens_result[0]['total'] if total_tokens_result else 0
        except:
            total_revenue = 0
            total_tokens = 0
        
        return {
            "users": user_count,
            "reports": report_stats,
            "accounts": account_stats,
            "total_revenue": total_revenue,
            "total_tokens_sold": total_tokens
        }

# Global database instance
db = Database()