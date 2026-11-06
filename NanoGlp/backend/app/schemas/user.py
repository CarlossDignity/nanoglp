import re
from datetime import datetime
from typing import List, Optional, Union
from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator
from app.models.user import UserRole

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")
ROLE_CODE_PATTERN = re.compile(r"^[A-Z0-9_]{2,40}$")


def validate_username_format(value: str) -> str:
    v = (value or "").strip()
    if len(v) < 2 or len(v) > 100:
        raise ValueError("Kullanıcı adı 2 ile 100 karakter arasında olmalıdır.")
    if not USERNAME_PATTERN.match(v):
        raise ValueError(
            "Kullanıcı adı boşluk içeremez; yalnızca İngilizce harf, rakam ve '_', '-', '.' karakterlerinden oluşabilir."
        )
    return v.lower()


def normalize_role_code(value: Union[str, UserRole]) -> str:
    if isinstance(value, UserRole):
        return value.value
    v = (str(value) if value is not None else "").strip().upper()
    if not ROLE_CODE_PATTERN.match(v):
        raise ValueError("Rol kodu yalnızca büyük harf, rakam ve '_' içerebilir (2-40 karakter).")
    return v


class ContactFields(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=60)

    @field_validator("email", "phone", mode="before")
    @classmethod
    def _blank_contact(cls, value):
        return (value.strip() or None) if isinstance(value, str) else value


class PersonnelContactUpdate(ContactFields):
    model_config = ConfigDict(extra="forbid")


class UserBase(ContactFields):
    username: str
    email: Optional[EmailStr] = None
    full_name: str
    role: Union[UserRole, str] = UserRole.ANALYST
    department: Optional[str] = None
    is_active: bool = True
    qualifications: List[str] = []
    max_daily_hours: int = 9

    @field_validator("username")
    @classmethod
    def _check_username(cls, v: str) -> str:
        return validate_username_format(v)

    @field_validator("role", mode="before")
    @classmethod
    def _check_role(cls, v: Union[str, UserRole]) -> str:
        return normalize_role_code(v)


class UserCreate(UserBase):
    password: Optional[str] = None


class PersonnelCreate(ContactFields):
    """Personel ekranından hızlı ekleme için (username verilmezse full_name'den türetilir)."""
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    full_name: str
    role: Union[UserRole, str] = UserRole.TECHNICIAN
    is_active: bool = True
    qualifications: List[str] = []
    max_daily_hours: int = 9
    password: Optional[str] = None

    @field_validator("role", mode="before")
    @classmethod
    def _check_role(cls, v: Union[str, UserRole]) -> str:
        return normalize_role_code(v)


class UserUpdate(ContactFields):
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: Optional[Union[UserRole, str]] = None
    department: Optional[str] = None
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

    @field_validator("role", mode="before")
    @classmethod
    def _check_optional_role(cls, v: Optional[Union[str, UserRole]]) -> Optional[str]:
        if v is None:
            return None
        return normalize_role_code(v)


class UserOut(UserBase):
    id: int
    role_label: Optional[str] = None
    allowed_menus: Optional[List[str]] = None
    is_read_only: Optional[bool] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RolePermissionCreate(BaseModel):
    role_code: str
    role_label: str
    allowed_menus: List[str] = []
    is_read_only: bool = False

    @field_validator("role_code")
    @classmethod
    def _check_code(cls, v: str) -> str:
        return normalize_role_code(v)


class RolePermissionUpdate(BaseModel):
    role_label: Optional[str] = None
    allowed_menus: Optional[List[str]] = None
    is_read_only: Optional[bool] = None


class RolePermissionOut(BaseModel):
    id: int
    role_code: str
    role_label: str
    allowed_menus: List[str]
    is_read_only: bool
    is_system: bool
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
