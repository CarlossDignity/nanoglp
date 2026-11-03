import hashlib
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.user import User, UserRole
from app.services import document_parser
from app.services.document_parser import SUPPORTED_EXTENSIONS, DocumentParsingError, aggregate_dossier
from app.utils.file_security import validate_and_sanitize_upload
from app.utils.security import require_management_read, require_management_write

router = APIRouter(prefix="/documents", tags=["Belge Yükleme, Vision OCR ve Dosya Birleştirme (FAZ 6.1 & 6.2)"])

DEFAULT_DOSSIER_KEY = "DOSSIER-ELISA-2026"
DEFAULT_DOSSIER_LABEL = "ELISA TIBBI GEREÇLER — GLP2026-024/026/031/034"


class DocumentOut(BaseModel):
    id: int
    original_filename: str
    content_type: Optional[str] = None
    size_bytes: int
    sha256: str
    dossier_key: Optional[str] = None
    dossier_label: Optional[str] = None
    doc_category: Optional[str] = None
    doc_category_label: Optional[str] = None
    primary_study_code: Optional[str] = None
    study_codes: Optional[List[str]] = None
    status: str
    extraction_method: Optional[str] = None
    ai_model: Optional[str] = None
    extracted_data: Optional[dict] = None
    error_message: Optional[str] = None
    uploaded_by_id: Optional[int] = None
    uploaded_by_name: Optional[str] = None
    uploaded_at: datetime

    class Config:
        from_attributes = True


def _get_active_sds(db: Session) -> List[User]:
    return (
        db.query(User)
        .filter(User.role == UserRole.STUDY_DIRECTOR, User.is_active == True)  # noqa: E712
        .order_by(User.id.asc())
        .all()
    )


def _to_out(doc: Document) -> DocumentOut:
    ed = doc.extracted_data or {}
    out = DocumentOut.model_validate(doc)
    out.uploaded_by_name = doc.uploaded_by.full_name if doc.uploaded_by else None
    out.dossier_key = doc.dossier_key or DEFAULT_DOSSIER_KEY
    out.dossier_label = doc.dossier_label or DEFAULT_DOSSIER_LABEL
    if not out.doc_category and ed.get("doc_category"):
        out.doc_category = ed.get("doc_category")
    if not out.doc_category_label and ed.get("doc_category_label"):
        out.doc_category_label = ed.get("doc_category_label")
    if not out.primary_study_code and ed.get("primary_study_code"):
        out.primary_study_code = ed.get("primary_study_code")
    if not out.study_codes and ed.get("study_codes"):
        out.study_codes = ed.get("study_codes")
    return out


def _read_limited(file: UploadFile) -> bytes:
    limit = settings.MAX_UPLOAD_MB * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Dosya {settings.MAX_UPLOAD_MB} MB sınırını aşıyor.",
        )
    return data


def _apply_parse_result(doc: Document, result: Dict[str, Any]) -> None:
    doc.extracted_data = result
    doc.extraction_method = result.get("extraction_method")
    doc.doc_category = result.get("doc_category")
    doc.doc_category_label = result.get("doc_category_label")
    doc.primary_study_code = result.get("primary_study_code")
    doc.study_codes = result.get("study_codes") or []
    doc.ai_model = result.get("ai_model") or settings.OPENAI_MODEL
    doc.status = "NEEDS_REVIEW" if result.get("needs_review") else "PARSED"
    doc.error_message = None


@router.post("/upload", response_model=DocumentOut, summary="Belge Yükle ve GPT-4o Vision ile Ayrıştır")
def upload_document(
    file: UploadFile = File(..., description="PDF, XLSX, PNG, JPG, TXT veya CSV"),
    dossier_key: Optional[str] = Query(None, description="Belgenin ekleneceği çalışma paketi anahtarı"),
    dossier_label: Optional[str] = Query(None, description="Çalışma paketi açıklaması"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_write),
):
    """
    Dosyayı alır, değiştirmeden saklar (SHA-256), PyMuPDF ile sayfa görüntülerine çevirir ve
    GPT-4o Vision ile belge kategorisini ve o belgede bulunan GLP alanlarını ayrıştırır.
    """
    raw_filename = file.filename or ""
    content = _read_limited(file)
    filename, ext = validate_and_sanitize_upload(
        raw_filename=raw_filename,
        content=content,
        allowed_extensions=SUPPORTED_EXTENSIONS,
        max_mb=settings.MAX_UPLOAD_MB,
    )
    sha256 = hashlib.sha256(content).hexdigest()

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    stored_name = f"{datetime.utcnow():%Y%m%d%H%M%S}_{uuid.uuid4().hex[:8]}.{ext}"
    with open(os.path.join(settings.UPLOAD_DIR, stored_name), "wb") as fh:
        fh.write(content)

    resolved_key = (dossier_key or DEFAULT_DOSSIER_KEY).strip()
    resolved_label = (dossier_label or "").strip() or (
        DEFAULT_DOSSIER_LABEL if resolved_key == DEFAULT_DOSSIER_KEY else resolved_key
    )

    doc = Document(
        original_filename=filename,
        stored_filename=stored_name,
        content_type=file.content_type,
        size_bytes=len(content),
        sha256=sha256,
        dossier_key=resolved_key,
        dossier_label=resolved_label,
        uploaded_by_id=current_user.id,
        ai_model=settings.OPENAI_MODEL,
    )

    error: Optional[DocumentParsingError] = None
    try:
        result = document_parser.parse_document(content, filename)
        _apply_parse_result(doc, result)
    except DocumentParsingError as exc:
        error = exc
        doc.status = "FAILED"
        doc.error_message = exc.message

    db.add(doc)
    db.commit()
    db.refresh(doc)

    db.add(
        AuditLog(
            user_id=current_user.id,
            entity_name="Document",
            entity_id=doc.id,
            action="DOCUMENT_UPLOAD_AI_PARSE",
            new_values={
                "filename": filename,
                "sha256": sha256,
                "status": doc.status,
                "doc_category": doc.doc_category,
                "ai_model": doc.ai_model,
                "primary_study_code": doc.primary_study_code,
                "study_codes": doc.study_codes,
            },
            reason=(
                f"{current_user.username} '{filename}' belgesini yükledi; kategori: {doc.doc_category_label or '-'}, durum: {doc.status}."
                + (f" Hata: {doc.error_message}" if doc.error_message else "")
            ),
        )
    )
    db.commit()

    if error is not None:
        raise HTTPException(status_code=error.status_code, detail={"message": error.message, "document_id": doc.id})
    return _to_out(doc)


@router.get("/dossiers", summary="Çalışma Paketlerini (Dossier) Listele")
def list_dossier_packages(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_read),
):
    docs = db.query(Document).order_by(Document.uploaded_at.desc(), Document.id.desc()).all()
    buckets: Dict[str, List[Document]] = {}
    labels: Dict[str, str] = {}
    for d in docs:
        key = d.dossier_key or DEFAULT_DOSSIER_KEY
        buckets.setdefault(key, []).append(d)
        if d.dossier_label and key not in labels:
            labels[key] = d.dossier_label

    if DEFAULT_DOSSIER_KEY not in buckets:
        buckets[DEFAULT_DOSSIER_KEY] = []
        labels[DEFAULT_DOSSIER_KEY] = DEFAULT_DOSSIER_LABEL

    packages = []
    for key, pkg_docs in buckets.items():
        codes: List[str] = []
        sponsor = None
        for d in pkg_docs:
            ed = d.extracted_data or {}
            if not sponsor and ed.get("sponsor_name"):
                sponsor = ed.get("sponsor_name")
            for c in (d.study_codes or ed.get("study_codes") or []):
                if c and c not in codes:
                    codes.append(c)
        packages.append(
            {
                "dossier_key": key,
                "dossier_label": labels.get(key)
                or (DEFAULT_DOSSIER_LABEL if key == DEFAULT_DOSSIER_KEY else key),
                "document_count": len(pkg_docs),
                "sponsor_name": sponsor,
                "study_codes": codes,
            }
        )
    return {"default_dossier_key": DEFAULT_DOSSIER_KEY, "dossiers": packages}


@router.get("/dossier", summary="Birleştirilmiş Çalışma Dosyası Özeti (Master Study Profile)")
def get_dossier_summary(
    dossier_key: Optional[str] = Query(None, description="Filtrelenecek çalışma paketi anahtarı"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_read),
):
    from app.services.sample_service import compute_next_study_codes

    q = db.query(Document)
    if dossier_key:
        q = q.filter(Document.dossier_key == dossier_key)
    docs = q.order_by(Document.uploaded_at.desc(), Document.id.desc()).all()
    active_sds = _get_active_sds(db)
    summary = aggregate_dossier(docs, active_sds=active_sds, dossier_key=dossier_key)
    codes = compute_next_study_codes(db)
    summary["next_glp_code"] = codes["next_glp_code"]
    summary["next_non_glp_code"] = codes["next_non_glp_code"]
    return summary


@router.post("/{document_id}/reparse", response_model=DocumentOut, summary="Belgeyi Vision OCR ile Yeniden Analiz Et (Re-parse)")
def reparse_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_write),
):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Belge bulunamadı.")

    file_path = os.path.join(settings.UPLOAD_DIR, doc.stored_filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Belge dosyası diskte bulunamadı ({doc.stored_filename}).")

    with open(file_path, "rb") as fh:
        content = fh.read()

    try:
        result = document_parser.parse_document(content, doc.original_filename)
        _apply_parse_result(doc, result)
    except DocumentParsingError as exc:
        doc.status = "FAILED"
        doc.error_message = exc.message
        db.commit()
        raise HTTPException(status_code=exc.status_code, detail={"message": exc.message, "document_id": doc.id})

    db.add(
        AuditLog(
            user_id=current_user.id,
            entity_name="Document",
            entity_id=doc.id,
            action="DOCUMENT_REPARSE_VISION",
            new_values={
                "filename": doc.original_filename,
                "doc_category": doc.doc_category,
                "status": doc.status,
                "primary_study_code": doc.primary_study_code,
            },
            reason=f"{current_user.username} '{doc.original_filename}' belgesini GPT-4o Vision ile yeniden analiz etti.",
        )
    )
    db.commit()
    db.refresh(doc)
    return _to_out(doc)


@router.post("/reparse-all", summary="Yüklü Tüm Belgeleri Vision OCR ile Yeniden Analiz Et")
def reparse_all_documents(
    only_unparsed_vision: bool = Query(False, description="True ise yalnızca PDF_VISION ile analiz edilmemiş olanları işler"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_write),
):
    docs = db.query(Document).order_by(Document.id.asc()).all()
    reparsed_count = 0
    errors: List[Dict[str, Any]] = []

    for doc in docs:
        if only_unparsed_vision and doc.extraction_method == "PDF_VISION" and doc.doc_category:
            continue
        file_path = os.path.join(settings.UPLOAD_DIR, doc.stored_filename)
        if not os.path.exists(file_path):
            errors.append({"document_id": doc.id, "filename": doc.original_filename, "error": "Dosya diskte bulunamadı"})
            continue
        with open(file_path, "rb") as fh:
            content = fh.read()
        try:
            result = document_parser.parse_document(content, doc.original_filename)
            _apply_parse_result(doc, result)
            reparsed_count += 1
        except DocumentParsingError as exc:
            doc.status = "FAILED"
            doc.error_message = exc.message
            errors.append({"document_id": doc.id, "filename": doc.original_filename, "error": exc.message})

    db.add(
        AuditLog(
            user_id=current_user.id,
            entity_name="Document",
            entity_id=0,
            action="DOCUMENT_REPARSE_ALL_VISION",
            new_values={"reparsed_count": reparsed_count, "error_count": len(errors)},
            reason=f"{current_user.username} tarafından {reparsed_count} belge Vision OCR ile yeniden analiz edildi.",
        )
    )
    db.commit()
    all_docs = db.query(Document).order_by(Document.uploaded_at.desc(), Document.id.desc()).all()
    active_sds = _get_active_sds(db)
    return {
        "reparsed_count": reparsed_count,
        "errors": errors,
        "documents": [_to_out(d) for d in all_docs],
        "dossier": aggregate_dossier(all_docs, active_sds=active_sds),
    }


@router.delete("/{document_id}", summary="Belgeyi Dosyadan Kaldır")
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_write),
):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Belge bulunamadı.")
    filename = doc.original_filename
    db.delete(doc)
    db.add(
        AuditLog(
            user_id=current_user.id,
            entity_name="Document",
            entity_id=document_id,
            action="DELETE_DOCUMENT",
            old_values={"filename": filename},
            reason=f"{current_user.username} '{filename}' belgesini çalışma dosyasından kaldırdı.",
        )
    )
    db.commit()
    return {"status": "success", "deleted_id": document_id}


@router.get("", response_model=List[DocumentOut], summary="Yüklenen Belgeleri Listele")
@router.get("/", response_model=List[DocumentOut], include_in_schema=False)
def list_documents(
    dossier_key: Optional[str] = Query(None, description="Filtrelenecek çalışma paketi anahtarı"),
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_read),
):
    q = db.query(Document)
    if dossier_key:
        q = q.filter(Document.dossier_key == dossier_key)
    docs = q.order_by(Document.uploaded_at.desc(), Document.id.desc()).limit(min(limit, 200)).all()
    return [_to_out(d) for d in docs]


@router.get("/{document_id}", response_model=DocumentOut, summary="Belge Detayı")
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_read),
):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Belge bulunamadı.")
    return _to_out(doc)
