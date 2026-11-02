"""
FAZ 8.2 — Numune çekmecesinden yüklenen TIIS / CoA / FM.083 belgelerinin saklanması, Vision OCR ile ayrıştırılması
ve çalışma kaydına (SampleRecord + Study.dossier_metadata) otomatik doldurulması.
"""
import hashlib
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.sample import SampleRecord
from app.models.study import Study
from app.models.user import User
from app.services import document_parser
from app.services.document_parser import SUPPORTED_EXTENSIONS, DocumentParsingError, aggregate_dossier

# (belge alanı, SampleRecord alanı, Study alanı, etiket)
AUTOFILL_FIELDS: List[Tuple[str, str, str, str]] = [
    ("lot_batch_no", "lot_no", "test_item_batch", "Lot / Seri No"),
    ("expiry_date", "expiry_date", "expiry_date", "Son Kullanma Tarihi"),
    ("manufacture_date", "manufacture_date", "manufacture_date", "Üretim Tarihi"),
    ("storage_conditions", "storage_condition", "test_item_storage_condition", "Saklama Koşulu"),
    ("sponsor_name", "sponsor_name", "sponsor_name", "Sponsor"),
    ("test_item_name", "test_item_name", "test_item_name", "Test Maddesi Adı"),
    ("extraction_polar_solvent", "extraction_polar_solvent", "extraction_polar_solvent", "Polar Ekstraksiyon Çözücüsü"),
    ("extraction_non_polar_solvent", "extraction_non_polar_solvent", "extraction_non_polar_solvent", "Apolar Ekstraksiyon Çözücüsü"),
    ("extraction_polar", "extraction_polar", "extraction_polar", "Polar Ekstraksiyon"),
    ("extraction_non_polar", "extraction_non_polar", "extraction_non_polar", "Apolar Ekstraksiyon"),
]
# Numune (test maddesi) düzeyinde olup aynı TI kodunu paylaşan çalışmalara boş olanlara yayılan alanlar
SHARED_ITEM_ATTRS = ("lot_no", "expiry_date", "manufacture_date", "storage_condition")

_PLACEHOLDER_PREFIXES = ("(numune bekleniyor", "belirtilmedi", "n/a", "-", "—")


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        v = value.strip().lower()
        return v == "" or any(v.startswith(p) for p in _PLACEHOLDER_PREFIXES)
    return False


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    return " ".join(str(a).lower().split()) == " ".join(str(b).lower().split())


def ingest_document(
    db: Session,
    content: bytes,
    filename: str,
    content_type: Optional[str],
    dossier_key: str,
    dossier_label: str,
    user: User,
) -> Tuple[Document, Optional[DocumentParsingError]]:
    """Dosyayı SHA-256 ile saklar, mevcut Vision OCR / PDF ayrıştırıcıyla okur ve Document kaydı oluşturur."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Desteklenmeyen dosya türü '.{ext}'. Desteklenen: PDF, XLSX, PNG, JPG, TXT, CSV.")
    sha256 = hashlib.sha256(content).hexdigest()
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    stored_name = f"{datetime.utcnow():%Y%m%d%H%M%S}_{uuid.uuid4().hex[:8]}.{ext}"
    with open(os.path.join(settings.UPLOAD_DIR, stored_name), "wb") as fh:
        fh.write(content)

    doc = Document(
        original_filename=filename,
        stored_filename=stored_name,
        content_type=content_type,
        size_bytes=len(content),
        sha256=sha256,
        dossier_key=dossier_key,
        dossier_label=dossier_label,
        uploaded_by_id=user.id,
        ai_model=settings.OPENAI_MODEL,
    )
    error: Optional[DocumentParsingError] = None
    try:
        result = document_parser.parse_document(content, filename)
        doc.extracted_data = result
        doc.extraction_method = result.get("extraction_method")
        doc.doc_category = result.get("doc_category")
        doc.doc_category_label = result.get("doc_category_label")
        doc.primary_study_code = result.get("primary_study_code")
        doc.study_codes = result.get("study_codes") or []
        doc.ai_model = result.get("ai_model") or settings.OPENAI_MODEL
        doc.status = "NEEDS_REVIEW" if result.get("needs_review") else "PARSED"
    except DocumentParsingError as exc:
        error = exc
        doc.status = "FAILED"
        doc.error_message = exc.message
    db.add(doc)
    db.commit()
    db.refresh(doc)
    db.add(
        AuditLog(
            user_id=user.id,
            entity_name="Document",
            entity_id=doc.id,
            action="DOCUMENT_UPLOAD_AI_PARSE",
            new_values={"filename": filename, "sha256": sha256, "status": doc.status, "dossier_key": dossier_key,
                        "doc_category": doc.doc_category, "source": "samples"},
            reason=(
                f"{user.username}: Numune & Çalışma Takip çekmecesinden '{filename}' yüklendi "
                f"({dossier_key}); kategori: {doc.doc_category_label or '-'}, durum: {doc.status}."
                + (f" Hata: {doc.error_message}" if doc.error_message else "")
            ),
        )
    )
    db.commit()
    return doc, error


def apply_document_autofill(
    db: Session,
    sample: SampleRecord,
    dossier_docs: List[Document],
    user: User,
    study: Optional[Study],
    related_samples: List[SampleRecord],
    overwrite: bool = False,
) -> Dict[str, Any]:
    """
    Klasördeki tüm belgelerden birleştirilmiş (aggregate_dossier) alanları SampleRecord'a ve bağlı Study'ye yazar.
    * Boş alanlar doldurulur; dolu ve farklı alanlar `differences` olarak bildirilir (overwrite=True ise üzerine yazılır).
    * Lot / SKT / Üretim / Saklama alanları aynı TI kodunu paylaşan diğer çalışmalara YALNIZCA boşsa yayılır.
    """
    usable = [d for d in dossier_docs if d.extracted_data and d.status != "FAILED"]
    if not usable:
        return {"applied": [], "differences": [], "fields": {}, "propagated_to": []}

    merged = aggregate_dossier(usable, dossier_key=sample.study_code).get("fields", {})
    applied: List[Dict[str, Any]] = []
    differences: List[Dict[str, Any]] = []
    changed_attrs: List[str] = []
    found: Dict[str, Any] = {}

    for doc_key, s_attr, _study_attr, label in AUTOFILL_FIELDS:
        entry = merged.get(doc_key)
        value = entry.get("value") if isinstance(entry, dict) else None
        if is_empty(value):
            continue
        source = entry.get("source_filename")
        found[s_attr] = {"value": value, "label": label, "source_filename": source}
        current = getattr(sample, s_attr)
        if is_empty(current):
            setattr(sample, s_attr, value)
            changed_attrs.append(s_attr)
            applied.append({"field": s_attr, "label": label, "value": value, "source_filename": source})
        elif not _same(current, value):
            if overwrite:
                setattr(sample, s_attr, value)
                changed_attrs.append(s_attr)
                applied.append({"field": s_attr, "label": label, "value": value, "source_filename": source, "overwritten": current})
            else:
                differences.append({"field": s_attr, "label": label, "current": current, "document_value": value, "source_filename": source})

    sample.document_autofill = {
        "at": datetime.utcnow().isoformat(timespec="seconds"),
        "by": user.full_name,
        "source_documents": [
            {"id": d.id, "filename": d.original_filename, "category": d.doc_category_label or d.doc_category, "status": d.status}
            for d in usable
        ],
        "fields": found,
    }

    if study is not None:
        _sync_study(study, sample, changed_attrs, sample.document_autofill)

    propagated: List[str] = []
    shared = [a for a in changed_attrs if a in SHARED_ITEM_ATTRS]
    if shared and sample.test_item_code:
        for other in related_samples:
            touched = False
            for attr in shared:
                if is_empty(getattr(other, attr)):
                    setattr(other, attr, getattr(sample, attr))
                    touched = True
            if touched:
                propagated.append(other.study_code)
                other_study = db.query(Study).filter(Study.study_code == other.study_code).first()
                if other_study is not None:
                    _sync_study(other_study, other, shared, None)

    db.add(
        AuditLog(
            user_id=user.id, entity_name="SampleRecord", entity_id=sample.id, action="SAMPLE_DOCUMENT_AUTOFILL",
            new_values={"applied": [a["field"] for a in applied], "differences": [d["field"] for d in differences],
                        "propagated_to": propagated},
            reason=(f"{user.username}: '{sample.study_code}' için belgelerden {len(applied)} alan otomatik dolduruldu, "
                    f"{len(differences)} alanda belge ile kayıt farklı."),
        )
    )
    return {"applied": applied, "differences": differences, "fields": found, "propagated_to": propagated}


def _sync_study(study: Study, sample: SampleRecord, attrs: List[str], autofill_meta: Optional[Dict[str, Any]]) -> None:
    """Değişen SampleRecord alanlarını bağlı Study kaydına ve dossier_metadata'ya yazar."""
    attr_map = {s: st for _d, s, st, _l in AUTOFILL_FIELDS}
    for a in attrs:
        st_attr = attr_map.get(a)
        if st_attr:
            setattr(study, st_attr, getattr(sample, a))
    if autofill_meta is not None:
        meta = dict(study.dossier_metadata or {})
        meta["document_autofill"] = autofill_meta
        study.dossier_metadata = meta
