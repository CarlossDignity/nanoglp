from datetime import datetime, date
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from app.models.study import StudyStatus
from app.schemas.study_step import StudyStepOut
from app.schemas.user import UserOut


class StudyBase(BaseModel):
    study_code: str
    title: str
    test_type: Optional[str] = None
    guideline: Optional[str] = None
    sponsor_name: Optional[str] = None
    sponsor_contact: Optional[str] = None
    test_item_name: str
    test_item_batch: Optional[str] = None
    manufacture_date: Optional[str] = None
    expiry_date: Optional[str] = None
    test_item_storage_condition: Optional[str] = None
    physical_state: Optional[str] = None
    sterility: Optional[str] = None
    extraction_polar: Optional[bool] = None
    extraction_polar_solvent: Optional[str] = None
    extraction_non_polar: Optional[bool] = None
    extraction_non_polar_solvent: Optional[str] = None
    extraction_ratio: Optional[str] = None
    extraction_conditions: Optional[str] = None
    animal_species_strain: Optional[str] = None
    animal_count: Optional[int] = None
    animal_birth_date: Optional[str] = None
    acclimatization_start_date: Optional[date] = None
    extraction_start_offset_days: Optional[int] = 0
    requested_start_period: Optional[str] = None
    study_director_id: int
    qa_officer_id: Optional[int] = None
    status: StudyStatus = StudyStatus.DRAFT
    protocol_approved_at: Optional[datetime] = None
    target_start_date: Optional[date] = None
    target_end_date: Optional[date] = None
    description: Optional[str] = None
    dossier_metadata: Optional[Dict[str, Any]] = None


class StudyCreate(StudyBase):
    pass


class StudyUpdate(BaseModel):
    study_code: Optional[str] = None
    title: Optional[str] = None
    test_type: Optional[str] = None
    guideline: Optional[str] = None
    sponsor_name: Optional[str] = None
    sponsor_contact: Optional[str] = None
    test_item_name: Optional[str] = None
    test_item_batch: Optional[str] = None
    manufacture_date: Optional[str] = None
    expiry_date: Optional[str] = None
    test_item_storage_condition: Optional[str] = None
    physical_state: Optional[str] = None
    sterility: Optional[str] = None
    extraction_polar: Optional[bool] = None
    extraction_polar_solvent: Optional[str] = None
    extraction_non_polar: Optional[bool] = None
    extraction_non_polar_solvent: Optional[str] = None
    extraction_ratio: Optional[str] = None
    extraction_conditions: Optional[str] = None
    animal_species_strain: Optional[str] = None
    animal_count: Optional[int] = None
    animal_birth_date: Optional[str] = None
    acclimatization_start_date: Optional[date] = None
    extraction_start_offset_days: Optional[int] = 0
    requested_start_period: Optional[str] = None
    study_director_id: Optional[int] = None
    qa_officer_id: Optional[int] = None
    status: Optional[StudyStatus] = None
    protocol_approved_at: Optional[datetime] = None
    target_start_date: Optional[date] = None
    target_end_date: Optional[date] = None
    description: Optional[str] = None
    dossier_metadata: Optional[Dict[str, Any]] = None


class StudyOut(StudyBase):
    id: int
    created_at: datetime
    updated_at: datetime
    study_director: Optional[UserOut] = None
    qa_officer: Optional[UserOut] = None
    steps: List[StudyStepOut] = []

    class Config:
        from_attributes = True
