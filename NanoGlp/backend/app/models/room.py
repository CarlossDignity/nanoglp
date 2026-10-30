from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from app.database import Base


class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    code = Column(String(50), unique=True, index=True, nullable=False) # Örn: ODA-HAYVAN-01, LAB-KİMYA-02
    room_type = Column(String(50), nullable=False) # Hayvan Ünitesi, Hücre Kültürü, Enstrümantal Analiz, Hazırlık vb.
    capacity = Column(Integer, default=1) # Aynı anda çalışabilecek maksimum personel / işlem sayısı
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    equipment_list = relationship("Equipment", back_populates="room")
    study_steps = relationship("StudyStep", back_populates="room")
