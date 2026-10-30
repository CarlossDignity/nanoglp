from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from app.models.conflict import ConflictType, ConflictSeverity


class ConflictBase(BaseModel):
    conflict_type: ConflictType
    severity: ConflictSeverity = ConflictSeverity.CRITICAL
    title: str
    description: str
    study_id: Optional[int] = None
    step_id: Optional[int] = None


class ConflictCreate(ConflictBase):
    pass


class ConflictOut(ConflictBase):
    id: int
    related_study_id: Optional[int] = None
    is_resolved: bool
    resolved_by_id: Optional[int] = None
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None
    detected_at: datetime

    class Config:
        from_attributes = True
