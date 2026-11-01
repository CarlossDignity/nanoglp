import enum
from datetime import datetime, date
from sqlalchemy import Boolean, Column, Integer, JSON, String, Text, DateTime, Date, Enum, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class StudyStatus(str, enum.Enum):
    DRAFT = "DRAFT"                  # Taslak
    APPROVED = "APPROVED"            # Plan Onaylandı
    IN_PROGRESS = "IN_PROGRESS"      # Test Uygulama Aşamasında
    REPORTING = "REPORTING"          # Raporlama Aşamasında
    COMPLETED = "COMPLETED"          # Tamamlandı / Arşivlendi
    CANCELLED = "CANCELLED"          # İptal Edildi


class Study(Base):
    __tablename__ = "studies"

    id = Column(Integer, primary_key=True, index=True)
    study_code = Column(String(100), unique=True, index=True, nullable=False)  # GLP Çalışma No (Örn: GLP2026-024)
    title = Column(String(255), nullable=False)                                # Çalışma Adı
    template_code = Column(String(60), nullable=True, default="ISO_10993_23_IC")
    test_type = Column(String(255), nullable=True)                             # Test Türü
    guideline = Column(String(255), nullable=True)                             # Standart / Kılavuz (Örn: ISO 10993-23)

    sponsor_name = Column(String(255), nullable=True)                          # Sponsor / Müşteri Firma Ünvanı
    sponsor_contact = Column(Text, nullable=True)                              # İlgili kişi, e-posta, telefon, adres

    test_item_name = Column(String(255), nullable=False)                       # Test Maddesi / Ürün Adı
    test_item_batch = Column(String(100), nullable=True)                       # Lot / Batch / Seri No
    manufacture_date = Column(String(100), nullable=True)                      # Üretim Tarihi
    expiry_date = Column(String(100), nullable=True)                           # Son Kullanma Tarihi
    test_item_storage_condition = Column(String(100), nullable=True)           # Saklama Koşulu
    physical_state = Column(String(255), nullable=True)                        # Fiziksel Görünüm
    sterility = Column(String(255), nullable=True)                             # Sterilite Durumu

    # Ekstraksiyon & Çözücü Bilgileri (TIIS Formu)
    extraction_polar = Column(Boolean, nullable=True)
    extraction_polar_solvent = Column(String(255), nullable=True)
    extraction_non_polar = Column(Boolean, nullable=True)
    extraction_non_polar_solvent = Column(String(255), nullable=True)
    extraction_ratio = Column(String(255), nullable=True)
    extraction_conditions = Column(String(255), nullable=True)

    # Hayvan & Aklimatizasyon Bilgileri (Hayvan Menşei Sertifikası & FM.083)
    animal_species_strain = Column(String(255), nullable=True)
    animal_count = Column(Integer, nullable=True)
    animal_birth_date = Column(String(255), nullable=True)
    acclimatization_start_date = Column(Date, nullable=True)
    extraction_start_offset_days = Column(Integer, default=0, nullable=True)
    requested_start_period = Column(String(255), nullable=True)

    # GLP Zorunlu Roller
    study_director_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # Çalışma Yöneticisi (SD)
    qa_officer_id = Column(Integer, ForeignKey("users.id"), nullable=True)       # Kalite Güvence Sorumlusu (QA)

    status = Column(Enum(StudyStatus), default=StudyStatus.DRAFT, nullable=False)
    protocol_approved_at = Column(DateTime, nullable=True)

    target_start_date = Column(Date, nullable=True)
    target_end_date = Column(Date, nullable=True)

    description = Column(Text, nullable=True)
    dossier_metadata = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    study_director = relationship("User", foreign_keys=[study_director_id], back_populates="directed_studies")
    qa_officer = relationship("User", foreign_keys=[qa_officer_id], back_populates="qa_studies")
    steps = relationship("StudyStep", back_populates="study", cascade="all, delete-orphan", order_by="StudyStep.step_order")
    conflicts = relationship("Conflict", foreign_keys="[Conflict.study_id]", back_populates="study", cascade="all, delete-orphan")
