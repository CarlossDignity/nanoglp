from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
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
    type: Optional[str] = None
    related_study_id: Optional[int] = None
    is_resolved: bool
    resolved_by_id: Optional[int] = None
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None
    detected_at: datetime
    conflict_category: str = "CONFIRMED_CONFLICT"
    missing_info_codes: List[str] = Field(default_factory=list)
    missing_info_badges: List[str] = Field(default_factory=list)
    missing_info_tags: List[str] = Field(default_factory=list)
    study_code: Optional[str] = None
    study_title: Optional[str] = None
    sample_id: Optional[int] = None
    related_study_code: Optional[str] = None
    step_name: Optional[str] = None
    planned_start: Optional[str] = None
    resolutions: List[Dict[str, Any]] = Field(default_factory=list)

    class Config:
        from_attributes = True

