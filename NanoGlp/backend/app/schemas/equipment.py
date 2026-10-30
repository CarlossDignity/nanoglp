from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel
from app.models.equipment import EquipmentStatus


class EquipmentBase(BaseModel):
    name: str
    code: str
    category: str
    room_id: Optional[int] = None
    status: EquipmentStatus = EquipmentStatus.AVAILABLE
    calibration_due_date: Optional[date] = None
    polar_capacity: Optional[int] = 3
    non_polar_capacity: Optional[int] = 1
    notes: Optional[str] = None


class EquipmentCreate(EquipmentBase):
    pass


class EquipmentUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    category: Optional[str] = None
    room_id: Optional[int] = None
    status: Optional[EquipmentStatus] = None
    calibration_due_date: Optional[date] = None
    polar_capacity: Optional[int] = None
    non_polar_capacity: Optional[int] = None
    notes: Optional[str] = None


class EquipmentOut(EquipmentBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
