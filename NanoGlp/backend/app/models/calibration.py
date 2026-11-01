from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from app.database import Base


class SystemCalibration(Base):
    """
    FAZ 6.4: Sistem Kalibrasyonu — Şablon adım süreleri, başlangıç saatleri ve biyolojik tolerans pencereleri.
    Settings.jsx ekranından güncellenir, AuditLog üretir ve scheduling_engine.py doğrudan bu değerleri kullanır.
    """
    __tablename__ = "system_calibrations"

    id = Column(Integer, primary_key=True, index=True)
    template_code = Column(String(60), nullable=False, index=True, default="ISO_10993_23_IC")
    step_order = Column(Integer, nullable=False, default=1)
    study_day = Column(Integer, nullable=False, default=0)
    step_name = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False, default="Gözlem")
    start_time = Column(String(10), nullable=False, default="09:00")
    duration_minutes = Column(Integer, nullable=False, default=60)
    tolerance_minutes = Column(Integer, nullable=False, default=0)
    is_biological_fixed_time = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
