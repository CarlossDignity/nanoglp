from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Literal
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user_access_log import UserAccessLog
from app.models.user import User
from app.utils.security import require_sysadmin
from app.utils.facility_time import FACILITY_TZ

router = APIRouter(prefix="/access-logs", tags=["Sistem Yöneticisi Erişim Kayıtları"])


@router.get("")
def list_access_logs(
    user_id: Optional[int] = None,
    user: Optional[str] = Query(None, max_length=255),
    event_type: Optional[Literal["LOGIN", "LOGIN_FAILED", "LOGOUT"]] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_sysadmin),
):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "Başlangıç tarihi bitiş tarihinden sonra olamaz.")
    q = db.query(UserAccessLog)
    if user_id is not None:
        q = q.filter(UserAccessLog.user_id == user_id)
    if user:
        pattern = (
            "%"
            + user.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%"
        )
        q = q.filter(
            or_(
                *(
                    col.ilike(pattern, escape="\\")
                    for col in (
                        UserAccessLog.username,
                        UserAccessLog.attempted_identifier,
                        UserAccessLog.email,
                        UserAccessLog.full_name,
                    )
                )
            )
        )
    if event_type:
        q = q.filter(UserAccessLog.event_type == event_type)

    def utc_midnight(d):
        return (
            datetime.combine(d, time.min, tzinfo=FACILITY_TZ)
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )

    try:
        if date_from:
            q = q.filter(UserAccessLog.created_at >= utc_midnight(date_from))
        if date_to:
            q = q.filter(
                UserAccessLog.created_at < utc_midnight(date_to + timedelta(days=1))
            )
    except OverflowError:
        raise HTTPException(422, "Tarih aralığı hesaplanamıyor.")
    total = q.count()
    rows = (
        q.order_by(UserAccessLog.created_at.desc(), UserAccessLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "timezone": "Europe/Istanbul",
        "items": [
            {
                **{c.name: getattr(r, c.name) for c in UserAccessLog.__table__.columns},
                "created_at": r.created_at.replace(tzinfo=timezone.utc).isoformat(),
            }
            for r in rows
        ],
    }
