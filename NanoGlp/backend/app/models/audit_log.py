from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, ForeignKey
from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True) # İşlemi yapan kullanıcı (Sistem ise null)
    user_email = Column(String(255), nullable=True)
    
    entity_name = Column(String(100), nullable=False) # örn: Study, StudyStep, Equipment
    entity_id = Column(Integer, nullable=False)
    action = Column(String(50), nullable=False)       # CREATE, UPDATE, DELETE, AI_PROPOSAL_APPLY, OVERRIDE
    
    old_values = Column(JSON, nullable=True)
    new_values = Column(JSON, nullable=True)
    
    reason = Column(Text, nullable=True) # GLP zorunluluğu: Değişiklik gerekçesi
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
