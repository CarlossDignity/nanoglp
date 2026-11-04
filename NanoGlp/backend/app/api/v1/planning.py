from datetime import date, datetime, time, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models.conflict import Conflict, ConflictSeverity
from app.models.study import Study, StudyStatus
from app.models.study_step import StudyStep, StepStatus
from app.models.user import User, UserRole
from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.equipment import Equipment
from app.models.calibration import SystemCalibration
from app.schemas.conflict import ConflictOut
from app.seed import seed_default_equipment
from app.services.document_parser import CANONICAL_STUDY_CODE_MAPPINGS
from app.services.scheduling_engine import (
    EXCLUDED_WORKLOAD_ROLES,
    REFERENCE_DATE,
    _safe_capacity_report,
    apply_conflict_resolution,
    build_conflict_resolutions,
    check_personnel_workload,
    calculate_personnel_workload,
    compute_biological_dependency_info,
    enrich_conflicts_with_category,
    get_all_studies_calendar_details,
    get_study_schedule_detail,
    is_eligible_lab_personnel,
    recompute_all_conflicts,
    revalidate_study_conflicts,
    schedule_new_study,
    sync_historical_completion_and_conflicts,
    MAX_DAILY_WORKLOAD_MINUTES,
)
from app.services.templates import (
    TEMPLATES,
    DEFAULT_TEMPLATE_CODE,
    ensure_default_calibrations,
    get_all_templates_calibrated,
    get_template,
)
from app.utils.security import get_current_user, require_management_read, require_management_write

router = APIRouter(prefix="/planning", tags=["Operasyonel Planlama ve Çakışma Yönetimi"])


class ScheduleStudyRequest(BaseModel):
    """study_id VEYA study_code verilmelidir. Kod sistemde yoksa DRAFT çalışma açılır."""
    study_id: Optional[int] = None
    study_code: Optional[str] = None
    acclimatization_start_date: date
    study_director_id: Optional[int] = None
    former_study_director_name: Optional[str] = None
    template_code: str = DEFAULT_TEMPLATE_CODE
    extraction_start_offset_days: Optional[int] = None
    align_extraction_to_friday: bool = False

    # FAZ 6 & 6.1: Birleştirilmiş çalışma dosyasından (Master Study Profile) gelen zengin GLP verileri
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
    requested_start_period: Optional[str] = None
    dossier_metadata: Optional[dict] = None
    source_document_id: Optional[int] = None
    source_document_ids: Optional[List[int]] = None

    @model_validator(mode="after")
    def _require_identifier(self):
        if self.study_id is None and not (self.study_code and self.study_code.strip()):
            raise ValueError("study_id veya study_code alanlarından biri zorunludur.")
        return self


class CheckWorkloadRequest(BaseModel):
    personnel_id: int
    target_date: date
    study_id: Optional[int] = None


class ResolveConflictRequest(BaseModel):
    resolution_notes: str
    resolved_by_id: Optional[int] = None


class ApplyResolutionRequest(BaseModel):
    action: str
    target_user_id: Optional[int] = None


class UpdateStepStatusRequest(BaseModel):
    status: Optional[StepStatus] = None
    notes: Optional[str] = None
    actual_start: Optional[str | datetime] = None
    actual_end: Optional[str | datetime] = None
    actual_reference_time: Optional[str | datetime] = None
    biological_reference_time: Optional[str | datetime] = None
    reference_time: Optional[str | datetime] = None
    deviation_notes: Optional[str] = None


def _parse_step_dt(val: Optional[str | datetime], fallback_date: date) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    raw = str(val).strip()
    if not raw:
        return None
    if len(raw) in (5, 8) and ":" in raw and "T" not in raw and "-" not in raw:
        parts = [int(x) for x in raw.split(":")]
        return datetime.combine(fallback_date, time(parts[0], parts[1], parts[2] if len(parts) > 2 else 0))
    return datetime.fromisoformat(raw.replace("Z", ""))


def _serialize_step(s: StudyStep, study_steps: Optional[List[StudyStep]] = None) -> dict:
    bio_item: dict = {}
    dep_steps: list = []
    rev_proposals: list = []
    if s.study is not None:
        steps_list = study_steps if study_steps is not None else list(getattr(s.study, "steps", None) or [s])
        bio_info = compute_biological_dependency_info(s.study, steps_list)
        bio_item = bio_info["by_step_id"].get(s.id) or {}
        dep_steps = bio_info["dependent_by_ref_order"].get(s.step_order, [])
        rev_proposals = bio_info["revision_proposals"]

    return {
        "id": s.id,
        "study_id": s.study_id,
        "study_code": s.study.study_code,
        "study_title": s.study.title,
        "study_status": s.study.status.value,
        "study_day": s.study_day,
        "step_order": s.step_order,
        "step_name": s.step_name,
        "step_type": s.step_type,
        "planned_start": s.planned_start.isoformat(),
        "planned_end": s.planned_end.isoformat(),
        "actual_start": s.actual_start.isoformat() if s.actual_start else None,
        "actual_end": s.actual_end.isoformat() if s.actual_end else None,
        "actual_reference_time": (
            s.actual_reference_time.isoformat() if getattr(s, "actual_reference_time", None) else None
        ),
        "planned_reference_time": bio_item.get("planned_reference_time"),
        "expected_start": bio_item.get("expected_start", s.planned_start.isoformat()),
        "expected_end": bio_item.get("expected_end", s.planned_end.isoformat()),
        "expected_reference_time": bio_item.get("expected_reference_time"),
        "reference_deviation_minutes": bio_item.get("deviation_minutes", 0),
        "exceeds_biological_tolerance": bio_item.get("exceeds_tolerance", False),
        "requires_plan_revision": bio_item.get("requires_revision", False),
        "revision_suggestion": bio_item.get("revision_suggestion"),
        "dependent_steps": dep_steps,
        "revision_proposals": rev_proposals,
        "duration_minutes": s.duration_minutes,
        "is_biological_fixed_time": s.is_biological_fixed_time,
        "biological_tolerance_minutes": s.biological_tolerance_minutes,
        "assignee_ids": s.assignee_ids,
        "assignee_names": [u.full_name for u in s.assignees],
        "status": s.status.value,
    }


def _apply_dossier_fields_to_study(study: Study, payload: ScheduleStudyRequest) -> None:
    """Birleştirilmiş çalışma dosyasından (Dossier) gelen alanları Study modeline yazar."""
    study.acclimatization_start_date = payload.acclimatization_start_date
    if payload.template_code:
        study.template_code = payload.template_code
    if payload.study_director_id is not None:
        study.study_director_id = payload.study_director_id
    for attr in (
        "title",
        "test_type",
        "guideline",
        "sponsor_name",
        "sponsor_contact",
        "test_item_name",
        "test_item_batch",
        "manufacture_date",
        "expiry_date",
        "test_item_storage_condition",
        "physical_state",
        "sterility",
        "extraction_polar",
        "extraction_polar_solvent",
        "extraction_non_polar",
        "extraction_non_polar_solvent",
        "extraction_ratio",
        "extraction_conditions",
        "animal_species_strain",
        "animal_count",
        "animal_birth_date",
        "requested_start_period",
        "dossier_metadata",
    ):
        val = getattr(payload, attr, None)
        if val is not None and val != "":
            setattr(study, attr, val)


def _resolve_or_create_draft_study(db: Session, payload: ScheduleStudyRequest) -> Study:
    # FAZ 6.4 (Madde 1): GLP2026-024, 031, 034 kodlarının yanlışlıkla ISO_10993_23_IC ile planlanmasını engelle
    code_hint = (payload.study_code or "").strip().upper()
    if not code_hint and payload.study_id is not None:
        existing_st = db.query(Study).filter(Study.id == payload.study_id).first()
        if existing_st and existing_st.study_code:
            code_hint = existing_st.study_code.strip().upper()
    if code_hint in CANONICAL_STUDY_CODE_MAPPINGS:
        canon = CANONICAL_STUDY_CODE_MAPPINGS[code_hint]
        if payload.template_code == DEFAULT_TEMPLATE_CODE and canon["suggested_template_code"] != DEFAULT_TEMPLATE_CODE:
            payload.template_code = canon["suggested_template_code"]
        if not payload.test_type:
            payload.test_type = canon["test_type"]
        if not payload.guideline:
            payload.guideline = canon["guideline"]

    try:
        template = get_template(payload.template_code, db=db)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    if payload.study_director_id is not None:
        sd_check = db.query(User).filter(User.id == payload.study_director_id).first()
        if sd_check and not is_eligible_lab_personnel(sd_check):
            raise HTTPException(
                status_code=400,
                detail="SYSADMIN, EXECUTIVE veya SALES rolündeki kullanıcılara Çalışma Yöneticiliği (SD) veya görev atanamaz.",
            )

    if payload.study_id is not None:
        study = db.query(Study).filter(Study.id == payload.study_id).first()
        if not study:
            raise HTTPException(status_code=404, detail="GLP çalışması bulunamadı.")
        if study.status == StudyStatus.DRAFT:
            _apply_dossier_fields_to_study(study, payload)
            db.commit()
            db.refresh(study)
        return study

    code = payload.study_code.strip()
    study = db.query(Study).filter(Study.study_code == code).first()
    if study:
        if study.status == StudyStatus.DRAFT:
            if not payload.title:
                study.title = f"{template.standard} {template.title} ({code})"
            _apply_dossier_fields_to_study(study, payload)
            db.commit()
            db.refresh(study)
        return study

    # Çalışma Yöneticisi: açıkça verilen ya da sistemdeki ilk aktif SD
    director_id = payload.study_director_id
    if director_id is None:
        sds = [
            u for u in db.query(User).filter(User.role == UserRole.STUDY_DIRECTOR, User.is_active == True).order_by(User.id).all()  # noqa: E712
            if is_eligible_lab_personnel(u)
        ]
        if not sds:
            raise HTTPException(
                status_code=400,
                detail="Sistemde aktif bir Çalışma Yöneticisi (STUDY_DIRECTOR) yok. Önce SD tanımlayın."
            )
        director_id = sds[0].id

    study = Study(
        study_code=code,
        template_code=template.code,
        title=payload.title or f"{template.standard} {template.title} ({code})",
        test_item_name=payload.test_item_name or "BELİRTİLMEDİ — SD tarafından girilecek",
        study_director_id=director_id,
        status=StudyStatus.DRAFT,
    )
    _apply_dossier_fields_to_study(study, payload)
    db.add(study)
    db.commit()
    db.refresh(study)

    db.add(AuditLog(
        user_id=director_id,
        entity_name="Study",
        entity_id=study.id,
        action="CREATE",
        reason=f"Planlama ekranından '{code}' kodlu DRAFT çalışma oluşturuldu.",
    ))
    db.commit()
    return study


@router.post("/schedule-study", summary="Yeni Çalışma Ekleme ve Çakışma Analizi (Non-Destructive)")
def api_schedule_new_study(
    payload: ScheduleStudyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_write),
):
    """
    Onaylanmış mevcut çalışmaların saatlerine DOKUNMADAN (Non-destructive)
    yeni çalışmanın adımlarını ve çakışmalarını (9 saat iş yükü, biyolojik kilitler, kaynak çakışmaları)
    tespit eder ve Conflict tablosuna kaydeder.
    """
    study = _resolve_or_create_draft_study(db, payload)
    try:
        result = schedule_new_study(
            db=db,
            study_id=study.id,
            acclimatization_start_date=payload.acclimatization_start_date,
            template_code=payload.template_code,
            extraction_start_offset_days=payload.extraction_start_offset_days,
            align_extraction_to_friday=payload.align_extraction_to_friday,
        )
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(ve))

    if payload.former_study_director_name:
        assigned_sd = db.query(User).filter(User.id == study.study_director_id).first()
        db.add(
            AuditLog(
                user_id=current_user.id,
                entity_name="Study",
                entity_id=study.id,
                action="SD_HANDOVER_ASSIGNMENT",
                old_values={"document_study_director": payload.former_study_director_name},
                new_values={
                    "assigned_study_director_id": study.study_director_id,
                    "assigned_study_director_name": assigned_sd.full_name if assigned_sd else None,
                },
                reason=(
                    f"Belgede yer alan eski Çalışma Direktörü '{payload.former_study_director_name}' yerine "
                    f"aktif Çalışma Direktörü '{assigned_sd.full_name if assigned_sd else study.study_director_id}' "
                    f"{current_user.username} onayıyla atandı."
                ),
            )
        )
        db.commit()

    if payload.source_document_id is not None:
        source = db.query(Document).filter(Document.id == payload.source_document_id).first()
        extracted = (source.extracted_data or {}) if source else {}
        db.add(AuditLog(
            user_id=current_user.id,
            entity_name="Study",
            entity_id=study.id,
            action="PLAN_FROM_AI_DOCUMENT",
            old_values={
                "ai_study_code": extracted.get("study_code"),
                "ai_requested_start_date": extracted.get("requested_start_date"),
            },
            new_values={
                "study_code": study.study_code,
                "acclimatization_start_date": payload.acclimatization_start_date.isoformat(),
                "source_document_id": payload.source_document_id,
                "source_sha256": source.sha256 if source else None,
            },
            reason=(f"{current_user.username}, AI tarafından '{source.original_filename if source else '?'}' "
                    f"belgesinden çıkarılan verileri doğrulayarak planlamayı başlattı."),
        ))
        db.commit()
        result["source_document_id"] = payload.source_document_id
    return result


@router.post("/check-workload", summary="Personel Günlük 9 Saat (540 dk) İş Yükü Denetimi")
def api_check_personnel_workload(
    payload: CheckWorkloadRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_write),
):
    """
    Toplam 540 dakikayı (9 saati) aşarsa sistem CRITICAL PERSONNEL_OVERLAP üretir ve saati sessizce kaydırmaz.
    """
    conflict = check_personnel_workload(
        db=db,
        personnel_id=payload.personnel_id,
        target_date=payload.target_date,
        study_id=payload.study_id,
    )
    if conflict:
        return {
            "has_conflict": True,
            "conflict": {
                "id": conflict.id,
                "type": conflict.conflict_type.value,
                "severity": conflict.severity.value,
                "title": conflict.title,
                "description": conflict.description,
            },
        }
    return {
        "has_conflict": False,
        "message": "Personel iş yükü yasal ve GLP 9 saat (540 dk) sınırları içerisindedir.",
    }


def _collect_active_dates_and_weeks(db: Session) -> dict:
    """Veritabanındaki tüm iptal edilmemiş görevlerin düştüğü benzersiz tarih ve haftaları (Pazartesi) döner."""
    rows = (
        db.query(StudyStep.planned_start, StudyStep.planned_end)
        .join(StudyStep.study)
        .filter(
            StudyStep.status != StepStatus.CANCELLED,
            Study.status != StudyStatus.CANCELLED,
        )
        .order_by(StudyStep.planned_start.asc())
        .all()
    )
    active_dates_set = set()
    for ps, _pe in rows:
        if ps:
            active_dates_set.add(ps.date())
    sorted_dates = sorted(active_dates_set)
    active_dates = [d.isoformat() for d in sorted_dates]
    active_weeks = sorted({(d - timedelta(days=d.weekday())).isoformat() for d in sorted_dates})
    today = date.today()
    today_iso = today.isoformat()
    default_focus_date = today_iso if today_iso in active_dates else (active_dates[0] if active_dates else today_iso)
    focus_dt = date.fromisoformat(default_focus_date)
    default_focus_week = (focus_dt - timedelta(days=focus_dt.weekday())).isoformat()
    return {
        "active_dates": active_dates,
        "active_weeks": active_weeks,
        "default_focus_date": default_focus_date,
        "default_focus_week": default_focus_week,
    }


@router.get("/workload", summary="Tüm Personelin Günlük İş Yükü (Salt-Okunur)")
@router.get("/personnel-workload", summary="Tüm Personelin Günlük İş Yükü (Alias)", include_in_schema=False)
def api_get_daily_workload(
    target_date: date = Query(default_factory=date.today, description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_read),
):
    """Her personelin hedef gündeki toplam dakikasını ve görev olan aktif tarihleri döner. Conflict tablosuna yazmaz."""
    users = [
        u for u in db.query(User).filter(User.is_active == True).order_by(User.full_name).all()  # noqa: E712
        if is_eligible_lab_personnel(u)
    ]
    result = []
    for u in users:
        wl = calculate_personnel_workload(db, u.id, target_date)
        wl.update({
            "full_name": u.full_name,
            "email": u.email,
            "role": u.role.value if hasattr(u.role, "value") else str(u.role),
            "qualifications": u.qualifications or [],
        })
        result.append(wl)
    cal_meta = _collect_active_dates_and_weeks(db)
    return {
        "date": target_date.isoformat(),
        "limit_minutes": MAX_DAILY_WORKLOAD_MINUTES,
        "personnel": result,
        **cal_meta,
    }


@router.get("/workload-weekly", summary="Tüm Personelin Haftalık (Pazartesi–Pazar) İş Yükü Matrisi (FAZ 6.3)")
def api_get_weekly_workload(
    target_date: date = Query(default_factory=date.today, description="Haftanın herhangi bir günü (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_read),
):
    """Seçilen haftanın 7 günü (Pzt–Paz) boyunca tüm aktif personelin günlük dakikalarını ve görevlerini döner."""
    monday = target_date - timedelta(days=target_date.weekday())
    days = [monday + timedelta(days=i) for i in range(7)]
    users = [
        u for u in db.query(User).filter(User.is_active == True).order_by(User.full_name).all()  # noqa: E712
        if is_eligible_lab_personnel(u)
    ]
    personnel_matrix = []
    for u in users:
        daily = []
        for d in days:
            wl = calculate_personnel_workload(db, u.id, d)
            daily.append({
                "date": d.isoformat(),
                "total_minutes": wl["total_minutes"],
                "exceeds_limit": wl["exceeds_limit"],
                "task_count": len(wl["tasks"]),
                "tasks": wl["tasks"],
            })
        personnel_matrix.append({
            "personnel_id": u.id,
            "full_name": u.full_name,
            "role": u.role.value if hasattr(u.role, "value") else str(u.role),
            "qualifications": u.qualifications or [],
            "weekly_total_minutes": sum(item["total_minutes"] for item in daily),
            "weekly_task_count": sum(item["task_count"] for item in daily),
            "any_day_exceeds": any(item["exceeds_limit"] for item in daily),
            "daily": daily,
        })
    cal_meta = _collect_active_dates_and_weeks(db)
    return {
        "week_start": days[0].isoformat(),
        "week_end": days[-1].isoformat(),
        "days": [d.isoformat() for d in days],
        "limit_minutes": MAX_DAILY_WORKLOAD_MINUTES,
        "personnel": personnel_matrix,
        **cal_meta,
    }


@router.get("/calendar", summary="Kalıcı Master Operasyon Takvimi — Tüm Çalışmalar, Adımlar ve Çakışmalar (FAZ 6.3)")
def api_get_master_calendar(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_read),
):
    """
    Sistemde kayıtlı tüm aktif ve taslak çalışmaları (DRAFT, APPROVED, IN_PROGRESS),
    adımlarını, açık çakışmalarını (tek tık çözüm butonlarıyla birlikte) ve görev olan aktif tarih/haftaları döner.
    """
    studies = (
        db.query(Study)
        .options(selectinload(Study.study_director))
        .filter(Study.status != StudyStatus.CANCELLED)
        .order_by(Study.id.asc())
        .all()
    )
    steps = (
        db.query(StudyStep)
        .join(StudyStep.study)
        .options(selectinload(StudyStep.assignees), selectinload(StudyStep.study))
        .filter(
            StudyStep.status != StepStatus.CANCELLED,
            Study.status != StudyStatus.CANCELLED,
        )
        .order_by(StudyStep.planned_start.asc())
        .all()
    )
    study_details = get_all_studies_calendar_details(db, studies, steps)

    conflict_step_ids = {
        sid
        for sd in study_details
        for c in sd["conflicts"]
        for sid in (c.get("step_ids") or ([c["step_id"]] if c.get("step_id") else []))
    }

    all_steps = []
    for st in steps:
        serialized = _serialize_step(st)
        serialized["equipment_id"] = st.equipment_id
        serialized["assignees"] = [
            {"id": u.id, "full_name": u.full_name, "role": u.role.value if hasattr(u.role, "value") else str(u.role)}
            for u in st.assignees
        ]
        serialized["has_conflict"] = st.id in conflict_step_ids
        all_steps.append(serialized)

    cal_meta = _collect_active_dates_and_weeks(db)
    return {
        "studies": study_details,
        "all_steps": all_steps,
        **cal_meta,
    }


@router.get("/studies/{study_id}/schedule", summary="Tekil Çalışmanın Kayıtlı Takvim ve Çakışma Detayı (FAZ 6.3)")
def api_get_study_schedule(
    study_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_read),
):
    study = db.query(Study).options(selectinload(Study.study_director)).filter(Study.id == study_id).first()
    if not study:
        raise HTTPException(status_code=404, detail="GLP çalışması bulunamadı.")
    return get_study_schedule_detail(db, study)


@router.post("/studies/{study_id}/approve", summary="Taslak Çalışma Planını Onayla ve Aktif Çalışmalara Al (FAZ 6.3)")
def api_approve_study_plan(
    study_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_write),
):
    """
    DRAFT durumundaki bir çalışmanın çözülmemiş CRITICAL çakışması yoksa statüsünü APPROVED yapar,
    protocol_approved_at zaman damgasını işler ve GLP AuditLog kaydı oluşturur.
    """
    study = db.query(Study).options(selectinload(Study.study_director)).filter(Study.id == study_id).first()
    if not study:
        raise HTTPException(status_code=404, detail="GLP çalışması bulunamadı.")
    if study.status != StudyStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"'{study.study_code}' çalışması zaten '{study.status.value}' durumundadır; yalnızca DRAFT çalışmalar onaylanabilir.",
        )

    step_count = (
        db.query(StudyStep)
        .filter(StudyStep.study_id == study.id, StudyStep.status != StepStatus.CANCELLED)
        .count()
    )
    if step_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{study.study_code}' çalışması için henüz takvim adımları oluşturulmamış. Önce planlama yapın.",
        )

    revalidate_study_conflicts(db, study, preserve_weekend_approvals=True)
    db.commit()

    template = get_template(study.template_code or DEFAULT_TEMPLATE_CODE, db=db)
    cap_info = _safe_capacity_report(db, study, template)
    if not cap_info.get("verified", False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"'{study.study_code}' çalışması için oda ve cihaz kapasitesi doğrulanamadı "
                f"({cap_info.get('error', 'kapasite servisi hatası')}). Kapasite doğrulanmadan çalışma onaylanamaz."
            ),
        )

    unresolved_critical = (
        db.query(Conflict)
        .filter(
            Conflict.study_id == study.id,
            Conflict.is_resolved == False,  # noqa: E712
            Conflict.severity == ConflictSeverity.CRITICAL,
        )
        .count()
    )
    if unresolved_critical > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"'{study.study_code}' çalışmasında {unresolved_critical} adet çözülmemiş KRİTİK (CRITICAL) "
                f"çakışma bulunmaktadır. GLP kuralları gereği kritik çakışmalar çözülmeden çalışma onaylanamaz."
            ),
        )

    now = datetime.utcnow()
    # Varsa kalan WARNING uyarılarını da plan onayıyla kapat
    open_warnings = (
        db.query(Conflict)
        .filter(
            Conflict.study_id == study.id,
            Conflict.is_resolved == False,  # noqa: E712
        )
        .all()
    )
    for wc in open_warnings:
        wc.is_resolved = True
        wc.resolved_by_id = current_user.id
        wc.resolved_at = now
        wc.resolution_notes = (
            f"Plan Onayı ({current_user.full_name}): Çalışma planı onaylanarak aktif çalışmalara (APPROVED) alındı."
        )

    study.status = StudyStatus.APPROVED
    study.protocol_approved_at = now
    db.add(
        AuditLog(
            user_id=current_user.id,
            entity_name="Study",
            entity_id=study.id,
            action="APPROVE_STUDY_PLAN",
            old_values={"status": "DRAFT"},
            new_values={
                "status": "APPROVED",
                "study_code": study.study_code,
                "protocol_approved_at": now.isoformat(),
            },
            reason=(
                f"{current_user.full_name} ({current_user.role.value}) '{study.study_code}' taslak çalışma "
                f"planını onaylayarak aktif çalışmalara (APPROVED) aldı."
            ),
        )
    )
    db.commit()
    db.refresh(study)

    res = get_study_schedule_detail(db, study)
    res["approval_message"] = (
        f"'{study.study_code}' çalışma planı GLP denetim iziyle onaylandı (APPROVED) ve Aktif Çalışmalara alındı."
    )
    return res


class CalibrationStepUpdateItem(BaseModel):
    id: Optional[int] = None
    template_code: Optional[str] = None
    step_order: Optional[int] = None
    step_name: Optional[str] = None
    start_time: Optional[str] = None
    duration_minutes: Optional[int] = None
    tolerance_minutes: Optional[int] = None


class CalibrationUpdateRequest(BaseModel):
    reason: str
    step_id: Optional[int] = None
    template_code: Optional[str] = None
    step_order: Optional[int] = None
    step_name: Optional[str] = None
    start_time: Optional[str] = None
    duration_minutes: Optional[int] = None
    tolerance_minutes: Optional[int] = None
    steps: Optional[List[CalibrationStepUpdateItem]] = None
    equipment_code: Optional[str] = None
    polar_capacity: Optional[int] = None
    non_polar_capacity: Optional[int] = None


def _build_calibration_response(db: Session) -> dict:
    ensure_default_calibrations(db)
    seed_default_equipment(db)

    cal_rows = (
        db.query(SystemCalibration)
        .order_by(SystemCalibration.template_code.asc(), SystemCalibration.step_order.asc())
        .all()
    )
    eq_rows = db.query(Equipment).order_by(Equipment.id.asc()).all()
    audit_rows = (
        db.query(AuditLog)
        .filter(AuditLog.entity_name.in_(["SystemCalibration", "Equipment"]))
        .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
        .limit(50)
        .all()
    )
    user_ids = {a.user_id for a in audit_rows if a.user_id is not None}
    users_by_id = (
        {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}
        if user_ids
        else {}
    )

    tpl_titles = {k: f"{v.standard} — {v.title}" for k, v in TEMPLATES.items()}

    return {
        "steps": [
            {
                "id": r.id,
                "template_code": r.template_code,
                "template_label": tpl_titles.get(r.template_code, r.template_code),
                "step_order": r.step_order,
                "study_day": r.study_day,
                "step_name": r.step_name,
                "step_type": r.category,
                "category": r.category,
                "start_time": r.start_time,
                "duration_minutes": r.duration_minutes,
                "is_biological_fixed_time": r.is_biological_fixed_time,
                "tolerance_minutes": r.tolerance_minutes,
            }
            for r in cal_rows
        ],
        "equipment": [
            {
                "id": eq.id,
                "code": eq.code,
                "name": eq.name,
                "category": eq.category,
                "polar_capacity": eq.polar_capacity,
                "non_polar_capacity": eq.non_polar_capacity,
                "status": eq.status.value if eq.status else "AVAILABLE",
            }
            for eq in eq_rows
        ],
        "audit_logs": [
            {
                "id": a.id,
                "timestamp": a.timestamp.isoformat() if a.timestamp else None,
                "user_id": a.user_id,
                "editor": users_by_id[a.user_id].full_name if a.user_id in users_by_id else "Sistem Yetkilisi",
                "editor_role": users_by_id[a.user_id].role.value if a.user_id in users_by_id else "SYSADMIN",
                "entity_name": a.entity_name,
                "entity_id": a.entity_id,
                "action": a.action,
                "old_values": a.old_values,
                "new_values": a.new_values,
                "reason": a.reason,
            }
            for a in audit_rows
        ],
    }


@router.get("/calibration", summary="Sistem Kalibrasyonu — Görev Süreleri, Toleranslar ve Su Banyosu Kapasiteleri (FAZ 6.4)")
def api_get_calibration(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_read),
):
    return _build_calibration_response(db)


@router.put("/calibration", summary="Sistem Kalibrasyonunu Güncelle ve GLP AuditLog Kaydı Üret (FAZ 6.4)")
def api_update_calibration(
    payload: CalibrationUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_write),
):
    reason = (payload.reason or "").strip()
    if len(reason) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GLP denetim izi gereği değişiklik gerekçesi (en az 3 karakter) zorunludur.",
        )

    ensure_default_calibrations(db)
    water_bath = seed_default_equipment(db)

    step_items: List[CalibrationStepUpdateItem] = list(payload.steps or [])
    if payload.step_id is not None or (payload.template_code and payload.step_order is not None):
        step_items.append(
            CalibrationStepUpdateItem(
                id=payload.step_id,
                template_code=payload.template_code,
                step_order=payload.step_order,
                step_name=payload.step_name,
                start_time=payload.start_time,
                duration_minutes=payload.duration_minutes,
                tolerance_minutes=payload.tolerance_minutes,
            )
        )

    for item in step_items:
        row = None
        if item.id is not None:
            row = db.query(SystemCalibration).filter(SystemCalibration.id == item.id).first()
        elif item.template_code and item.step_order is not None:
            row = (
                db.query(SystemCalibration)
                .filter(
                    SystemCalibration.template_code == item.template_code,
                    SystemCalibration.step_order == item.step_order,
                )
                .first()
            )
        if not row:
            raise HTTPException(status_code=404, detail="Güncellenecek kalibrasyon adımı bulunamadı.")

        old_vals = {
            "template_code": row.template_code,
            "step_order": row.step_order,
            "step_name": row.step_name,
            "start_time": row.start_time,
            "duration_minutes": row.duration_minutes,
            "tolerance_minutes": row.tolerance_minutes,
        }
        if item.step_name is not None and item.step_name.strip():
            row.step_name = item.step_name.strip()
        if item.start_time is not None and item.start_time.strip():
            row.start_time = item.start_time.strip()
        if item.duration_minutes is not None:
            if item.duration_minutes < 1 or item.duration_minutes > 1440:
                raise HTTPException(status_code=400, detail="Görev süresi 1–1440 dakika arasında olmalıdır.")
            row.duration_minutes = int(item.duration_minutes)
        if item.tolerance_minutes is not None:
            if item.tolerance_minutes < 0 or item.tolerance_minutes > 720:
                raise HTTPException(status_code=400, detail="Biyolojik tolerans 0–720 dakika arasında olmalıdır.")
            row.tolerance_minutes = int(item.tolerance_minutes)
        row.updated_at = datetime.utcnow()

        new_vals = {
            "template_code": row.template_code,
            "step_order": row.step_order,
            "step_name": row.step_name,
            "start_time": row.start_time,
            "duration_minutes": row.duration_minutes,
            "tolerance_minutes": row.tolerance_minutes,
        }
        if old_vals != new_vals:
            db.add(
                AuditLog(
                    user_id=current_user.id,
                    entity_name="SystemCalibration",
                    entity_id=row.id,
                    action="UPDATE_SYSTEM_CALIBRATION",
                    old_values=old_vals,
                    new_values=new_vals,
                    reason=reason,
                )
            )

    if payload.polar_capacity is not None or payload.non_polar_capacity is not None:
        eq_code = (payload.equipment_code or "EQ-WB-001").strip()
        eq = db.query(Equipment).filter(Equipment.code == eq_code).first() or water_bath
        old_eq = {
            "code": eq.code,
            "name": eq.name,
            "polar_capacity": eq.polar_capacity,
            "non_polar_capacity": eq.non_polar_capacity,
        }
        if payload.polar_capacity is not None:
            if payload.polar_capacity < 1 or payload.polar_capacity > 99:
                raise HTTPException(status_code=400, detail="Polar kapasite 1–99 arasında olmalıdır.")
            eq.polar_capacity = int(payload.polar_capacity)
        if payload.non_polar_capacity is not None:
            if payload.non_polar_capacity < 1 or payload.non_polar_capacity > 99:
                raise HTTPException(status_code=400, detail="Apolar kapasite 1–99 arasında olmalıdır.")
            eq.non_polar_capacity = int(payload.non_polar_capacity)
        new_eq = {
            "code": eq.code,
            "name": eq.name,
            "polar_capacity": eq.polar_capacity,
            "non_polar_capacity": eq.non_polar_capacity,
        }
        if old_eq != new_eq:
            db.add(
                AuditLog(
                    user_id=current_user.id,
                    entity_name="Equipment",
                    entity_id=eq.id,
                    action="UPDATE_EQUIPMENT_CAPACITY",
                    old_values=old_eq,
                    new_values=new_eq,
                    reason=reason,
                )
            )

    db.commit()
    return _build_calibration_response(db)


@router.get("/templates", summary="Tanımlı GLP Çalışma Şablonları")
def api_get_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_read),
):
    """Planlama formunda gösterilecek şablonlar ve veritabanı kalibrasyonuyla güncel gün/adım/rol tanımları."""
    return {
        "default": DEFAULT_TEMPLATE_CODE,
        "templates": [t.to_dict() for t in get_all_templates_calibrated(db)],
    }


@router.get("/steps", summary="Zaman Aralığındaki Görevler / Biyolojik Kilometre Taşları")
def api_get_steps(
    start: Optional[datetime] = Query(None, description="Başlangıç (varsayılan: şimdi)"),
    days: int = Query(14, ge=1, le=180),
    biological_only: bool = Query(False),
    include_all: bool = Query(False, description="True ise tarih filtresi uygulamadan tüm planlı adımları döner"),
    active_only: bool = Query(False, description="True ise tamamlanmış (COMPLETED) ve geçmiş (< 2026-11-03) adımları gizler"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = (
        db.query(StudyStep)
        .join(StudyStep.study)
        .options(selectinload(StudyStep.assignees), selectinload(StudyStep.study))
        .filter(
            StudyStep.status != StepStatus.CANCELLED,
            Study.status != StudyStatus.CANCELLED,
        )
    )
    if active_only:
        q = q.filter(
            StudyStep.status != StepStatus.COMPLETED,
            Study.status != StudyStatus.COMPLETED,
            StudyStep.planned_start >= datetime.combine(REFERENCE_DATE, time.min),
        )
    elif not include_all:
        start = start or datetime.now()
        end = start + timedelta(days=days)
        q = q.filter(
            StudyStep.planned_end >= start,
            StudyStep.planned_start <= end,
        )
    if current_user.role == UserRole.TECHNICIAN:
        q = q.join(StudyStep.assignees).filter(User.id == current_user.id)
    if biological_only:
        q = q.filter(StudyStep.is_biological_fixed_time == True)  # noqa: E712
    steps = q.order_by(StudyStep.planned_start).all()

    return [_serialize_step(s) for s in steps]


@router.get("/my-tasks", summary="Giriş Yapan Personelin Bugünkü ve Yaklaşan Görevleri (Teknisyen Ekranı)")
def api_get_my_tasks(
    target_date: date = Query(default_factory=date.today, description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Oturum açmış personelin (özellikle TECHNICIAN) seçilen tarihteki (varsayılan: bugün)
    görevlerini, 9 saat iş yükü durumunu ve kendisine atanmış tüm aktif çalışma adımlarını döner.
    """
    day_start = datetime.combine(target_date, time.min)
    day_end = datetime.combine(target_date, time.max)

    all_steps = (
        db.query(StudyStep)
        .join(StudyStep.assignees)
        .join(StudyStep.study)
        .options(selectinload(StudyStep.assignees), selectinload(StudyStep.study))
        .filter(
            User.id == current_user.id,
            StudyStep.status != StepStatus.CANCELLED,
            Study.status != StudyStatus.CANCELLED,
        )
        .order_by(StudyStep.planned_start)
        .all()
    )

    todays_steps = [
        s for s in all_steps
        if s.planned_start <= day_end and s.planned_end >= day_start
    ]

    workload = calculate_personnel_workload(db, current_user.id, target_date)

    return {
        "user": {
            "id": current_user.id,
            "full_name": current_user.full_name,
            "role": current_user.role.value,
            "max_daily_hours": current_user.max_daily_hours,
        },
        "target_date": target_date.isoformat(),
        "today_workload": workload,
        "todays_tasks": [_serialize_step(s) for s in todays_steps],
        "all_assigned_tasks": [_serialize_step(s) for s in all_steps],
    }


@router.patch("/steps/{step_id}/status", summary="Görev Durumunu Güncelle (GLP Denetim Kayıtlı)")
def api_update_step_status(
    step_id: int,
    payload: UpdateStepStatusRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role in (UserRole.QA, UserRole.EXECUTIVE) or getattr(current_user, "is_read_only", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Kalite Güvence (QA) ve Üst Yönetim (EXECUTIVE) rolleri SADECE OKUMA yetkisine sahiptir; görev durumu güncelleyemez.",
        )

    step = (
        db.query(StudyStep)
        .options(selectinload(StudyStep.assignees), selectinload(StudyStep.study))
        .filter(StudyStep.id == step_id)
        .first()
    )
    if not step:
        raise HTTPException(status_code=404, detail="Görev adımı bulunamadı.")

    if current_user.role == UserRole.TECHNICIAN and current_user.id not in step.assignee_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Yalnızca kendinize atanmış görevlerin durumunu güncelleyebilirsiniz.",
        )

    old_status = step.status.value
    now = datetime.utcnow()
    fallback_date = step.planned_start.date()
    parsed_start = _parse_step_dt(payload.actual_start, fallback_date)
    parsed_end = _parse_step_dt(payload.actual_end, fallback_date)
    raw_ref = (
        payload.actual_reference_time
        if payload.actual_reference_time is not None
        else (payload.biological_reference_time if payload.biological_reference_time is not None else payload.reference_time)
    )
    parsed_ref = _parse_step_dt(raw_ref, fallback_date)

    if payload.status is not None:
        step.status = payload.status
    if parsed_start is not None:
        step.actual_start = parsed_start
    if parsed_end is not None:
        step.actual_end = parsed_end
    if parsed_ref is not None:
        step.actual_reference_time = parsed_ref
    if payload.deviation_notes is not None:
        step.deviation_notes = payload.deviation_notes
    elif payload.notes and not step.deviation_notes:
        step.deviation_notes = payload.notes

    if step.status == StepStatus.IN_PROGRESS and not step.actual_start:
        step.actual_start = now
    elif step.status == StepStatus.COMPLETED:
        if not step.actual_start:
            step.actual_start = now
        if not step.actual_end:
            step.actual_end = now

    db.flush()
    if step.study is not None:
        revalidate_study_conflicts(db, step.study, preserve_weekend_approvals=True)

    db.add(AuditLog(
        user_id=current_user.id,
        entity_name="StudyStep",
        entity_id=step.id,
        action="UPDATE_STEP_STATUS",
        old_values={"status": old_status},
        new_values={
            "status": step.status.value,
            "actual_start": step.actual_start.isoformat() if step.actual_start else None,
            "actual_end": step.actual_end.isoformat() if step.actual_end else None,
            "actual_reference_time": step.actual_reference_time.isoformat() if step.actual_reference_time else None,
        },
        reason=payload.notes or payload.deviation_notes or f"{current_user.full_name} görev durumunu {old_status} -> {step.status.value} olarak güncelledi.",
    ))
    db.commit()
    db.refresh(step)
    study_steps = (
        db.query(StudyStep)
        .options(selectinload(StudyStep.assignees), selectinload(StudyStep.study))
        .filter(StudyStep.study_id == step.study_id, StudyStep.status != StepStatus.CANCELLED)
        .order_by(StudyStep.step_order.asc())
        .all()
    )
    open_conflicts = (
        db.query(Conflict)
        .filter(Conflict.study_id == step.study_id, Conflict.is_resolved == False)  # noqa: E712
        .order_by(Conflict.id.asc())
        .all()
    )
    serialized = _serialize_step(step, study_steps=study_steps)
    serialized["conflicts"] = [
        {
            "id": c.id,
            "conflict_type": c.conflict_type.value,
            "severity": c.severity.value,
            "title": c.title,
            "description": c.description,
            "is_resolved": c.is_resolved,
        }
        for c in open_conflicts
    ]
    return serialized


@router.get("/summary", summary="Yönetici Dashboard Özeti")
def api_get_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_read),
):
    today = date.today()
    day_start = datetime.combine(today, time.min)
    day_end = datetime.combine(today, time.max)

    active_studies = db.query(Study).filter(
        Study.status.in_([StudyStatus.APPROVED, StudyStatus.IN_PROGRESS])
    ).count()
    draft_studies = db.query(Study).filter(Study.status == StudyStatus.DRAFT).count()
    open_conflict_rows = db.query(Conflict).filter(Conflict.is_resolved == False).all()  # noqa: E712
    enriched_open = enrich_conflicts_with_category(db, open_conflict_rows, include_resolutions=False)
    confirmed_conflicts = sum(1 for item in enriched_open if item["conflict_category"] == "CONFIRMED_CONFLICT")
    missing_info_conflicts = sum(1 for item in enriched_open if item["conflict_category"] == "MISSING_INFO")
    critical_conflicts = sum(1 for c in open_conflict_rows if c.severity == ConflictSeverity.CRITICAL)
    open_conflicts = len(open_conflict_rows)
    todays_tasks = db.query(StudyStep).filter(
        StudyStep.status != StepStatus.CANCELLED,
        StudyStep.status != StepStatus.COMPLETED,
        StudyStep.planned_start <= day_end,
        StudyStep.planned_end >= day_start,
    ).count()
    total_planned_tasks = (
        db.query(StudyStep)
        .join(StudyStep.study)
        .filter(
            StudyStep.status != StepStatus.CANCELLED,
            Study.status != StudyStatus.CANCELLED,
        )
        .count()
    )
    active_pending_tasks = (
        db.query(StudyStep)
        .join(StudyStep.study)
        .filter(
            StudyStep.status != StepStatus.CANCELLED,
            StudyStep.status != StepStatus.COMPLETED,
            Study.status != StudyStatus.CANCELLED,
            Study.status != StudyStatus.COMPLETED,
        )
        .count()
    )
    completed_tasks = (
        db.query(StudyStep)
        .join(StudyStep.study)
        .filter(
            StudyStep.status == StepStatus.COMPLETED,
            Study.status != StudyStatus.CANCELLED,
        )
        .count()
    )

    from app.models.sample import SampleRecord

    ongoing_rows = db.query(SampleRecord).filter(SampleRecord.stored_status == "ONGOING").all()
    ongoing_in_experiment = 0
    ongoing_in_reporting = 0
    ongoing_overdue_draft = 0
    for sr in ongoing_rows:
        end_ref = sr.experiment_end_date or sr.planned_end
        if end_ref is not None and end_ref < REFERENCE_DATE:
            ongoing_in_reporting += 1
        else:
            ongoing_in_experiment += 1
        if (sr.glp_type or "GLP").upper() == "GLP" and sr.draft_report_date is not None and sr.draft_report_date < REFERENCE_DATE:
            ongoing_overdue_draft += 1

    return {
        "date": today.isoformat(),
        "active_studies": active_studies,
        "draft_studies": draft_studies,
        "ongoing_studies": len(ongoing_rows),
        "ongoing_in_experiment": ongoing_in_experiment,
        "ongoing_in_reporting": ongoing_in_reporting,
        "ongoing_overdue_draft": ongoing_overdue_draft,
        "critical_conflicts": critical_conflicts,
        "confirmed_conflicts": confirmed_conflicts,
        "missing_info_conflicts": missing_info_conflicts,
        "open_conflicts": open_conflicts,
        "todays_tasks": todays_tasks,
        "total_planned_tasks": total_planned_tasks,
        "active_pending_tasks": active_pending_tasks,
        "completed_tasks": completed_tasks,
    }


@router.get("/conflicts", response_model=List[ConflictOut], summary="Kayıtlı Çakışmaları Listele")
def api_get_conflicts(
    study_id: Optional[int] = Query(None),
    unresolved_only: bool = Query(True),
    category: Optional[str] = Query(None, description="CONFIRMED_CONFLICT veya MISSING_INFO"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_read),
):
    query = db.query(Conflict)
    if study_id is not None:
        query = query.filter(Conflict.study_id == study_id)
    if unresolved_only:
        query = query.filter(Conflict.is_resolved == False)  # noqa: E712
    rows = query.order_by(Conflict.detected_at.desc()).all()
    enriched = enrich_conflicts_with_category(db, rows, include_resolutions=unresolved_only)
    if category:
        cat_norm = category.strip().upper()
        enriched = [item for item in enriched if item.get("conflict_category") == cat_norm]
    return enriched


@router.post("/recompute-conflicts", summary="Tüm Çalışma Çakışmalarını Yeniden Hesapla (FAZ 9.2)")
def api_recompute_all_conflicts(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_write),
):
    """
    FAZ 9.2: Geçmiş/tamamlanmış görevleri kapatır, aktif çalışmaları yeniden denetler ve
    açık çakışmaları `CONFIRMED_CONFLICT` (Gerçek Çakışma) ile `MISSING_INFO` (Eksik Bilgi) olarak sınıflandırır.
    """
    return recompute_all_conflicts(db=db, user=current_user)


@router.post("/conflicts/{conflict_id}/resolve", summary="Çakışmayı Çözüldü Olarak İşaretle (GLP Gerekçeli)")
def api_resolve_conflict(
    conflict_id: int,
    payload: ResolveConflictRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_write),
):
    conflict = db.query(Conflict).filter(Conflict.id == conflict_id).first()
    if not conflict:
        raise HTTPException(status_code=404, detail="Çakışma kaydı bulunamadı.")
    if not payload.resolution_notes.strip():
        raise HTTPException(status_code=400, detail="GLP gereği çözüm gerekçesi zorunludur.")

    resolved_by_id = payload.resolved_by_id or current_user.id
    conflict.is_resolved = True
    conflict.resolved_by_id = resolved_by_id
    conflict.resolved_at = datetime.utcnow()
    conflict.resolution_notes = payload.resolution_notes

    db.add(AuditLog(
        user_id=resolved_by_id,
        entity_name="Conflict",
        entity_id=conflict_id,
        action="RESOLVE_CONFLICT",
        reason=payload.resolution_notes,
    ))
    db.commit()
    return {"status": "success", "message": "Çakışma GLP denetim kaydıyla çözüldü.", "conflict_id": conflict_id}


@router.post(
    "/conflicts/{conflict_id}/apply-resolution",
    summary="Çakışma / Uyarı için Tek Tık Çözüm Aksiyonunu Uygula (FAZ 6.2)",
)
def api_apply_conflict_resolution(
    conflict_id: int,
    payload: ApplyResolutionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_write),
):
    try:
        return apply_conflict_resolution(
            db=db,
            conflict_id=conflict_id,
            action=payload.action,
            user=current_user,
            target_user_id=payload.target_user_id,
        )
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
