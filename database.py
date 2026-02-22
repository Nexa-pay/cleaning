import motor.motor_asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import logging
import uuid

from models import *
import config
from utils import encrypt_data, decrypt_data

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.client = None
        self.db = None
        
    async def connect(self):
        """Connect to MongoDB"""
        try:
            if not config.MONGODB_URI:
                logger.error("MONGODB_URI not set!")
                return False
                
            self.client = motor.motor_asyncio.AsyncIOMotorClient(config.MONGODB_URI)
            self.db = self.client[config.DATABASE_NAME]
            
            # Create indexes
            await self.db.users.create_index("user_id", unique=True)
            await self.db.accounts.create_index([("user_id", 1), ("account_id", 1)], unique=True)
            await self.db.sessions.create_index("session_id", unique=True)
            await self.db.sessions.create_index("expires_at", expireAfterSeconds=0)
            await self.db.transactions.create_index("transaction_id", unique=True)
            await self.db.reports.create_index("report_id", unique=True)
            await self.db.reports.create_index([("user_id", 1), ("created_at", -1)])
            await self.db.reports.create_index([("status", 1), ("created_at", -1)])
            
            # Initialize default data
            await self.init_token_packages()
            await self.init_report_templates()
            
            logger.info("✅ Database connected successfully")
            return True
        except Exception as e:
            logger.error(f"❌ Database connection failed: {e}")
            return False
    
    async def init_token_packages(self):
        """Initialize default token packages"""
        packages = [
            {
                "package_id": "basic",
                "name": "Basic Pack",
                "tokens": 5,
                "price_stars": 50,
                "price_inr": 50,
                "description": "5 reports - Perfect for testing"
            },
            {
                "package_id": "standard",
                "name": "Standard Pack", 
                "tokens": 15,
                "price_stars": 120,
                "price_inr": 120,
                "description": "15 reports - Most popular choice"
            },
            {
                "package_id": "premium",
                "name": "Premium Pack",
                "tokens": 30,
                "price_stars": 200,
                "price_inr": 200,
                "description": "30 reports - Great value"
            },
            {
                "package_id": "pro",
                "name": "Pro Pack",
                "tokens": 100,
                "price_stars": 500,
                "price_inr": 500,
                "description": "100 reports - For power users"
            }
        ]
        
        for package in packages:
            existing = await self.db.token_packages.find_one({"package_id": package["package_id"]})
            if not existing:
                await self.db.token_packages.insert_one(package)
    
    async def init_report_templates(self):
        """Initialize default report templates"""
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
            },
            {
                "template_id": "impersonation",
                "name": "Impersonation Report",
                "category": "impersonation",
                "content": "This account is impersonating a legitimate user or organization.",
                "created_by": 0,
                "is_public": True
            },
            {
                "template_id": "illegal",
                "name": "Illegal Content",
                "category": "illegal",
                "content": "This account is sharing illegal content or engaging in illegal activities.",
                "created_by": 0,
                "is_public": True
            }
        ]
        
        for template in templates:
            existing = await self.db.report_templates.find_one({"template_id": template["template_id"]})
            if not existing:
                await self.db.report_templates.insert_one(template)
    
    # User methods
    async def get_user(self, user_id: int) -> Optional[User]:
        """Get user by ID"""
        user_data = await self.db.users.find_one({"user_id": user_id})
        if user_data:
            return User.from_dict(user_data)
        return None
    
    async def create_user(self, user_id: int, username: str, first_name: str, 
                         last_name: str = None, referred_by: int = None) -> User:
        """Create new user"""
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
    
    async def update_user(self, user_id: int, updates: dict) -> bool:
        """Update user information"""
        result = await self.db.users.update_one(
            {"user_id": user_id},
            {"$set": updates}
        )
        return result.modified_count > 0
    
    async def update_user_role(self, user_id: int, role: UserRole) -> bool:
        """Update user role"""
        result = await self.db.users.update_one(
            {"user_id": user_id},
            {"$set": {"role": role.value}}
        )
        return result.modified_count > 0
    
    async def update_user_tokens(self, user_id: int, tokens_change: int) -> bool:
        """Update user tokens (positive for add, negative for deduct)"""
        result = await self.db.users.update_one(
            {"user_id": user_id},
            {"$inc": {"tokens": tokens_change}}
        )
        return result.modified_count > 0
    
    async def update_last_active(self, user_id: int):
        """Update user's last active timestamp"""
        await self.db.users.update_one(
            {"user_id": user_id},
            {"$set": {"last_active": datetime.now()}}
        )
    
    async def add_report_count(self, user_id: int):
        """Increment user's report count"""
        await self.db.users.update_one(
            {"user_id": user_id},
            {
                "$inc": {"total_reports": 1},
                "$set": {"last_active": datetime.now()}
            }
        )
    
    async def get_all_users(self, skip: int = 0, limit: int = 100) -> List[User]:
        """Get all users with pagination"""
        cursor = self.db.users.find().skip(skip).limit(limit).sort("joined_date", -1)
        users = []
        async for doc in cursor:
            users.append(User.from_dict(doc))
        return users
    
    async def get_user_count(self) -> int:
        """Get total user count"""
        return await self.db.users.count_documents({})
    
    async def block_user(self, user_id: int) -> bool:
        """Block a user"""
        result = await self.db.users.update_one(
            {"user_id": user_id},
            {"$set": {"is_blocked": True}}
        )
        return result.modified_count > 0
    
    async def unblock_user(self, user_id: int) -> bool:
        """Unblock a user"""
        result = await self.db.users.update_one(
            {"user_id": user_id},
            {"$set": {"is_blocked": False}}
        )
        return result.modified_count > 0
    
    # Account management methods
    async def add_telegram_account(self, user_id: int, phone_number: str, 
                                  session_string: str, account_name: str,
                                  twofa_password: str = None) -> TelegramAccount:
        """Add a new Telegram account for reporting"""
        # Check account limit
        account_count = await self.db.accounts.count_documents({"user_id": user_id})
        if account_count >= config.MAX_ACCOUNTS_PER_USER:
            raise Exception(f"Maximum accounts limit reached ({config.MAX_ACCOUNTS_PER_USER})")
        
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
            is_primary=(account_count == 0)  # First account is primary
        )
        
        await self.db.accounts.insert_one(account.to_dict())
        logger.info(f"✅ New account added for user {user_id}")
        return account
    
    async def get_user_accounts(self, user_id: int) -> List[TelegramAccount]:
        """Get all accounts for a user"""
        cursor = self.db.accounts.find({"user_id": user_id})
        accounts = []
        async for doc in cursor:
            accounts.append(TelegramAccount.from_dict(doc))
        return accounts
    
    async def get_account(self, account_id: str) -> Optional[TelegramAccount]:
        """Get account by ID"""
        account_data = await self.db.accounts.find_one({"account_id": account_id})
        if account_data:
            return TelegramAccount.from_dict(account_data)
        return None
    
    async def update_account_status(self, account_id: str, status: AccountStatus) -> bool:
        """Update account status"""
        result = await self.db.accounts.update_one(
            {"account_id": account_id},
            {"$set": {"status": status.value}}
        )
        return result.modified_count > 0
    
    async def set_primary_account(self, user_id: int, account_id: str) -> bool:
        """Set an account as primary"""
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
    
    async def update_account_last_used(self, account_id: str):
        """Update account's last used timestamp"""
        await self.db.accounts.update_one(
            {"account_id": account_id},
            {
                "$set": {"last_used": datetime.now()},
                "$inc": {"total_reports_used": 1}
            }
        )
    
    async def delete_account(self, account_id: str) -> bool:
        """Delete an account"""
        result = await self.db.accounts.delete_one({"account_id": account_id})
        return result.deleted_count > 0
    
    async def get_account_stats(self) -> dict:
        """Get account statistics (admin)"""
        total = await self.db.accounts.count_documents({})
        active = await self.db.accounts.count_documents({"status": AccountStatus.ACTIVE.value})
        users_with_accounts = len(await self.db.accounts.distinct("user_id"))
        
        return {
            "total": total,
            "active": active,
            "users_with_accounts": users_with_accounts
        }
    
    # Session management
    async def create_session(self, user_id: int, account_id: str) -> ActiveSession:
        """Create an active session"""
        session = ActiveSession(
            session_id=str(uuid.uuid4()),
            user_id=user_id,
            account_id=account_id,
            expires_at=datetime.now() + timedelta(seconds=config.SESSION_TIMEOUT)
        )
        await self.db.sessions.insert_one(session.__dict__)
        return session
    
    async def get_active_session(self, session_id: str) -> Optional[ActiveSession]:
        """Get active session"""
        session_data = await self.db.sessions.find_one({
            "session_id": session_id,
            "expires_at": {"$gt": datetime.now()}
        })
        if session_data:
            return ActiveSession(**session_data)
        return None
    
    async def end_session(self, session_id: str) -> bool:
        """End a session"""
        result = await self.db.sessions.delete_one({"session_id": session_id})
        return result.deleted_count > 0
    
    async def cleanup_expired_sessions(self):
        """Clean up expired sessions"""
        result = await self.db.sessions.delete_many({
            "expires_at": {"$lt": datetime.now()}
        })
        if result.deleted_count > 0:
            logger.info(f"Cleaned up {result.deleted_count} expired sessions")
    
    # Transaction methods
    async def create_transaction(self, user_id: int, amount: float, currency: str,
                                tokens: int, payment_method: str) -> Transaction:
        """Create a new transaction"""
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
    
    async def get_transaction(self, transaction_id: str) -> Optional[Transaction]:
        """Get transaction by ID"""
        transaction_data = await self.db.transactions.find_one({"transaction_id": transaction_id})
        if transaction_data:
            return Transaction(**transaction_data)
        return None
    
    async def complete_transaction(self, transaction_id: str, payment_details: Dict = None) -> bool:
        """Mark transaction as completed"""
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
                logger.info(f"✅ Transaction {transaction_id} completed, added {transaction.tokens_purchased} tokens")
        
        return result.modified_count > 0
    
    async def get_user_transactions(self, user_id: int, limit: int = 10) -> List[Transaction]:
        """Get user's transactions"""
        cursor = self.db.transactions.find({"user_id": user_id}).sort("created_at", -1).limit(limit)
        transactions = []
        async for doc in cursor:
            transactions.append(Transaction(**doc))
        return transactions
    
    async def get_pending_transactions(self) -> List[Transaction]:
        """Get pending transactions for admin"""
        cursor = self.db.transactions.find({"status": "pending"}).sort("created_at", 1)
        transactions = []
        async for doc in cursor:
            transactions.append(Transaction(**doc))
        return transactions
    
    # Report methods
    async def create_report(self, user_id: int, account_id: str, report_type: str,
                          target: str, reason: str, details: str,
                          tokens_used: int = 1, evidence: List[str] = None) -> Report:
        """Create a new report"""
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
        
        # Update account usage
        await self.update_account_last_used(account_id)
        
        logger.info(f"✅ New report created: {report.report_id} by user {user_id}")
        return report
    
    async def get_report(self, report_id: str) -> Optional[Report]:
        """Get report by ID"""
        report_data = await self.db.reports.find_one({"report_id": report_id})
        if report_data:
            return Report.from_dict(report_data)
        return None
    
    async def get_user_reports(self, user_id: int, page: int = 1) -> List[Report]:
        """Get user's reports with pagination"""
        skip = (page - 1) * config.REPORTS_PER_PAGE
        cursor = self.db.reports.find({"user_id": user_id})\
                               .sort("created_at", -1)\
                               .skip(skip)\
                               .limit(config.REPORTS_PER_PAGE)
        
        reports = []
        async for doc in cursor:
            reports.append(Report.from_dict(doc))
        return reports
    
    async def get_pending_reports(self, limit: int = 50) -> List[Report]:
        """Get pending reports for admin"""
        cursor = self.db.reports.find({"status": ReportStatus.PENDING.value})\
                               .sort("created_at", 1)\
                               .limit(limit)
        
        reports = []
        async for doc in cursor:
            reports.append(Report.from_dict(doc))
        return reports
    
    async def get_all_reports(self, status: str = None, page: int = 1, limit: int = 50) -> List[Report]:
        """Get all reports with filters"""
        query = {}
        if status:
            query["status"] = status
            
        skip = (page - 1) * limit
        cursor = self.db.reports.find(query)\
                               .sort("created_at", -1)\
                               .skip(skip)\
                               .limit(limit)
        
        reports = []
        async for doc in cursor:
            reports.append(Report.from_dict(doc))
        return reports
    
    async def update_report_status(self, report_id: str, status: ReportStatus,
                                  reviewed_by: int, result: str = None) -> bool:
        """Update report status"""
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
    
    async def get_report_stats(self) -> dict:
        """Get report statistics"""
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
    
    # Template methods
    async def get_templates(self, category: str = None) -> List[ReportTemplate]:
        """Get report templates"""
        query = {"is_public": True}
        if category:
            query["category"] = category
            
        cursor = self.db.report_templates.find(query).sort("name", 1)
        templates = []
        async for doc in cursor:
            templates.append(ReportTemplate(**doc))
        return templates
    
    async def get_template(self, template_id: str) -> Optional[ReportTemplate]:
        """Get template by ID"""
        template_data = await self.db.report_templates.find_one({"template_id": template_id})
        if template_data:
            return ReportTemplate(**template_data)
        return None
    
    async def create_template(self, template: ReportTemplate) -> bool:
        """Create a custom template"""
        result = await self.db.report_templates.insert_one(template.__dict__)
        return result.inserted_id is not None
    
    # Token package methods
    async def get_token_packages(self) -> List[TokenPackage]:
        """Get all active token packages"""
        cursor = self.db.token_packages.find({"is_active": True}).sort("tokens", 1)
        packages = []
        async for doc in cursor:
            packages.append(TokenPackage(**doc))
        return packages
    
    async def get_package(self, package_id: str) -> Optional[TokenPackage]:
        """Get package by ID"""
        package_data = await self.db.token_packages.find_one({"package_id": package_id})
        if package_data:
            return TokenPackage(**package_data)
        return None
    
    # Statistics methods
    async def get_bot_stats(self) -> dict:
        """Get comprehensive bot statistics"""
        user_count = await self.get_user_count()
        report_stats = await self.get_report_stats()
        account_stats = await self.get_account_stats()
        
        # Transaction stats
        total_revenue_pipeline = [
            {"$match": {"status": "completed"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
        ]
        total_revenue = await self.db.transactions.aggregate(total_revenue_pipeline).to_list(1)
        total_revenue = total_revenue[0]['total'] if total_revenue else 0
        
        total_tokens_pipeline = [
            {"$match": {"status": "completed"}},
            {"$group": {"_id": None, "total": {"$sum": "$tokens_purchased"}}}
        ]
        total_tokens = await self.db.transactions.aggregate(total_tokens_pipeline).to_list(1)
        total_tokens = total_tokens[0]['total'] if total_tokens else 0
        
        return {
            "users": user_count,
            "reports": report_stats,
            "accounts": account_stats,
            "total_revenue": total_revenue,
            "total_tokens_sold": total_tokens
        }

# Global database instance
db = Database()