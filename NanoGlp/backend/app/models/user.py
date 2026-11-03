import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON, TypeDecorator
from sqlalchemy.orm import relationship
from app.database import Base


class UserRole(str, enum.Enum):
    SYSADMIN = "SYSADMIN"                          # Sistem Yöneticisi (Kurumsal Admin)
    EXECUTIVE = "EXECUTIVE"                        # Üst Yönetim (GM / GMY — Salt Okunur İzleme)
    TFM = "TFM"                                    # Test Facility Management (Test Tesis Yöneticisi)
    STUDY_DIRECTOR = "STUDY_DIRECTOR"              # Çalışma Yöneticisi (SD)
    PLANNING_COORDINATOR = "PLANNING_COORDINATOR"  # Planlama Koordinatörü
    QA = "QA"                                      # Kalite Güvence Birimi
    ANALYST = "ANALYST"                            # Analist
    TECHNICIAN = "TECHNICIAN"                      # Teknisyen
    ADMIN = "ADMIN"                                # Eski uyumluluk rolü


class DynamicRole(str):
    """SYSADMIN tarafından çalışma zamanında eklenen özel roller için UserRole uyumlu sarmalayıcı."""

    @property
    def value(self) -> str:
        return str(self)


class FlexibleRoleType(TypeDecorator):
    """Hem standart UserRole enum değerlerini hem de dinamik oluşturulan özel rol kodlarını saklar."""

    impl = String(64)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, enum.Enum):
            return value.value
        return str(value).strip().upper()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        val_str = str(value).strip().upper()
        try:
            return UserRole(val_str)
        except ValueError:
            return DynamicRole(val_str)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    # Kurumsal kullanıcı adı: boşluksuz, benzersiz, alfanumerik ve _ - . karakterleri
    username = Column(String(100), unique=True, index=True, nullable=False)
    # E-posta opsiyoneldir: GLP gereği sistem kişiye ait veri uyduramaz; bilinmiyorsa boş bırakılır.
    email = Column(String(255), unique=True, index=True, nullable=True)
    hashed_password = Column(String(255), nullable=True)
    full_name = Column(String(255), nullable=False)
    role = Column(FlexibleRoleType(), default=UserRole.ANALYST, nullable=False)
    department = Column(String(120), nullable=True)
    is_active = Column(Boolean, default=True)

    # Personel GLP yetkinlik sertifikaları ve yapabileceği test türleri listesi
    qualifications = Column(JSON, default=list)

    # Günlük maksimum çalışma saati (GLP aşırı yük/yorgunluk engeli)
    max_daily_hours = Column(Integer, default=9)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    directed_studies = relationship("Study", foreign_keys="[Study.study_director_id]", back_populates="study_director")
    qa_studies = relationship("Study", foreign_keys="[Study.qa_officer_id]", back_populates="qa_officer")
    # Çok kişilik görev ataması (örn. Gün 7 uygulaması: SD + Teknisyen)
    assigned_steps = relationship("StudyStep", secondary="study_step_assignees", back_populates="assignees")
