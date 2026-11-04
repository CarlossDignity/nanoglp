import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Enum, ForeignKey, Table
from sqlalchemy.orm import relationship
from app.database import Base


class StepStatus(str, enum.Enum):
    PENDING = "PENDING"          # Beklemede
    IN_PROGRESS = "IN_PROGRESS"  # Yürütülüyor
    COMPLETED = "COMPLETED"      # Tamamlandı
    DELAYED = "DELAYED"          # Gecikmede / Risk Var
    CANCELLED = "CANCELLED"      # İptal Edildi


# Görev ↔ Personel çoktan-çoğa atama tablosu (bir adımda birden fazla rol/kişi görev alabilir)
step_assignees = Table(
    "study_step_assignees",
    Base.metadata,
    Column("step_id", Integer, ForeignKey("study_steps.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)


class StudyStep(Base):
    __tablename__ = "study_steps"

    id = Column(Integer, primary_key=True, index=True)
    study_id = Column(Integer, ForeignKey("studies.id"), nullable=False)
    
    step_order = Column(Integer, nullable=False, default=1)
    study_day = Column(Integer, nullable=True)      # Çalışma günü (Gün 0 = aklimatizasyon başlangıcı)
    step_name = Column(String(255), nullable=False) # Örn: Test Maddesi Hazırlığı, Dozlama, Örnekleme (T=4s), Spektrofotometrik Okuma
    step_type = Column(String(100), nullable=True)  # Hazırlık, Dozlama, İnkübasyon, Analiz, vb.
    
    planned_start = Column(DateTime, nullable=False)
    planned_end = Column(DateTime, nullable=False)
    
    # -------------------------------------------------------------
    # GLP BİYOLOJİK SAAT VE KATILIK KURALLARI (MIMARI.md Madde 1 & 4)
    # "Yapay zeka hiçbir zaman biyolojik saatleri kaydıramaz."
    # -------------------------------------------------------------
    is_biological_fixed_time = Column(Boolean, default=False, nullable=False)
    biological_tolerance_minutes = Column(Integer, default=0, nullable=False) # Kabul edilebilir maksimum sapma toleransı (dk)
    
    # Kaynak Atamaları (personel ataması çoktan-çoğa: bkz. `assignees`)
    equipment_id = Column(Integer, ForeignKey("equipment.id"), nullable=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    
    # Yürütme ve Sapma Takibi
    status = Column(Enum(StepStatus), default=StepStatus.PENDING, nullable=False)
    actual_start = Column(DateTime, nullable=True)
    actual_end = Column(DateTime, nullable=True)
    actual_reference_time = Column(DateTime, nullable=True)  # Biyolojik referans olay (enjeksiyon/uygulama) gerçekleşme zamanı
    deviation_notes = Column(Text, nullable=True) # GLP Sapma Kaydı (Planlanan saatten farklı ise zorunlu açıklama)
    completed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def duration_minutes(self) -> int:
        """Adımın planlanan toplam süresi (dakika cinsinden)."""
        if self.planned_start and self.planned_end:
            return max(0, int((self.planned_end - self.planned_start).total_seconds() / 60))
        return 0

    @property
    def assignee_ids(self):
        return [u.id for u in self.assignees]

    # Relationships
    study = relationship("Study", back_populates="steps")
    assignees = relationship("User", secondary=step_assignees, back_populates="assigned_steps", order_by="User.id")
    completed_by = relationship("User", foreign_keys=[completed_by_id])
    equipment = relationship("Equipment", back_populates="study_steps")
    room = relationship("Room", back_populates="study_steps")
    conflicts = relationship("Conflict", back_populates="step", cascade="all, delete-orphan")
