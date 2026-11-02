from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.test_restriction import TestRestriction
from app.models.user import User
from app.services.capacity_service import apply_restriction_shift
from app.services.templates import TEMPLATES, resolve_template_code
from app.utils.security import require_management_read, require_management_write

router = APIRouter(prefix="/restrictions", tags=["Test Kısıtlama ve Uygunluk Takvimi (FAZ 8.1)"])


class RestrictionIn(BaseModel):
    template_code: str = "ALL"
    test_name: str
    restricted_from: date
    restricted_until: date
    reason: str
    is_active: bool = True

    @field_validator("template_code")
    @classmethod
    def _code(cls, v: str) -> str:
        code = resolve_template_code(v) or "ALL"
        if code != "ALL" and code not in TEMPLATES:
            raise ValueError(f"Tanımsız test şablonu: '{v}'. Geçerli: ALL, {', '.join(TEMPLATES)}")
        return code

    @field_validator("test_name", "reason")
    @classmethod
    def _text(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Bu alan boş bırakılamaz.")
        return v

    @model_validator(mode="after")
    def _range(self):
        if self.restricted_until < self.restricted_from:
            raise ValueError("Kısıtlama bitiş tarihi, başlangıç tarihinden önce olamaz.")
        return self


class RestrictionUpdate(BaseModel):
    template_code: Optional[str] = None
    test_name: Optional[str] = None
    restricted_from: Optional[date] = None
    restricted_until: Optional[date] = None
    reason: Optional[str] = None
    is_active: Optional[bool] = None


class ShiftPreviewIn(BaseModel):
    template_code: str
    start_date: date


def _serialize(r: TestRestriction) -> dict:
    code = resolve_template_code(r.template_code)
    tpl = TEMPLATES.get(code)
    today = date.today()
    return {
        "id": r.id,
        "template_code": code,
        "template_label": "Tüm Testler" if code == "ALL" else (f"{tpl.standard} — {tpl.title}" if tpl else code),
        "test_name": r.test_name,
        "restricted_from": r.restricted_from.isoformat(),
        "restricted_until": r.restricted_until.isoformat(),
        "reason": r.reason,
        "is_active": bool(r.is_active),
        "is_current": bool(r.is_active and r.restricted_from <= today <= r.restricted_until),
        "is_expired": r.restricted_until < today,
        "created_by": r.created_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("", summary="Test Kısıtlama Kayıtlarını Listele")
@router.get("/", include_in_schema=False)
def list_restrictions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_read),
):
    rows = db.query(TestRestriction).order_by(TestRestriction.restricted_until.desc(), TestRestriction.id.desc()).all()
    return {
        "restrictions": [_serialize(r) for r in rows],
        "templates": [{"code": "ALL", "label": "Tüm Testler"}]
        + [{"code": t.code, "label": f"{t.standard} — {t.title}"} for t in TEMPLATES.values()],
    }


@router.post("", status_code=status.HTTP_201_CREATED, summary="Yeni Test Kısıtlaması Ekle")
@router.post("/", status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_restriction(
    payload: RestrictionIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_write),
):
    row = TestRestriction(
        template_code=payload.template_code,
        test_name=payload.test_name,
        restricted_from=payload.restricted_from,
        restricted_until=payload.restricted_until,
        reason=payload.reason,
        is_active=payload.is_active,
        created_by=current_user.full_name,
    )
    db.add(row)
    db.flush()
    db.add(
        AuditLog(
            user_id=current_user.id, entity_name="TestRestriction", entity_id=row.id, action="CREATE_TEST_RESTRICTION",
            new_values=_serialize(row),
            reason=(
                f"{current_user.username}: '{row.test_name}' testi '{row.reason}' nedeniyle "
                f"{row.restricted_until:%d.%m.%Y} tarihine kadar kısıtlandı."
            ),
        )
    )
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.put("/{restriction_id}", summary="Test Kısıtlamasını Güncelle")
def update_restriction(
    restriction_id: int,
    payload: RestrictionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_write),
):
    row = db.query(TestRestriction).filter(TestRestriction.id == restriction_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Kısıtlama kaydı bulunamadı.")
    old = _serialize(row)
    data = payload.model_dump(exclude_unset=True)
    if "template_code" in data and data["template_code"] is not None:
        code = resolve_template_code(data["template_code"]) or "ALL"
        if code != "ALL" and code not in TEMPLATES:
            raise HTTPException(status_code=422, detail=f"Tanımsız test şablonu: '{data['template_code']}'.")
        row.template_code = code
    for f in ("test_name", "reason"):
        if data.get(f) is not None:
            if not str(data[f]).strip():
                raise HTTPException(status_code=422, detail=f"'{f}' boş bırakılamaz.")
            setattr(row, f, str(data[f]).strip())
    for f in ("restricted_from", "restricted_until", "is_active"):
        if data.get(f) is not None:
            setattr(row, f, data[f])
    if row.restricted_until < row.restricted_from:
        raise HTTPException(status_code=422, detail="Kısıtlama bitiş tarihi, başlangıç tarihinden önce olamaz.")
    db.add(
        AuditLog(
            user_id=current_user.id, entity_name="TestRestriction", entity_id=row.id, action="UPDATE_TEST_RESTRICTION",
            old_values=old, new_values=_serialize(row),
            reason=f"{current_user.username}: '{row.test_name}' kısıtlaması güncellendi.",
        )
    )
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.delete("/{restriction_id}", summary="Test Kısıtlamasını Sil")
def delete_restriction(
    restriction_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_write),
):
    row = db.query(TestRestriction).filter(TestRestriction.id == restriction_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Kısıtlama kaydı bulunamadı.")
    old = _serialize(row)
    db.delete(row)
    db.add(
        AuditLog(
            user_id=current_user.id, entity_name="TestRestriction", entity_id=restriction_id,
            action="DELETE_TEST_RESTRICTION", old_values=old,
            reason=f"{current_user.username}: '{old['test_name']}' kısıtlaması silindi.",
        )
    )
    db.commit()
    return {"status": "success", "deleted_id": restriction_id}


@router.post("/preview-shift", summary="Seçilen Test ve Gün 0 İçin Otomatik Ötelemeyi Önizle")
def preview_shift(
    payload: ShiftPreviewIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_read),
):
    code = resolve_template_code(payload.template_code)
    if code not in TEMPLATES:
        raise HTTPException(status_code=422, detail=f"Tanımsız test şablonu: '{payload.template_code}'.")
    res = apply_restriction_shift(db, code, payload.start_date)
    return {
        "requested_start_date": payload.start_date.isoformat(),
        "new_start_date": res["g0"].isoformat(),
        "shifted": res["shifted"],
        "notice": res["notice"],
        "restrictions": res["restrictions"],
    }
