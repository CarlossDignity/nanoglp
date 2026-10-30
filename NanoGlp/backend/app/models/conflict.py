import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Enum, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class ConflictType(str, enum.Enum):
    PERSONNEL_OVERLAP = "PERSONNEL_OVERLAP"               # Personel zaman çakışması veya aşırı yük
    EQUIPMENT_OVERLAP = "EQUIPMENT_OVERLAP"               # Cihaz rezervasyon çakışması
    ROOM_CAPACITY_EXCEEDED = "ROOM_CAPACITY_EXCEEDED"     # Oda/Kabin kapasitesi aşımı
    BIOLOGICAL_TIME_VIOLATION = "BIOLOGICAL_TIME_VIOLATION" # Biyolojik kilitli saat ihlali (AI asla kaydıramaz!)
    CALIBRATION_EXPIRED = "CALIBRATION_EXPIRED"           # Kalibrasyonu geçmiş cihaz kullanımı
    QUALIFICATION_MISMATCH = "QUALIFICATION_MISMATCH"     # Personel GLP yetkinlik/eğitim uyumsuzluğu


class ConflictSeverity(str, enum.Enum):
    CRITICAL = "CRITICAL" # GLP kural ihlali veya fiziksel imkansızlık (engelleme gerektirir)
    WARNING = "WARNING"   # Kapasite sınırına yakınlık veya risk
    INFO = "INFO"         # Optimizasyon önerisi


class Conflict(Base):
    __tablename__ = "conflicts"

    id = Column(Integer, primary_key=True, index=True)
    conflict_type = Column(Enum(ConflictType), nullable=False)
    severity = Column(Enum(ConflictSeverity), default=ConflictSeverity.CRITICAL, nullable=False)
    
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    
    study_id = Column(Integer, ForeignKey("studies.id"), nullable=True)
    step_id = Column(Integer, ForeignKey("study_steps.id"), nullable=True)
    # Çakışmanın karşı tarafındaki çalışma (örn. taslak ↔ taslak veya taslak ↔ onaylı)
    related_study_id = Column(Integer, ForeignKey("studies.id"), nullable=True)
    
    is_resolved = Column(Boolean, default=False, nullable=False)
    resolved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)
    
    detected_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    study = relationship("Study", foreign_keys=[study_id], back_populates="conflicts")
    related_study = relationship("Study", foreign_keys=[related_study_id])
    step = relationship("StudyStep", back_populates="conflicts")
    resolved_by = relationship("User", foreign_keys=[resolved_by_id])
