from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
from app.models.study_step import StepStatus


class StudyStepBase(BaseModel):
    step_order: int = 1
    study_day: Optional[int] = None
    step_name: str
    step_type: Optional[str] = None
    planned_start: datetime
    planned_end: datetime
    is_biological_fixed_time: bool = False
    biological_tolerance_minutes: int = 0
    assignee_ids: List[int] = []
    equipment_id: Optional[int] = None
    room_id: Optional[int] = None


class StudyStepCreate(StudyStepBase):
    study_id: int


class StudyStepUpdate(BaseModel):
    step_order: Optional[int] = None
    step_name: Optional[str] = None
    step_type: Optional[str] = None
    planned_start: Optional[datetime] = None
    planned_end: Optional[datetime] = None
    is_biological_fixed_time: Optional[bool] = None
    biological_tolerance_minutes: Optional[int] = None
    assignee_ids: Optional[List[int]] = None
    equipment_id: Optional[int] = None
    room_id: Optional[int] = None
    status: Optional[StepStatus] = None
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    deviation_notes: Optional[str] = None
    completed_by_id: Optional[int] = None


class StudyStepOut(StudyStepBase):
    id: int
    study_id: int
    status: StepStatus
    duration_minutes: int = 0
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    deviation_notes: Optional[str] = None
    completed_by_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
