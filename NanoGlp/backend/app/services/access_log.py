from app.models.user_access_log import UserAccessLog
from app.utils.client_ip import client_ip


def record_access(db, request, event_type, user=None, identifier=None):
    db.add(
        UserAccessLog(
            user_id=user.id if user else None,
            username=user.username if user else None,
            attempted_identifier=identifier[:255] if identifier else None,
            email=user.email if user else None,
            full_name=user.full_name if user else None,
            role=(
                str(user.role.value if hasattr(user.role, "value") else user.role)
                if user
                else None
            ),
            event_type=event_type,
            ip_address=client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:1024] or None,
        )
    )
