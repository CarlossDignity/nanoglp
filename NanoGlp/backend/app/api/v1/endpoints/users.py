from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.role_permission import (
    ALL_MENU_KEYS,
    RolePermission,
    ensure_default_role_permissions,
)
from app.models.study import Study
from app.models.user import User
from app.schemas.user import (
    RolePermissionCreate,
    RolePermissionOut,
    RolePermissionUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.seed import DEFAULT_PASSWORD
from app.utils.security import (
    enrich_user_with_permissions,
    get_current_user,
    get_password_hash,
    require_sysadmin,
    require_user_admin,
)

router = APIRouter(prefix="/users", tags=["Kullanıcı ve Rol Yönetimi (SYSADMIN & TFM)"])

VALID_MENU_KEYS = {m["key"] for m in ALL_MENU_KEYS}


@router.get("/roles", response_model=List[RolePermissionOut], summary="Tüm Rolleri ve Ekran Yetki Matrisini Listele")
def list_roles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return ensure_default_role_permissions(db)


@router.post(
    "/roles",
    response_model=RolePermissionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Yeni Rol ve Ekran Yetkisi Oluştur (Sadece SYSADMIN)",
)
def create_role(
    role_in: RolePermissionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_sysadmin),
):
    ensure_default_role_permissions(db)
    code = role_in.role_code.strip().upper()
    if db.query(RolePermission).filter(func.upper(RolePermission.role_code) == code).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{code}' rol kodu zaten tanımlı.",
        )
    clean_label = (role_in.role_label or "").strip()
    if not clean_label:
        raise HTTPException(status_code=400, detail="Rol görünen adı (Türkçe etiket) zorunludur.")

    clean_menus = [m for m in (role_in.allowed_menus or []) if m in VALID_MENU_KEYS]
    if not clean_menus:
        clean_menus = ["dashboard"]

    row = RolePermission(
        role_code=code,
        role_label=clean_label,
        allowed_menus=clean_menus,
        is_read_only=bool(role_in.is_read_only),
        is_system=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    db.add(
        AuditLog(
            user_id=current_user.id,
            entity_name="RolePermission",
            entity_id=row.id,
            action="CREATE_ROLE_PERMISSION",
            new_values={
                "role_code": row.role_code,
                "role_label": row.role_label,
                "allowed_menus": row.allowed_menus,
                "is_read_only": row.is_read_only,
            },
            reason=f"SYSADMIN ({current_user.username}) tarafından '{row.role_code}' ({row.role_label}) rolü oluşturuldu.",
        )
    )
    db.commit()
    return row


@router.put(
    "/roles/{role_code}",
    response_model=RolePermissionOut,
    summary="Rolün Ekran Yetkilerini ve Salt Okunur Durumunu Güncelle (Sadece SYSADMIN)",
)
def update_role(
    role_code: str,
    role_in: RolePermissionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_sysadmin),
):
    ensure_default_role_permissions(db)
    code = role_code.strip().upper()
    row = db.query(RolePermission).filter(func.upper(RolePermission.role_code) == code).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"'{code}' rolü bulunamadı.")

    old_vals = {
        "role_label": row.role_label,
        "allowed_menus": list(row.allowed_menus or []),
        "is_read_only": bool(row.is_read_only),
    }

    if role_in.role_label is not None and role_in.role_label.strip():
        row.role_label = role_in.role_label.strip()

    if role_in.allowed_menus is not None:
        clean_menus = [m for m in role_in.allowed_menus if m in VALID_MENU_KEYS]
        # SYSADMIN kendi users yetkisini kilitlemesin
        if code == "SYSADMIN" and "users" not in clean_menus:
            clean_menus.append("users")
        row.allowed_menus = clean_menus

    if role_in.is_read_only is not None:
        # SYSADMIN salt okunur yapılamaz
        row.is_read_only = False if code == "SYSADMIN" else bool(role_in.is_read_only)

    db.add(
        AuditLog(
            user_id=current_user.id,
            entity_name="RolePermission",
            entity_id=row.id,
            action="UPDATE_ROLE_PERMISSION",
            old_values=old_vals,
            new_values={
                "role_label": row.role_label,
                "allowed_menus": row.allowed_menus,
                "is_read_only": row.is_read_only,
            },
            reason=f"SYSADMIN ({current_user.username}) tarafından '{row.role_code}' ekran yetkileri güncellendi.",
        )
    )
    db.commit()
    db.refresh(row)
    return row


@router.delete("/roles/{role_code}", summary="Özel Rolü Sil (Sadece SYSADMIN)")
def delete_role(
    role_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_sysadmin),
):
    ensure_default_role_permissions(db)
    code = role_code.strip().upper()
    row = db.query(RolePermission).filter(func.upper(RolePermission.role_code) == code).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"'{code}' rolü bulunamadı.")
    if row.is_system:
        raise HTTPException(status_code=400, detail="Varsayılan sistem rolleri silinemez; ekran yetkilerini düzenleyebilirsiniz.")

    used_count = db.query(User).filter(User.role == code).count()
    if used_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"'{code}' rolüne atanmış {used_count} kullanıcı bulunduğu için silinemez.",
        )

    rid = row.id
    db.delete(row)
    db.add(
        AuditLog(
            user_id=current_user.id,
            entity_name="RolePermission",
            entity_id=rid,
            action="DELETE_ROLE_PERMISSION",
            old_values={"role_code": code, "role_label": row.role_label},
            reason=f"SYSADMIN ({current_user.username}) tarafından '{code}' rolü silindi.",
        )
    )
    db.commit()
    return {"status": "success", "deleted_role_code": code}


@router.get("", response_model=List[UserOut], summary="Tüm Kullanıcıları Listele")
@router.get("/", response_model=List[UserOut], include_in_schema=False)
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user_admin),
):
    users = db.query(User).order_by(User.id).all()
    for u in users:
        enrich_user_with_permissions(u, db)
    return users


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED, summary="Yeni Kullanıcı Oluştur")
@router.post("/", response_model=UserOut, status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_user(
    user_in: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user_admin),
):
    ensure_default_role_permissions(db)
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
        department=user_in.department,
        is_active=user_in.is_active,
        qualifications=user_in.qualifications or [],
        max_daily_hours=user_in.max_daily_hours,
        hashed_password=get_password_hash(raw_password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    db.add(
        AuditLog(
            user_id=current_user.id,
            entity_name="User",
            entity_id=user.id,
            action="CREATE_USER",
            new_values={"username": user.username, "full_name": user.full_name, "role": role_val},
            reason=f"{current_user.username} tarafından '{user.username}' kullanıcısı oluşturuldu.",
        )
    )
    db.commit()
    enrich_user_with_permissions(user, db)
    return user


@router.put("/{user_id}", response_model=UserOut, summary="Kullanıcı Bilgilerini ve Şifresini Güncelle")
def update_user(
    user_id: int,
    user_in: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_user_admin),
):
    ensure_default_role_permissions(db)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı.")

    is_protected_yigit = (user.username or "").strip().lower() == "yigit"
    curr_role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    is_self_sysadmin = user.id == current_user.id and curr_role.upper() == "SYSADMIN"

    if user_in.username is not None and user_in.username.lower() != user.username.lower():
        if is_protected_yigit:
            raise HTTPException(status_code=400, detail="Ana sistem yöneticisi ('yigit') kullanıcı adı değiştirilemez.")
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
    if user_in.department is not None:
        user.department = user_in.department.strip() if user_in.department else None
    if user_in.role is not None:
        new_role_str = (user_in.role.value if hasattr(user_in.role, "value") else str(user_in.role)).strip().upper()
        if (is_protected_yigit or is_self_sysadmin) and new_role_str != "SYSADMIN":
            raise HTTPException(
                status_code=400,
                detail="Ana sistem yöneticisi ('yigit') veya kendi oturumundaki aktif SYSADMIN kullanıcısının rolü SYSADMIN dışına düşürülemez.",
            )
        user.role = user_in.role
    if user_in.is_active is not None:
        if (is_protected_yigit or user.id == current_user.id) and not user_in.is_active:
            raise HTTPException(
                status_code=400,
                detail="Ana sistem yöneticisi ('yigit') veya kendi aktif oturum hesabınızı pasife alamazsınız.",
            )
        user.is_active = user_in.is_active
    if user_in.qualifications is not None:
        user.qualifications = user_in.qualifications
    if user_in.max_daily_hours is not None:
        user.max_daily_hours = user_in.max_daily_hours
    if user_in.password and user_in.password.strip():
        user.hashed_password = get_password_hash(user_in.password.strip())

    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    db.add(
        AuditLog(
            user_id=current_user.id,
            entity_name="User",
            entity_id=user.id,
            action="UPDATE_USER",
            new_values={"username": user.username, "full_name": user.full_name, "role": role_val, "is_active": user.is_active},
            reason=f"{current_user.username} tarafından '{user.username}' kullanıcısı güncellendi.",
        )
    )
    db.commit()
    db.refresh(user)
    enrich_user_with_permissions(user, db)
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
    if (user.username or "").strip().lower() == "yigit":
        raise HTTPException(status_code=400, detail="Ana sistem yöneticisi ('yigit') silinemez.")
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
    db.query(AuditLog).filter(AuditLog.user_id == user_id).update({AuditLog.user_id: None}, synchronize_session=False)
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
