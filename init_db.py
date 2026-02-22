#!/usr/bin/env python3
"""
Database Initialization Script
Run this once to set up your database with required data
"""

import asyncio
import logging
from database import db
from models import UserRole, TokenPackage
import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def init_database():
    """Initialize database with required data"""
    print("=" * 50)
    print("🔧 Database Initialization Script")
    print("=" * 50)
    
    # Connect to database
    print("\n🔄 Connecting to MongoDB...")
    connected = await db.connect()
    
    if not connected:
        print("❌ Failed to connect to database!")
        print("Please check your MONGODB_URI in environment variables.")
        return False
    
    print("✅ Database connected successfully!")
    
    # Check if admin users exist
    print("\n🔍 Checking for admin users...")
    
    admin_ids = config.ADMIN_IDS
    owner_ids = config.OWNER_IDS
    super_admin_id = config.SUPER_ADMIN_ID
    
    # Create admin users if they don't exist
    all_admins = set()
    all_admins.update(admin_ids)
    all_admins.update(owner_ids)
    if super_admin_id:
        all_admins.add(super_admin_id)
    
    for user_id in all_admins:
        user = await db.get_user(user_id)
        if not user:
            # Create user
            role = UserRole.NORMAL
            if user_id == super_admin_id:
                role = UserRole.SUPER_ADMIN
            elif user_id in owner_ids:
                role = UserRole.OWNER
            elif user_id in admin_ids:
                role = UserRole.ADMIN
            
            user_data = {
                "user_id": user_id,
                "username": f"admin_{user_id}",
                "first_name": "Admin",
                "last_name": None,
                "role": role.value,
                "tokens": 1000,  # Give admins 1000 tokens
                "total_reports": 0,
                "joined_date": datetime.now(),
                "last_active": datetime.now(),
                "is_blocked": False,
                "language": "en",
                "referred_by": None
            }
            
            await db.db.users.insert_one(user_data)
            print(f"✅ Created admin user: {user_id} with role {role.value}")
        else:
            print(f"✅ Admin user already exists: {user_id}")
    
    # Create token packages if they don't exist
    print("\n🔍 Checking token packages...")
    
    packages = [
        {
            "package_id": "basic",
            "name": "Basic Pack",
            "tokens": 5,
            "price_stars": 50,
            "price_inr": 50,
            "is_active": True,
            "description": "5 reports - Perfect for testing"
        },
        {
            "package_id": "standard",
            "name": "Standard Pack",
            "tokens": 15,
            "price_stars": 120,
            "price_inr": 120,
            "is_active": True,
            "description": "15 reports - Most popular choice"
        },
        {
            "package_id": "premium",
            "name": "Premium Pack",
            "tokens": 30,
            "price_stars": 200,
            "price_inr": 200,
            "is_active": True,
            "description": "30 reports - Great value"
        },
        {
            "package_id": "pro",
            "name": "Pro Pack",
            "tokens": 100,
            "price_stars": 500,
            "price_inr": 500,
            "is_active": True,
            "description": "100 reports - For power users"
        }
    ]
    
    for package in packages:
        existing = await db.db.token_packages.find_one({"package_id": package["package_id"]})
        if not existing:
            await db.db.token_packages.insert_one(package)
            print(f"✅ Created token package: {package['name']}")
        else:
            print(f"✅ Token package already exists: {package['name']}")
    
    # Create report templates
    print("\n🔍 Checking report templates...")
    
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
        existing = await db.db.report_templates.find_one({"template_id": template["template_id"]})
        if not existing:
            await db.db.report_templates.insert_one(template)
            print(f"✅ Created report template: {template['name']}")
        else:
            print(f"✅ Report template already exists: {template['name']}")
    
    print("\n" + "=" * 50)
    print("✅ Database initialization complete!")
    print("=" * 50)
    
    # Show summary
    user_count = await db.get_user_count()
    package_count = await db.db.token_packages.count_documents({})
    template_count = await db.db.report_templates.count_documents({})
    
    print(f"\n📊 Summary:")
    print(f"• Users: {user_count}")
    print(f"• Token Packages: {package_count}")
    print(f"• Report Templates: {template_count}")
    
    return True

if __name__ == "__main__":
    from datetime import datetime
    asyncio.run(init_database())
