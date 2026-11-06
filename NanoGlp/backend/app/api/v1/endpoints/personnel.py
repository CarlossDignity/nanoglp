import re
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserOut, PersonnelCreate, PersonnelContactUpdate, validate_username_format
from app.models.audit_log import AuditLog
from sqlalchemy.exc import IntegrityError
from app.seed import DEFAULT_PASSWORD
from app.utils.security import get_password_hash, require_management_read, require_management_write

router = APIRouter(prefix="/personnel", tags=["Personel Yönetimi"])

_TR_MAP = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
EXCLUDED_PERSONNEL_ROLES = {"SYSADMIN", "ADMIN", "EXECUTIVE", "SALES", "TRM_KABUL", "TRM_ACCEPTANCE"}


def _role_str(user: User) -> str:
    return (user.role.value if hasattr(user.role, "value") else str(user.role or "")).strip().upper()


def _derive_unique_username(db: Session, full_name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", full_name.translate(_TR_MAP).strip().lower()).strip("_") or "personel"
    candidate = slug
    idx = 1
    while db.query(User).filter(func.lower(User.username) == candidate.lower()).first():
        idx += 1
        candidate = f"{slug}_{idx}"
    return candidate


@router.get("", response_model=List[UserOut])
@router.get("/", response_model=List[UserOut], include_in_schema=False)
def get_all_personnel(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_read),
):
    rows = db.query(User).order_by(User.id).all()
    return [
        u for u in rows
        if _role_str(u) not in EXCLUDED_PERSONNEL_ROLES and (u.username or "").strip().lower() != "yigit"
    ]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=UserOut, status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_personnel(
    user_in: PersonnelCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_write),
):
    role_code = (user_in.role.value if hasattr(user_in.role, "value") else str(user_in.role or "")).strip().upper()
    if role_code in EXCLUDED_PERSONNEL_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Personel İş Yükü ekranından yalnızca laboratuvar ve çalışma personeli (STUDY_DIRECTOR, TECHNICIAN, ANALYST, VET, QA, TFM, PLANNING_COORDINATOR) eklenebilir.",
        )
    if user_in.username:
        try:
            username = validate_username_format(user_in.username)
        except ValueError as ve:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
        if db.query(User).filter(func.lower(User.username) == username.lower()).first():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"'{username}' kullanıcı adı zaten mevcut.")
    else:
        username = _derive_unique_username(db, user_in.full_name)

    if user_in.email and db.query(User).filter(User.email == user_in.email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bu e-posta adresi ile kayıtlı bir personel zaten var.",
        )
    raw_password = (user_in.password or "").strip() or DEFAULT_PASSWORD
    user = User(
        username=username,
        email=user_in.email,
        phone=user_in.phone,
        full_name=user_in.full_name,
        role=user_in.role,
        is_active=user_in.is_active,
        qualifications=user_in.qualifications,
        max_daily_hours=user_in.max_daily_hours,
        hashed_password=get_password_hash(raw_password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}/contact", response_model=UserOut, summary="Yalnız Personel İletişim Bilgilerini Güncelle")
def update_personnel_contact(
    user_id: int,
    payload: "PersonnelContactUpdate",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_management_write),
):
    user = db.get(User, user_id)
    if user is None or _role_str(user) in EXCLUDED_PERSONNEL_ROLES:
        raise HTTPException(status_code=404, detail="Personel bulunamadı.")
    values = payload.model_dump(exclude_unset=True)
    if values.get("email") and db.query(User).filter(
        func.lower(User.email) == values["email"].lower(), User.id != user_id
    ).first():
        raise HTTPException(status_code=400, detail="Bu e-posta adresi başka bir kullanıcıda kayıtlı.")
    old = {key: getattr(user, key) for key in values}
    for key, value in values.items():
        setattr(user, key, value)
    if old != values:
        db.add(AuditLog(user_id=current_user.id, entity_name="User", entity_id=user.id,
                        action="UPDATE_PERSONNEL_CONTACT", old_values=old, new_values=values))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="İletişim bilgisi başka bir kullanıcıda kayıtlı.")
    db.refresh(user)
    return user
