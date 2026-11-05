"""
Gerçek Nanolab personel kayıtları ve veritabanı sıfırlama yardımcıları.

FAZ 5.1: Kurumsal kullanıcı adları (username) ile ekranda görünen tam adlar (full_name)
ayrılmıştır. Tüm varsayılan hesaplar 'Nanolab2026!' parolası (bcrypt ile hashlenmiş)
ile oluşturulur.
"""
from typing import List

from sqlalchemy.orm import Session

import app.models  # noqa: F401  (tüm tabloların metadata'ya kaydı)
from app.database import Base, engine
from app.models.audit_log import AuditLog
from app.models.equipment import Equipment, EquipmentStatus
from app.models.user import User, UserRole
from app.utils.security import get_password_hash

DEFAULT_PASSWORD = "Nanolab2026!"

REAL_PERSONNEL = (
    ("admin", "Sistem Yöneticisi", UserRole.SYSADMIN),
    ("emine", "Emine ARMUTOĞLU", UserRole.TFM),
    ("ezgi", "Ezgi Nur AKIN", UserRole.STUDY_DIRECTOR),
    ("koray", "Koray SAL", UserRole.PLANNING_COORDINATOR),
    ("invivo_1", "In Vivo Teknisyeni 1", UserRole.TECHNICIAN),
    ("invivo_2", "In Vivo Teknisyeni 2", UserRole.TECHNICIAN),
    ("qa_user", "Kalite Güvence Birimi", UserRole.QA),
)
MAX_DAILY_HOURS = 9


def seed_default_equipment(db: Session, commit: bool = True) -> Equipment:
    """Varsayılan kritik cihaz olan Çalkalamalı Su Banyosu 1 (EQ-WB-001) kaydını oluşturur."""
    read_only = (not commit) or db.in_nested_transaction()
    eq = db.query(Equipment).filter(Equipment.code == "EQ-WB-001").first()
    if eq is None:
        eq = Equipment(
            name="Çalkalamalı Su Banyosu 1",
            code="EQ-WB-001",
            category="Ekstraksiyon / İnkübasyon",
            status=EquipmentStatus.AVAILABLE,
            polar_capacity=3,
            non_polar_capacity=1,
            max_concurrent_studies=4,
            notes="Polar Max Kapasite: 3 çalışma, Apolar/Non-Polar Max Kapasite: 1 çalışma (72 Saatlik Ekstraksiyon)",
        )
        if not read_only:
            db.add(eq)
            db.commit()
            db.refresh(eq)
    else:
        if not read_only:
            changed = False
            if eq.polar_capacity is None:
                eq.polar_capacity = 3
                changed = True
            if eq.non_polar_capacity is None:
                eq.non_polar_capacity = 1
                changed = True
            if changed:
                db.commit()
                db.refresh(eq)
    seed_long_duration_equipment(db, commit=commit)
    return eq


# FAZ 8.1: Yalnızca 24-72+ saatlik uzun süreli darboğaz cihazları kapasite denetimine alınır
# (15 dakikalık kısa cihazlar dahil değildir). Eşzamanlı çalışma kapasiteleri Ayarlar ekranından düzenlenebilir.
LONG_DURATION_EQUIPMENT = (
    ("EQ-INC-001", "CO2 İnkübatörü", "Hücre Kültürü / İnkübasyon (24-72 saat)", 4,
     "24-72 saatlik hücre maruziyeti; eşzamanlı çalışma kapasitesi Ayarlar'dan düzenlenebilir."),
    ("EQ-OVN-001", "Etüv / İnkübatör", "Ekstraksiyon / İnkübasyon (24-72 saat)", 3,
     "24-72 saatlik 37 °C ekstraksiyon/inkübasyon; eşzamanlı çalışma kapasitesi Ayarlar'dan düzenlenebilir."),
)


def seed_long_duration_equipment(db: Session, commit: bool = True) -> None:
    """EQ-INC-001 (CO2 İnkübatörü) ve EQ-OVN-001 (Etüv/İnkübatör) kayıtlarını (yoksa) oluşturur."""
    from app.models.room_capacity import ensure_default_room_capacities

    read_only = (not commit) or db.in_nested_transaction()
    if read_only:
        ensure_default_room_capacities(db, commit=False)
        return
    existing = {e.code: e for e in db.query(Equipment).filter(Equipment.code.in_([c[0] for c in LONG_DURATION_EQUIPMENT])).all()}
    changed = False
    for code, name, category, cap, notes in LONG_DURATION_EQUIPMENT:
        row = existing.get(code)
        if row is None:
            db.add(
                Equipment(
                    name=name, code=code, category=category, status=EquipmentStatus.AVAILABLE,
                    polar_capacity=1, non_polar_capacity=1, max_concurrent_studies=cap, notes=notes,
                )
            )
            changed = True
        elif row.max_concurrent_studies is None:
            row.max_concurrent_studies = cap
            changed = True
    wb = db.query(Equipment).filter(Equipment.code == "EQ-WB-001").first()
    if wb is not None and wb.max_concurrent_studies is None:
        wb.max_concurrent_studies = (wb.polar_capacity or 3) + (wb.non_polar_capacity or 1)
        changed = True
    if changed:
        db.commit()
    ensure_default_room_capacities(db, commit=commit)


def reset_schema() -> None:
    """TÜM tabloları siler ve güncel şemayla yeniden oluşturur. Geri alınamaz."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def seed_personnel(db: Session, default_password: str = DEFAULT_PASSWORD) -> List[User]:
    """Kurumsal kullanıcı adları ve şifrelenmiş varsayılan parola ile personeli ekler."""
    hashed_pw = get_password_hash(default_password)
    users = []
    for username, full_name, role in REAL_PERSONNEL:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            if not existing.hashed_password:
                existing.hashed_password = hashed_pw
            users.append(existing)
            continue
        user = User(
            username=username,
            full_name=full_name,
            role=role,
            max_daily_hours=MAX_DAILY_HOURS,
            qualifications=[],
            email=None,
            hashed_password=hashed_pw,
        )
        db.add(user)
        users.append(user)
    db.commit()
    for u in users:
        db.refresh(u)
    seed_default_equipment(db)
    return users


def log_reset(db: Session, personnel_count: int) -> None:
    db.add(AuditLog(
        entity_name="System",
        entity_id=0,
        action="SYSTEM_RESET",
        new_values={"seeded_personnel": personnel_count, "auth_enabled": True},
        reason="FAZ 5.1: Kurumsal username standartları, SYSADMIN rolü ve bcrypt şifreleme ile başlatıldı.",
    ))
    db.commit()
