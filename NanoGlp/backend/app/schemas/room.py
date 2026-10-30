from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class RoomBase(BaseModel):
    name: str
    code: str
    room_type: str
    capacity: int = 1
    is_active: bool = True


class RoomCreate(RoomBase):
    pass


class RoomOut(RoomBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True
