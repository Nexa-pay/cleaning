from datetime import datetime
from typing import Optional, List, Dict
from dataclasses import dataclass, field
import enum

class UserRole(enum.Enum):
    NORMAL = "normal"
    PREMIUM = "premium"
    ADMIN = "admin"
    OWNER = "owner"
    SUPER_ADMIN = "super_admin"

class AccountStatus(enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    BANNED = "banned"

class ReportStatus(enum.Enum):
    PENDING = "pending"
    REVIEWED = "reviewed"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    PROCESSING = "processing"

@dataclass
class User:
    user_id: int
    username: Optional[str]
    first_name: str
    last_name: Optional[str] = None
    role: UserRole = UserRole.NORMAL
    tokens: int = 0
    total_reports: int = 0
    joined_date: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
    is_blocked: bool = False
    language: str = "en"
    referred_by: Optional[int] = None
    
    def to_dict(self):
        data = self.__dict__.copy()
        data['role'] = data['role'].value
        return data
    
    @classmethod
    def from_dict(cls, data):
        if 'role' in data and isinstance(data['role'], str):
            data['role'] = UserRole(data['role'])
        return cls(**data)

@dataclass
class TelegramAccount:
    account_id: str
    user_id: int
    phone_number: str
    session_string: str
    account_name: str
    status: AccountStatus = AccountStatus.ACTIVE
    added_date: datetime = field(default_factory=datetime.now)
    last_used: Optional[datetime] = None
    total_reports_used: int = 0
    is_primary: bool = False
    twofa_password: Optional[str] = None
    
    def to_dict(self):
        data = self.__dict__.copy()
        data['status'] = data['status'].value
        return data
    
    @classmethod
    def from_dict(cls, data):
        if 'status' in data and isinstance(data['status'], str):
            data['status'] = AccountStatus(data['status'])
        return cls(**data)

@dataclass
class ActiveSession:
    session_id: str
    user_id: int
    account_id: str
    login_time: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    expires_at: datetime

@dataclass
class Transaction:
    transaction_id: str
    user_id: int
    amount: float
    currency: str
    tokens_purchased: int
    payment_method: str
    status: str
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    payment_details: Dict = field(default_factory=dict)

@dataclass
class Report:
    report_id: str
    user_id: int
    account_id: str
    report_type: str
    target: str
    reason: str
    details: str
    status: ReportStatus = ReportStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    tokens_used: int = 1
    result: Optional[str] = None
    evidence: List[str] = field(default_factory=list)
    
    def to_dict(self):
        data = self.__dict__.copy()
        data['status'] = data['status'].value
        return data
    
    @classmethod
    def from_dict(cls, data):
        if 'status' in data and isinstance(data['status'], str):
            data['status'] = ReportStatus(data['status'])
        return cls(**data)

@dataclass
class TokenPackage:
    package_id: str
    name: str
    tokens: int
    price_stars: int
    price_inr: int
    is_active: bool = True
    description: str = ""

@dataclass
class ReportTemplate:
    template_id: str
    name: str
    category: str
    content: str
    created_by: int
    is_public: bool = False
    created_at: datetime = field(default_factory=datetime.now)