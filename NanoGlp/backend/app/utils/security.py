from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.role_permission import get_role_permission_map
from app.models.user import User, UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login",
    auto_error=False,
)

# Yönetim ekranlarında yazma yetkisi olan roller
MANAGEMENT_WRITE_ROLES = {
    UserRole.SYSADMIN,
    UserRole.TFM,
    UserRole.STUDY_DIRECTOR,
    UserRole.PLANNING_COORDINATOR,
    UserRole.ADMIN,
    "SYSADMIN",
    "TFM",
    "STUDY_DIRECTOR",
    "PLANNING_COORDINATOR",
    "ADMIN",
}

# Yönetim ekranlarını görüntüleme yetkisi olan roller (QA ve EXECUTIVE salt-okunur dahil)
MANAGEMENT_READ_ROLES = MANAGEMENT_WRITE_ROLES | {
    UserRole.QA,
    UserRole.EXECUTIVE,
    "QA",
    "EXECUTIVE",
}

# Kullanıcı Yönetimi (/api/v1/users) erişim yetkisi olan roller
USER_ADMIN_ROLES = {
    UserRole.SYSADMIN,
    UserRole.TFM,
    "SYSADMIN",
    "TFM",
}

MANAGEMENT_MENU_KEYS = {"dashboard", "upload", "planning", "personnel", "studies", "conflicts", "settings"}


def verify_password(plain_password: str, hashed_password: Optional[str]) -> bool:
    if not plain_password or not hashed_password:
        return False
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta if expires_delta is not None else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def enrich_user_with_permissions(user: User, db: Session) -> User:
    """User nesnesine veritabanındaki aktif RolePermission (allowed_menus, is_read_only, role_label) bilgilerini ekler."""
    try:
        role_code = user.role.value if hasattr(user.role, "value") else str(user.role)
        perm_map = get_role_permission_map(db)
        rp = perm_map.get(role_code)
        if rp is not None:
            user.role_label = rp.role_label
            user.allowed_menus = list(rp.allowed_menus or [])
            user.is_read_only = bool(rp.is_read_only)
        else:
            user.role_label = role_code
            user.allowed_menus = ["my_tasks"] if role_code in ("TECHNICIAN", "ANALYST") else ["dashboard", "planning", "personnel", "studies", "conflicts"]
            user.is_read_only = role_code in ("QA", "EXECUTIVE")
    except Exception:
        role_code = user.role.value if hasattr(user.role, "value") else str(user.role)
        user.role_label = role_code
        user.allowed_menus = ["my_tasks"] if role_code in ("TECHNICIAN", "ANALYST") else ["dashboard", "planning", "personnel", "studies", "conflicts"]
        user.is_read_only = role_code in ("QA", "EXECUTIVE")
    return user


def get_current_user(
    db: Session = Depends(get_db),
    token: Optional[str] = Depends(oauth2_scheme),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Oturum açmanız gerekiyor veya kimlik doğrulama anahtarı (JWT) geçersiz.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        sub = payload.get("sub")
        if sub is None:
            raise credentials_exception
        user_id = int(sub)
    except (JWTError, ValueError):
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise credentials_exception
    return enrich_user_with_permissions(user, db)


def require_management_read(current_user: User = Depends(get_current_user)) -> User:
    """SYSADMIN, EXECUTIVE (GM/GMY), TFM, SD, PLANNING_COORDINATOR, ADMIN ve QA (salt okunur) erişebilir; TECHNICIAN erişemez."""
    role_code = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    allowed_menus = set(getattr(current_user, "allowed_menus", None) or [])
    has_dynamic_mgmt_menu = bool(allowed_menus & MANAGEMENT_MENU_KEYS)

    if role_code not in MANAGEMENT_READ_ROLES and not has_dynamic_mgmt_menu:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu ekrana/veriye erişim yetkiniz bulunmamaktadır. Teknisyen rolü yalnızca kendi görevlerini görüntüleyebilir.",
        )
    return current_user


def require_management_write(current_user: User = Depends(get_current_user)) -> User:
    """Yalnızca yazma yetkisi olan yönetim rolleri kayıt oluşturabilir veya güncelleyebilir; QA ve EXECUTIVE (Salt Okunur) engellenir."""
    role_code = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    is_ro = getattr(current_user, "is_read_only", False)

    if role_code in ("QA", "EXECUTIVE") or is_ro:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Salt Okunur (İzleme Modu — QA / Üst Yönetim) rolü yalnızca izleme ve rapor indirme yetkisine sahiptir. Form gönderemez ve kayıt değiştiremez.",
        )
    allowed_menus = set(getattr(current_user, "allowed_menus", None) or [])
    has_dynamic_write = bool(allowed_menus & MANAGEMENT_MENU_KEYS) and not is_ro
    if role_code not in MANAGEMENT_WRITE_ROLES and not has_dynamic_write:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem için yönetim yazma yetkisi (SYSADMIN, TFM, Çalışma Yöneticisi veya Planlama Koordinatörü) gereklidir.",
        )
    return current_user


def require_user_admin(current_user: User = Depends(get_current_user)) -> User:
    """Yalnızca SYSADMIN ve TFM (veya users menüsü açık yönetici rolü) kullanıcı yönetimi (/api/v1/users) işlemlerini yapabilir."""
    role_code = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    allowed_menus = set(getattr(current_user, "allowed_menus", None) or [])
    if role_code not in USER_ADMIN_ROLES and "users" not in allowed_menus:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Kullanıcı yönetimi işlemlerine yalnızca SYSADMIN ve TFM rolleri erişebilir.",
        )
    return current_user


def require_sysadmin(current_user: User = Depends(get_current_user)) -> User:
    """Yalnızca SYSADMIN rol ve ekran yetki matrisini değiştirebilir."""
    role_code = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    if role_code not in ("SYSADMIN", "ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Rol ve ekran yetki matrisi yönetimi yalnızca Sistem Yöneticisi (SYSADMIN) yetkisindedir.",
        )
    return current_user
