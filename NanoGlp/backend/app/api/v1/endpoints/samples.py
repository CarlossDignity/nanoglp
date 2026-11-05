import copy
import os
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.sample import APPROVAL_ROLES, WORKFLOW_STEPS, SampleRecord
from app.models.study import Study, StudyStatus
from app.models.user import User, UserRole
from app.config import settings
from app.models.document import Document
from app.services import document_ingest as di
from app.services import sample_service as ss
from app.services.document_parser import SUPPORTED_EXTENSIONS
from app.services.study_plan_docx import generate_study_plan_docx
from app.utils.file_security import validate_and_sanitize_upload
from app.utils.security import get_current_user

router = APIRouter(prefix="/samples", tags=["Numune ve Çalışma Takip (FAZ 8.1)"])

DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def require_samples_access(current_user: User = Depends(get_current_user)) -> User:
    menus = set(getattr(current_user, "allowed_menus", None) or [])
    if "samples" not in menus:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Numune & Çalışma Takip ekranına erişim yetkiniz bulunmamaktadır.",
        )
    return current_user


class ContactIn(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None


class SampleIn(BaseModel):
    study_code: Optional[str] = None
    glp_type: Optional[str] = None
    template_code: Optional[str] = None
    requested_analysis: Optional[str] = None
    test_item_name: Optional[str] = None
    billing_company: Optional[str] = None
    sponsor_name: Optional[str] = None
    contacts: Optional[List[ContactIn]] = None
    quote_no: Optional[str] = None
    sales_manager: Optional[str] = None
    expected_arrival_date: Optional[date] = None
    study_agreement_date: Optional[date] = None
    payment_status: Optional[str] = None
    sample_status: Optional[str] = None
    test_item_code: Optional[str] = None
    istanbul_arrival_date: Optional[date] = None
    lab_arrival_date: Optional[date] = None
    received_quantity: Optional[str] = None
    animal_consumable_status: Optional[str] = None
    animal_procurement_date: Optional[date] = None
    lot_no: Optional[str] = None
    expiry_date: Optional[str] = None
    storage_condition: Optional[str] = None
    sample_note: Optional[str] = None
    manufacture_date: Optional[str] = None
    extraction_polar_solvent: Optional[str] = None
    extraction_non_polar_solvent: Optional[str] = None
    study_director_name: Optional[str] = None
    apply_to_related: bool = False


class PlanIn(BaseModel):
    start_date: Optional[date] = None


class WorkflowActionIn(BaseModel):
    action: str                      # complete | undo | sign | revoke
    approver: Optional[str] = None   # CY | KG | TBY (adım 6 ve 11)


def _get_or_404(db: Session, sample_id: int) -> SampleRecord:
    s = db.query(SampleRecord).filter(SampleRecord.id == sample_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Numune / çalışma kaydı bulunamadı.")
    return s


def _payload_dict(payload: SampleIn) -> Dict[str, Any]:
    data = payload.model_dump(exclude_unset=True)
    data.pop("apply_to_related", None)
    return data


def _check_edit_perms(data: Dict[str, Any], perms: Dict[str, Any]) -> None:
    if any(f in data for f in ss.SALES_FIELDS) and not perms["can_edit_sales"]:
        raise HTTPException(status_code=403, detail="Satış bilgilerini yalnızca Satış rolü (veya TFM / SYSADMIN) düzenleyebilir.")
    if any(f in data for f in ss.TRM_FIELDS) and not perms["can_edit_trm"]:
        raise HTTPException(status_code=403, detail="Numune kabul bilgilerini yalnızca TRM Kabul rolü (veya TFM / SYSADMIN) düzenleyebilir.")
    if any(f in data for f in ss.PLANNING_FIELDS) and not perms["can_assign_planning"]:
        raise HTTPException(status_code=403, detail="Şablon ve Çalışma Yöneticisi atamasını yalnızca planlama / satış yetkisi olan roller yapabilir.")


def _list_payload(db: Session, perms: Dict[str, Any]) -> Dict[str, Any]:
    samples = (
        db.query(SampleRecord)
        .order_by(SampleRecord.serial_no.asc().nullslast(), SampleRecord.study_code.desc())
        .all()
    )
    items = [ss.serialize_sample(db, s, perms, all_samples=samples, detailed=False) for s in samples]
    db.commit()  # sync_dates_from_study ile eşitlenen tarihleri kalıcılaştır
    sds = (
        db.query(User).filter(User.role == UserRole.STUDY_DIRECTOR, User.is_active == True)  # noqa: E712
        .order_by(User.full_name).all()
    )
    return {
        "items": items,
        "summary": ss.build_summary(items),
        "permissions": perms,
        "study_directors": [u.full_name for u in sds],
        "templates": [
            {
                "code": t.code,
                "label": f"{t.standard} — {t.title}",
                "cage_count": t.cage_count,
                "species": t.species_label,
                "animal_count": t.animal_count,
                "tat_without_quarantine_days": t.tat_without_quarantine_days,
                "tat_with_quarantine_days": t.tat_with_quarantine_days,
                "animal_fate_tr": t.animal_fate_tr,
            }
            for t in ss.TEMPLATES.values()
        ],
    }


@router.get("", summary="Numune ve Çalışma Takip Listesi (özet şeridi dahil)")
@router.get("/", include_in_schema=False)
def list_samples(db: Session = Depends(get_db), current_user: User = Depends(require_samples_access)):
    return _list_payload(db, ss.sample_permissions(current_user))


@router.post("", status_code=status.HTTP_201_CREATED, summary="Yeni Numune / Çalışma Kaydı")
@router.post("/", status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_sample(payload: SampleIn, db: Session = Depends(get_db), current_user: User = Depends(require_samples_access)):
    perms = ss.sample_permissions(current_user)
    if not perms["can_import"]:
        raise HTTPException(status_code=403, detail="Yeni numune kaydı oluşturma yetkiniz yok.")
    code = re.sub(r"\s+", "", (payload.study_code or "").upper())
    if not code:
        raise HTTPException(status_code=422, detail="Çalışma kodu (GLP No) zorunludur.")
    if db.query(SampleRecord).filter(SampleRecord.study_code == code).first():
        raise HTTPException(status_code=400, detail=f"'{code}' kodlu kayıt zaten mevcut.")
    data = _payload_dict(payload)
    data.pop("study_code", None)
    _check_edit_perms(data, perms)
    sample = SampleRecord(study_code=code, workflow={}, stored_status="EXPECTED")
    db.add(sample)
    ss.apply_field_updates(sample, data, ss.SALES_FIELDS + ss.TRM_FIELDS + ss.PLANNING_FIELDS)
    if not sample.template_code:
        sample.template_code = ss.infer_template_code(sample.requested_analysis)
    if sample.lab_arrival_date:
        sample.stored_status = "PLANNED"
    db.flush()
    db.add(
        AuditLog(
            user_id=current_user.id, entity_name="SampleRecord", entity_id=sample.id, action="CREATE_SAMPLE",
            new_values={"study_code": code}, reason=f"{current_user.username}: '{code}' numune kaydı oluşturuldu.",
        )
    )
    db.commit()
    return ss.serialize_sample(db, sample, perms)


@router.post("/import-excel", summary="Excel (.xlsx) / CSV İçe Aktarma — Sütunlar Otomatik Eşlenir")
async def import_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_samples_access),
):
    perms = ss.sample_permissions(current_user)
    if not perms["can_import"]:
        raise HTTPException(status_code=403, detail="Excel içe aktarma yetkiniz yok.")
    limit = settings.MAX_UPLOAD_MB * 1024 * 1024
    content = await file.read(limit + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Dosya boş.")
    clean_filename, _ext = validate_and_sanitize_upload(
        raw_filename=file.filename or "",
        content=content,
        allowed_extensions={"xlsx", "xls", "csv"},
        max_mb=settings.MAX_UPLOAD_MB,
    )
    if ss.is_study_status_workbook(clean_filename, content):
        try:
            result = ss.import_study_status_workbook(db, content, current_user, auto_schedule=True, prune_non_excel=True)
        except ValueError as ve:
            raise HTTPException(status_code=422, detail=str(ve))
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Study Status Excel dosyası okunamadı: {exc}")
        result["data"] = _list_payload(db, perms)
        return result
    try:
        records = ss.read_tabular_file(clean_filename, content)
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    except Exception as exc:  # bozuk dosya
        raise HTTPException(status_code=422, detail=f"Dosya okunamadı: {exc}")
    result = ss.import_rows(db, records, current_user)
    result["data"] = _list_payload(db, perms)
    return result


@router.post("/auto-schedule-all", summary="Planlanan (takvimi çıkmamış) Tüm Numuneleri Otomatik Takvimle")
def auto_schedule_all(db: Session = Depends(get_db), current_user: User = Depends(require_samples_access)):
    perms = ss.sample_permissions(current_user)
    if not perms["can_plan"]:
        raise HTTPException(status_code=403, detail="Otomatik takvim oluşturma yetkiniz yok (SD / PK / TFM / SYSADMIN).")
    samples = db.query(SampleRecord).order_by(SampleRecord.study_code.asc()).all()
    results: List[Dict[str, Any]] = []
    for s in samples:
        info = ss.serialize_sample(db, s, perms, all_samples=samples, detailed=False)
        if info["status"] != "PLANNED" or info["scheduled"]:
            continue
        try:
            plan = ss.plan_sample(db, s, current_user)
            results.append({"study_code": s.study_code, "ok": True, **plan})
        except (PermissionError, ValueError) as exc:
            db.rollback()
            results.append({"study_code": s.study_code, "ok": False, "error": str(exc)})
        except Exception as exc:  # beklenmeyen hata tek kaydı durdurmasın
            db.rollback()
            results.append({"study_code": s.study_code, "ok": False, "error": f"Beklenmeyen hata: {exc}"})
    return {
        "scheduled": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "results": results,
        "data": _list_payload(db, perms),
    }


@router.get("/next-code", summary="Sıradaki Önerilen GLP ve Non-GLP Çalışma Kodu (FAZ 9.3)")
def get_next_study_code(db: Session = Depends(get_db), current_user: User = Depends(require_samples_access)):
    return ss.compute_next_study_codes(db)


@router.get("/export-excel", summary="Güncel Çalışma Takip Listesini Excel (.xlsx) Olarak İndir (FAZ 9.3)")
def export_samples_excel(db: Session = Depends(get_db), current_user: User = Depends(require_samples_access)):
    perms = ss.sample_permissions(current_user)
    xlsx_bytes = ss.export_samples_workbook_bytes(db, perms)
    filename = "NANOLAB_GLP_Calisma_Takip_Listesi.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{sample_id}", summary="Numune / Çalışma Detayı (11 adımlı iş akışı dahil)")
def get_sample(sample_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_samples_access)):
    sample = _get_or_404(db, sample_id)
    perms = ss.sample_permissions(current_user)
    out = ss.serialize_sample(db, sample, perms)
    db.commit()
    return out


@router.put("/{sample_id}", summary="Numune / Çalışma Bilgilerini Güncelle (Rol Bazlı)")
def update_sample(
    sample_id: int, payload: SampleIn, db: Session = Depends(get_db), current_user: User = Depends(require_samples_access)
):
    sample = _get_or_404(db, sample_id)
    perms = ss.sample_permissions(current_user)
    if not (perms["can_edit_sales"] or perms["can_edit_trm"] or perms["can_assign_planning"]):
        raise HTTPException(status_code=403, detail="Numune kaydı düzenleme yetkiniz bulunmamaktadır.")
    data = _payload_dict(payload)
    data.pop("study_code", None)
    _check_edit_perms(data, perms)
    changed = ss.apply_field_updates(sample, data, ss.SALES_FIELDS + ss.TRM_FIELDS + ss.PLANNING_FIELDS)
    propagated: List[str] = []
    trm_changes = {k: v for k, v in data.items() if k in ss.TRM_FIELDS}
    if payload.apply_to_related and trm_changes and sample.test_item_code:
        related = (
            db.query(SampleRecord)
            .filter(SampleRecord.test_item_code == sample.test_item_code, SampleRecord.id != sample.id)
            .all()
        )
        for o in related:
            if ss.apply_field_updates(o, trm_changes, ss.TRM_FIELDS):
                propagated.append(o.study_code)
    if sample.lab_arrival_date and (sample.stored_status or "").upper() in ("", "EXPECTED"):
        sample.stored_status = "PLANNED"
    if changed:
        db.add(
            AuditLog(
                user_id=current_user.id, entity_name="SampleRecord", entity_id=sample.id, action="UPDATE_SAMPLE",
                new_values={"changed": changed, "propagated_to": propagated},
                reason=(
                    f"{current_user.username}: '{sample.study_code}' numune kaydı güncellendi"
                    + (f" (ortak güncelleme: {', '.join(propagated)})." if propagated else ".")
                ),
            )
        )
    db.commit()
    out = ss.serialize_sample(db, sample, perms)
    out["propagated_to"] = propagated
    db.commit()
    return out


@router.delete("/{sample_id}", summary="Numune / Çalışma Kaydını Sil")
def delete_sample(sample_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_samples_access)):
    perms = ss.sample_permissions(current_user)
    if not perms["can_delete"]:
        raise HTTPException(status_code=403, detail="Numune kaydı silme yetkiniz yok.")
    sample = _get_or_404(db, sample_id)
    code = sample.study_code
    db.delete(sample)
    db.add(
        AuditLog(
            user_id=current_user.id, entity_name="SampleRecord", entity_id=sample_id, action="DELETE_SAMPLE",
            old_values={"study_code": code}, reason=f"{current_user.username}: '{code}' numune kaydı silindi.",
        )
    )
    db.commit()
    return {"status": "success", "deleted_id": sample_id}


@router.post("/{sample_id}/plan", summary="Numuneden Otomatik Taslak Takvim Oluştur / Yeniden Planla")
def plan_one(
    sample_id: int, payload: PlanIn, db: Session = Depends(get_db), current_user: User = Depends(require_samples_access)
):
    perms = ss.sample_permissions(current_user)
    if not perms["can_plan"]:
        raise HTTPException(status_code=403, detail="Takvim oluşturma yetkiniz yok (SD / PK / TFM / SYSADMIN).")
    sample = _get_or_404(db, sample_id)
    try:
        plan = ss.plan_sample(db, sample, current_user, start_date=payload.start_date)
    except PermissionError as pe:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    if payload.start_date is not None and sample.planned_start is not None:
        sample.experiment_start_date = sample.planned_start
        st_obj = ss.find_study(db, sample.study_code)
        if st_obj is not None:
            meta = dict(st_obj.dossier_metadata or {})
            meta["start_date_confirmed"] = True
            st_obj.dossier_metadata = meta
    out = ss.serialize_sample(db, sample, perms)
    db.commit()
    return {"plan": plan, "sample": out}


@router.post("/{sample_id}/workflow/{step_no}", summary="İş Akışı Adımını Tamamla / Geri Al veya Onay İmzası At")
def workflow_action(
    sample_id: int,
    step_no: int,
    payload: WorkflowActionIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_samples_access),
):
    sample = _get_or_404(db, sample_id)
    perms = ss.sample_permissions(current_user)
    step_def = next((s for s in WORKFLOW_STEPS if s["no"] == step_no), None)
    if step_def is None:
        raise HTTPException(status_code=404, detail="Geçersiz iş akışı adımı.")
    wf = copy.deepcopy(sample.workflow or {})
    state = wf.get(str(step_no), {})
    now = datetime.utcnow().isoformat(timespec="seconds")
    action = (payload.action or "").lower()

    if step_def["kind"] == "approval":
        key = (payload.approver or "").upper()
        if key not in APPROVAL_ROLES:
            raise HTTPException(status_code=422, detail="Onaylayan rol belirtilmeli: CY, KG veya TBY.")
        if key not in perms["approval_roles"]:
            raise HTTPException(
                status_code=403,
                detail=f"{APPROVAL_ROLES[key]['full']} onayını yalnızca ilgili rol ({APPROVAL_ROLES[key]['label']}) verebilir.",
            )
        approvals = dict(state.get("approvals") or {})
        if action == "sign":
            approvals[key] = {"by": current_user.full_name, "by_username": current_user.username, "at": now}
        elif action == "revoke":
            prev = approvals.get(key)
            if prev and prev.get("by_username") not in (None, current_user.username) and perms["role"] not in ("SYSADMIN", "ADMIN"):
                raise HTTPException(status_code=403, detail="Onayı yalnızca onaylayan kişi veya SYSADMIN geri alabilir.")
            approvals.pop(key, None)
        else:
            raise HTTPException(status_code=422, detail="Onay adımları için action 'sign' veya 'revoke' olmalıdır.")
        wf[str(step_no)] = {"approvals": approvals}
    else:
        if step_no not in perms["workflow_steps"]:
            raise HTTPException(status_code=403, detail=f"'{step_def['title']}' adımını yalnızca {step_def['owner']} güncelleyebilir.")
        if step_no == 4 and sample.lab_arrival_date:
            raise HTTPException(status_code=409, detail="Laboratuvara geliş tarihi girildiği için bu adım otomatik tamamlandı.")
        if action == "complete":
            wf[str(step_no)] = {"done": True, "done_by": current_user.full_name, "done_at": now}
        elif action == "undo":
            wf[str(step_no)] = {"done": False}
        else:
            raise HTTPException(status_code=422, detail="action 'complete' veya 'undo' olmalıdır.")

    sample.workflow = wf
    db.add(
        AuditLog(
            user_id=current_user.id, entity_name="SampleRecord", entity_id=sample.id, action="SAMPLE_WORKFLOW_STEP",
            new_values={"step": step_no, "action": action, "approver": payload.approver},
            reason=f"{current_user.full_name} ({perms['role']}): '{sample.study_code}' — adım {step_no} '{step_def['title']}' → {action}.",
        )
    )
    db.commit()
    out = ss.serialize_sample(db, sample, perms)
    db.commit()
    return out


def _dossier_docs(db: Session, sample: SampleRecord) -> List[Document]:
    return (
        db.query(Document)
        .filter(Document.dossier_key == sample.study_code)
        .order_by(Document.uploaded_at.desc(), Document.id.desc())
        .all()
    )


def _doc_row(d: Document) -> Dict[str, Any]:
    return {
        "id": d.id,
        "filename": d.original_filename,
        "status": d.status,
        "category": d.doc_category,
        "category_label": d.doc_category_label,
        "extraction_method": d.extraction_method,
        "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
        "error": d.error_message,
    }


@router.get("/{sample_id}/documents", summary="Çalışma Klasöründeki (TIIS / CoA / FM.083) Belgeleri Listele")
def list_sample_documents(
    sample_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_samples_access)
):
    sample = _get_or_404(db, sample_id)
    return {"dossier_key": sample.study_code, "documents": [_doc_row(d) for d in _dossier_docs(db, sample)]}


@router.post("/{sample_id}/documents", summary="Çekmeceden PDF Yükle (TIIS / CoA / FM.083) ve Çalışma Alanlarını Otomatik Doldur")
def upload_sample_documents(
    sample_id: int,
    files: List[UploadFile] = File(..., description="Bir veya birden fazla PDF / görüntü / Excel belgesi"),
    overwrite: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_samples_access),
):
    """
    Dosyalar çalışmanın klasörüne (dossier_key = study_code) yüklenir, mevcut PyMuPDF + GPT-4o Vision ayrıştırıcıyla okunur;
    Lot / SKT / Üretim Tarihi / Saklama Koşulu / Sponsor / Test Maddesi / Polar-Apolar çözücüler SampleRecord'a ve bağlı
    Study (dossier_metadata) kaydına yazılır.
    """
    perms = ss.sample_permissions(current_user)
    if not perms["can_upload_documents"]:
        raise HTTPException(status_code=403, detail="Bu çalışmaya belge yükleme yetkiniz yok (Satış / TRM Kabul / SD / PK / TFM).")
    sample = _get_or_404(db, sample_id)
    if not files:
        raise HTTPException(status_code=400, detail="En az bir dosya seçin.")

    label = f"{sample.study_code} — {sample.test_item_name or sample.requested_analysis or 'Numune Belgeleri'}"
    limit = settings.MAX_UPLOAD_MB * 1024 * 1024
    results: List[Dict[str, Any]] = []
    for f in files:
        raw_name = f.filename or ""
        name = os.path.basename(raw_name.replace("\\", "/")).strip()
        row: Dict[str, Any] = {"filename": name or raw_name, "ok": False}
        try:
            if not raw_name.strip():
                raise ValueError("Dosya adı eksik.")
            data = f.file.read(limit + 1)
            if not data:
                raise ValueError("Dosya boş.")
            if len(data) > limit:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Dosya boyutu {settings.MAX_UPLOAD_MB} MB sınırını aşıyor.",
                )
            doc, err = di.ingest_document(db, data, raw_name, f.content_type, sample.study_code, label, current_user)
            row.update(_doc_row(doc))
            row["ok"] = err is None
            if err is not None:
                row["error"] = err.message
        except HTTPException:
            raise
        except ValueError as ve:
            row["error"] = str(ve)
        except Exception as exc:  # beklenmeyen ayrıştırma hatası tek dosyayı düşürsün
            db.rollback()
            row["error"] = f"Beklenmeyen hata: {exc}"
        results.append(row)

    study = ss.find_study(db, sample.study_code)
    related = (
        db.query(SampleRecord)
        .filter(SampleRecord.test_item_code == sample.test_item_code, SampleRecord.id != sample.id)
        .all()
        if sample.test_item_code
        else []
    )
    autofill = di.apply_document_autofill(
        db, sample, _dossier_docs(db, sample), current_user, study, related, overwrite=overwrite
    )
    db.commit()
    out = ss.serialize_sample(db, sample, perms)
    db.commit()
    return {
        "documents": results,
        "ok_count": sum(1 for r in results if r["ok"]),
        "failed_count": sum(1 for r in results if not r["ok"]),
        "applied": autofill["applied"],
        "differences": autofill["differences"],
        "propagated_to": autofill["propagated_to"],
        "sample": out,
    }


@router.get("/{sample_id}/study-plan-docx", summary="Satırın Verileriyle Doldurulmuş Resmi Study Plan (.docx) İndir")
def download_study_plan(
    sample_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_samples_access)
):
    sample = _get_or_404(db, sample_id)
    perms = ss.sample_permissions(current_user)
    study = ss.find_study(db, sample.study_code)
    # An existing study can be exported with TBD dates. Downloading its DOCX
    # must not create/rebuild a schedule merely because planned dates are absent.
    has_ready_study = study is not None
    if not has_ready_study:
        if not perms["can_plan"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Bu çalışma için henüz takvim oluşturulmamış. Önce yetkili bir kullanıcı (SD / PK / TFM) planlamalıdır.",
            )
        try:
            ss.plan_sample(db, sample, current_user, allow_non_draft=True)
        except PermissionError as pe:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(pe))
        except ValueError as ve:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
        study = ss.find_study(db, sample.study_code)
    docx_bytes = generate_study_plan_docx(db, study)
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", study.study_code)
    filename = f"GLP_Study_Plan_Draft_{safe}.docx"
    db.add(
        AuditLog(
            user_id=current_user.id, entity_name="Study", entity_id=study.id, action="EXPORT_STUDY_PLAN_DOCX",
            new_values={"study_code": study.study_code, "filename": filename, "source": "samples"},
            reason=f"{current_user.username}: Numune & Çalışma Takip ekranından '{study.study_code}' Study Plan (.docx) indirildi.",
        )
    )
    db.commit()
    return Response(
        content=docx_bytes,
        media_type=DOCX_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
