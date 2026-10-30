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


def seed_default_equipment(db: Session) -> Equipment:
    """Varsayılan kritik cihaz olan Çalkalamalı Su Banyosu 1 (EQ-WB-001) kaydını oluşturur."""
    eq = db.query(Equipment).filter(Equipment.code == "EQ-WB-001").first()
    if eq is None:
        eq = Equipment(
            name="Çalkalamalı Su Banyosu 1",
            code="EQ-WB-001",
            category="Ekstraksiyon / İnkübasyon",
            status=EquipmentStatus.AVAILABLE,
            polar_capacity=3,
            non_polar_capacity=1,
            notes="Polar Max Kapasite: 3 çalışma, Apolar/Non-Polar Max Kapasite: 1 çalışma (72 Saatlik Ekstraksiyon)",
        )
        db.add(eq)
        db.commit()
        db.refresh(eq)
    else:
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
    return eq


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
