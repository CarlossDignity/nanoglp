from datetime import datetime
from typing import Any, Dict, List
from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON
from sqlalchemy.orm import Session
from app.database import Base

# Sol menüdeki 9 ekranın kanonik anahtarları ve Türkçe etiketleri
ALL_MENU_KEYS: List[Dict[str, str]] = [
    {"key": "dashboard", "label": "Yönetici Paneli"},
    {"key": "samples", "label": "Numune & Çalışma Takip"},
    {"key": "upload", "label": "Belge Yükleme"},
    {"key": "planning", "label": "Çoklu Çalışma Planlama"},
    {"key": "personnel", "label": "Personel İş Yükü"},
    {"key": "studies", "label": "GLP Çalışmaları"},
    {"key": "conflicts", "label": "Açık Çakışmalar"},
    {"key": "my_tasks", "label": "Bugünkü Görevlerim"},
    {"key": "users", "label": "Kullanıcı Yönetimi"},
    {"key": "settings", "label": "Sistem Ayarları"},
]

DEFAULT_ROLE_PERMISSIONS: List[Dict[str, Any]] = [
    {
        "role_code": "EXECUTIVE",
        "role_label": "Üst Yönetim (GM / GMY)",
        "allowed_menus": ["dashboard", "samples", "planning", "personnel", "studies", "conflicts"],
        "is_read_only": True,
        "is_system": True,
    },
    {
        "role_code": "SYSADMIN",
        "role_label": "Sistem Yöneticisi (SYSADMIN)",
        "allowed_menus": [
            "dashboard",
            "samples",
            "upload",
            "planning",
            "personnel",
            "studies",
            "conflicts",
            "my_tasks",
            "users",
            "settings",
        ],
        "is_read_only": False,
        "is_system": True,
    },
    {
        "role_code": "TFM",
        "role_label": "Test Tesisi Yöneticisi (TFM)",
        "allowed_menus": [
            "dashboard",
            "samples",
            "upload",
            "planning",
            "personnel",
            "studies",
            "conflicts",
            "my_tasks",
            "users",
            "settings",
        ],
        "is_read_only": False,
        "is_system": True,
    },
    {
        "role_code": "STUDY_DIRECTOR",
        "role_label": "Çalışma Yöneticisi (SD)",
        "allowed_menus": [
            "dashboard",
            "samples",
            "upload",
            "planning",
            "personnel",
            "studies",
            "conflicts",
            "my_tasks",
            "settings",
        ],
        "is_read_only": False,
        "is_system": True,
    },
    {
        "role_code": "PLANNING_COORDINATOR",
        "role_label": "Planlama Koordinatörü (PK)",
        "allowed_menus": [
            "dashboard",
            "samples",
            "upload",
            "planning",
            "personnel",
            "studies",
            "conflicts",
            "my_tasks",
            "settings",
        ],
        "is_read_only": False,
        "is_system": True,
    },
    {
        "role_code": "QA",
        "role_label": "Kalite Güvence (QA)",
        "allowed_menus": [
            "dashboard",
            "samples",
            "upload",
            "planning",
            "personnel",
            "studies",
            "conflicts",
            "settings",
        ],
        "is_read_only": True,
        "is_system": True,
    },
    {
        "role_code": "TECHNICIAN",
        "role_label": "Teknisyen",
        "allowed_menus": ["my_tasks"],
        "is_read_only": False,
        "is_system": True,
    },
    {
        "role_code": "ANALYST",
        "role_label": "Analist",
        "allowed_menus": ["my_tasks"],
        "is_read_only": False,
        "is_system": True,
    },
    {
        "role_code": "SALES",
        "role_label": "Satış",
        "allowed_menus": ["samples", "dashboard"],
        "is_read_only": True,
        "is_system": True,
    },
    {
        "role_code": "TRM_KABUL",
        "role_label": "TRM Kabul (Test ve Referans Madde Kabul)",
        "allowed_menus": ["samples", "upload"],
        "is_read_only": False,
        "is_system": True,
    },
    {
        "role_code": "TRM_ACCEPTANCE",
        "role_label": "TRM Kabul (Test ve Referans Madde Kabul)",
        "allowed_menus": ["samples", "upload"],
        "is_read_only": False,
        "is_system": True,
    },
]


class RolePermission(Base):
    __tablename__ = "role_permissions"

    id = Column(Integer, primary_key=True, index=True)
    role_code = Column(String(64), unique=True, index=True, nullable=False)
    role_label = Column(String(255), nullable=False)
    allowed_menus = Column(JSON, default=list, nullable=False)
    is_read_only = Column(Boolean, default=False, nullable=False)
    is_system = Column(Boolean, default=False, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def ensure_default_role_permissions(db: Session) -> List[RolePermission]:
    """Varsayılan rol ve ekran yetkilerini (EXECUTIVE dahil) veritabanında oluşturur."""
    Base.metadata.create_all(bind=db.get_bind(), tables=[RolePermission.__table__])
    existing = {r.role_code: r for r in db.query(RolePermission).all()}
    added = False
    for item in DEFAULT_ROLE_PERMISSIONS:
        if item["role_code"] not in existing:
            row = RolePermission(
                role_code=item["role_code"],
                role_label=item["role_label"],
                allowed_menus=list(item["allowed_menus"]),
                is_read_only=bool(item["is_read_only"]),
                is_system=bool(item.get("is_system", False)),
            )
            db.add(row)
            added = True
    if added:
        db.commit()
    _migrate_add_samples_menu(db)
    _migrate_faz83_role_menus(db)
    return db.query(RolePermission).order_by(RolePermission.id.asc()).all()


def _migrate_add_samples_menu(db: Session) -> None:
    """FAZ 8.1: 'Numune & Çalışma Takip' menüsünü mevcut sistem rollerine BİR KEZ ekler (denetim izi işaretli)."""
    from app.models.audit_log import AuditLog

    marker = (
        db.query(AuditLog)
        .filter(AuditLog.entity_name == "RolePermission", AuditLog.action == "MIGRATE_ADD_SAMPLES_MENU")
        .first()
    )
    if marker is not None:
        return
    rows = {r.role_code: r for r in db.query(RolePermission).all()}
    for item in DEFAULT_ROLE_PERMISSIONS:
        if "samples" in item["allowed_menus"]:
            row = rows.get(item["role_code"])
            if row is not None and "samples" not in (row.allowed_menus or []):
                menus = list(row.allowed_menus or [])
                menus.insert(1 if menus and menus[0] == "dashboard" else 0, "samples")
                row.allowed_menus = menus
    db.add(
        AuditLog(
            entity_name="RolePermission",
            entity_id=0,
            action="MIGRATE_ADD_SAMPLES_MENU",
            reason="FAZ 8.1: 'Numune & Çalışma Takip' (samples) ekranı varsayılan rol yetkilerine eklendi.",
        )
    )
    db.commit()


def _migrate_faz83_role_menus(db: Session) -> None:
    """FAZ 8.3: SALES rolüne ['samples', 'dashboard'] ve TRM_KABUL/TRM_ACCEPTANCE rollerine ['samples', 'upload'] yetkilerini BİR KEZ ekler."""
    from app.models.audit_log import AuditLog

    marker = (
        db.query(AuditLog)
        .filter(AuditLog.entity_name == "RolePermission", AuditLog.action == "MIGRATE_FAZ83_ROLE_MENUS")
        .first()
    )
    if marker is not None:
        return
    rows = {r.role_code: r for r in db.query(RolePermission).all()}
    sales_row = rows.get("SALES")
    if sales_row is not None:
        menus = list(sales_row.allowed_menus or [])
        for k in ("samples", "dashboard"):
            if k not in menus:
                menus.append(k)
        sales_row.allowed_menus = menus
    for trm_code in ("TRM_KABUL", "TRM_ACCEPTANCE"):
        trm_row = rows.get(trm_code)
        if trm_row is not None:
            menus = list(trm_row.allowed_menus or [])
            for k in ("samples", "upload"):
                if k not in menus:
                    menus.append(k)
            trm_row.allowed_menus = menus
            trm_row.is_read_only = False
    db.add(
        AuditLog(
            entity_name="RolePermission",
            entity_id=0,
            action="MIGRATE_FAZ83_ROLE_MENUS",
            reason="FAZ 8.3: SALES rolüne ['samples', 'dashboard'] ve TRM_KABUL/TRM_ACCEPTANCE rollerine ['samples', 'upload'] yetkisi tanımlandı.",
        )
    )
    db.commit()


def get_role_permission_map(db: Session) -> Dict[str, RolePermission]:
    rows = ensure_default_role_permissions(db)
    return {r.role_code: r for r in rows}

