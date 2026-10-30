import re
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr, field_validator
from app.models.user import UserRole

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")


def validate_username_format(value: str) -> str:
    v = (value or "").strip()
    if len(v) < 2 or len(v) > 100:
        raise ValueError("Kullanıcı adı 2 ile 100 karakter arasında olmalıdır.")
    if not USERNAME_PATTERN.match(v):
        raise ValueError(
            "Kullanıcı adı boşluk içeremez; yalnızca İngilizce harf, rakam ve '_', '-', '.' karakterlerinden oluşabilir."
        )
    return v.lower()


class UserBase(BaseModel):
    username: str
    email: Optional[EmailStr] = None
    full_name: str
    role: UserRole = UserRole.ANALYST
    is_active: bool = True
    qualifications: List[str] = []
    max_daily_hours: int = 9

    @field_validator("username")
    @classmethod
    def _check_username(cls, v: str) -> str:
        return validate_username_format(v)


class UserCreate(UserBase):
    password: Optional[str] = None


class PersonnelCreate(BaseModel):
    """Personel ekranından hızlı ekleme için (username verilmezse full_name'den türetilir)."""
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    full_name: str
    role: UserRole = UserRole.TECHNICIAN
    is_active: bool = True
    qualifications: List[str] = []
    max_daily_hours: int = 9
    password: Optional[str] = None


class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    qualifications: Optional[List[str]] = None
    max_daily_hours: Optional[int] = None
    password: Optional[str] = None

    @field_validator("username")
    @classmethod
    def _check_optional_username(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return validate_username_format(v)


class UserOut(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
