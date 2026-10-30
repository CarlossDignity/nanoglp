from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
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
}

# Yönetim ekranlarını görüntüleme yetkisi olan roller (QA salt-okunur dahil)
MANAGEMENT_READ_ROLES = MANAGEMENT_WRITE_ROLES | {UserRole.QA}

# Kullanıcı Yönetimi (/api/v1/users) erişim yetkisi olan roller
USER_ADMIN_ROLES = {
    UserRole.SYSADMIN,
    UserRole.TFM,
}


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
    return user


def require_management_read(current_user: User = Depends(get_current_user)) -> User:
    """SYSADMIN, TFM, SD, PLANNING_COORDINATOR, ADMIN ve QA (salt okunur) erişebilir; TECHNICIAN erişemez."""
    if current_user.role not in MANAGEMENT_READ_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu ekrana/veriye erişim yetkiniz bulunmamaktadır. Teknisyen rolü yalnızca kendi görevlerini görüntüleyebilir.",
        )
    return current_user


def require_management_write(current_user: User = Depends(get_current_user)) -> User:
    """Yalnızca SYSADMIN, TFM, SD, PLANNING_COORDINATOR ve ADMIN kayıt oluşturabilir veya güncelleyebilir."""
    if current_user.role == UserRole.QA:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Kalite Güvence (QA) rolü SADECE OKUMA (Read-Only) yetkisine sahiptir. Form gönderemez ve kayıt değiştiremez.",
        )
    if current_user.role not in MANAGEMENT_WRITE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem için yönetim yetkisi (SYSADMIN, TFM, Çalışma Yöneticisi veya Planlama Koordinatörü) gereklidir.",
        )
    return current_user


def require_user_admin(current_user: User = Depends(get_current_user)) -> User:
    """Yalnızca SYSADMIN ve TFM kullanıcı yönetimi (/api/v1/users) işlemlerini yapabilir."""
    if current_user.role not in USER_ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Kullanıcı yönetimi işlemlerine yalnızca SYSADMIN ve TFM rolleri erişebilir.",
        )
    return current_user
