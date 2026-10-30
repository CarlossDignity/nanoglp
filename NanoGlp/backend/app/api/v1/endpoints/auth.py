from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.user import UserOut
from app.utils.security import create_access_token, get_current_user, verify_password

router = APIRouter(prefix="/auth", tags=["Kimlik Doğrulama ve Yetkilendirme (Auth & RBAC)"])


class LoginRequest(BaseModel):
    username: Optional[str] = None
    identifier: Optional[str] = None
    email: Optional[str] = None
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


async def _extract_credentials(request: Request) -> tuple[str, str]:
    """Hem JSON ({username, password}) hem de OAuth2 form-data (Swagger UI) destekler."""
    content_type = (request.headers.get("content-type") or "").lower()
    ident = ""
    password = ""

    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Geçersiz JSON gövdesi.")
        ident = (body.get("username") or body.get("identifier") or body.get("email") or "").strip()
        password = body.get("password") or ""
    else:
        form = await request.form()
        ident = str(form.get("username") or form.get("identifier") or form.get("email") or "").strip()
        password = str(form.get("password") or "")

    if not ident or not password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Kullanıcı adı ve şifre alanları zorunludur.",
        )
    return ident, password


@router.post("/login", response_model=TokenResponse, summary="JWT Oturum Açma (Kullanıcı Adı ile)")
async def login(request: Request, db: Session = Depends(get_db)):
    ident, password = await _extract_credentials(request)
    ident_lower = ident.lower()

    user = (
        db.query(User)
        .filter(
            User.is_active == True,  # noqa: E712
            or_(
                func.lower(User.username) == ident_lower,
                func.lower(User.email) == ident_lower,
            ),
        )
        .first()
    )

    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kullanıcı adı veya şifre hatalı.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        data={
            "sub": str(user.id),
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role.value,
        }
    )

    db.add(
        AuditLog(
            user_id=user.id,
            entity_name="User",
            entity_id=user.id,
            action="LOGIN",
            reason=f"{user.username} ({user.full_name} - {user.role.value}) sisteme giriş yaptı.",
        )
    )
    db.commit()

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user,
    }


@router.get("/me", response_model=UserOut, summary="Mevcut Oturum Kullanıcı Bilgisi")
def get_me(current_user: User = Depends(get_current_user)):
    return current_user
