import motor.motor_asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import logging
import uuid
import asyncio

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
        """Connect to MongoDB with retry logic"""
        try:
            if not config.MONGODB_URI:
                logger.error("❌ MONGODB_URI not set in environment variables!")
                return False
                
            logger.info(f"🔄 Attempting to connect to MongoDB...")
            
            # Connect with timeout
            self.client = motor.motor_asyncio.AsyncIOMotorClient(
                config.MONGODB_URI,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000
            )
            
            # Test connection
            await self.client.admin.command('ping')
            logger.info("✅ MongoDB ping successful!")
            
            # Get database
            self.db = self.client[config.DATABASE_NAME]
            logger.info(f"✅ Using database: {config.DATABASE_NAME}")
            
            # Initialize default data
            await self._init_default_data()
            
            # Create indexes (with error handling)
            try:
                await self._create_indexes()
                logger.info("✅ Database indexes created successfully!")
            except Exception as e:
                logger.error(f"⚠️ Index creation warning: {e}")
            
            logger.info("✅ Database connected successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Database connection failed: {e}")
            self.client = None
            self.db = None
            return False
    
    async def _create_indexes(self):
        """Create database indexes"""
        if not self.db:
            return
            
        # Users collection indexes
        await self.db.users.create_index("user_id", unique=True)
        
        # Accounts collection indexes
        await self.db.accounts.create_index([("user_id", 1), ("account_id", 1)], unique=True)
        
        # Sessions collection indexes
        await self.db.sessions.create_index("session_id", unique=True)
        await self.db.sessions.create_index("expires_at", expireAfterSeconds=0)
        
        # Transactions collection indexes
        await self.db.transactions.create_index("transaction_id", unique=True)
        
        # Reports collection indexes
        await self.db.reports.create_index("report_id", unique=True)
        await self.db.reports.create_index([("user_id", 1), ("created_at", -1)])
        await self.db.reports.create_index([("status", 1), ("created_at", -1)])
        
        # Token packages indexes
        await self.db.token_packages.create_index("package_id", unique=True)
        
        # Report templates indexes
        await self.db.report_templates.create_index("template_id", unique=True)
    
    async def _init_default_data(self):
        """Initialize default data in database"""
        if not self.db:
            return
            
        # Initialize token packages if not exist
        packages = self._get_default_packages()
        for package in packages:
            existing = await self.db.token_packages.find_one({"package_id": package.package_id})
            if not existing:
                await self.db.token_packages.insert_one(package.__dict__)
        
        # Initialize report templates if not exist
        templates = [
            {
                "template_id": "spam",
                "name": "Spam Report",
                "category": "spam",
                "content": "This account is sending spam messages including promotional content and unwanted advertisements.",
                "created_by": 0,
                "is_public": True
            },
            {
                "template_id": "scam",
                "name": "Scam Report",
                "category": "scam",
                "content": "This account is attempting to scam users by promising fake rewards and requesting personal information.",
                "created_by": 0,
                "is_public": True
            },
            {
                "template_id": "harassment",
                "name": "Harassment Report",
                "category": "harassment",
                "content": "This user is engaging in harassment, bullying, and making threats against others.",
                "created_by": 0,
                "is_public": True
            }
        ]
        
        for template in templates:
            existing = await self.db.report_templates.find_one({"template_id": template["template_id"]})
            if not existing:
                await self.db.report_templates.insert_one(template)
    
    async def ensure_connection(self):
        """Ensure database is connected, attempt reconnection if needed"""
        if not self.db or not self.client:
            logger.warning("⚠️ Database not connected, attempting reconnection...")
            return await self.connect()
        return True
    
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