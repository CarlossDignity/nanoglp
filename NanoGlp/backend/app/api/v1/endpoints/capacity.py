from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.equipment import Equipment
from app.models.room_capacity import (
    FACILITY_AVAILABLE_ANIMALS_SUMMARY,
    AnimalRoomCapacity,
    compute_planning_capacity,
    ensure_default_room_capacities,
)
from app.models.user import User
from app.seed import LONG_DURATION_EQUIPMENT, seed_default_equipment
from app.services.capacity_service import room_capacity_overview
from app.utils.security import require_management_read, require_management_write

router = APIRouter(tags=["Kafes Kapasitesi ve Uzun Süreli Cihazlar (FAZ 8.1)"])

LONG_CODES = ["EQ-WB-001"] + [c[0] for c in LONG_DURATION_EQUIPMENT]


class RoomCapacityUpdate(BaseModel):
    physical_cages: Optional[int] = None
    flexibility_pct: Optional[float] = None
    reason: Optional[str] = None


class LongEquipmentUpdate(BaseModel):
    max_concurrent_studies: int
    reason: Optional[str] = None


@router.get("/room-capacities", summary="Hayvan Odaları Kafes Kapasite Tablosu (Fiziksel + Dr. Anoop Esneklik %)")
def get_room_capacities(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_read),
):
    return {
        "formula": "Sistem Planlama Kapasitesi = Fiziksel Kafes Sayısı × (1 + Esneklik Yüzdesi / 100)",
        "available_animals": dict(FACILITY_AVAILABLE_ANIMALS_SUMMARY),
        "rooms": room_capacity_overview(db),
    }


@router.put("/room-capacities/{room_code}", summary="Oda Fiziksel Kafes Sayısını ve Esneklik Yüzdesini Güncelle")
def update_room_capacity(
    room_code: str,
    payload: RoomCapacityUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_write),
):
    ensure_default_room_capacities(db)
    row = db.query(AnimalRoomCapacity).filter(AnimalRoomCapacity.room_code == room_code.strip().upper()).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"'{room_code}' oda kaydı bulunamadı.")
    old = {"physical_cages": row.physical_cages, "flexibility_pct": row.flexibility_pct, "planning_capacity": row.planning_capacity}
    if payload.physical_cages is not None:
        if payload.physical_cages < 1 or payload.physical_cages > 5000:
            raise HTTPException(status_code=400, detail="Fiziksel kafes sayısı 1–5000 arasında olmalıdır.")
        row.physical_cages = int(payload.physical_cages)
    if payload.flexibility_pct is not None:
        if payload.flexibility_pct < 0 or payload.flexibility_pct > 1000:
            raise HTTPException(status_code=400, detail="Esneklik yüzdesi 0–1000 arasında olmalıdır.")
        row.flexibility_pct = float(payload.flexibility_pct)
    new = {
        "physical_cages": row.physical_cages,
        "flexibility_pct": row.flexibility_pct,
        "planning_capacity": compute_planning_capacity(row.physical_cages, row.flexibility_pct),
    }
    if old != new:
        db.add(
            AuditLog(
                user_id=current_user.id, entity_name="AnimalRoomCapacity", entity_id=row.id,
                action="UPDATE_ROOM_CAGE_CAPACITY", old_values=old, new_values=new,
                reason=(payload.reason or "").strip()
                or f"{current_user.username}: {row.room_label} kafes kapasitesi güncellendi.",
            )
        )
    db.commit()
    return {"formula": "Sistem Planlama Kapasitesi = Fiziksel Kafes Sayısı × (1 + Esneklik Yüzdesi / 100)", "rooms": room_capacity_overview(db)}


@router.get("/long-equipment", summary="24-72+ Saatlik Darboğaz Cihazlar ve Eşzamanlı Çalışma Kapasiteleri")
def get_long_equipment(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_read),
):
    seed_default_equipment(db)
    rows = db.query(Equipment).filter(Equipment.code.in_(LONG_CODES)).order_by(Equipment.id.asc()).all()
    return [
        {
            "id": e.id,
            "code": e.code,
            "name": e.name,
            "category": e.category,
            "max_concurrent_studies": e.max_concurrent_studies or 1,
            "note": (
                "72 saat — Polar/Apolar kapasitesi 'Sistem Kalibrasyonu' bölümünde ayrıca yönetilir."
                if e.code == "EQ-WB-001"
                else e.notes
            ),
        }
        for e in rows
    ]


@router.put("/long-equipment/{code}", summary="Uzun Süreli Cihazın Eşzamanlı Çalışma Kapasitesini Güncelle")
def update_long_equipment(
    code: str,
    payload: LongEquipmentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_write),
):
    seed_default_equipment(db)
    code = code.strip().upper()
    if code not in LONG_CODES:
        raise HTTPException(status_code=404, detail="Yalnızca 24-72+ saatlik darboğaz cihazlar düzenlenebilir.")
    eq = db.query(Equipment).filter(Equipment.code == code).first()
    if not eq:
        raise HTTPException(status_code=404, detail="Cihaz bulunamadı.")
    if payload.max_concurrent_studies < 1 or payload.max_concurrent_studies > 99:
        raise HTTPException(status_code=400, detail="Eşzamanlı çalışma kapasitesi 1–99 arasında olmalıdır.")
    old = {"max_concurrent_studies": eq.max_concurrent_studies}
    eq.max_concurrent_studies = int(payload.max_concurrent_studies)
    db.add(
        AuditLog(
            user_id=current_user.id, entity_name="Equipment", entity_id=eq.id, action="UPDATE_EQUIPMENT_CONCURRENCY",
            old_values=old, new_values={"max_concurrent_studies": eq.max_concurrent_studies},
            reason=(payload.reason or "").strip() or f"{current_user.username}: {eq.name} eşzamanlı kapasitesi güncellendi.",
        )
    )
    db.commit()
    return {"code": eq.code, "max_concurrent_studies": eq.max_concurrent_studies}
