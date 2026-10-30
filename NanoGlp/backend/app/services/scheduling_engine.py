"""
NANOLAB GLP AI - OPERASYONEL PLANLAMA VE ÇAKIŞMA YÖNETİM MOTORU (SCHEDULING ENGINE)

KESİN GLP KURALLARI:
1. WORKLOAD_EXCEEDS_9H: Günlük çalışma süresi 540 dakikayı (9 saati) aşan personele CRITICAL PERSONNEL_OVERLAP.
2. BİYOLOJİK ZAMAN KİLİDİ: is_biological_fixed_time == True olan görevler "personel dolu" veya
   "mesai bitti / hafta sonu" gerekçesiyle kaydırılamaz. Doğrudan BIOLOGICAL_TIME_VIOLATION üretilir.
3. YENİ ÇALIŞMA EKLEME (Non-Destructive): Onaylanmış (APPROVED / IN_PROGRESS) çalışmaların saatlerine
   dokunulmaz. Yalnızca DRAFT çalışmalar (yeniden) planlanabilir.
4. TASLAK ↔ TASLAK KONTROLÜ: Yeni taslak, diğer DRAFT çalışmalarla da kıyaslanır (onlar da değiştirilmez).

Motor hiçbir koşulda görev saatini kendi kendine öteleyemez; yalnızca çakışmaları raporlar.
"""

from datetime import datetime, date, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.models.user import User, UserRole
from app.models.study import Study, StudyStatus
from app.models.study_step import StudyStep, StepStatus
from app.models.conflict import Conflict, ConflictType, ConflictSeverity
from app.models.equipment import Equipment
from app.models.audit_log import AuditLog
from app.seed import seed_default_equipment
from app.services.templates import DEFAULT_TEMPLATE_CODE, TemplateStep, get_template

MAX_DAILY_WORKLOAD_MINUTES = 540  # 9 Saat = 540 Dakika (Yasal & GLP Üst Sınırı)
WORKDAY_START = time(8, 0)
WORKDAY_END = time(18, 0)

# Yeni taslağın kıyaslandığı çalışma durumları (bu çalışmalar ASLA değiştirilmez)
COMPARED_STUDY_STATUSES = (StudyStatus.APPROVED, StudyStatus.IN_PROGRESS, StudyStatus.DRAFT)
LOCKED_STUDY_STATUSES = (StudyStatus.APPROVED, StudyStatus.IN_PROGRESS)

_TR_DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


def _fmt(dt: datetime) -> str:
    return dt.strftime("%d.%m.%Y %H:%M")


def _overlap_minutes(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> int:
    return max(0, int((min(a_end, b_end) - max(a_start, b_start)).total_seconds() // 60))


def _working_hours_issue(start: datetime, end: datetime) -> Optional[str]:
    """Görev hafta sonuna veya mesai dışına düşüyorsa açıklama döner."""
    if start.weekday() >= 5:
        return f"hafta sonuna ({_TR_DAYS[start.weekday()]} {start:%d.%m.%Y}) denk geliyor"
    if start.time() < WORKDAY_START or end.time() > WORKDAY_END or end.date() != start.date():
        return (f"mesai saatleri ({WORKDAY_START:%H:%M}–{WORKDAY_END:%H:%M}) dışına taşıyor "
                f"({start:%H:%M}–{end:%H:%M})")
    return None


# ---------------------------------------------------------------------------
# KURAL 1: 9 SAAT İŞ YÜKÜ
# ---------------------------------------------------------------------------
def calculate_personnel_workload(db: Session, personnel_id: int, target_date: date) -> Dict[str, Any]:
    """
    SALT-OKUNUR iş yükü hesabı: Personelin hedef gündeki aktif görevlerinin o güne düşen
    dakikalarını toplar. Conflict tablosuna YAZMAZ (dashboard / personel ekranı için).
    İptal edilmiş görevler ve iptal edilmiş çalışmaların görevleri sayılmaz.
    """
    day_start = datetime.combine(target_date, time.min)
    day_end = datetime.combine(target_date, time.max)

    steps = (
        db.query(StudyStep)
        .join(StudyStep.assignees)
        .join(StudyStep.study)
        .filter(
            User.id == personnel_id,
            StudyStep.status != StepStatus.CANCELLED,
            Study.status != StudyStatus.CANCELLED,
            StudyStep.planned_start <= day_end,
            StudyStep.planned_end >= day_start,
        )
        .order_by(StudyStep.planned_start)
        .all()
    )

    total_minutes = 0
    tasks = []
    for step in steps:
        # Görevin o gün içerisine düşen süresi (gece yarısını aşan görevler bölünür)
        minutes = _overlap_minutes(step.planned_start, step.planned_end, day_start, day_end + timedelta(microseconds=1))
        total_minutes += minutes
        tasks.append({
            "step_id": step.id,
            "study_id": step.study_id,
            "study_code": step.study.study_code,
            "study_status": step.study.status.value,
            "step_name": step.step_name,
            "study_day": step.study_day,
            "planned_start": step.planned_start.isoformat(),
            "planned_end": step.planned_end.isoformat(),
            "minutes": minutes,
            "is_biological_fixed_time": step.is_biological_fixed_time,
        })

    return {
        "personnel_id": personnel_id,
        "date": target_date.isoformat(),
        "total_minutes": total_minutes,
        "limit_minutes": MAX_DAILY_WORKLOAD_MINUTES,
        "exceeds_limit": total_minutes > MAX_DAILY_WORKLOAD_MINUTES,
        "tasks": tasks,
    }


def _build_workload_conflict(
    db: Session,
    personnel: User,
    target_date: date,
    study_id: Optional[int],
    step_id: Optional[int] = None,
) -> Optional[Conflict]:
    """540 dk aşılmışsa CRITICAL PERSONNEL_OVERLAP oluşturur (commit etmez)."""
    workload = calculate_personnel_workload(db, personnel.id, target_date)
    total = workload["total_minutes"]
    if total <= MAX_DAILY_WORKLOAD_MINUTES:
        return None

    title = f"9 Saat İş Yükü Aşımı: {personnel.full_name} — {target_date:%d.%m.%Y}"
    existing = db.query(Conflict).filter(
        Conflict.conflict_type == ConflictType.PERSONNEL_OVERLAP,
        Conflict.is_resolved == False,  # noqa: E712
        Conflict.title == title,
        Conflict.study_id == study_id,
    ).first()
    if existing:
        return existing

    details = ", ".join(
        f"{t['study_code']} ({t['study_status']}) / '{t['step_name']}' {t['minutes']} dk" for t in workload["tasks"]
    )
    conflict = Conflict(
        conflict_type=ConflictType.PERSONNEL_OVERLAP,
        severity=ConflictSeverity.CRITICAL,
        title=title,
        description=(
            f"{personnel.full_name} ({personnel.role.value}) {target_date:%d.%m.%Y} tarihinde toplam {total} dk "
            f"({total / 60:.1f} sa) görevlendirilmiş; {MAX_DAILY_WORKLOAD_MINUTES} dk (9 sa) sınırı "
            f"{total - MAX_DAILY_WORKLOAD_MINUTES} dk aşıldı. Görevler: {details}. "
            f"Sistem saati sessizce kaydırmaz; ek personel atanmalı veya plan SD onayıyla revize edilmelidir."
        ),
        study_id=study_id,
        step_id=step_id,
        is_resolved=False,
    )
    db.add(conflict)
    return conflict


def check_personnel_workload(
    db: Session,
    personnel_id: int,
    target_date: date,
    study_id: Optional[int] = None,
) -> Optional[Conflict]:
    """
    KURAL 1: WORKLOAD_EXCEEDS_9H KONTROLÜ
    Personelin hedef gündeki görev sürelerinin toplamı 540 dakikayı aşıyorsa Conflict tablosuna
    CRITICAL PERSONNEL_OVERLAP kaydeder. Sistemi asla sessizce saati kaydırmaya zorlamaz.
    """
    personnel = db.query(User).filter(User.id == personnel_id).first()
    if not personnel:
        return None
    conflict = _build_workload_conflict(db, personnel, target_date, study_id)
    if conflict is not None:
        db.commit()
        db.refresh(conflict)
    return conflict


# ---------------------------------------------------------------------------
# KURAL 2: BİYOLOJİK ZAMAN KİLİDİ
# ---------------------------------------------------------------------------
def register_biological_time_violation(
    db: Session,
    step: StudyStep,
    reason: str = "Personel dolu veya mesai bitti gerekçesiyle saat kaydırma denemesi",
    attempted_time: Optional[datetime] = None,
    related_study_id: Optional[int] = None,
    title: Optional[str] = None,
    severity: ConflictSeverity = ConflictSeverity.CRITICAL,
    commit: bool = True,
) -> Conflict:
    """
    is_biological_fixed_time == True olan bir görevin TARİHİ/SAATİ değiştirilemez.
    Bunun yerine Conflict tablosuna BIOLOGICAL_TIME_VIOLATION kaydedilir.
    Hafta sonu / mesai dışı uyarıları WARNING seviyesinde üretilir ve tek tıkla
    nöbetçi personel onayı veya Cuma ekstraksiyon hizalaması ile çözülebilir.
    """
    attempted_info = f" Denenen yeni zaman: {_fmt(attempted_time)}." if attempted_time else ""
    conflict = Conflict(
        conflict_type=ConflictType.BIOLOGICAL_TIME_VIOLATION,
        severity=severity,
        title=title or f"Biyolojik Zaman Kilidi: {step.step_name}",
        description=(
            f"'{step.step_name}' biyolojik kilitli (planlanan: {_fmt(step.planned_start)}, "
            f"tolerans ±{step.biological_tolerance_minutes} dk).{attempted_info} Gerekçe: {reason} "
            f"GLP kuralı: Biyolojik saatler kendiliğinden KAYDIRILAMAZ. "
            f"Nöbetçi/yedek yetkin personel onaylanmalı veya ekstraksiyon başlangıcı Cuma'ya hizalanmalıdır."
        ),
        study_id=step.study_id,
        step_id=step.id,
        related_study_id=related_study_id,
        is_resolved=False,
    )
    db.add(conflict)
    if commit:
        db.commit()
        db.refresh(conflict)
    return conflict


# ---------------------------------------------------------------------------
# KURAL 3 & 4: YENİ ÇALIŞMA (ŞABLONDAN) — NON-DESTRUCTIVE, TASLAK ↔ TASLAK KONTROLLÜ
# ---------------------------------------------------------------------------
def _supersede_previous_plan(db: Session, study: Study, now: datetime) -> Tuple[int, int]:
    """
    Taslak yeniden planlanırken eski adımları kaldırır. Eski çakışma kayıtları SİLİNMEZ (denetim izi);
    'SUPERSEDED' notuyla kapatılır. Bu taslağı karşı taraf olarak içeren diğer taslakların
    çakışmaları da kapatılır (çünkü artık geçerli değiller).
    """
    note = (f"SUPERSEDED: {study.study_code} taslak planı {now:%d.%m.%Y %H:%M} UTC itibarıyla yeniden "
            f"analiz edildi; bu kayıt yerini yeni analize bıraktı.")
    superseded = db.query(Conflict).filter(
        Conflict.is_resolved == False,  # noqa: E712
        or_(Conflict.study_id == study.id, Conflict.related_study_id == study.id),
    ).update(
        {Conflict.is_resolved: True, Conflict.resolved_at: now, Conflict.resolution_notes: note},
        synchronize_session=False,
    )

    old_ids = [sid for (sid,) in db.query(StudyStep.id).filter(StudyStep.study_id == study.id).all()]
    if old_ids:
        # Geçmiş çakışma kayıtları adım silinirken cascade ile yok olmasın
        db.query(Conflict).filter(Conflict.step_id.in_(old_ids)).update(
            {Conflict.step_id: None}, synchronize_session=False
        )
    db.expire_all()
    for step in db.query(StudyStep).filter(StudyStep.study_id == study.id).all():
        db.delete(step)
    db.flush()
    return superseded, len(old_ids)


def _assign_roles(
    db: Session,
    study: Study,
    planned: List[Tuple[TemplateStep, datetime, datetime]],
    existing_steps: List[StudyStep],
    existing_assignees: Dict[int, set],
) -> Tuple[Dict[UserRole, User], List[UserRole]]:
    """
    Şablondaki rolleri kişilere çözer. Saatlere DOKUNMAZ.
      * STUDY_DIRECTOR → çalışmanın kendi SD'si.
      * Diğer roller → çalışma boyunca TEK kişi (GLP skorlama tutarlılığı). Aday sırası:
        (1) şablon pencerelerinde en az çakışan dakika, (2) o günlerdeki en düşük iş yükü, (3) en küçük ID.
    Hiçbir aday boş değilse en az çakışan atanır ve çakışma raporlanır.
    """
    needed: List[UserRole] = []
    for ts, _, _ in planned:
        for role in ts.roles:
            if role not in needed:
                needed.append(role)

    assignment: Dict[UserRole, User] = {}
    unfilled: List[UserRole] = []
    for role in needed:
        if role == UserRole.STUDY_DIRECTOR:
            sd = study.study_director
            if sd is not None and sd.is_active:
                assignment[role] = sd
            else:
                unfilled.append(role)
            continue

        candidates = db.query(User).filter(User.role == role, User.is_active == True).order_by(User.id).all()  # noqa: E712
        if not candidates:
            unfilled.append(role)
            continue

        windows = [(s, e) for ts, s, e in planned if role in ts.roles]
        days = sorted({s.date() for s, _ in windows})

        def score(user: User):
            busy = sum(
                _overlap_minutes(s, e, ex.planned_start, ex.planned_end)
                for s, e in windows
                for ex in existing_steps
                if user.id in existing_assignees[ex.id]
            )
            load = sum(calculate_personnel_workload(db, user.id, d)["total_minutes"] for d in days)
            return busy, load, user.id

        assignment[role] = min(candidates, key=score)
    return assignment, unfilled


def compute_friday_alignment_offset(acclimatization_start_date: date) -> int:
    """
    G0 sabit kalarak (minimum 4 gün aklimatizasyon korunarak) G4 ekstraksiyon adımını
    ilk uygun Cuma gününe hizalayan ek aklimatizasyon gün sayısını hesaplar.
    Cuma ekstraksiyon -> Cmt/Paz su banyosunda -> Pazartesi enjeksiyon -> Salı/Çarşamba/Perşembe gözlem (0 hafta sonu insan görevi).
    """
    base_ex_date = acclimatization_start_date + timedelta(days=4)
    return (4 - base_ex_date.weekday()) % 7


def _find_next_available_water_bath_offset(
    db: Session,
    study: Study,
    acclimatization_start_date: date,
    current_offset: int,
    existing_steps: List[StudyStep],
    water_bath: Equipment,
) -> Tuple[int, date]:
    """
    Çalkalamalı Su Banyosu 1 (EQ-WB-001) cihazının bu çalışmanın Polar/Apolar ekstraksiyonu için
    72 saat boyunca müsait olduğu ilk günü (ve G4'e göre gün ofsetini) bulur.
    """
    max_polar = water_bath.polar_capacity or 3
    max_apolar = water_bath.non_polar_capacity or 1
    ex_steps = [ex for ex in existing_steps if ex.step_type == "Ekstraksiyon" or "Ekstraksiyon" in ex.step_name]

    for candidate_offset in range(max(0, current_offset) + 1, max(0, current_offset) + 60):
        cand_ex_date = acclimatization_start_date + timedelta(days=4 + candidate_offset)
        wb_start = datetime.combine(cand_ex_date, time(8, 0))
        wb_end = wb_start + timedelta(hours=72)

        apolar_busy = 0
        polar_busy = 0
        for ex in ex_steps:
            other_start = ex.planned_start
            other_end = other_start + timedelta(hours=72)
            if _overlap_minutes(wb_start, wb_end, other_start, other_end) > 0:
                if ex.study.extraction_non_polar is True:
                    apolar_busy += 1
                if ex.study.extraction_polar is True:
                    polar_busy += 1

        apolar_ok = (study.extraction_non_polar is not True) or (1 + apolar_busy <= max_apolar)
        polar_ok = (study.extraction_polar is not True) or (1 + polar_busy <= max_polar)
        if apolar_ok and polar_ok:
            return candidate_offset, cand_ex_date

    fallback_offset = max(0, current_offset) + 3
    return fallback_offset, acclimatization_start_date + timedelta(days=4 + fallback_offset)


def build_conflict_resolutions(
    db: Session,
    conflict: Conflict,
    study: Optional[Study] = None,
    existing_steps: Optional[List[StudyStep]] = None,
) -> List[Dict[str, Any]]:
    """
    FAZ 6.2 — Her çakışma/uyarı kartının içine doğrudan "Tek Tık Çözüm Butonları" üretir.
    """
    if conflict.is_resolved:
        return []
    study = study or conflict.study
    resolutions: List[Dict[str, Any]] = []

    # a) Hafta Sonu / Mesai Dışı Görevi (WARNING)
    if (
        conflict.conflict_type == ConflictType.BIOLOGICAL_TIME_VIOLATION
        and (conflict.severity == ConflictSeverity.WARNING or "Mesai Dışında" in conflict.title or "Hafta Sonu" in conflict.title)
    ):
        resolutions.append(
            {
                "action": "APPROVE_WEEKEND_DUTY",
                "label": "Hafta Sonu Nöbetçi Personeli Onayla",
                "style": "emerald",
                "description": (
                    "Hafta sonu gözlem/uygulama adımlarını nöbetçi personel ile yürütülecek şekilde "
                    "denetim iziyle (AuditLog) otomatik RESOLVED yapar ve planı onaylanabilir hale getirir."
                ),
            }
        )
        if study:
            base_day0 = study.acclimatization_start_date or study.target_start_date or date.today()
            fri_offset = compute_friday_alignment_offset(base_day0)
            fri_date = base_day0 + timedelta(days=4 + fri_offset)
            resolutions.append(
                {
                    "action": "ALIGN_EXTRACTION_TO_FRIDAY",
                    "label": "Ekstraksiyonu Cuma'ya Hizala (Gözlemler Hafta İçi Olsun)",
                    "style": "blue",
                    "suggested_offset_days": fri_offset,
                    "aligned_extraction_date": fri_date.isoformat(),
                    "description": (
                        f"G0 ({base_day0:%d.%m.%Y}) sabit kalarak ekstraksiyonu ilk uygun Cuma gününe "
                        f"({fri_date:%d.%m.%Y}), enjeksiyonu Pazartesi'ye ve 24/48/72s gözlemlerini "
                        f"Salı-Çarşamba-Perşembe'ye hizalar (0 hafta sonu insan görevi)."
                    ),
                }
            )
        return resolutions

    # b) Personel 9 Saat Aşımı / Çakışması (PERSONNEL_OVERLAP veya Personel Dolu)
    if conflict.conflict_type == ConflictType.PERSONNEL_OVERLAP or (
        conflict.conflict_type == ConflictType.BIOLOGICAL_TIME_VIOLATION and "Personel Dolu" in conflict.title
    ):
        step = conflict.step or (
            db.query(StudyStep).filter(StudyStep.id == conflict.step_id).first() if conflict.step_id else None
        )
        current_assignee_ids = set(step.assignee_ids) if step else set()
        target_day = step.planned_start.date() if step else date.today()

        techs = (
            db.query(User)
            .filter(User.role == UserRole.TECHNICIAN, User.is_active == True)  # noqa: E712
            .order_by(User.id.asc())
            .all()
        )
        backup_candidates = [u for u in techs if u.id not in current_assignee_ids] or techs
        best_backup = None
        if backup_candidates:
            best_backup = min(
                backup_candidates,
                key=lambda u: (calculate_personnel_workload(db, u.id, target_day)["total_minutes"], u.id),
            )
        resolutions.append(
            {
                "action": "REASSIGN_TO_BACKUP_TECHNICIAN",
                "label": (
                    f"Boştaki Yedek Teknisyene Devret ({best_backup.full_name})"
                    if best_backup
                    else "Boştaki Yedek Teknisyene Devret"
                ),
                "style": "blue",
                "target_user_id": best_backup.id if best_backup else None,
                "target_user_name": best_backup.full_name if best_backup else None,
                "description": (
                    f"O gün iş yükü müsait olan yedek teknisyene ({best_backup.full_name if best_backup else 'Yedek Teknisyen'}) "
                    f"görevi tek tıkla atar ve çakışmayı çözer."
                ),
            }
        )
        return resolutions

    # c) Cihaz Kapasite Aşımı (EQUIPMENT_OVERLAP)
    if conflict.conflict_type == ConflictType.EQUIPMENT_OVERLAP and study:
        water_bath = seed_default_equipment(db)
        base_day0 = study.acclimatization_start_date or study.target_start_date or date.today()
        cur_offset = study.extraction_start_offset_days or 0
        if existing_steps is None:
            others = db.query(Study).filter(Study.id != study.id, Study.status.in_(COMPARED_STUDY_STATUSES)).all()
            other_ids = [s.id for s in others]
            existing_steps = (
                db.query(StudyStep)
                .options(selectinload(StudyStep.study))
                .filter(StudyStep.study_id.in_(other_ids), StudyStep.status != StepStatus.CANCELLED)
                .all()
                if other_ids
                else []
            )
        next_offset, next_date = _find_next_available_water_bath_offset(
            db, study, base_day0, cur_offset, existing_steps, water_bath
        )
        resolutions.append(
            {
                "action": "SHIFT_TO_NEXT_AVAILABLE_EQUIPMENT_DATE",
                "label": f"Cihazın Boşaldığı İlk Güne Kaydır ({next_date:%d.%m.%Y})",
                "style": "blue",
                "suggested_offset_days": next_offset,
                "next_available_date": next_date.isoformat(),
                "description": (
                    f"Ekstraksiyon başlangıcını '{water_bath.name}' cihazının boşaldığı ilk gün olan "
                    f"{next_date:%d.%m.%Y} (G{4 + next_offset}) tarihine kaydırarak yeniden planlar."
                ),
            }
        )
        return resolutions

    return resolutions


def schedule_new_study(
    db: Session,
    study_id: int,
    acclimatization_start_date: date,
    template_code: str = DEFAULT_TEMPLATE_CODE,
    extraction_start_offset_days: Optional[int] = None,
    align_extraction_to_friday: bool = False,
) -> Dict[str, Any]:
    """
    Seçilen şablonun adımlarını Gün 0 = acclimatization_start_date olacak şekilde dizer ve çakışmaları tespit eder.

    * Non-Destructive: APPROVED / IN_PROGRESS çalışmalara dokunulmaz; yalnızca DRAFT çalışma planlanabilir.
    * Diğer DRAFT çalışmalarla da kıyaslanır (onlar da değiştirilmez).
    * Saatler kendiliğinden sessizce kaydırılmaz; sorunlar Conflict tablosuna yazılır ve her çakışma için
      aksiyon alınabilir çözüm butonları (resolutions) sunulur.
    * Kullanıcı açıkça "Ekstraksiyonu Cuma'ya Hizala" veya "Cihazın Boşaldığı İlk Güne Kaydır" çözümünü
      tetiklediğinde `extraction_start_offset_days` uygulanır.
    """
    study = db.query(Study).filter(Study.id == study_id).first()
    if not study:
        raise ValueError(f"ID={study_id} olan GLP çalışması bulunamadı.")
    if study.status != StudyStatus.DRAFT:
        raise PermissionError(
            f"'{study.study_code}' çalışması {study.status.value} durumundadır. Yalnızca DRAFT çalışmalar "
            f"(yeniden) planlanabilir; onaylanmış çalışmaların görev saatleri değiştirilemez (Non-Destructive kuralı)."
        )
    template = get_template(template_code)
    now = datetime.utcnow()
    water_bath = seed_default_equipment(db)

    if align_extraction_to_friday:
        offset_days = compute_friday_alignment_offset(acclimatization_start_date)
    elif extraction_start_offset_days is not None:
        offset_days = max(0, int(extraction_start_offset_days))
    else:
        offset_days = 0
    study.extraction_start_offset_days = offset_days
    study.acclimatization_start_date = acclimatization_start_date

    # 1) Bu taslağın eski planını kapat
    superseded_count, removed_steps = _supersede_previous_plan(db, study, now)

    # 2) Kıyas kümesi: onaylı + yürütülen + diğer taslaklar (hepsi salt-okunur)
    others = db.query(Study).filter(Study.id != study.id, Study.status.in_(COMPARED_STUDY_STATUSES)).all()
    other_ids = [s.id for s in others]
    existing_steps: List[StudyStep] = []
    if other_ids:
        existing_steps = (
            db.query(StudyStep)
            .options(selectinload(StudyStep.assignees), selectinload(StudyStep.study))
            .filter(StudyStep.study_id.in_(other_ids), StudyStep.status != StepStatus.CANCELLED)
            .all()
        )
    existing_assignees = {ex.id: {u.id for u in ex.assignees} for ex in existing_steps}

    # 3) Şablon → kesin zaman pencereleri (G4 ve sonrası biyolojik zincir olarak birlikte hareket eder)
    day0 = datetime.combine(acclimatization_start_date, time.min)
    planned: List[Tuple[TemplateStep, datetime, datetime, int]] = []
    for ts in template.steps:
        effective_day = ts.day + (offset_days if ts.day >= 4 else 0)
        start = day0 + timedelta(days=effective_day, hours=ts.start.hour, minutes=ts.start.minute)
        planned.append((ts, start, start + timedelta(minutes=ts.duration_minutes), effective_day))

    # 4) Rol → personel
    planned_3 = [(ts, s, e) for ts, s, e, _ in planned]
    assignment, unfilled_roles = _assign_roles(db, study, planned_3, existing_steps, existing_assignees)

    # 5) Adımları oluştur
    new_steps: List[Tuple[TemplateStep, StudyStep]] = []
    for ts, start, end, effective_day in planned:
        is_extraction = ts.step_type == "Ekstraksiyon" or "Ekstraksiyon" in ts.name
        eq_id = (
            water_bath.id
            if is_extraction and (study.extraction_polar is True or study.extraction_non_polar is True)
            else None
        )
        step = StudyStep(
            study_id=study.id,
            step_order=ts.order,
            study_day=effective_day,
            step_name=ts.name,
            step_type=ts.step_type,
            planned_start=start,
            planned_end=end,
            is_biological_fixed_time=ts.is_biological_fixed_time,
            biological_tolerance_minutes=ts.tolerance_minutes,
            equipment_id=eq_id,
            status=StepStatus.PENDING,
        )
        step.assignees = [assignment[r] for r in ts.roles if r in assignment]
        db.add(step)
        new_steps.append((ts, step))
    db.flush()

    # 6) Çakışma tespiti
    findings: List[Tuple[Conflict, List[int]]] = []

    def record(conflict: Conflict, step_ids: List[int]):
        db.add(conflict)
        findings.append((conflict, step_ids))

    for role in unfilled_roles:
        affected = [s.id for ts, s in new_steps if role in ts.roles]
        record(Conflict(
            conflict_type=ConflictType.QUALIFICATION_MISMATCH,
            severity=ConflictSeverity.CRITICAL,
            title=f"Atanacak aktif personel yok: {role.value}",
            description=(f"Şablon '{role.value}' rolünde personel gerektiriyor ancak sistemde aktif kayıt yok. "
                         f"İlgili {len(affected)} adım atamasız bırakıldı."),
            study_id=study.id,
            step_id=affected[0] if affected else None,
        ), affected)

    for ts, step in new_steps:
        # 6a) Biyolojik kilitli adım mesai dışı / hafta sonu → WARNING (Nöbetçi personel onayı veya Cuma hizalama sunulur)
        issue = _working_hours_issue(step.planned_start, step.planned_end)
        if step.is_biological_fixed_time and issue:
            conflict = register_biological_time_violation(
                db, step, commit=False,
                severity=ConflictSeverity.WARNING,
                title=f"Biyolojik Kilit Mesai Dışında (Hafta Sonu Görevi): Gün {step.study_day} — {step.step_name}",
                reason=f"Adım {issue}. Saat ötelenemez; nöbetçi / hafta sonu personeli onaylanmalı veya ekstraksiyon Cuma'ya hizalanmalıdır.",
            )
            findings.append((conflict, [step.id]))

        # 6b) Aynı kişinin başka bir çalışmada (onaylı veya taslak) eşzamanlı görevi
        for person in step.assignees:
            for ex in existing_steps:
                if person.id not in existing_assignees[ex.id]:
                    continue
                ov = _overlap_minutes(step.planned_start, step.planned_end, ex.planned_start, ex.planned_end)
                if ov <= 0:
                    continue
                other = ex.study
                context = (f"{person.full_name}, {other.study_code} ({other.status.value}) çalışmasının "
                           f"'{ex.step_name}' görevinde ({_fmt(ex.planned_start)}–{ex.planned_end:%H:%M}) zaten "
                           f"görevli; {ov} dk örtüşme.")
                if step.is_biological_fixed_time:
                    conflict = register_biological_time_violation(
                        db, step, commit=False, related_study_id=other.id,
                        severity=ConflictSeverity.CRITICAL,
                        title=f"Biyolojik Kilit + Personel Dolu: Gün {step.study_day} — {person.full_name}",
                        reason=context,
                    )
                    findings.append((conflict, [step.id]))
                else:
                    record(Conflict(
                        conflict_type=ConflictType.PERSONNEL_OVERLAP,
                        severity=ConflictSeverity.CRITICAL,
                        title=f"Personel Çakışması: Gün {step.study_day} — {person.full_name}",
                        description=context + " Esnek adım olsa da sistem saati kendiliğinden kaydırmaz; "
                                              "planlayıcı/SD kararı gereklidir.",
                        study_id=study.id,
                        step_id=step.id,
                        related_study_id=other.id,
                    ), [step.id])

        # 6c) Cihaz çakışması — FAZ 6.2: Çalkalamalı Su Banyosu 1 (EQ-WB-001) Polar (Max: 3) & Apolar (Max: 1) 72s Kapasite Kilidi
        is_extraction = ts.step_type == "Ekstraksiyon" or "Ekstraksiyon" in ts.name
        if is_extraction and (study.extraction_polar is True or study.extraction_non_polar is True):
            wb_start = step.planned_start
            wb_end = step.planned_start + timedelta(hours=72)
            overlapping_apolar: List[Study] = []
            overlapping_polar: List[Study] = []

            for ex in existing_steps:
                ex_is_extraction = ex.step_type == "Ekstraksiyon" or "Ekstraksiyon" in ex.step_name
                if not ex_is_extraction:
                    continue
                other_wb_start = ex.planned_start
                other_wb_end = ex.planned_start + timedelta(hours=72)
                if _overlap_minutes(wb_start, wb_end, other_wb_start, other_wb_end) > 0:
                    if ex.study.extraction_non_polar is True and ex.study not in overlapping_apolar:
                        overlapping_apolar.append(ex.study)
                    if ex.study.extraction_polar is True and ex.study not in overlapping_polar:
                        overlapping_polar.append(ex.study)

            max_apolar = water_bath.non_polar_capacity or 1
            max_polar = water_bath.polar_capacity or 3

            if study.extraction_non_polar is True and (1 + len(overlapping_apolar) > max_apolar):
                other_codes = ", ".join(f"{s.study_code} ({s.status.value})" for s in overlapping_apolar)
                record(
                    Conflict(
                        conflict_type=ConflictType.EQUIPMENT_OVERLAP,
                        severity=ConflictSeverity.CRITICAL,
                        title=f"Çalkalamalı Su Banyosu Apolar Kapasite Aşımı (Max: {max_apolar})",
                        description=(
                            f"'{water_bath.name} ({water_bath.code})' cihazında {_fmt(wb_start)} – {_fmt(wb_end)} "
                            f"(72 saatlik ekstraksiyon) penceresinde Apolar/Non-Polar kapasitesi (Max: {max_apolar} çalışma) "
                            f"aşıldı. Bu çalışma ile birlikte eşzamanlı {1 + len(overlapping_apolar)} Apolar çalışma "
                            f"({other_codes}) çakışıyor."
                        ),
                        study_id=study.id,
                        step_id=step.id,
                        related_study_id=overlapping_apolar[0].id,
                    ),
                    [step.id],
                )

            if study.extraction_polar is True and (1 + len(overlapping_polar) > max_polar):
                other_codes = ", ".join(f"{s.study_code} ({s.status.value})" for s in overlapping_polar)
                record(
                    Conflict(
                        conflict_type=ConflictType.EQUIPMENT_OVERLAP,
                        severity=ConflictSeverity.CRITICAL,
                        title=f"Çalkalamalı Su Banyosu Polar Kapasite Aşımı (Max: {max_polar})",
                        description=(
                            f"'{water_bath.name} ({water_bath.code})' cihazında {_fmt(wb_start)} – {_fmt(wb_end)} "
                            f"(72 saatlik ekstraksiyon) penceresinde Polar kapasitesi (Max: {max_polar} çalışma) "
                            f"aşıldı. Bu çalışma ile birlikte eşzamanlı {1 + len(overlapping_polar)} Polar çalışma "
                            f"({other_codes}) çakışıyor."
                        ),
                        study_id=study.id,
                        step_id=step.id,
                        related_study_id=overlapping_polar[0].id,
                    ),
                    [step.id],
                )
        elif step.equipment_id and step.equipment_id != water_bath.id:
            for ex in existing_steps:
                if ex.equipment_id == step.equipment_id and _overlap_minutes(
                        step.planned_start, step.planned_end, ex.planned_start, ex.planned_end) > 0:
                    record(Conflict(
                        conflict_type=ConflictType.EQUIPMENT_OVERLAP,
                        severity=ConflictSeverity.CRITICAL,
                        title=f"Cihaz Çakışması: Gün {step.study_day} — Ekipman #{step.equipment_id}",
                        description=f"Cihaz, {ex.study.study_code} çalışmasının '{ex.step_name}' adımında kullanımda.",
                        study_id=study.id,
                        step_id=step.id,
                        related_study_id=ex.study_id,
                    ), [step.id])

    db.flush()

    # 6d) KURAL 1: kişi-gün bazında 9 saat kontrolü (tüm çalışmalar dahil)
    person_days: Dict[Tuple[int, date], Tuple[User, List[int]]] = {}
    for _, step in new_steps:
        for person in step.assignees:
            person_days.setdefault((person.id, step.planned_start.date()), (person, []))[1].append(step.id)
    for (_, day), (person, step_ids) in sorted(person_days.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        conflict = _build_workload_conflict(db, person, day, study.id, step_id=step_ids[0])
        if conflict is not None:
            findings.append((conflict, step_ids))

    # 7) Çalışma meta verisi + GLP denetim izi
    study.target_start_date = acclimatization_start_date
    study.target_end_date = max(s.planned_end for _, s in new_steps).date()
    db.add(AuditLog(
        user_id=study.study_director_id,
        entity_name="Study",
        entity_id=study.id,
        action="SCHEDULE_ANALYSIS",
        new_values={
            "template": template.code,
            "day0": acclimatization_start_date.isoformat(),
            "extraction_start_offset_days": offset_days,
            "steps": len(new_steps),
            "conflicts": len(findings),
            "superseded_conflicts": superseded_count,
            "removed_previous_steps": removed_steps,
        },
        reason=(f"{template.standard} şablonuyla Gün 0={acclimatization_start_date} (ekstraksiyon ofseti=+{offset_days} gün) "
                f"için non-destructive planlama; {len(findings)} bulgu tespit edildi."),
    ))
    db.commit()
    for conflict, _ in findings:
        db.refresh(conflict)

    return _format_schedule_response(
        db=db,
        study=study,
        template=template,
        acclimatization_start_date=acclimatization_start_date,
        findings=findings,
        superseded_count=superseded_count,
        others=others,
        steps=[s for _, s in new_steps],
        existing_steps=existing_steps,
    )


def _format_schedule_response(
    db: Session,
    study: Study,
    template: Any,
    acclimatization_start_date: date,
    findings: List[Tuple[Conflict, List[int]]],
    superseded_count: int,
    others: List[Study],
    steps: List[StudyStep],
    existing_steps: Optional[List[StudyStep]] = None,
) -> Dict[str, Any]:
    def person_dict(u: User) -> Dict[str, Any]:
        return {"id": u.id, "full_name": u.full_name, "role": u.role.value}

    active_findings = [(c, sids) for c, sids in findings if not c.is_resolved]
    critical_count = sum(1 for c, _ in active_findings if c.severity == ConflictSeverity.CRITICAL)
    warning_count = sum(1 for c, _ in active_findings if c.severity == ConflictSeverity.WARNING)

    return {
        "study_id": study.id,
        "study_code": study.study_code,
        "study_status": study.status.value,
        "title": study.title,
        "sponsor_name": study.sponsor_name,
        "test_item_name": study.test_item_name,
        "test_item_batch": study.test_item_batch,
        "extraction_polar": study.extraction_polar,
        "extraction_polar_solvent": study.extraction_polar_solvent,
        "extraction_non_polar": study.extraction_non_polar,
        "extraction_non_polar_solvent": study.extraction_non_polar_solvent,
        "study_director_id": study.study_director_id,
        "study_director_name": study.study_director.full_name if study.study_director else None,
        "template": {"code": template.code, "standard": template.standard, "title": template.title},
        "acclimatization_start_date": acclimatization_start_date.isoformat(),
        "target_start_date": (study.target_start_date or acclimatization_start_date).isoformat(),
        "target_end_date": study.target_end_date.isoformat() if study.target_end_date else None,
        "protocol_approved_at": study.protocol_approved_at.isoformat() if study.protocol_approved_at else None,
        "extraction_start_offset_days": study.extraction_start_offset_days or 0,
        "status": (
            "CONFLICTS_DETECTED"
            if critical_count > 0
            else ("WARNINGS_DETECTED" if warning_count > 0 else "SCHEDULED_CLEAN")
        ),
        "can_approve": study.status == StudyStatus.DRAFT and critical_count == 0 and len(steps) > 0,
        "total_conflicts": len(active_findings),
        "critical_conflicts": critical_count,
        "warning_conflicts": warning_count,
        "superseded_conflicts": superseded_count,
        "conflicts": [
            {
                "id": c.id,
                "type": c.conflict_type.value,
                "severity": c.severity.value,
                "title": c.title,
                "description": c.description,
                "step_id": c.step_id,
                "step_ids": step_ids,
                "related_study_id": c.related_study_id,
                "resolutions": build_conflict_resolutions(db, c, study=study, existing_steps=existing_steps),
            }
            for c, step_ids in active_findings
        ],
        "untouched_approved_studies": [s.study_code for s in others if s.status in LOCKED_STUDY_STATUSES],
        "compared_draft_studies": [s.study_code for s in others if s.status == StudyStatus.DRAFT],
        "total_new_steps": len(steps),
        "steps": [
            {
                "id": s.id,
                "step_order": s.step_order,
                "study_day": s.study_day,
                "step_name": s.step_name,
                "step_type": s.step_type,
                "planned_start": s.planned_start.isoformat(),
                "planned_end": s.planned_end.isoformat(),
                "duration_minutes": s.duration_minutes,
                "is_biological_fixed_time": s.is_biological_fixed_time,
                "biological_tolerance_minutes": s.biological_tolerance_minutes,
                "equipment_id": s.equipment_id,
                "assignees": [person_dict(u) for u in s.assignees],
            }
            for s in steps
        ],
    }


def get_study_schedule_detail(db: Session, study: Study) -> Dict[str, Any]:
    """
    FAZ 6.3 — Veritabanında kayıtlı (DRAFT, APPROVED veya IN_PROGRESS) bir çalışmanın mevcut adımlarını,
    açık çakışmalarını ve tek tık çözüm önerilerini yeniden planlama yapmadan (salt-okunur) döner.
    """
    template = get_template(DEFAULT_TEMPLATE_CODE)
    base_day0 = study.acclimatization_start_date or study.target_start_date or date.today()
    others = db.query(Study).filter(Study.id != study.id, Study.status.in_(COMPARED_STUDY_STATUSES)).all()
    other_ids = [s.id for s in others]
    existing_steps = (
        db.query(StudyStep)
        .options(selectinload(StudyStep.study), selectinload(StudyStep.assignees))
        .filter(StudyStep.study_id.in_(other_ids), StudyStep.status != StepStatus.CANCELLED)
        .all()
        if other_ids
        else []
    )
    steps = (
        db.query(StudyStep)
        .options(selectinload(StudyStep.assignees))
        .filter(StudyStep.study_id == study.id, StudyStep.status != StepStatus.CANCELLED)
        .order_by(StudyStep.step_order)
        .all()
    )
    open_conflicts = (
        db.query(Conflict)
        .filter(Conflict.study_id == study.id, Conflict.is_resolved == False)  # noqa: E712
        .order_by(Conflict.id.asc())
        .all()
    )
    findings = [(c, [c.step_id] if c.step_id else []) for c in open_conflicts]
    return _format_schedule_response(
        db=db,
        study=study,
        template=template,
        acclimatization_start_date=base_day0,
        findings=findings,
        superseded_count=0,
        others=others,
        steps=steps,
        existing_steps=existing_steps,
    )


def apply_conflict_resolution(
    db: Session,
    conflict_id: int,
    action: str,
    user: User,
    target_user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    FAZ 6.2 — Kullanıcının çakışma kartındaki "Tek Tık Çözüm Butonu"na tıklamasıyla tetiklenen
    karar destek aksiyonlarını yürütür, AuditLog'a yazar ve güncellenmiş çalışma takvimini döner.
    """
    conflict = db.query(Conflict).filter(Conflict.id == conflict_id).first()
    if not conflict:
        raise ValueError(f"ID={conflict_id} olan çakışma kaydı bulunamadı.")
    study = db.query(Study).filter(Study.id == conflict.study_id).first()
    if not study:
        raise ValueError("Çakışmanın bağlı olduğu çalışma bulunamadı.")

    now = datetime.utcnow()
    template = get_template(DEFAULT_TEMPLATE_CODE)
    base_day0 = study.acclimatization_start_date or study.target_start_date or date.today()

    if action == "APPROVE_WEEKEND_DUTY":
        # Çalışmaya ait tüm açık hafta sonu / mesai dışı uyarılarını denetim iziyle RESOLVED yap
        open_weekend = (
            db.query(Conflict)
            .filter(
                Conflict.study_id == study.id,
                Conflict.is_resolved == False,  # noqa: E712
                Conflict.conflict_type == ConflictType.BIOLOGICAL_TIME_VIOLATION,
            )
            .all()
        )
        resolved_ids = []
        note = (
            f"GLP Hafta Sonu Nöbetçi Personel Onayı ({user.full_name}): "
            f"Hafta sonu gözlem/uygulama adımları nöbetçi yetkin personelle yürütülmek üzere onaylandı."
        )
        for wc in open_weekend:
            if wc.severity == ConflictSeverity.WARNING or "Mesai Dışında" in wc.title or "Hafta Sonu" in wc.title or wc.id == conflict.id:
                wc.is_resolved = True
                wc.resolved_by_id = user.id
                wc.resolved_at = now
                wc.resolution_notes = note
                resolved_ids.append(wc.id)

        db.add(
            AuditLog(
                user_id=user.id,
                entity_name="Study",
                entity_id=study.id,
                action="APPROVE_WEEKEND_DUTY",
                new_values={"study_code": study.study_code, "resolved_conflict_ids": resolved_ids},
                reason=note,
            )
        )
        db.commit()

    elif action == "ALIGN_EXTRACTION_TO_FRIDAY":
        offset = compute_friday_alignment_offset(base_day0)
        res = schedule_new_study(
            db=db,
            study_id=study.id,
            acclimatization_start_date=base_day0,
            template_code=template.code,
            extraction_start_offset_days=offset,
            align_extraction_to_friday=True,
        )
        db.add(
            AuditLog(
                user_id=user.id,
                entity_name="Study",
                entity_id=study.id,
                action="ALIGN_EXTRACTION_TO_FRIDAY",
                new_values={
                    "study_code": study.study_code,
                    "day0": base_day0.isoformat(),
                    "extraction_start_offset_days": offset,
                },
                reason=(
                    f"{user.full_name} ekstraksiyon başlangıcını Cuma gününe (+{offset} gün aklimatizasyon) "
                    f"hizalayarak hafta sonu insan görevlerini hafta içine çekti."
                ),
            )
        )
        db.commit()
        res["resolution_applied"] = {
            "action": action,
            "message": f"Ekstraksiyon Cuma gününe (+{offset} gün) hizalandı; tüm gözlemler hafta içine alındı.",
        }
        return res

    elif action == "REASSIGN_TO_BACKUP_TECHNICIAN":
        step = db.query(StudyStep).filter(StudyStep.id == conflict.step_id).first() if conflict.step_id else None
        target_day = step.planned_start.date() if step else base_day0
        current_ids = set(step.assignee_ids) if step else set()

        if target_user_id:
            backup = db.query(User).filter(User.id == target_user_id, User.is_active == True).first()  # noqa: E712
        else:
            techs = (
                db.query(User)
                .filter(User.role == UserRole.TECHNICIAN, User.is_active == True)  # noqa: E712
                .order_by(User.id.asc())
                .all()
            )
            candidates = [u for u in techs if u.id not in current_ids] or techs
            backup = (
                min(candidates, key=lambda u: (calculate_personnel_workload(db, u.id, target_day)["total_minutes"], u.id))
                if candidates
                else None
            )

        if not backup:
            raise ValueError("Devredilecek aktif yedek teknisyen bulunamadı.")

        # İlgili adımdaki (veya o gündeki) teknisyeni yedek teknisyenle değiştir
        steps_to_update = (
            [step]
            if step
            else db.query(StudyStep).filter(StudyStep.study_id == study.id).all()
        )
        for st in steps_to_update:
            non_techs = [u for u in st.assignees if u.role != UserRole.TECHNICIAN]
            st.assignees = non_techs + [backup]

        note = (
            f"Yedek Teknisyen Devri ({user.full_name}): Görev iş yükü müsait olan "
            f"'{backup.full_name}' personeline devredildi ve çakışma çözüldü."
        )
        conflict.is_resolved = True
        conflict.resolved_by_id = user.id
        conflict.resolved_at = now
        conflict.resolution_notes = note

        db.add(
            AuditLog(
                user_id=user.id,
                entity_name="Conflict",
                entity_id=conflict.id,
                action="REASSIGN_TO_BACKUP_TECHNICIAN",
                new_values={
                    "study_code": study.study_code,
                    "step_id": step.id if step else None,
                    "assigned_technician_id": backup.id,
                    "assigned_technician_name": backup.full_name,
                },
                reason=note,
            )
        )
        db.commit()

    elif action == "SHIFT_TO_NEXT_AVAILABLE_EQUIPMENT_DATE":
        water_bath = seed_default_equipment(db)
        others = db.query(Study).filter(Study.id != study.id, Study.status.in_(COMPARED_STUDY_STATUSES)).all()
        other_ids = [s.id for s in others]
        existing_steps = (
            db.query(StudyStep)
            .options(selectinload(StudyStep.study))
            .filter(StudyStep.study_id.in_(other_ids), StudyStep.status != StepStatus.CANCELLED)
            .all()
            if other_ids
            else []
        )
        next_offset, next_date = _find_next_available_water_bath_offset(
            db, study, base_day0, study.extraction_start_offset_days or 0, existing_steps, water_bath
        )
        res = schedule_new_study(
            db=db,
            study_id=study.id,
            acclimatization_start_date=base_day0,
            template_code=template.code,
            extraction_start_offset_days=next_offset,
        )
        db.add(
            AuditLog(
                user_id=user.id,
                entity_name="Study",
                entity_id=study.id,
                action="SHIFT_TO_NEXT_AVAILABLE_EQUIPMENT_DATE",
                new_values={
                    "study_code": study.study_code,
                    "equipment_code": water_bath.code,
                    "new_extraction_date": next_date.isoformat(),
                    "extraction_start_offset_days": next_offset,
                },
                reason=(
                    f"{user.full_name} ekstraksiyon başlangıcını '{water_bath.name}' cihazının boşaldığı "
                    f"ilk gün olan {next_date:%d.%m.%Y} tarihine (+{next_offset} gün) kaydırdı."
                ),
            )
        )
        db.commit()
        res["resolution_applied"] = {
            "action": action,
            "message": f"Ekstraksiyon '{water_bath.name}' cihazının boşaldığı {next_date:%d.%m.%Y} gününe kaydırıldı.",
        }
        return res

    else:
        raise ValueError(f"Tanımsız çözüm aksiyonu: '{action}'")

    # Güncel çalışma durumunu döndür
    others = db.query(Study).filter(Study.id != study.id, Study.status.in_(COMPARED_STUDY_STATUSES)).all()
    steps = (
        db.query(StudyStep)
        .options(selectinload(StudyStep.assignees))
        .filter(StudyStep.study_id == study.id)
        .order_by(StudyStep.step_order)
        .all()
    )
    open_conflicts = (
        db.query(Conflict)
        .filter(Conflict.study_id == study.id, Conflict.is_resolved == False)  # noqa: E712
        .all()
    )
    findings = [(c, [c.step_id] if c.step_id else []) for c in open_conflicts]
    res = _format_schedule_response(
        db=db,
        study=study,
        template=template,
        acclimatization_start_date=base_day0,
        findings=findings,
        superseded_count=0,
        others=others,
        steps=steps,
    )
    res["resolution_applied"] = {"action": action, "message": "Çözüm başarıyla uygulandı ve denetim izine kaydedildi."}
    return res
