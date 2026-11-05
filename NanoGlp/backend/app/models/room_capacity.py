from datetime import datetime
from typing import Dict, List
from sqlalchemy import Column, DateTime, Float, Integer, String
from sqlalchemy.orm import Session
from app.database import Base

# FAZ 8.1 — Hayvan Odaları Kafes Kapasite Tablosu (Dr. Anoop Esneklik Yüzdesi ile)
DEFAULT_ROOM_CAPACITIES: List[Dict] = [
    {"room_code": "RABBIT_ROOM", "room_label": "Tavşan Odası", "species_label": "Tavşan (NZW)", "physical_cages": 100, "flexibility_pct": 100.0},
    {"room_code": "RAT_ROOM", "room_label": "Rat / Sıçan Odası", "species_label": "Rat / Sıçan", "physical_cages": 100, "flexibility_pct": 40.0},
    {"room_code": "GUINEA_PIG_ROOM", "room_label": "Kobay Odası", "species_label": "Kobay", "physical_cages": 100, "flexibility_pct": 50.0},
    {"room_code": "MOUSE_ROOM", "room_label": "Fare Odası", "species_label": "Fare", "physical_cages": 120, "flexibility_pct": 50.0},
]

# FAZ 8.3 — Tesiste mevcut hayvanlar (Study Status last version (2).xlsx — GLP Medikal satır 3–5)
FACILITY_AVAILABLE_ANIMALS: Dict[str, int] = {
    "GUINEA_PIG_ROOM": 152,
    "RABBIT_ROOM": 98,
    "MOUSE_ROOM": 20,
    "RAT_ROOM": 19,
}
FACILITY_AVAILABLE_ANIMALS_SUMMARY: Dict[str, int] = {
    "Guinea pig": 152,
    "Rabbit": 98,
    "Mouse": 20,
    "Rat": 19,
}


def compute_planning_capacity(physical_cages: int, flexibility_pct: float) -> int:
    """Sistem Planlama Kapasitesi = Fiziksel Kafes Sayısı × (1 + Esneklik Yüzdesi / 100)"""
    return int(round(float(physical_cages) * (1.0 + float(flexibility_pct) / 100.0)))


class AnimalRoomCapacity(Base):
    __tablename__ = "animal_room_capacities"

    id = Column(Integer, primary_key=True, index=True)
    room_code = Column(String(40), unique=True, index=True, nullable=False)
    room_label = Column(String(120), nullable=False)
    species_label = Column(String(120), nullable=True)
    physical_cages = Column(Integer, nullable=False, default=100)
    flexibility_pct = Column(Float, nullable=False, default=0.0)  # Dr. Anoop esneklik oranı (%)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def planning_capacity(self) -> int:
        return compute_planning_capacity(self.physical_cages, self.flexibility_pct)


def ensure_default_room_capacities(db: Session, commit: bool = True) -> List[AnimalRoomCapacity]:
    """Eksik oda kayıtlarını varsayılanlarla tamamlar; mevcut (düzenlenmiş) değerlere dokunmaz."""
    read_only = (not commit) or db.in_nested_transaction()
    try:
        rows = db.query(AnimalRoomCapacity).all()
    except Exception:
        if not read_only:
            db.rollback()
            Base.metadata.create_all(bind=db.get_bind(), tables=[AnimalRoomCapacity.__table__])
            rows = db.query(AnimalRoomCapacity).all()
        else:
            raise
    existing = {r.room_code for r in rows}
    if read_only:
        transient_rows = list(rows)
        for item in DEFAULT_ROOM_CAPACITIES:
            if item["room_code"] not in existing:
                transient_rows.append(AnimalRoomCapacity(**item))
        return sorted(transient_rows, key=lambda r: (r.id is None, r.id or 0, r.room_code))
    added = False
    for item in DEFAULT_ROOM_CAPACITIES:
        if item["room_code"] not in existing:
            db.add(AnimalRoomCapacity(**item))
            added = True
    if added:
        db.commit()
    return db.query(AnimalRoomCapacity).order_by(AnimalRoomCapacity.id.asc()).all()
