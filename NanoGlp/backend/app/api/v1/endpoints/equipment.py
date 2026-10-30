from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.equipment import Equipment
from app.models.room import Room
from app.models.user import User
from app.schemas.equipment import EquipmentOut, EquipmentCreate
from app.schemas.room import RoomOut, RoomCreate
from app.utils.security import require_management_read, require_management_write

router = APIRouter(tags=["Envanter ve Laboratuvar Alanları"])


@router.get("/equipment", response_model=List[EquipmentOut])
def get_all_equipment(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_read),
):
    return db.query(Equipment).all()


@router.post("/equipment", response_model=EquipmentOut, status_code=status.HTTP_201_CREATED)
def create_equipment(
    eq_in: EquipmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_write),
):
    existing = db.query(Equipment).filter(Equipment.code == eq_in.code).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"'{eq_in.code}' kodlu cihaz zaten kayıtlı.")

    eq = Equipment(**eq_in.model_dump())
    db.add(eq)
    db.commit()
    db.refresh(eq)
    return eq


@router.get("/rooms", response_model=List[RoomOut])
def get_all_rooms(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_read),
):
    return db.query(Room).all()


@router.post("/rooms", response_model=RoomOut, status_code=status.HTTP_201_CREATED)
def create_room(
    room_in: RoomCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_write),
):
    existing = db.query(Room).filter(Room.code == room_in.code).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"'{room_in.code}' kodlu oda/alan zaten kayıtlı.")

    room = Room(**room_in.model_dump())
    db.add(room)
    db.commit()
    db.refresh(room)
    return room
