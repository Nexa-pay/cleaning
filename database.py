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
    
    async def ensure_connection(self):
        """Ensure database is connected, attempt reconnection if needed"""
        if not self.db:
            logger.warning("⚠️ Database not connected, attempting reconnection...")
            return await self.connect()
        return True
    
    # User methods
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
    
    # Token packages methods
    async def get_token_packages(self) -> List[TokenPackage]:
        """Get all active token packages"""
        if not await self.ensure_connection():
            # Return default packages if database not connected
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
                )
            ]
            
        try:
            cursor = self.db.token_packages.find({"is_active": True}).sort("tokens", 1)
            packages = []
            async for doc in cursor:
                packages.append(TokenPackage(**doc))
            return packages if packages else self._get_default_packages()
        except Exception as e:
            logger.error(f"Error getting token packages: {e}")
            return self._get_default_packages()
    
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
    
    # Add placeholder methods for other required functions
    async def get_user_reports(self, user_id: int, page: int = 1) -> List:
        """Get user's reports"""
        return []  # Return empty list for now
    
    async def get_user_transactions(self, user_id: int, limit: int = 10) -> List:
        """Get user's transactions"""
        return []  # Return empty list for now

# Global database instance
db = Database()