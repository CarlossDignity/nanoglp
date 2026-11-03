import re
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.study import Study
from app.models.user import User
from app.schemas.study import StudyOut, StudyCreate
from app.services.study_plan_docx import generate_study_plan_docx
from app.utils.security import require_management_read, require_management_write

router = APIRouter(prefix="/studies", tags=["GLP Çalışmaları (Studies)"])


@router.get("", response_model=List[StudyOut])
@router.get("/", response_model=List[StudyOut], include_in_schema=False)
def get_all_studies(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_read),
):
    return db.query(Study).all()


@router.post("", response_model=StudyOut, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=StudyOut, status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_study(
    study_in: StudyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_write),
):
    existing = db.query(Study).filter(Study.study_code == study_in.study_code).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{study_in.study_code}' kodlu GLP çalışması zaten mevcut.",
        )

    if study_in.study_director_id is not None:
        sd_user = db.query(User).filter(User.id == study_in.study_director_id).first()
        if sd_user:
            sd_role = (sd_user.role.value if hasattr(sd_user.role, "value") else str(sd_user.role or "")).strip().upper()
            if sd_role in {"SYSADMIN", "ADMIN", "EXECUTIVE", "SALES", "TRM_KABUL", "TRM_ACCEPTANCE"} or (sd_user.username or "").lower() == "yigit":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="SYSADMIN, EXECUTIVE veya SALES rolündeki kullanıcılara Çalışma Yöneticiliği (SD) atanamaz.",
                )

    study = Study(**study_in.model_dump())
    db.add(study)
    db.commit()
    db.refresh(study)
    return study


@router.get("/{study_id}", response_model=StudyOut)
def get_study_by_id(
    study_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_read),
):
    study = db.query(Study).filter(Study.id == study_id).first()
    if not study:
        raise HTTPException(status_code=404, detail="GLP Çalışması bulunamadı.")
    return study


@router.get(
    "/{study_id}/export-study-plan",
    summary="Resmi GLP Study Plan Taslağı (.docx) Word Belgesi Üret ve İndir (FAZ 6.2)",
)
def export_study_plan_docx(
    study_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_read),
):
    study = db.query(Study).filter(Study.id == study_id).first()
    if not study:
        raise HTTPException(status_code=404, detail="GLP Çalışması bulunamadı.")

    docx_bytes = generate_study_plan_docx(db, study)
    safe_code = re.sub(r"[^A-Za-z0-9_.-]+", "_", study.study_code or f"Study_{study.id}")
    filename = f"GLP_Study_Plan_Draft_{safe_code}.docx"

    db.add(
        AuditLog(
            user_id=current_user.id,
            entity_name="Study",
            entity_id=study.id,
            action="EXPORT_STUDY_PLAN_DOCX",
            new_values={"study_code": study.study_code, "filename": filename},
            reason=f"{current_user.username} '{study.study_code}' için GLP Study Plan Taslağı (.docx) belgesini üretti.",
        )
    )
    db.commit()

    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
