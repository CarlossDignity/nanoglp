from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.study import Study
from app.models.user import User
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.seed import DEFAULT_PASSWORD
from app.utils.security import get_password_hash, require_user_admin

router = APIRouter(prefix="/users", tags=["Kullanıcı Yönetimi (SYSADMIN & TFM)"])


@router.get("", response_model=List[UserOut], summary="Tüm Kullanıcıları Listele")
@router.get("/", response_model=List[UserOut], include_in_schema=False)
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user_admin),
):
    return db.query(User).order_by(User.id).all()


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED, summary="Yeni Kullanıcı Oluştur")
@router.post("/", response_model=UserOut, status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_user(
    user_in: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user_admin),
):
    if db.query(User).filter(func.lower(User.username) == user_in.username.lower()).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{user_in.username}' kullanıcı adı zaten kullanımda.",
        )
    if user_in.email and db.query(User).filter(func.lower(User.email) == user_in.email.lower()).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bu e-posta adresi ile kayıtlı bir kullanıcı zaten mevcut.",
        )

    raw_password = (user_in.password or "").strip() or DEFAULT_PASSWORD
    user = User(
        username=user_in.username,
        email=user_in.email,
        full_name=user_in.full_name.strip(),
        role=user_in.role,
        is_active=user_in.is_active,
        qualifications=user_in.qualifications or [],
        max_daily_hours=user_in.max_daily_hours,
        hashed_password=get_password_hash(raw_password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    db.add(
        AuditLog(
            user_id=current_user.id,
            entity_name="User",
            entity_id=user.id,
            action="CREATE_USER",
            new_values={"username": user.username, "full_name": user.full_name, "role": user.role.value},
            reason=f"{current_user.username} tarafından '{user.username}' kullanıcısı oluşturuldu.",
        )
    )
    db.commit()
    return user


@router.put("/{user_id}", response_model=UserOut, summary="Kullanıcı Bilgilerini ve Şifresini Güncelle")
def update_user(
    user_id: int,
    user_in: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı.")

    if user_in.username is not None and user_in.username.lower() != user.username.lower():
        conflict = db.query(User).filter(func.lower(User.username) == user_in.username.lower(), User.id != user_id).first()
        if conflict:
            raise HTTPException(status_code=400, detail=f"'{user_in.username}' kullanıcı adı zaten kullanımda.")
        user.username = user_in.username

    if user_in.email is not None:
        clean_email = user_in.email.strip() if user_in.email else None
        if clean_email:
            conflict = db.query(User).filter(func.lower(User.email) == clean_email.lower(), User.id != user_id).first()
            if conflict:
                raise HTTPException(status_code=400, detail="Bu e-posta adresi başka bir kullanıcıda kayıtlı.")
        user.email = clean_email

    if user_in.full_name is not None:
        user.full_name = user_in.full_name.strip()
    if user_in.role is not None:
        user.role = user_in.role
    if user_in.is_active is not None:
        if user.id == current_user.id and not user_in.is_active:
            raise HTTPException(status_code=400, detail="Kendi aktif oturum hesabınızı pasife alamazsınız.")
        user.is_active = user_in.is_active
    if user_in.qualifications is not None:
        user.qualifications = user_in.qualifications
    if user_in.max_daily_hours is not None:
        user.max_daily_hours = user_in.max_daily_hours
    if user_in.password and user_in.password.strip():
        user.hashed_password = get_password_hash(user_in.password.strip())

    db.add(
        AuditLog(
            user_id=current_user.id,
            entity_name="User",
            entity_id=user.id,
            action="UPDATE_USER",
            new_values={"username": user.username, "full_name": user.full_name, "role": user.role.value, "is_active": user.is_active},
            reason=f"{current_user.username} tarafından '{user.username}' kullanıcısı güncellendi.",
        )
    )
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", summary="Kullanıcıyı Sil")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı.")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Kendi aktif oturum hesabınızı silemezsiniz.")

    directed_count = db.query(Study).filter(Study.study_director_id == user.id).count()
    if directed_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"'{user.full_name}' {directed_count} GLP çalışmasında Çalışma Yöneticisi (SD) olarak kayıtlıdır. Denetim izi bütünlüğü için silinemez; pasife alabilirsiniz.",
        )

    deleted_username = user.username
    deleted_fullname = user.full_name
    user.assigned_steps = []
    db.delete(user)
    db.add(
        AuditLog(
            user_id=current_user.id,
            entity_name="User",
            entity_id=user_id,
            action="DELETE_USER",
            old_values={"username": deleted_username, "full_name": deleted_fullname},
            reason=f"{current_user.username} tarafından '{deleted_username}' kullanıcısı silindi.",
        )
    )
    db.commit()
    return {"status": "success", "message": f"'{deleted_username}' kullanıcısı silindi.", "deleted_id": user_id}
