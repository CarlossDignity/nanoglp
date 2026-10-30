import enum
from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, Enum, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class EquipmentStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"            # Müsait / Kullanıma Hazır
    IN_USE = "IN_USE"                  # Kullanımda
    MAINTENANCE = "MAINTENANCE"        # Bakımda
    CALIBRATION_DUE = "CALIBRATION_DUE"# Kalibrasyon Süresi Dolmuş (GLP gereği kilitli)
    OUT_OF_SERVICE = "OUT_OF_SERVICE"  # Hizmet Dışı


class Equipment(Base):
    __tablename__ = "equipment"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False) # Örn: UV-Vis Spektrofotometre, HPLC-01, CO2 İnkübatörü
    code = Column(String(50), unique=True, index=True, nullable=False) # Cihaz Envanter Kodu
    category = Column(String(100), nullable=False) # Spektrometri, Kromatografi, İnkübasyon vb.
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=True)
    
    status = Column(Enum(EquipmentStatus), default=EquipmentStatus.AVAILABLE, nullable=False)
    calibration_due_date = Column(Date, nullable=True) # Kalibrasyon geçerlilik tarihi
    polar_capacity = Column(Integer, default=3, nullable=True)      # Polar ekstraksiyon eşzamanlı çalışma kapasitesi (Max: 3)
    non_polar_capacity = Column(Integer, default=1, nullable=True)  # Apolar (Non-Polar) eşzamanlı çalışma kapasitesi (Max: 1)
    notes = Column(String(255), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    room = relationship("Room", back_populates="equipment_list")
    study_steps = relationship("StudyStep", back_populates="equipment")
