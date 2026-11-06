from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from app.database import Base


class UserAccessLog(Base):
    __tablename__ = "user_access_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    username = Column(String(100), nullable=True)
    attempted_identifier = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    full_name = Column(String(255), nullable=True)
    role = Column(String(64), nullable=True)
    event_type = Column(String(20), nullable=False, index=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(1024), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
