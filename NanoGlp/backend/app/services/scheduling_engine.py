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
from app.services.templates import DEFAULT_TEMPLATE_CODE, TemplateStep, get_template, resolve_template_code
from app.services.capacity_service import (
    apply_restriction_shift,
    build_capacity_report,
    compute_peak_concurrent_details,
    evaluate_capacity_conflicts,
    evaluate_study_capacity_conflicts,
    find_first_free_g0,
    get_auto_schedule_notice,
    is_capacity_conflict,
    peak_concurrent_usage,
    persist_auto_schedule_notice,
)

MAX_DAILY_WORKLOAD_MINUTES = 540  # 9 Saat = 540 Dakika (Yasal & GLP Üst Sınırı)
WORKDAY_START = time(8, 0)
WORKDAY_END = time(18, 0)
REFERENCE_DATE = date(2026, 11, 3)  # FAZ 9.2 Referans Operasyon Tarihi (03.11.2026)

# Yeni taslağın kıyaslandığı çalışma durumları (bu çalışmalar ASLA değiştirilmez)
COMPARED_STUDY_STATUSES = (StudyStatus.APPROVED, StudyStatus.IN_PROGRESS, StudyStatus.DRAFT)
LOCKED_STUDY_STATUSES = (StudyStatus.APPROVED, StudyStatus.IN_PROGRESS)

# FAZ 8.4: Personel İş Yükü ve görev atamalarından hariç tutulan idari/satış/kabul rolleri
EXCLUDED_WORKLOAD_ROLES = {"SYSADMIN", "ADMIN", "EXECUTIVE", "SALES", "TRM_KABUL", "TRM_ACCEPTANCE"}


def is_eligible_lab_personnel(user: Optional[User]) -> bool:
    """SYSADMIN, EXECUTIVE, SALES ve TRM_KABUL/TRM_ACCEPTANCE rollerine SD veya biyolojik adım atanamaz."""
    if user is None:
        return False
    role_code = (user.role.value if hasattr(user.role, "value") else str(user.role or "")).strip().upper()
    if role_code in EXCLUDED_WORKLOAD_ROLES:
        return False
    if (user.username or "").strip().lower() == "yigit":
        return False
    return True

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


def _get_human_task_window(step: StudyStep) -> Tuple[datetime, datetime]:
    """
    Bir adımın insan (teknisyen) iş yükü ve mesai/personel çakışma penceresini döner.
    Eğer adım doğrudan 24s/72s gibi uzun süreli bir cihaz/ekstraksiyon penceresi taşıyorsa
    (`planned_end - planned_start >= 24 saat`), cihaz o süre boyunca çalışırken teknisyen
    yalnız başlangıçtaki kurulum süresinde (90 dk) fiziksel olarak görev yapar.
    """
    s_dt = step.planned_start
    e_dt = step.planned_end
    if (
        s_dt is not None
        and e_dt is not None
        and (e_dt - s_dt) >= timedelta(hours=24)
        and (
            step.equipment_id is not None
            or step.step_type == "Ekstraksiyon"
            or "Ekstraksiyon" in (step.step_name or "")
            or "İnkübatör" in (step.step_name or "")
        )
    ):
        return s_dt, s_dt + timedelta(minutes=90)
    return s_dt, e_dt


# ---------------------------------------------------------------------------
# KURAL 1: 9 SAAT İŞ YÜKÜ
# ---------------------------------------------------------------------------
def calculate_personnel_workload(
    db: Session,
    personnel_id: int,
    target_date: date,
    study_steps_override: Optional[Tuple[Study, List[StudyStep]]] = None,
) -> Dict[str, Any]:
    """
    SALT-OKUNUR iş yükü hesabı: Personelin hedef gündeki aktif görevlerinin o güne düşen
    dakikalarını toplar. Conflict tablosuna YAZMAZ (dashboard / personel ekranı için).
    İptal edilmiş görevler ve iptal edilmiş çalışmaların görevleri sayılmaz.
    """
    day_start = datetime.combine(target_date, time.min)
    day_end = datetime.combine(target_date, time.max)

    query = (
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
    )
    if study_steps_override is not None:
        ov_study, _ = study_steps_override
        query = query.filter(StudyStep.study_id != ov_study.id)

    steps = list(query.order_by(StudyStep.planned_start).all())
    if study_steps_override is not None:
        ov_study, ov_steps = study_steps_override
        if ov_study.status != StudyStatus.CANCELLED:
            for s in ov_steps:
                if (
                    s.status != StepStatus.CANCELLED
                    and any(u.id == personnel_id for u in s.assignees)
                    and s.planned_start <= day_end
                    and s.planned_end >= day_start
                ):
                    steps.append(s)
        steps.sort(key=lambda x: x.planned_start)

    total_minutes = 0
    tasks = []
    for step in steps:
        st_obj = study_steps_override[0] if (study_steps_override and step.study_id == study_steps_override[0].id) else step.study
        h_start, h_end = _get_human_task_window(step)
        # Görevin o gün içerisine düşen süresi (gece yarısını aşan görevler bölünür)
        minutes = _overlap_minutes(h_start, h_end, day_start, day_end + timedelta(microseconds=1))
        if minutes <= 0:
            continue
        total_minutes += minutes
        tasks.append({
            "step_id": step.id,
            "study_id": step.study_id,
            "study_code": st_obj.study_code,
            "study_status": st_obj.status.value,
            "step_name": step.step_name,
            "study_day": step.study_day,
            "planned_start": h_start.isoformat(),
            "planned_end": h_end.isoformat(),
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
    study_steps_override: Optional[Tuple[Study, List[StudyStep]]] = None,
    persist_conflict: bool = True,
) -> Optional[Conflict]:
    """540 dk aşılmışsa CRITICAL PERSONNEL_OVERLAP oluşturur (commit etmez)."""
    workload = calculate_personnel_workload(
        db, personnel.id, target_date, study_steps_override=study_steps_override
    )
    total = workload["total_minutes"]
    if total <= MAX_DAILY_WORKLOAD_MINUTES:
        return None

    title = f"9 Saat İş Yükü Aşımı: {personnel.full_name} — {target_date:%d.%m.%Y}"
    if persist_conflict:
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
    if persist_conflict:
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
    persist_conflict: bool = True,
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
    if persist_conflict:
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


def _find_free_slot_for_flexible_step(
    target_day: date,
    default_start: datetime,
    duration_minutes: int,
    assignees: List[User],
    busy_steps: List[StudyStep],
    busy_assignees_map: Dict[int, set],
) -> Tuple[datetime, datetime]:
    """
    FAZ 6.4 (Madde 2B): Esnek (is_biological_fixed_time == False) bir adım atanırken,
    atanacak personelin varsayılan saat diliminde (örn. 09:00-11:00) başka bir görevi varsa,
    yeni görevi aynı saate üst üste bindirmek yerine personelin o günkü ilk boş saat dilimine
    (örn. 11:00-13:00) otomatik yerleştirir.
    """
    default_end = default_start + timedelta(minutes=duration_minutes)
    assignee_ids = {u.id for u in assignees}
    if not assignee_ids:
        return default_start, default_end

    # Bu personellerin o günkü mevcut dolu aralıklarını topla
    day_start_bound = datetime.combine(target_day, WORKDAY_START)
    day_end_bound = datetime.combine(target_day, WORKDAY_END)

    busy_intervals: List[Tuple[datetime, datetime]] = []
    for ex in busy_steps:
        ex_uids = busy_assignees_map.get(ex.id)
        if ex_uids is None:
            ex_uids = {u.id for u in ex.assignees}
        if assignee_ids.intersection(ex_uids):
            if ex.planned_start.date() == target_day or ex.planned_end.date() == target_day:
                busy_intervals.append((ex.planned_start, ex.planned_end))

    def _is_free(c_start: datetime, c_end: datetime) -> bool:
        return all(_overlap_minutes(c_start, c_end, b_s, b_e) == 0 for b_s, b_e in busy_intervals)

    if _is_free(default_start, default_end):
        return default_start, default_end

    # Aday başlangıç saatleri: önce varsayılan saatten (örn. 09:00) mesai bitimine kadar olan
    # görev bitiş noktaları ve 30 dk'lık dilimler; bulunamazsa 08:00..default_start arası.
    post_candidates = {default_start}
    pre_candidates = set()
    for _, b_e in busy_intervals:
        if day_start_bound <= b_e <= day_end_bound - timedelta(minutes=duration_minutes):
            if b_e >= default_start:
                post_candidates.add(b_e)
            else:
                pre_candidates.add(b_e)

    cursor = day_start_bound
    while cursor + timedelta(minutes=duration_minutes) <= day_end_bound:
        if cursor >= default_start:
            post_candidates.add(cursor)
        else:
            pre_candidates.add(cursor)
        cursor += timedelta(minutes=30)

    for cand_start in sorted(post_candidates) + sorted(pre_candidates):
        cand_end = cand_start + timedelta(minutes=duration_minutes)
        if cand_end <= day_end_bound and _is_free(cand_start, cand_end):
            return cand_start, cand_end

    return default_start, default_end


def _assign_roles(
    db: Session,
    study: Study,
    planned: List[Tuple[TemplateStep, datetime, datetime]],
    existing_steps: List[StudyStep],
    existing_assignees: Dict[int, set],
) -> Tuple[Dict[UserRole, User], List[UserRole]]:
    """
    Şablondaki rolleri kişilere çözer.
      * STUDY_DIRECTOR → çalışmanın kendi SD'si.
      * Diğer roller → çalışma boyunca TEK kişi (GLP skorlama tutarlılığı). Aday sırası:
        (1) biyolojik kilitli pencerelerde en az çakışan dakika,
        (2) tüm şablon pencerelerinde en az çakışan dakika,
        (3) o günlerdeki en düşük iş yükü,
        (4) en küçük ID.
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
            if sd is not None and sd.is_active and is_eligible_lab_personnel(sd):
                assignment[role] = sd
            else:
                fallback_sds = [
                    u for u in db.query(User).filter(User.role == UserRole.STUDY_DIRECTOR, User.is_active == True).order_by(User.id).all()  # noqa: E712
                    if is_eligible_lab_personnel(u)
                ]
                if fallback_sds:
                    assignment[role] = fallback_sds[0]
                    study.study_director_id = fallback_sds[0].id
                else:
                    unfilled.append(role)
            continue

        candidates = [
            u for u in db.query(User).filter(User.role == role, User.is_active == True).order_by(User.id).all()  # noqa: E712
            if is_eligible_lab_personnel(u)
        ]
        if not candidates:
            unfilled.append(role)
            continue

        locked_windows = [(s, e) for ts, s, e in planned if role in ts.roles and ts.is_biological_fixed_time]
        all_windows = [(s, e) for ts, s, e in planned if role in ts.roles]
        days = sorted({s.date() for s, _ in all_windows})

        def score(user: User):
            locked_busy = sum(
                _overlap_minutes(s, e, ex.planned_start, ex.planned_end)
                for s, e in locked_windows
                for ex in existing_steps
                if user.id in existing_assignees[ex.id]
            )
            total_busy = sum(
                _overlap_minutes(s, e, ex.planned_start, ex.planned_end)
                for s, e in all_windows
                for ex in existing_steps
                if user.id in existing_assignees[ex.id]
            )
            load = sum(calculate_personnel_workload(db, user.id, d)["total_minutes"] for d in days)
            return locked_busy, total_busy, load, user.id

        assignment[role] = min(candidates, key=score)
    return assignment, unfilled


def compute_friday_alignment_offset(acclimatization_start_date: date, min_offset_days: int = 0) -> int:
    """
    G0 sabit kalarak (minimum 4 gün aklimatizasyon korunarak) G4 ekstraksiyon adımını
    ilk uygun Cuma gününe hizalayan ek aklimatizasyon gün sayısını hesaplar.
    Cuma ekstraksiyon -> Cmt/Paz su banyosunda -> Pazartesi enjeksiyon -> Salı/Çarşamba/Perşembe gözlem (0 hafta sonu insan görevi).
    """
    start_offset = max(0, int(min_offset_days))
    base_ex_date = acclimatization_start_date + timedelta(days=4 + start_offset)
    return start_offset + ((4 - base_ex_date.weekday()) % 7)


def get_study_extraction_usage(study: Optional[Study], has_extraction_step: bool = True) -> Dict[str, Any]:
    """
    Bir çalışmanın Polar ve Apolar ekstraksiyon kullanım durumunu ve Çalkalamalı Su Banyosu
    (EQ-WB-001) kaynak gereksinimini tek merkezden hesaplar.
    `None` (henüz girilmemiş / bilinmeyen bilgi) ASLA `True` veya `False` olarak varsayılmaz:
      * extraction_polar is True     -> Polar kapasite kullanılır (EQ-WB-001)
      * extraction_non_polar is True -> Apolar kapasite kullanılır (EQ-WB-001)
      * False                        -> İlgili kapasite kullanılmaz
      * None                         -> İlgili bileşen bilgisi eksik/belirsizdir
    Cihaz atama, rezervasyon, kapasite çakışması ve alternatif tarih önerisi aynı
    doğrulanmış kaynak tanımını (`uses_water_bath = uses_polar or uses_apolar`) kullanır.
    """
    if study is None:
        return {
            "polar": None,
            "apolar": None,
            "polar_known": False,
            "apolar_known": False,
            "uses_polar": False,
            "uses_apolar": False,
            "uses_water_bath": False,
            "missing_components": ["polar", "apolar"] if has_extraction_step else [],
            "missing_extraction_info": bool(has_extraction_step),
            "status": "MISSING" if has_extraction_step else "NOT_APPLICABLE",
            "message": "Çalışmanın polar/apolar ekstraksiyon çözücü bilgisi henüz girilmedi.",
        }
    polar = getattr(study, "extraction_polar", None)
    apolar = getattr(study, "extraction_non_polar", None)
    polar_known = polar is not None
    apolar_known = apolar is not None
    uses_polar = polar is True
    uses_apolar = apolar is True
    uses_water_bath = bool(uses_polar or uses_apolar)

    missing_components: List[str] = []
    if has_extraction_step:
        if polar is None:
            missing_components.append("polar")
        if apolar is None:
            missing_components.append("apolar")
    missing = len(missing_components) > 0

    if not has_extraction_step:
        status_code = "NOT_APPLICABLE"
        msg = "Çalışmada ekstraksiyon adımı bulunmuyor."
    elif polar is None and apolar is None:
        status_code = "MISSING"
        msg = "Ekstraksiyon çözücü bilgisi (Polar / Apolar) eksik; cihaz kullanımı varsayılmadı."
    elif missing:
        status_code = "PARTIAL_MISSING"
        missing_labels = ", ".join("Polar" if c == "polar" else "Apolar" for c in missing_components)
        msg = f"Ekstraksiyon çözücü bilgisi kısmen eksik ({missing_labels} belirsiz); yalnızca bilinen bileşen değerlendirildi."
    elif uses_polar and uses_apolar:
        status_code = "POLAR_AND_APOLAR"
        msg = "Polar ve Apolar ekstraksiyon birlikte kullanılıyor (Çalkalamalı Su Banyosu)."
    elif uses_polar:
        status_code = "POLAR_ONLY"
        msg = "Yalnızca Polar ekstraksiyon kullanılıyor (Çalkalamalı Su Banyosu)."
    elif uses_apolar:
        status_code = "APOLAR_ONLY"
        msg = "Yalnızca Apolar ekstraksiyon kullanılıyor (Çalkalamalı Su Banyosu)."
    else:
        status_code = "NONE"
        msg = "Polar veya Apolar ekstraksiyon kullanılmıyor."

    return {
        "polar": polar,
        "apolar": apolar,
        "polar_known": polar_known,
        "apolar_known": apolar_known,
        "uses_polar": uses_polar,
        "uses_apolar": uses_apolar,
        "uses_water_bath": uses_water_bath,
        "missing_components": missing_components,
        "missing_extraction_info": missing,
        "status": status_code,
        "message": msg,
    }


def _get_water_bath_window(step: StudyStep) -> Tuple[datetime, datetime]:
    """
    Bir ekstraksiyon adımının Çalkalamalı Su Banyosu (EQ-WB-001) rezervasyon penceresini `[start, end)` döner:
      - Adımın `planned_end - planned_start` süresi >= 4 saat ise (doğrudan 24s veya 72s pencere
        olarak tanımlanmışsa) `[planned_start, planned_end)` kullanılır.
      - Adım yalnız teknisyen kurulum süresini (örn. 90 dk) taşıyorsa, adım adında '24 saat'
        geçiyorsa +24 saat, aksi halde standart +72 saat rezervasyon penceresi kullanılır.
    """
    wb_start = step.planned_start
    if step.planned_end is not None and (step.planned_end - wb_start) >= timedelta(hours=4):
        return wb_start, step.planned_end
    name_low = (step.step_name or "").lower()
    if "24 saat" in name_low or "24h" in name_low or "24 s" in name_low:
        return wb_start, wb_start + timedelta(hours=24)
    return wb_start, wb_start + timedelta(hours=72)


def _is_water_bath_extraction_step(
    step: StudyStep,
    water_bath: Optional[Equipment] = None,
    study_ext_usage: Optional[Dict[str, Any]] = None,
) -> bool:
    if step.step_type == "Ekstraksiyon" or "Ekstraksiyon" in (step.step_name or ""):
        return True
    ext_u = study_ext_usage or get_study_extraction_usage(getattr(step, "study", None))
    if (
        water_bath is not None
        and step.equipment_id == water_bath.id
        and (ext_u.get("uses_polar") or ext_u.get("uses_apolar"))
        and step.planned_start is not None
        and step.planned_end is not None
        and (step.planned_end - step.planned_start) >= timedelta(hours=4)
    ):
        return True
    return False


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
    yarı-açık `[start, end)` aralığında tepe eşzamanlı kullanım (`peak_concurrent_usage`) kapasitesini
    aşmadan müsait olduğu ilk günü (ve G4'e göre gün ofsetini) bulur.
    """
    max_polar = water_bath.polar_capacity or 3
    max_apolar = water_bath.non_polar_capacity or 1
    study_ext = get_study_extraction_usage(study)
    ex_steps = [
        ex
        for ex in existing_steps
        if ex.status != StepStatus.CANCELLED
        and not is_historical_unverified_step(ex, getattr(ex, "study", None))
        and (not getattr(ex, "study", None) or ex.study.status not in (StudyStatus.COMPLETED, StudyStatus.CANCELLED))
        and _is_water_bath_extraction_step(ex, water_bath=water_bath)
    ]

    apolar_intervals: List[Tuple[datetime, datetime, Any, Any]] = []
    polar_intervals: List[Tuple[datetime, datetime, Any, Any]] = []
    for ex in ex_steps:
        other_start, other_end = _get_water_bath_window(ex)
        ex_ext = get_study_extraction_usage(getattr(ex, "study", None))
        key_id = ex.study_id if ex.study_id is not None else ex.id
        if ex_ext["uses_apolar"]:
            apolar_intervals.append((other_start, other_end, ex.study or ex, key_id))
        if ex_ext["uses_polar"]:
            polar_intervals.append((other_start, other_end, ex.study or ex, key_id))

    own_ex_step = (
        db.query(StudyStep)
        .filter(StudyStep.study_id == study.id, StudyStep.status != StepStatus.CANCELLED)
        .order_by(StudyStep.step_order.asc())
        .all()
        if getattr(study, "id", None) is not None
        else []
    )
    own_wb_hours = 72.0
    own_start_tod = time(8, 0)
    for os_step in own_ex_step:
        if _is_water_bath_extraction_step(os_step, water_bath=water_bath, study_ext_usage=study_ext):
            s_w, e_w = _get_water_bath_window(os_step)
            own_start_tod = s_w.time()
            own_wb_hours = max(1.0, (e_w - s_w).total_seconds() / 3600.0)
            break

    for candidate_offset in range(max(0, current_offset) + 1, max(0, current_offset) + 60):
        cand_ex_date = acclimatization_start_date + timedelta(days=4 + candidate_offset)
        wb_start = datetime.combine(cand_ex_date, own_start_tod)
        wb_end = wb_start + timedelta(hours=own_wb_hours)

        apolar_peak = peak_concurrent_usage(wb_start, wb_end, apolar_intervals, include_self=True)
        polar_peak = peak_concurrent_usage(wb_start, wb_end, polar_intervals, include_self=True)

        apolar_ok = (not study_ext["uses_apolar"]) or (apolar_peak <= max_apolar)
        polar_ok = (not study_ext["uses_polar"]) or (polar_peak <= max_polar)
        if apolar_ok and polar_ok:
            return candidate_offset, cand_ex_date

    fallback_offset = max(0, current_offset) + 3
    return fallback_offset, acclimatization_start_date + timedelta(days=4 + fallback_offset)


def build_conflict_resolutions(
    db: Session,
    conflict: Conflict,
    study: Optional[Study] = None,
    existing_steps: Optional[List[StudyStep]] = None,
    fast_mode: bool = False,
    active_techs: Optional[List[User]] = None,
    water_bath: Optional[Equipment] = None,
    step_by_id: Optional[Dict[int, StudyStep]] = None,
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
            fri_offset = compute_friday_alignment_offset(base_day0, study.extraction_start_offset_days or 0)
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
        step = (
            step_by_id.get(conflict.step_id)
            if (step_by_id is not None and conflict.step_id)
            else (
                conflict.step
                or (db.query(StudyStep).filter(StudyStep.id == conflict.step_id).first() if conflict.step_id else None)
            )
        )
        current_assignee_ids = set(step.assignee_ids) if step else set()
        target_day = step.planned_start.date() if step else date.today()

        techs = (
            active_techs
            if active_techs is not None
            else [
                u for u in db.query(User).filter(User.role == UserRole.TECHNICIAN, User.is_active == True).order_by(User.id.asc()).all()  # noqa: E712
                if is_eligible_lab_personnel(u)
            ]
        )
        backup_candidates = [u for u in techs if u.id not in current_assignee_ids] or techs
        best_backup = None
        if backup_candidates:
            if fast_mode:
                best_backup = backup_candidates[0]
            else:
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
                    f"görevi tek tıkla atar ve çakışmayı yeniden denetler."
                ),
            }
        )
        return resolutions

    # c0) FAZ 8.1: Kafes kapasitesi / 24-72s uzun süreli cihaz kapasitesi aşımı → ilk boşalan tarihe yönlendir
    if study and is_capacity_conflict(conflict):
        base_day0 = study.acclimatization_start_date or study.target_start_date or date.today()
        if fast_mode:
            cand_dt = (study.target_end_date or (base_day0 + timedelta(days=7))) + timedelta(days=1)
            while cand_dt.weekday() >= 5:
                cand_dt += timedelta(days=1)
            free_g0 = cand_dt.isoformat()
        else:
            tpl_for_study = get_template(getattr(study, 'template_code', None) or DEFAULT_TEMPLATE_CODE, db=db)
            free_g0 = find_first_free_g0(db, study, tpl_for_study, base_day0, study.extraction_start_offset_days or 0)
        if free_g0:
            resolutions.append(
                {
                    'action': 'SHIFT_TO_NEXT_AVAILABLE_CAPACITY_DATE',
                    'label': f"İlk Boşalan Tarihe Kaydır ({date.fromisoformat(free_g0):%d.%m.%Y})",
                    'style': 'blue',
                    'next_available_date': free_g0,
                    'description': (
                        f"Gün 0'ı kafes / cihaz kapasitesinin uygun olduğu ilk iş günü olan "
                        f"{date.fromisoformat(free_g0):%d.%m.%Y} tarihine kaydırarak yeniden planlar."
                    ),
                }
            )
        return resolutions

    # c) Cihaz Kapasite Aşımı (EQUIPMENT_OVERLAP)
    if conflict.conflict_type == ConflictType.EQUIPMENT_OVERLAP and study:
        water_bath = water_bath or seed_default_equipment(db)
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


def is_historical_unverified_step(
    step: StudyStep,
    study: Optional[Study] = None,
    sample: Optional[Any] = None,
    ref_date: date = REFERENCE_DATE,
) -> bool:
    """
    Excel/demo geçmiş içe aktarımından gelen ve referans tarihten (2026-11-03) önceye
    planlanmış olup gerçekleşme detayı bilinmeyen (tamamlanmamış, actual_start/end/ref girilmemiş)
    adımları tespit eder. Bu adımlar COMPLETED yapılmaz ve tamamlanan görev istatistiğine
    eklenmez; ancak aktif çakışma ekranını eski belirsiz kayıtlarla doldurmamak için aktif
    çakışma hesabından hariç tutulur.
    Normal (canlı) çalışmaların gecikmiş/açık geçmiş adımları buraya GİRMEZ.
    """
    if step is None or step.status in (StepStatus.COMPLETED, StepStatus.CANCELLED):
        return False
    if (
        getattr(step, "actual_start", None) is not None
        or getattr(step, "actual_end", None) is not None
        or getattr(step, "actual_reference_time", None) is not None
    ):
        return False
    st = study or getattr(step, "study", None)
    if st is None:
        return False
    meta = st.dossier_metadata if isinstance(getattr(st, "dossier_metadata", None), dict) else {}
    if not (meta.get("historical_excel_import") or meta.get("is_historical_demo")):
        return False
    if step.planned_start and step.planned_start.date() < ref_date:
        return True
    if sample is not None:
        exp_end = getattr(sample, "experiment_end_date", None)
        if exp_end is not None and exp_end < ref_date:
            return True
    return False


_LATEST_PREVIEW_SNAPSHOTS: Dict[Tuple[int, str], str] = {}


def check_step_revision_eligibility(
    step: StudyStep,
    schedule_deviation_minutes: int = 0,
    has_source_actual_reference: bool = True,
) -> Tuple[bool, Optional[str]]:
    """
    Bağımlı bir biyolojik gözlem adımının SD onaylı plan revizyonu ile kaydırılıp kaydırılamayacağını denetler.
    Yalnızca durumu PENDING olan ve hiçbir gerçekleşen zaman verisi (actual_start, actual_end, actual_reference_time)
    bulunmayan bağımlı adımlar kaydırılabilir.
    """
    if not has_source_actual_reference:
        return (
            False,
            "Kaynak biyolojik referans adımı için gerçekleşen referans saati (actual_reference_time) henüz kaydedilmemiştir.",
        )
    if step.status == StepStatus.COMPLETED:
        return (
            False,
            "Adım tamamlanmış (COMPLETED) olduğu için planlanan saati değiştirilemez.",
        )
    if step.status == StepStatus.CANCELLED:
        return (
            False,
            "Adım iptal edilmiş (CANCELLED) olduğu için planlanan saati değiştirilemez.",
        )
    if step.status == StepStatus.IN_PROGRESS:
        return (
            False,
            "Adım başlamış / devam ediyor (IN_PROGRESS) olduğu için planlanan saati değiştirilemez.",
        )
    if step.status == StepStatus.DELAYED:
        return (
            False,
            "Adım gecikmede / işlem görmüş (DELAYED) durumunda olduğu için yalnızca PENDING adımlar revize edilebilir; planlanan saati değiştirilemez.",
        )
    if step.status != StepStatus.PENDING:
        st_label = step.status.value if hasattr(step.status, "value") else str(step.status)
        return (
            False,
            f"Adım durumu PENDING olmadığı ({st_label}) için planlanan saati değiştirilemez.",
        )
    has_actual_start = step.actual_start is not None
    has_actual_end = step.actual_end is not None
    has_actual_ref = getattr(step, "actual_reference_time", None) is not None
    if has_actual_start or has_actual_end or has_actual_ref:
        present_fields = []
        if has_actual_start:
            present_fields.append("actual_start")
        if has_actual_end:
            present_fields.append("actual_end")
        if has_actual_ref:
            present_fields.append("actual_reference_time")
        fields_str = ", ".join(present_fields)
        return (
            False,
            f"Adım durumu PENDING olsa bile gerçekleşen zaman verisi ({fields_str}) girilmiş olduğu için başlamış/gerçekleşmiş kabul edilir ve kaydırılamaz.",
        )
    if schedule_deviation_minutes == 0:
        return (
            False,
            "Adımın planlanan saati zaten beklenen biyolojik pencere ile uyumludur (sapma: 0 dk).",
        )
    return True, None


def compute_biological_dependency_info(
    study: Study,
    steps: List[StudyStep],
    template: Any = None,
) -> Dict[str, Any]:
    """
    Biyolojik referans adımı (örn. Gün 7 Uygulama / Enjeksiyon) ile ona bağlı 24/48/72. saat
    gözlem adımları arasındaki ilişkiyi hesaplar.
    Onaylanmış plan saatlerini (planned_start / planned_end) DEĞİŞTİRMEZ; beklenen saatleri,
    kaynak adım sapmasını, bağımlı gözlem toleransını ve gerçekleşen gözlem zamanı denetimini
    birbirinden ayrı hesaplayıp döner.
    """
    if template is None:
        try:
            template = get_template(getattr(study, "template_code", None) or DEFAULT_TEMPLATE_CODE, db=None)
        except Exception:
            template = None

    base_day0 = (
        getattr(study, "acclimatization_start_date", None)
        or getattr(study, "target_start_date", None)
        or (steps[0].planned_start.date() if steps and steps[0].planned_start else date.today())
    )
    raw_meta = getattr(study, "dossier_metadata", None) if study is not None else None
    bio_revisions: List[Dict[str, Any]] = (
        list(raw_meta.get("biological_revisions") or [])
        if isinstance(raw_meta, dict)
        else []
    )

    ts_by_order: Dict[int, TemplateStep] = (
        {ts.order: ts for ts in template.steps} if (template and getattr(template, "steps", None)) else {}
    )
    step_by_order: Dict[int, StudyStep] = {s.step_order: s for s in steps}
    by_step_id: Dict[int, Dict[str, Any]] = {}
    dependent_by_ref_order: Dict[int, List[Dict[str, Any]]] = {}
    revision_proposals: List[Dict[str, Any]] = []
    ineligible_revision_steps: List[Dict[str, Any]] = []
    ref_exceeds_any = False

    for s in steps:
        ts = ts_by_order.get(s.step_order)
        is_ref = bool(ts and getattr(ts, "is_biological_reference", False))
        ref_tod = getattr(ts, "reference_event_time", None) if ts else None
        planned_ref_dt: Optional[datetime] = None
        if is_ref and s.planned_start:
            planned_ref_dt = datetime.combine(s.planned_start.date(), ref_tod or s.planned_start.time())

        actual_ref_dt: Optional[datetime] = getattr(s, "actual_reference_time", None)
        ref_order = getattr(ts, "reference_step_order", None) if ts else None
        offset_hours = getattr(ts, "reference_offset_hours", None) if ts else None
        is_dep_obs = bool(ref_order is not None and offset_hours is not None)
        requires_ref_time = bool(is_ref or is_dep_obs)
        ref_time_role = "SOURCE" if is_ref else ("DEPENDENT_OBSERVATION" if is_dep_obs else None)
        ref_time_label = (
            "Uygulama / Enjeksiyon Referans Saati"
            if is_ref
            else ("Gerçekleşen Gözlem / Ölçüm Saati" if is_dep_obs else None)
        )

        expected_start = s.planned_start
        expected_end = s.planned_end
        deviation_minutes = 0
        schedule_deviation_minutes = 0
        exceeds_tol = False
        source_exceeds_tol = False
        schedule_exceeds_dep_tol = False
        actual_obs_dev_min: Optional[int] = None
        actual_obs_exceeds_tol = False
        missing_actual_obs_time = False
        requires_revision = False
        eligible_for_rev = False
        ineligible_reason: Optional[str] = None
        proposed_study_day = s.study_day
        expected_study_day = s.study_day
        day_changed = False
        expected_day_changed = False
        revision_suggestion: Optional[str] = None

        if is_ref:
            if actual_ref_dt is not None and planned_ref_dt is not None:
                deviation_minutes = int(round((actual_ref_dt - planned_ref_dt).total_seconds() / 60.0))
                schedule_deviation_minutes = deviation_minutes
                ref_tol = s.biological_tolerance_minutes or 0
                exceeds_tol = abs(deviation_minutes) > ref_tol
                source_exceeds_tol = exceeds_tol
                if exceeds_tol:
                    ref_exceeds_any = True
        elif is_dep_obs:
            dep_tol = s.biological_tolerance_minutes or 0
            ref_step = step_by_order.get(ref_order)
            ts_ref = ts_by_order.get(ref_order)
            ref_actual = getattr(ref_step, "actual_reference_time", None) if ref_step is not None else None
            if ref_step is not None and ref_actual is not None:
                ref_planned_tod = getattr(ts_ref, "reference_event_time", None) if ts_ref else None
                ref_planned_dt = (
                    datetime.combine(ref_step.planned_start.date(), ref_planned_tod or ref_step.planned_start.time())
                    if ref_step.planned_start
                    else None
                )
                ref_tol = ref_step.biological_tolerance_minutes or 0
                if ref_planned_dt is not None:
                    ref_dev_min = int(round((ref_actual - ref_planned_dt).total_seconds() / 60.0))
                    source_exceeds_tol = abs(ref_dev_min) > ref_tol

                expected_start = ref_actual + timedelta(hours=float(offset_hours))
                expected_end = expected_start + timedelta(minutes=s.duration_minutes)
                expected_study_day = (expected_start.date() - base_day0).days
                expected_day_changed = expected_study_day != s.study_day
                schedule_deviation_minutes = int(round((expected_start - s.planned_start).total_seconds() / 60.0))
                # Bağımlı gözlemin planlanan saatten kayması YALNIZCA gözlemin kendi toleransına (dep_tol) göre değerlendirilir
                schedule_exceeds_dep_tol = abs(schedule_deviation_minutes) > dep_tol
                eligible_for_rev, ineligible_reason = check_step_revision_eligibility(
                    s, schedule_deviation_minutes, has_source_actual_reference=True
                )
                proposed_study_day = expected_study_day if eligible_for_rev else s.study_day
                day_changed = bool(expected_day_changed and eligible_for_rev)
            else:
                eligible_for_rev, ineligible_reason = check_step_revision_eligibility(
                    s, 0, has_source_actual_reference=False
                )

            # Gözlemin gerçek yapılma zamanı (actual_reference_time) beklenen biyolojik saate (expected_start) göre denetlenir
            if actual_ref_dt is not None and expected_start is not None:
                actual_obs_dev_min = int(round((actual_ref_dt - expected_start).total_seconds() / 60.0))
                actual_obs_exceeds_tol = abs(actual_obs_dev_min) > dep_tol
                deviation_minutes = actual_obs_dev_min
                exceeds_tol = actual_obs_exceeds_tol
            else:
                deviation_minutes = schedule_deviation_minutes
                exceeds_tol = schedule_exceeds_dep_tol
                if s.status == StepStatus.COMPLETED and actual_ref_dt is None:
                    missing_actual_obs_time = True

            if ref_step is not None and ref_actual is not None:
                requires_revision = bool(
                    eligible_for_rev
                    and schedule_deviation_minutes != 0
                    and (schedule_exceeds_dep_tol or s.is_biological_fixed_time)
                )
                if schedule_deviation_minutes != 0:
                    if eligible_for_rev:
                        revision_suggestion = (
                            f"Referans adım ({_fmt(ref_actual)}) baz alınarak +{int(offset_hours)}. saat "
                            f"'{s.step_name}' adımının {_fmt(expected_start)}–{expected_end:%H:%M} aralığına "
                            f"revize edilmesi önerilir (mevcut plan: {_fmt(s.planned_start)}–{s.planned_end:%H:%M}, "
                            f"sapma: {schedule_deviation_minutes:+d} dk)."
                        )
                    else:
                        revision_suggestion = f"Adım revize edilemez: {ineligible_reason}"
                dep_entry = {
                    "step_id": s.id,
                    "step_order": s.step_order,
                    "study_day": s.study_day,
                    "current_study_day": s.study_day,
                    "proposed_study_day": proposed_study_day,
                    "expected_study_day": expected_study_day,
                    "day_changed": day_changed,
                    "expected_day_changed": expected_day_changed,
                    "step_name": s.step_name,
                    "status": s.status.value if s.status else "PENDING",
                    "reference_step_order": ref_order,
                    "offset_hours": offset_hours,
                    "planned_start": s.planned_start.isoformat(),
                    "planned_end": s.planned_end.isoformat(),
                    "current_planned_start": s.planned_start.isoformat(),
                    "current_planned_end": s.planned_end.isoformat(),
                    "proposed_planned_start": expected_start.isoformat() if eligible_for_rev else s.planned_start.isoformat(),
                    "proposed_planned_end": expected_end.isoformat() if eligible_for_rev else s.planned_end.isoformat(),
                    "expected_start": expected_start.isoformat(),
                    "expected_end": expected_end.isoformat(),
                    "expected_reference_time": expected_start.isoformat(),
                    "actual_start": s.actual_start.isoformat() if s.actual_start else None,
                    "actual_end": s.actual_end.isoformat() if s.actual_end else None,
                    "actual_reference_time": actual_ref_dt.isoformat() if actual_ref_dt else None,
                    "deviation_minutes": deviation_minutes,
                    "schedule_deviation_minutes": schedule_deviation_minutes,
                    "actual_observation_deviation_minutes": actual_obs_dev_min,
                    "tolerance_minutes": s.biological_tolerance_minutes,
                    "exceeds_tolerance": exceeds_tol,
                    "source_exceeds_tolerance": source_exceeds_tol,
                    "schedule_exceeds_dependent_tolerance": schedule_exceeds_dep_tol,
                    "actual_observation_exceeds_tolerance": actual_obs_exceeds_tol,
                    "missing_actual_observation_time": missing_actual_obs_time,
                    "eligible": eligible_for_rev,
                    "eligible_for_revision": eligible_for_rev,
                    "ineligible_reason": ineligible_reason,
                    "requires_revision": requires_revision,
                    "revision_suggestion": revision_suggestion,
                }
                dependent_by_ref_order.setdefault(ref_order, []).append(dep_entry)
                if requires_revision:
                    revision_proposals.append(dep_entry)
                elif not eligible_for_rev and schedule_deviation_minutes != 0:
                    ineligible_revision_steps.append(dep_entry)

        by_step_id[s.id] = {
            "is_biological_reference": is_ref,
            "is_dependent_observation": is_dep_obs,
            "requires_reference_time": requires_ref_time,
            "reference_time_role": ref_time_role,
            "reference_time_label": ref_time_label,
            "planned_reference_time": (
                planned_ref_dt.isoformat()
                if planned_ref_dt
                else (s.planned_start.isoformat() if (is_dep_obs and s.planned_start) else None)
            ),
            "actual_reference_time": actual_ref_dt.isoformat() if actual_ref_dt else None,
            "reference_step_order": ref_order,
            "offset_hours": offset_hours,
            "expected_start": expected_start.isoformat() if expected_start else None,
            "expected_end": expected_end.isoformat() if expected_end else None,
            "expected_reference_time": (
                actual_ref_dt.isoformat()
                if (is_ref and actual_ref_dt)
                else (planned_ref_dt.isoformat() if (is_ref and planned_ref_dt) else (expected_start.isoformat() if expected_start else None))
            ),
            "current_study_day": s.study_day,
            "proposed_study_day": proposed_study_day,
            "expected_study_day": expected_study_day,
            "day_changed": day_changed,
            "expected_day_changed": expected_day_changed,
            "deviation_minutes": deviation_minutes,
            "schedule_deviation_minutes": schedule_deviation_minutes,
            "actual_observation_deviation_minutes": actual_obs_dev_min,
            "exceeds_tolerance": exceeds_tol,
            "source_exceeds_tolerance": source_exceeds_tol,
            "schedule_exceeds_dependent_tolerance": schedule_exceeds_dep_tol,
            "actual_observation_exceeds_tolerance": actual_obs_exceeds_tol,
            "missing_actual_observation_time": missing_actual_obs_time,
            "eligible": eligible_for_rev,
            "eligible_for_revision": eligible_for_rev,
            "ineligible_reason": ineligible_reason,
            "requires_revision": requires_revision,
            "revision_suggestion": revision_suggestion,
            "sd_revision_approved": False,
            "sd_revision_decision": None,
        }

    source_deviations: List[Dict[str, Any]] = []
    for s in steps:
        s_info = by_step_id.get(s.id)
        if not s_info or not s_info.get("is_biological_reference"):
            continue
        actual_ref_iso = s_info.get("actual_reference_time")
        matching_rev = None
        if actual_ref_iso:
            for rev in reversed(bio_revisions):
                rev_ref_iso = rev.get("source_actual_reference_time") or rev.get("approved_for_actual_reference_time")
                if (
                    rev_ref_iso == actual_ref_iso
                    and (rev.get("source_step_order") == s.step_order or rev.get("source_step_id") == s.id)
                ):
                    matching_rev = rev
                    break
        deps_for_ref = dependent_by_ref_order.get(s.step_order, [])
        has_unrevised_eligible = any(d.get("requires_revision") for d in deps_for_ref)
        sd_rev_approved = bool(matching_rev is not None and not has_unrevised_eligible)
        s_info["sd_revision_approved"] = sd_rev_approved
        s_info["sd_revision_decision"] = matching_rev if sd_rev_approved else None
        s_info["latest_revision_record"] = matching_rev
        if actual_ref_iso is not None:
            source_deviations.append(
                {
                    "step_id": s.id,
                    "step_order": s.step_order,
                    "study_day": s.study_day,
                    "step_name": s.step_name,
                    "planned_start": s.planned_start.isoformat() if s.planned_start else None,
                    "planned_end": s.planned_end.isoformat() if s.planned_end else None,
                    "planned_reference_time": s_info.get("planned_reference_time"),
                    "actual_reference_time": actual_ref_iso,
                    "deviation_minutes": s_info.get("deviation_minutes", 0),
                    "tolerance_minutes": s.biological_tolerance_minutes or 0,
                    "exceeds_tolerance": s_info.get("exceeds_tolerance", False),
                    "sd_revision_approved": sd_rev_approved,
                    "sd_revision_decision": matching_rev if sd_rev_approved else None,
                }
            )

    all_dep_steps = [item for sub in dependent_by_ref_order.values() for item in sub]
    return {
        "by_step_id": by_step_id,
        "dependent_by_ref_order": dependent_by_ref_order,
        "dependent_steps": all_dep_steps,
        "revision_proposals": revision_proposals,
        "ineligible_revision_steps": ineligible_revision_steps,
        "source_deviations": source_deviations,
        "biological_revisions": bio_revisions,
        "ref_exceeds_tolerance": ref_exceeds_any,
    }


def _build_other_studies_expected_windows(
    existing_steps: List[StudyStep],
) -> Dict[int, Tuple[datetime, datetime]]:
    """
    Diğer çalışmalardaki referans saat gecikmeleri nedeniyle kaymış beklenen biyolojik
    gözlem pencerelerini (`step_id -> (expected_start, expected_end)`) hesaplar.
    Böylece çalışmalar arası çakışma kontrolü her iki yönde ve oluşturma sırasından
    bağımsız olarak tutarlı çalışır.
    """
    steps_by_study: Dict[int, List[StudyStep]] = {}
    study_obj_by_id: Dict[int, Study] = {}
    for ex in existing_steps:
        if ex.status == StepStatus.CANCELLED:
            continue
        steps_by_study.setdefault(ex.study_id, []).append(ex)
        if getattr(ex, "study", None) is not None:
            study_obj_by_id[ex.study_id] = ex.study

    shifted_windows: Dict[int, Tuple[datetime, datetime]] = {}
    for st_id, st_steps in steps_by_study.items():
        if not any(getattr(s, "actual_reference_time", None) is not None for s in st_steps):
            continue
        st_obj = study_obj_by_id.get(st_id)
        if st_obj is None:
            continue
        ordered = sorted(st_steps, key=lambda x: x.step_order)
        info = compute_biological_dependency_info(st_obj, ordered)
        for s in ordered:
            if s.status in (StepStatus.COMPLETED, StepStatus.CANCELLED):
                continue
            b = info["by_step_id"].get(s.id) or {}
            if not b.get("eligible_for_revision", True):
                continue
            exp_s_str = b.get("expected_start")
            exp_e_str = b.get("expected_end")
            if exp_s_str and exp_e_str:
                exp_s = datetime.fromisoformat(exp_s_str)
                exp_e = datetime.fromisoformat(exp_e_str)
                if exp_s != s.planned_start or exp_e != s.planned_end:
                    shifted_windows[s.id] = (exp_s, exp_e)
    return shifted_windows


def evaluate_study_conflicts(
    db: Session,
    study: Study,
    steps: List[StudyStep],
    existing_steps: List[StudyStep],
    existing_assignees: Dict[int, set],
    water_bath: Equipment,
    unfilled_roles: Optional[List[UserRole]] = None,
    template: Any = None,
    preserve_approved_weekend_step_ids: Optional[set] = None,
    persist_conflicts: bool = True,
) -> List[Tuple[Conflict, List[int]]]:
    """
    FAZ 6.4 (Madde 3): Bir çalışmanın tüm adımları için hafta sonu/mesai dışı kontrolü,
    personel eşzamanlı saat çakışması, Su Banyosu (EQ-WB-001) Polar/Apolar kapasite kontrolü,
    biyolojik referans gecikmesi / bağımlı adım sapmaları ve 9 saatlik (540 dk) günlük iş yükü denetimini çalıştırır.
    """
    findings: List[Tuple[Conflict, List[int]]] = []
    approved_wk_steps = preserve_approved_weekend_step_ids or set()
    if template is None:
        try:
            template = get_template(getattr(study, "template_code", None) or DEFAULT_TEMPLATE_CODE, db=db)
        except Exception:
            template = None

    # Personel aktif görev çakışması için yalnızca tamamlanmamış ve tarihsel-belirsiz olmayan aktif adımlar dikkate alınır
    active_personnel_steps = [
        ex for ex in existing_steps
        if ex.status != StepStatus.COMPLETED
        and ex.status != StepStatus.CANCELLED
        and not is_historical_unverified_step(ex, getattr(ex, "study", None))
        and (not getattr(ex, "study", None) or ex.study.status not in (StudyStatus.COMPLETED, StudyStatus.CANCELLED))
    ]
    # 72 saatlik Su Banyosu ve uzun süreli cihaz rezervasyonları için kurulum adımı COMPLETED olsa dahi
    # çalışma devam ettiği sürece 72 saatlik cihaz rezervasyon penceresi aktif kalır!
    active_equipment_steps = [
        ex for ex in existing_steps
        if ex.status != StepStatus.CANCELLED
        and not is_historical_unverified_step(ex, getattr(ex, "study", None))
        and (not getattr(ex, "study", None) or ex.study.status not in (StudyStatus.COMPLETED, StudyStatus.CANCELLED))
    ]
    other_shifted_windows = _build_other_studies_expected_windows(existing_steps)
    recorded_overlap_keys: set = set()

    def record(conflict: Conflict, step_ids: List[int]):
        if persist_conflicts:
            db.add(conflict)
        findings.append((conflict, step_ids))

    # 6.0) Şablonun gerektirdiği roller ile mevcut adım atamalarını (eksik, pasif veya uygunsuz rol) her doğrulamada denetle
    ts_by_order = {ts.order: ts for ts in template.steps} if (template and getattr(template, "steps", None)) else {}
    missing_role_steps: Dict[UserRole, List[int]] = {}
    if unfilled_roles:
        for role in unfilled_roles:
            missing_role_steps[role] = [
                s.id for s in steps
                if s.status not in (StepStatus.COMPLETED, StepStatus.CANCELLED)
                and not is_historical_unverified_step(s, study)
                and s.step_order in ts_by_order
                and role in ts_by_order[s.step_order].roles
            ]

    for s in steps:
        if s.status in (StepStatus.COMPLETED, StepStatus.CANCELLED) or is_historical_unverified_step(s, study):
            continue
        ts = ts_by_order.get(s.step_order)
        # Mevcut atanan personelin aktiflik ve uygunluk kontrolü
        for u in s.assignees:
            if not getattr(u, "is_active", True) or not is_eligible_lab_personnel(u):
                record(
                    Conflict(
                        conflict_type=ConflictType.QUALIFICATION_MISMATCH,
                        severity=ConflictSeverity.CRITICAL,
                        title=f"Uygunsuz veya Pasif Personel Ataması: {u.full_name}",
                        description=(
                            f"'{s.step_name}' adımına atanan '{u.full_name}' pasif durumdadır veya laboratuvar "
                            f"görevi için uygun rolde değildir."
                        ),
                        study_id=study.id,
                        step_id=s.id,
                    ),
                    [s.id],
                )
        if ts is not None:
            for req_role in ts.roles:
                has_valid_role_assignee = any(
                    getattr(u, "is_active", True)
                    and is_eligible_lab_personnel(u)
                    and u.role == req_role
                    for u in s.assignees
                )
                if not has_valid_role_assignee:
                    bucket = missing_role_steps.setdefault(req_role, [])
                    if s.id not in bucket:
                        bucket.append(s.id)

    for role, affected in missing_role_steps.items():
        if not affected:
            continue
        record(
            Conflict(
                conflict_type=ConflictType.QUALIFICATION_MISMATCH,
                severity=ConflictSeverity.CRITICAL,
                title=f"Atanacak aktif personel yok: {role.value}",
                description=(
                    f"Şablon '{role.value}' rolünde personel gerektiriyor ancak ilgili {len(affected)} adımda "
                    f"aktif ve yetkin personel ataması bulunmuyor."
                ),
                study_id=study.id,
                step_id=affected[0] if affected else None,
            ),
            affected,
        )

    study_ext_usage = get_study_extraction_usage(study)

    for step in steps:
        if step.status == StepStatus.CANCELLED or is_historical_unverified_step(step, study):
            continue

        if step.status != StepStatus.COMPLETED:
            step_h_start, step_h_end = _get_human_task_window(step)
            # 6a) Biyolojik kilitli adım mesai dışı / hafta sonu → WARNING (Nöbetçi personel onayı veya Cuma hizalama sunulur)
            issue = _working_hours_issue(step_h_start, step_h_end)
            if step.is_biological_fixed_time and issue and step.id not in approved_wk_steps:
                conflict = register_biological_time_violation(
                    db,
                    step,
                    commit=False,
                    persist_conflict=persist_conflicts,
                    severity=ConflictSeverity.WARNING,
                    title=f"Biyolojik Kilit Mesai Dışında (Hafta Sonu Görevi): Gün {step.study_day} — {step.step_name}",
                    reason=f"Adım {issue}. Saat ötelenemez; nöbetçi / hafta sonu personeli onaylanmalı veya ekstraksiyon Cuma'ya hizalanmalıdır.",
                )
                findings.append((conflict, [step.id]))

            # 6b) Aynı kişinin başka bir çalışmada (onaylı veya taslak) eşzamanlı görevi (planlanan VE beklenen biyolojik pencereler)
            for person in step.assignees:
                for ex in active_personnel_steps:
                    if person.id not in existing_assignees.get(ex.id, set()):
                        continue
                    other = ex.study
                    ex_h_start, ex_h_end = _get_human_task_window(ex)
                    ov = _overlap_minutes(step_h_start, step_h_end, ex_h_start, ex_h_end)
                    if ov > 0:
                        pair_key = ("PLANNED", step.id, ex.id, person.id)
                        if pair_key not in recorded_overlap_keys:
                            recorded_overlap_keys.add(pair_key)
                            context = (
                                f"{person.full_name}, {other.study_code} ({other.status.value}) çalışmasının "
                                f"'{ex.step_name}' görevinde ({_fmt(ex_h_start)}–{ex_h_end:%H:%M}) zaten "
                                f"görevli; {ov} dk örtüşme."
                            )
                            if step.is_biological_fixed_time:
                                record(
                                    Conflict(
                                        conflict_type=ConflictType.PERSONNEL_OVERLAP,
                                        severity=ConflictSeverity.CRITICAL,
                                        title=f"Personel Çakışması (Biyolojik Kilitli Adım): Gün {step.study_day} — {person.full_name}",
                                        description=(
                                            f"'{step.step_name}' biyolojik kilitli (planlanan: {_fmt(step_h_start)}, "
                                            f"tolerans ±{step.biological_tolerance_minutes} dk). {context} "
                                            f"Bu rolde o saatte boşta başka yetkin personel bulunamadı."
                                        ),
                                        study_id=study.id,
                                        step_id=step.id,
                                        related_study_id=other.id,
                                    ),
                                    [step.id],
                                )
                            else:
                                record(
                                    Conflict(
                                        conflict_type=ConflictType.PERSONNEL_OVERLAP,
                                        severity=ConflictSeverity.CRITICAL,
                                        title=f"Personel Çakışması: Gün {step.study_day} — {person.full_name}",
                                        description=context + " Gün içinde boş saat dilimi bulunamadı; planlayıcı/SD kararı gereklidir.",
                                        study_id=study.id,
                                        step_id=step.id,
                                        related_study_id=other.id,
                                    ),
                                    [step.id],
                                )

                    # Karşı çalışmanın referans gecikmesi nedeniyle kaymış beklenen biyolojik penceresi varsa onu da denetle
                    ex_shifted = other_shifted_windows.get(ex.id)
                    if ex_shifted is not None:
                        ex_exp_start, ex_exp_end = ex_shifted
                        ov_exp = _overlap_minutes(step_h_start, step_h_end, ex_exp_start, ex_exp_end)
                        if ov_exp > 0:
                            pair_key_exp = ("EXPECTED_OTHER", step.id, ex.id, person.id)
                            if pair_key_exp not in recorded_overlap_keys:
                                recorded_overlap_keys.add(pair_key_exp)
                                record(
                                    Conflict(
                                        conflict_type=ConflictType.PERSONNEL_OVERLAP,
                                        severity=ConflictSeverity.CRITICAL,
                                        title=(
                                            f"Personel Çakışması (Beklenen Biyolojik Pencere): "
                                            f"Gün {step.study_day} — {person.full_name}"
                                        ),
                                        description=(
                                            f"'{step.step_name}' görevi ({_fmt(step_h_start)}–{step_h_end:%H:%M}), "
                                            f"{person.full_name} personelinin {other.study_code} ({other.status.value}) "
                                            f"çalışmasındaki '{ex.step_name}' adımının referans gecikmesi sonrası beklenen "
                                            f"biyolojik penceresiyle ({_fmt(ex_exp_start)}–{ex_exp_end:%H:%M}) {ov_exp} dk çakışıyor."
                                        ),
                                        study_id=study.id,
                                        step_id=step.id,
                                        related_study_id=other.id,
                                    ),
                                    [step.id],
                                )

                # Aynı çalışma içindeki (intra-study) diğer aktif adımlarla planlanan pencere çakışması
                for own_other in steps:
                    if (
                        own_other.id == step.id
                        or own_other.status in (StepStatus.COMPLETED, StepStatus.CANCELLED)
                        or is_historical_unverified_step(own_other, study)
                    ):
                        continue
                    if not any(u.id == person.id for u in own_other.assignees):
                        continue
                    own_h_start, own_h_end = _get_human_task_window(own_other)
                    ov_own = _overlap_minutes(
                        step_h_start, step_h_end, own_h_start, own_h_end
                    )
                    if ov_own > 0:
                        intra_planned_key = (
                            "INTRA_STUDY",
                            min(step.id, own_other.id),
                            max(step.id, own_other.id),
                            person.id,
                        )
                        if intra_planned_key not in recorded_overlap_keys:
                            recorded_overlap_keys.add(intra_planned_key)
                            record(
                                Conflict(
                                    conflict_type=ConflictType.PERSONNEL_OVERLAP,
                                    severity=ConflictSeverity.CRITICAL,
                                    title=f"Personel Çakışması (Çalışma İçi): Gün {step.study_day} — {person.full_name}",
                                    description=(
                                        f"Aynı çalışmadaki '{step.step_name}' ({_fmt(step_h_start)}–{step_h_end:%H:%M}) "
                                        f"ve '{own_other.step_name}' ({_fmt(own_h_start)}–{own_h_end:%H:%M}) "
                                        f"adımları {person.full_name} personeli için {ov_own} dk çakışıyor."
                                    ),
                                    study_id=study.id,
                                    step_id=step.id,
                                    related_study_id=study.id,
                                ),
                                [step.id, own_other.id],
                            )

        # 6c) Cihaz çakışması — Çalkalamalı Su Banyosu 1 (EQ-WB-001) Polar & Apolar Kapasite Kilidi
        # ve Genel / Uzun Süreli Cihaz Eşzamanlı Tepe Kullanım (Peak Concurrent Usage) Denetimi:
        # Kurulum adımı (90 dk) COMPLETED olsa bile su banyosu / uzun süreli cihaz rezervasyonu devam eder.
        # Bilinmeyen (None) ekstraksiyon bilgisi ASLA True (kesin polar kullanımı) olarak varsayılmaz.
        # Yarı-açık aralık kuralına (`[start, end)`) göre hedef pencereyle kesişen diğer çalışmalar
        # doğrudan toplanmaz; herhangi bir `t` anındaki maksimum eşzamanlı kullanım (`peak_concurrent_usage`) baz alınır.
        is_extraction = _is_water_bath_extraction_step(step, water_bath=water_bath, study_ext_usage=study_ext_usage)
        study_uses_polar = study_ext_usage["uses_polar"]
        study_uses_apolar = study_ext_usage["uses_apolar"]
        if is_extraction and (study_uses_polar or study_uses_apolar):
            wb_start, wb_end = _get_water_bath_window(step)
            apolar_intervals: List[Tuple[datetime, datetime, Study, Any]] = []
            polar_intervals: List[Tuple[datetime, datetime, Study, Any]] = []

            for ex in active_equipment_steps:
                if not _is_water_bath_extraction_step(ex, water_bath=water_bath):
                    continue
                other_wb_start, other_wb_end = _get_water_bath_window(ex)
                if _overlap_minutes(wb_start, wb_end, other_wb_start, other_wb_end) > 0:
                    ex_usage = get_study_extraction_usage(getattr(ex, "study", None))
                    ex_key = ex.study_id if ex.study_id is not None else ex.id
                    if ex_usage["uses_apolar"] and ex.study is not None:
                        apolar_intervals.append((other_wb_start, other_wb_end, ex.study, ex_key))
                    if ex_usage["uses_polar"] and ex.study is not None:
                        polar_intervals.append((other_wb_start, other_wb_end, ex.study, ex_key))

            max_apolar = water_bath.non_polar_capacity or 1
            max_polar = water_bath.polar_capacity or 3

            apolar_peak_info = compute_peak_concurrent_details(wb_start, wb_end, apolar_intervals)
            polar_peak_info = compute_peak_concurrent_details(wb_start, wb_end, polar_intervals)

            if study_uses_apolar and apolar_peak_info["peak_total"] > max_apolar:
                peak_apolar_studies = apolar_peak_info["peak_items"] or apolar_peak_info["overlapping_items"]
                other_codes = ", ".join(f"{s.study_code} ({s.status.value})" for s in peak_apolar_studies)
                record(
                    Conflict(
                        conflict_type=ConflictType.EQUIPMENT_OVERLAP,
                        severity=ConflictSeverity.CRITICAL,
                        title=f"Çalkalamalı Su Banyosu Apolar Kapasite Aşımı (Max: {max_apolar})",
                        description=(
                            f"'{water_bath.name} ({water_bath.code})' cihazında {_fmt(wb_start)} – {_fmt(wb_end)} "
                            f"(72 saatlik ekstraksiyon) penceresinde Apolar/Non-Polar kapasitesi (Max: {max_apolar} çalışma) "
                            f"aşıldı. Bu çalışma ile birlikte eşzamanlı {apolar_peak_info['peak_total']} Apolar çalışma "
                            f"({other_codes}) çakışıyor."
                        ),
                        study_id=study.id,
                        step_id=step.id,
                        related_study_id=peak_apolar_studies[0].id if peak_apolar_studies else None,
                    ),
                    [step.id],
                )

            if study_uses_polar and polar_peak_info["peak_total"] > max_polar:
                peak_polar_studies = polar_peak_info["peak_items"] or polar_peak_info["overlapping_items"]
                other_codes = ", ".join(f"{s.study_code} ({s.status.value})" for s in peak_polar_studies)
                record(
                    Conflict(
                        conflict_type=ConflictType.EQUIPMENT_OVERLAP,
                        severity=ConflictSeverity.CRITICAL,
                        title=f"Çalkalamalı Su Banyosu Polar Kapasite Aşımı (Max: {max_polar})",
                        description=(
                            f"'{water_bath.name} ({water_bath.code})' cihazında {_fmt(wb_start)} – {_fmt(wb_end)} "
                            f"(72 saatlik ekstraksiyon) penceresinde Polar kapasitesi (Max: {max_polar} çalışma) "
                            f"aşıldı. Bu çalışma ile birlikte eşzamanlı {polar_peak_info['peak_total']} Polar çalışma "
                            f"({other_codes}) çakışıyor."
                        ),
                        study_id=study.id,
                        step_id=step.id,
                        related_study_id=peak_polar_studies[0].id if peak_polar_studies else None,
                    ),
                    [step.id],
                )
        elif step.equipment_id and not is_extraction and (
            step.status != StepStatus.COMPLETED
            or (step.planned_end is not None and step.planned_start is not None and (step.planned_end - step.planned_start) >= timedelta(hours=4))
        ):
            eq_obj = db.query(Equipment).filter(Equipment.id == step.equipment_id).first()
            raw_cap = int((getattr(eq_obj, "max_concurrent_studies", None) if eq_obj else None) or 1)
            step_is_long = bool(
                step.planned_start is not None
                and step.planned_end is not None
                and (step.planned_end - step.planned_start) >= timedelta(hours=4)
            )
            overlapping_other_eq = [
                ex
                for ex in active_equipment_steps
                if ex.equipment_id == step.equipment_id
                and _overlap_minutes(step.planned_start, step.planned_end, ex.planned_start, ex.planned_end) > 0
            ]
            any_long_overlap = step_is_long or any(
                (ex.planned_end - ex.planned_start) >= timedelta(hours=4)
                for ex in overlapping_other_eq
                if ex.planned_start and ex.planned_end
            )
            # 1-2 saatlik kısa adım çakışmalarında varsayılan 4 kapasiteli uzun süreli cihazlar (EQ-WB-001 / EQ-INC-001)
            # tekil adım ekipmanı olarak atanmışsa 1 kapasiteyle denetlenir; uzun süreli (>= 4s) veya özel kapasiteli
            # cihazlarda ise `max_concurrent_studies` ve sweep-line `peak_concurrent_usage` kullanılır.
            if not any_long_overlap and eq_obj is not None and eq_obj.code in ("EQ-WB-001", "EQ-INC-001") and raw_cap == 4:
                eq_cap = 1
            else:
                eq_cap = max(1, raw_cap)

            if eq_cap == 1:
                for ex in overlapping_other_eq:
                    record(
                        Conflict(
                            conflict_type=ConflictType.EQUIPMENT_OVERLAP,
                            severity=ConflictSeverity.CRITICAL,
                            title=f"Cihaz Çakışması: Gün {step.study_day} — Ekipman #{step.equipment_id}",
                            description=f"Cihaz, {ex.study.study_code} çalışmasının '{ex.step_name}' adımında kullanımda.",
                            study_id=study.id,
                            step_id=step.id,
                            related_study_id=ex.study_id,
                        ),
                        [step.id],
                    )
                for own_eq in steps:
                    if (
                        own_eq.id != step.id
                        and own_eq.status not in (StepStatus.COMPLETED, StepStatus.CANCELLED)
                        and own_eq.equipment_id == step.equipment_id
                        and _overlap_minutes(step.planned_start, step.planned_end, own_eq.planned_start, own_eq.planned_end) > 0
                    ):
                        eq_intra_key = ("EQ_INTRA", min(step.id, own_eq.id), max(step.id, own_eq.id), step.equipment_id)
                        if eq_intra_key not in recorded_overlap_keys:
                            recorded_overlap_keys.add(eq_intra_key)
                            record(
                                Conflict(
                                    conflict_type=ConflictType.EQUIPMENT_OVERLAP,
                                    severity=ConflictSeverity.CRITICAL,
                                    title=f"Cihaz Çakışması (Çalışma İçi): Gün {step.study_day} — Ekipman #{step.equipment_id}",
                                    description=f"Cihaz aynı çalışmanın '{own_eq.step_name}' adımında eşzamanlı kullanımda.",
                                    study_id=study.id,
                                    step_id=step.id,
                                    related_study_id=study.id,
                                ),
                                [step.id, own_eq.id],
                            )
            else:
                eq_intervals: List[Tuple[datetime, datetime, StudyStep, Any]] = []
                for ex in overlapping_other_eq:
                    ex_key = ("OTHER", ex.study_id if ex.study_id is not None else ex.id)
                    eq_intervals.append((ex.planned_start, ex.planned_end, ex, ex_key))
                for own_eq in steps:
                    if (
                        own_eq.id != step.id
                        and own_eq.status not in (StepStatus.COMPLETED, StepStatus.CANCELLED)
                        and own_eq.equipment_id == step.equipment_id
                        and _overlap_minutes(step.planned_start, step.planned_end, own_eq.planned_start, own_eq.planned_end) > 0
                    ):
                        eq_intervals.append((own_eq.planned_start, own_eq.planned_end, own_eq, ("SELF", own_eq.id)))

                eq_peak_info = compute_peak_concurrent_details(step.planned_start, step.planned_end, eq_intervals)
                if eq_peak_info["peak_total"] > eq_cap:
                    peak_steps: List[StudyStep] = eq_peak_info["peak_items"] or eq_peak_info["overlapping_items"]
                    other_labels = ", ".join(
                        f"{ps.study.study_code if getattr(ps, 'study', None) else study.study_code} ('{ps.step_name}')"
                        for ps in peak_steps
                    )
                    eq_label = f"{eq_obj.name} ({eq_obj.code})" if eq_obj else f"Ekipman #{step.equipment_id}"
                    rel_sid = peak_steps[0].study_id if peak_steps else None
                    record(
                        Conflict(
                            conflict_type=ConflictType.EQUIPMENT_OVERLAP,
                            severity=ConflictSeverity.CRITICAL,
                            title=f"Cihaz Kapasite Aşımı: Gün {step.study_day} — {eq_label} (Max: {eq_cap})",
                            description=(
                                f"'{eq_label}' cihazında {_fmt(step.planned_start)} – {_fmt(step.planned_end)} "
                                f"penceresinde eşzamanlı çalışma kapasitesi (Max: {eq_cap}) aşıldı. "
                                f"Bu çalışma ile birlikte eşzamanlı tepe kullanım {eq_peak_info['peak_total']} çalışma "
                                f"({other_labels}) çakışıyor."
                            ),
                            study_id=study.id,
                            step_id=step.id,
                            related_study_id=rel_sid,
                        ),
                        [step.id],
                    )

    # 6f) Biyolojik referans adımının gerçekleşen saati ve bağımlı (24/48/72s) gözlem adımlarının denetimi
    bio_info = compute_biological_dependency_info(study, steps, template)
    step_by_id = {s.id: s for s in steps}

    # Bağımlı gözlem adımlarında tamamlanma sonrası gerçek gözlem saati (actual_reference_time) denetimi
    # (Kaynak adım tamamlanmış olsun veya olmasın, gözlem adımı COMPLETED ise gerçek gözlem saati kontrol edilir)
    for s in steps:
        if s.status == StepStatus.CANCELLED or is_historical_unverified_step(s, study):
            continue
        s_bio = bio_info["by_step_id"].get(s.id) or {}
        if s_bio.get("is_dependent_observation"):
            obs_offset = int(s_bio.get("offset_hours") or 0)
            exp_start_str = s_bio.get("expected_start") or s.planned_start.isoformat()
            exp_start_dt = datetime.fromisoformat(exp_start_str)
            if s.status == StepStatus.COMPLETED and getattr(s, "actual_reference_time", None) is None:
                record(
                    Conflict(
                        conflict_type=ConflictType.BIOLOGICAL_TIME_VIOLATION,
                        severity=ConflictSeverity.CRITICAL,
                        title=f"Eksik Biyolojik Gözlem Saati: Gün {s.study_day} — {s.step_name}",
                        description=(
                            f"'{s.step_name}' (+{obs_offset}s bağımlı biyolojik gözlem) adımı tamamlandı olarak "
                            f"işaretlendi ancak gözlemin gerçek yapılma saati (actual_reference_time) girilmedi. "
                            f"Görev başlangıç saati (actual_start) gözlem saati olarak varsayılamaz; +{obs_offset}. saat "
                            f"biyolojik pencere doğrulaması için gerçek gözlem saati girilmelidir."
                        ),
                        study_id=study.id,
                        step_id=s.id,
                    ),
                    [s.id],
                )
            elif getattr(s, "actual_reference_time", None) is not None and s_bio.get("actual_observation_exceeds_tolerance"):
                obs_dev = s_bio.get("actual_observation_deviation_minutes") or 0
                record(
                    Conflict(
                        conflict_type=ConflictType.BIOLOGICAL_TIME_VIOLATION,
                        severity=ConflictSeverity.CRITICAL,
                        title=(
                            f"Gerçekleşen Gözlem Biyolojik Pencere İhlali (+{obs_offset}s): "
                            f"Gün {s.study_day} — {s.step_name}"
                        ),
                        description=(
                            f"+{obs_offset}. saat '{s.step_name}' gözleminin beklenen biyolojik saati "
                            f"{_fmt(exp_start_dt)} (tolerans ±{s.biological_tolerance_minutes} dk) iken "
                            f"gerçekleşen gözlem saati {_fmt(s.actual_reference_time)} olarak kaydedildi "
                            f"({obs_dev:+d} dk sapma). Gözlemin kendi biyolojik tolerans penceresi aşıldı."
                        ),
                        study_id=study.id,
                        step_id=s.id,
                    ),
                    [s.id],
                )

    for s in steps:
        if s.status == StepStatus.CANCELLED or is_historical_unverified_step(s, study):
            continue
        s_bio = bio_info["by_step_id"].get(s.id) or {}
        if not s_bio.get("is_biological_reference"):
            continue
        if s.status == StepStatus.COMPLETED and getattr(s, "actual_reference_time", None) is None:
            record(
                Conflict(
                    conflict_type=ConflictType.BIOLOGICAL_TIME_VIOLATION,
                    severity=ConflictSeverity.CRITICAL,
                    title=f"Eksik Biyolojik Referans Saati: Gün {s.study_day} — {s.step_name}",
                    description=(
                        f"'{s.step_name}' birleşik hazırlık ve uygulama adımı tamamlandı olarak işaretlendi ancak "
                        f"biyolojik referans olay (enjeksiyon/uygulama) gerçekleşme saati girilmedi. Görev başlangıç "
                        f"saati (actual_start) referans saat olarak varsayılamaz; bağımlı 24/48/72. saat gözlem "
                        f"adımlarının doğrulanması için referans saat girilmelidir."
                    ),
                    study_id=study.id,
                    step_id=s.id,
                ),
                [s.id],
            )
            continue

        if getattr(s, "actual_reference_time", None) is not None:
            dev_min = s_bio.get("deviation_minutes", 0)
            if s_bio.get("exceeds_tolerance") and not s_bio.get("sd_revision_approved"):
                planned_ref_str = s_bio.get("planned_reference_time") or s.planned_start.isoformat()
                record(
                    Conflict(
                        conflict_type=ConflictType.BIOLOGICAL_TIME_VIOLATION,
                        severity=ConflictSeverity.CRITICAL,
                        title=f"Biyolojik Referans Saat Sapması: Gün {s.study_day} — {s.step_name}",
                        description=(
                            f"Planlanan biyolojik referans saati {_fmt(datetime.fromisoformat(planned_ref_str))} "
                            f"(tolerans ±{s.biological_tolerance_minutes} dk) iken gerçekleşen referans saati "
                            f"{_fmt(s.actual_reference_time)} olarak kaydedildi ({dev_min:+d} dk sapma). "
                            f"Onaylanmış plan saatleri sessizce değiştirilmedi; bağımlı adımlar için SD revizyonu gereklidir."
                        ),
                        study_id=study.id,
                        step_id=s.id,
                    ),
                    [s.id],
                )

            for dep_item in bio_info["dependent_by_ref_order"].get(s.step_order, []):
                dep_step = step_by_id.get(dep_item["step_id"])
                if dep_step is None or dep_step.status == StepStatus.CANCELLED:
                    continue
                exp_start = datetime.fromisoformat(dep_item["expected_start"])
                exp_end = datetime.fromisoformat(dep_item["expected_end"])
                dep_sched_dev = dep_item.get("schedule_deviation_minutes", dep_item["deviation_minutes"])

                # Henüz gerçekleşmemiş bağımlı adımda beklenen pencere kayması gözlemin kendi toleransını aşıyorsa
                if (
                    dep_step.status != StepStatus.COMPLETED
                    and getattr(dep_step, "actual_reference_time", None) is None
                    and dep_item.get("schedule_exceeds_dependent_tolerance")
                ):
                    record(
                        Conflict(
                            conflict_type=ConflictType.BIOLOGICAL_TIME_VIOLATION,
                            severity=ConflictSeverity.CRITICAL,
                            title=(
                                f"Bağımlı Biyolojik Adım Sapması (+{int(dep_item['offset_hours'])}s): "
                                f"Gün {dep_step.study_day} — {dep_step.step_name}"
                            ),
                            description=(
                                f"Referans adım {_fmt(s.actual_reference_time)} saatinde gerçekleştiği için "
                                f"+{int(dep_item['offset_hours'])}. saat bağımlı adımın beklenen biyolojik penceresi "
                                f"{_fmt(exp_start)}–{exp_end:%H:%M} oldu (planlanan: {_fmt(dep_step.planned_start)}–"
                                f"{dep_step.planned_end:%H:%M}, sapma: {dep_sched_dev:+d} dk, tolerans: "
                                f"±{dep_step.biological_tolerance_minutes} dk). {dep_item['revision_suggestion'] or ''}"
                            ),
                            study_id=study.id,
                            step_id=dep_step.id,
                        ),
                        [dep_step.id],
                    )

                if dep_sched_dev != 0 and dep_item.get("eligible_for_revision", True):
                    # 1) Beklenen yeni pencerede diğer çalışmalarla (planlanan ve beklenen) oluşan personel çakışmalarını denetle
                    for person in dep_step.assignees:
                        for ex in active_personnel_steps:
                            if person.id not in existing_assignees.get(ex.id, set()):
                                continue
                            other = ex.study
                            cand_windows = [(ex.planned_start, ex.planned_end)]
                            if ex.id in other_shifted_windows:
                                cand_windows.append(other_shifted_windows[ex.id])
                            for w_start, w_end in cand_windows:
                                ov = _overlap_minutes(exp_start, exp_end, w_start, w_end)
                                if ov <= 0:
                                    continue
                                pair_key = ("EXPECTED_SELF_OTHER", dep_step.id, ex.id, person.id, w_start)
                                if pair_key in recorded_overlap_keys:
                                    continue
                                recorded_overlap_keys.add(pair_key)
                                record(
                                    Conflict(
                                        conflict_type=ConflictType.PERSONNEL_OVERLAP,
                                        severity=ConflictSeverity.CRITICAL,
                                        title=(
                                            f"Personel Çakışması (Beklenen Biyolojik Pencere): "
                                            f"Gün {dep_step.study_day} — {person.full_name}"
                                        ),
                                        description=(
                                            f"Referans adım gecikmesi sonrası '{dep_step.step_name}' adımının beklenen "
                                            f"biyolojik penceresi ({_fmt(exp_start)}–{exp_end:%H:%M}), {person.full_name} "
                                            f"personelinin {other.study_code} ({other.status.value}) çalışmasındaki "
                                            f"'{ex.step_name}' göreviyle ({_fmt(w_start)}–{w_end:%H:%M}) "
                                            f"{ov} dk çakışıyor."
                                        ),
                                        study_id=study.id,
                                        step_id=dep_step.id,
                                        related_study_id=other.id,
                                    ),
                                    [dep_step.id],
                                )

                        # 2) Aynı çalışma içindeki (intra-study) diğer aktif adımlarla oluşan personel çakışmalarını denetle
                        for own_other in steps:
                            if (
                                own_other.id == dep_step.id
                                or own_other.status in (StepStatus.COMPLETED, StepStatus.CANCELLED)
                                or is_historical_unverified_step(own_other, study)
                            ):
                                continue
                            if not any(u.id == person.id for u in own_other.assignees):
                                continue
                            own_b = bio_info["by_step_id"].get(own_other.id) or {}
                            own_w_start = (
                                datetime.fromisoformat(own_b["expected_start"])
                                if own_b.get("expected_start")
                                else own_other.planned_start
                            )
                            own_w_end = (
                                datetime.fromisoformat(own_b["expected_end"])
                                if own_b.get("expected_end")
                                else own_other.planned_end
                            )
                            ov_intra = max(
                                _overlap_minutes(exp_start, exp_end, own_other.planned_start, own_other.planned_end),
                                _overlap_minutes(exp_start, exp_end, own_w_start, own_w_end),
                            )
                            if ov_intra <= 0:
                                continue
                            intra_key = (
                                "INTRA_STUDY",
                                min(dep_step.id, own_other.id),
                                max(dep_step.id, own_other.id),
                                person.id,
                            )
                            if intra_key in recorded_overlap_keys:
                                continue
                            recorded_overlap_keys.add(intra_key)
                            record(
                                Conflict(
                                    conflict_type=ConflictType.PERSONNEL_OVERLAP,
                                    severity=ConflictSeverity.CRITICAL,
                                    title=(
                                        f"Personel Çakışması (Çalışma İçi Beklenen Pencere): "
                                        f"Gün {dep_step.study_day} — {person.full_name}"
                                    ),
                                    description=(
                                        f"Referans adım gecikmesi sonrası '{dep_step.step_name}' adımının beklenen "
                                        f"biyolojik penceresi ({_fmt(exp_start)}–{exp_end:%H:%M}), aynı çalışmadaki "
                                        f"'{own_other.step_name}' adımıyla ({_fmt(own_other.planned_start)}–"
                                        f"{own_other.planned_end:%H:%M}) {ov_intra} dk çakışıyor."
                                    ),
                                    study_id=study.id,
                                    step_id=dep_step.id,
                                    related_study_id=study.id,
                                ),
                                [dep_step.id, own_other.id],
                            )

    # 6e) FAZ 8.1: Kafes kapasitesi (Fiziksel + Dr. Anoop esneklik) ve 24-72s uzun süreli cihaz (CO2 inkübatör / etüv) kapasitesi
    has_non_historical_step = (not steps) or any(
        s.status != StepStatus.COMPLETED and not is_historical_unverified_step(s, study)
        for s in steps
    )
    if has_non_historical_step:
        try:
            _ = build_capacity_report(db, study, template)
            for cap_conflict, cap_step_ids in evaluate_capacity_conflicts(db, study, steps, template):
                record(cap_conflict, cap_step_ids)
        except Exception as exc:
            anchor_id = steps[0].id if steps else None
            record(
                Conflict(
                    conflict_type=ConflictType.ROOM_CAPACITY_EXCEEDED,
                    severity=ConflictSeverity.CRITICAL,
                    title="Kapasite Doğrulanamadı: Oda ve Cihaz Kapasite Kontrolü Hatası",
                    description=(
                        f"Kafes veya uzun süreli cihaz kapasitesi kontrol edilirken teknik bir hata oluştuğu için "
                        f"kapasite uygunluğu doğrulanamadı ({exc}). Kapasite doğrulanmadan çalışma planı temiz "
                        f"(SCHEDULED_CLEAN) sayılamaz ve onaylanamaz."
                    ),
                    study_id=study.id,
                    step_id=anchor_id,
                ),
                [anchor_id] if anchor_id else [],
            )

    if persist_conflicts:
        db.flush()

    # 6d) KURAL 1: kişi-gün bazında 9 saat kontrolü (tüm çalışmalar dahil)
    person_days: Dict[Tuple[int, date], Tuple[User, List[int]]] = {}
    for step in steps:
        if step.status == StepStatus.COMPLETED or is_historical_unverified_step(step, study):
            continue
        for person in step.assignees:
            person_days.setdefault((person.id, step.planned_start.date()), (person, []))[1].append(step.id)
    for (_, day), (person, step_ids) in sorted(person_days.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        conflict = _build_workload_conflict(
            db,
            person,
            day,
            study.id,
            step_id=step_ids[0],
            study_steps_override=(study, steps),
            persist_conflict=persist_conflicts,
        )
        if conflict is not None:
            findings.append((conflict, step_ids))

    if persist_conflicts:
        db.flush()
    return findings


def revalidate_study_conflicts(
    db: Session,
    study: Study,
    preserve_weekend_approvals: bool = True,
) -> List[Tuple[Conflict, List[int]]]:
    """
    FAZ 6.4 (Madde 3 & 6): Çözüm uygulandıktan, görev durumu/referans saat güncellendikten veya
    ilişkili bir çalışma kaydırıldıktan sonra çakışma motorunu (eksik personel, hafta sonu,
    personel 9 saat / saat çakışması, 72s cihaz kapasitesi, biyolojik bağımlılık sapması) yeniden çalıştırır.
    """
    if study.status in (StudyStatus.COMPLETED, StudyStatus.CANCELLED):
        open_conflicts = (
            db.query(Conflict)
            .filter(Conflict.study_id == study.id, Conflict.is_resolved == False)  # noqa: E712
            .order_by(Conflict.id.asc())
            .all()
        )
        return [(c, [c.step_id] if c.step_id else []) for c in open_conflicts]

    now = datetime.utcnow()
    base_day0 = study.acclimatization_start_date or study.target_start_date or date.today()
    water_bath = seed_default_equipment(db, commit=False)
    template = get_template(getattr(study, "template_code", None) or DEFAULT_TEMPLATE_CODE, db=db)

    approved_wk_steps = set()
    if preserve_weekend_approvals:
        prev_approved = (
            db.query(Conflict)
            .filter(
                Conflict.study_id == study.id,
                Conflict.is_resolved == True,  # noqa: E712
                Conflict.conflict_type == ConflictType.BIOLOGICAL_TIME_VIOLATION,
                or_(
                    Conflict.resolution_notes.like("GLP Hafta Sonu Nöbetçi Personel Onayı%"),
                    Conflict.resolution_notes.like("Plan Onayı%"),
                ),
            )
            .all()
        )
        approved_wk_steps = {c.step_id for c in prev_approved if c.step_id is not None}

    # Mevcut açık çakışmaları yeniden doğrulama öncesi SUPERSEDED olarak kapat
    note = f"SUPERSEDED: {study.study_code} çakışma denetimi {now:%d.%m.%Y %H:%M} UTC itibarıyla yeniden çalıştırıldı."
    db.query(Conflict).filter(
        Conflict.study_id == study.id,
        Conflict.is_resolved == False,  # noqa: E712
    ).update(
        {Conflict.is_resolved: True, Conflict.resolved_at: now, Conflict.resolution_notes: note},
        synchronize_session="fetch",
    )
    db.flush()

    steps = (
        db.query(StudyStep)
        .options(selectinload(StudyStep.assignees))
        .filter(StudyStep.study_id == study.id, StudyStep.status != StepStatus.CANCELLED)
        .order_by(StudyStep.step_order)
        .all()
    )
    ext_usage = get_study_extraction_usage(study)
    for st in steps:
        is_ext = st.step_type == "Ekstraksiyon" or "Ekstraksiyon" in st.step_name
        if is_ext and (st.equipment_id is None or st.equipment_id == water_bath.id):
            st.equipment_id = water_bath.id if ext_usage["uses_water_bath"] else None
        if study.status == StudyStatus.DRAFT:
            st.study_day = (st.planned_start.date() - base_day0).days
    if study.status == StudyStatus.DRAFT and steps:
        study.target_end_date = max(s.planned_end for s in steps).date()

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

    findings = evaluate_study_conflicts(
        db=db,
        study=study,
        steps=steps,
        existing_steps=existing_steps,
        existing_assignees=existing_assignees,
        water_bath=water_bath,
        template=template,
        preserve_approved_weekend_step_ids=approved_wk_steps,
    )
    db.flush()
    return findings


def schedule_new_study(
    db: Session,
    study_id: int,
    acclimatization_start_date: date,
    template_code: str = DEFAULT_TEMPLATE_CODE,
    extraction_start_offset_days: Optional[int] = None,
    align_extraction_to_friday: bool = False,
    apply_restrictions: bool = True,
) -> Dict[str, Any]:
    """
    Seçilen şablonun adımlarını Gün 0 = acclimatization_start_date olacak şekilde dizer ve çakışmaları tespit eder.

    * Non-Destructive: APPROVED / IN_PROGRESS çalışmalara dokunulmaz; yalnızca DRAFT çalışma planlanabilir.
    * Diğer DRAFT çalışmalarla da kıyaslanır (onlar da değiştirilmez).
    * FAZ 6.4 (Madde 2B): Esnek (is_biological_fixed_time == False) adımlarda personelin o saatte başka görevi
      varsa aynı günkü ilk boş saat dilimine (örn. 11:00-13:00) otomatik yerleştirilir. Biyolojik kilitli
      adımlarda saat sabit tutulur; çakışma varsa aynı roldeki boştaki diğer yetkin personele atanır, yoksa
      PERSONNEL_OVERLAP üretilir.
    * FAZ 6.4 (Madde 5 & 6): Şablon süreleri/toleransları ve Su Banyosu kapasiteleri doğrudan veritabanından okunur;
      tüm adımların G kodları `(step_date - g0_date).days` ile birebir senkronize edilir.
    """
    study = db.query(Study).filter(Study.id == study_id).first()
    if not study:
        raise ValueError(f"ID={study_id} olan GLP çalışması bulunamadı.")
    if study.status != StudyStatus.DRAFT:
        raise PermissionError(
            f"'{study.study_code}' çalışması {study.status.value} durumundadır. Yalnızca DRAFT çalışmalar "
            f"(yeniden) planlanabilir; onaylanmış çalışmaların görev saatleri değiştirilemez (Non-Destructive kuralı)."
        )
    resolved_template_code = template_code or getattr(study, "template_code", None) or DEFAULT_TEMPLATE_CODE
    template = get_template(resolved_template_code, db=db)
    study.template_code = template.code
    # FAZ 8.1: Test Kısıtlama Takvimi — Gün 0 kısıtlı aralıktaysa restricted_until + 1 (ilk iş günü) tarihine otomatik ötele
    requested_g0 = acclimatization_start_date
    if apply_restrictions:
        shift = apply_restriction_shift(db, template.code, acclimatization_start_date)
    else:
        shift = {'g0': acclimatization_start_date, 'shifted': False, 'notice': None, 'restrictions': []}
    acclimatization_start_date = shift['g0']
    now = datetime.utcnow()
    water_bath = seed_default_equipment(db)

    if align_extraction_to_friday:
        min_off = extraction_start_offset_days if extraction_start_offset_days is not None else (study.extraction_start_offset_days or 0)
        offset_days = compute_friday_alignment_offset(acclimatization_start_date, min_off)
    elif extraction_start_offset_days is not None:
        offset_days = max(0, int(extraction_start_offset_days))
    else:
        offset_days = 0
    study.extraction_start_offset_days = offset_days
    study.acclimatization_start_date = acclimatization_start_date

    # 1) Bu taslağın eski planını kapat
    superseded_count, removed_steps = _supersede_previous_plan(db, study, now)
    # _supersede_previous_plan içindeki db.expire_all() bekleyen değişiklikleri attığı için Gün 0, ekstraksiyon ofseti ve
    # FAZ 8.1 otomatik tarih notunu burada (expire sonrası) yeniden yazıyoruz.
    study.template_code = template.code
    study.extraction_start_offset_days = offset_days
    study.acclimatization_start_date = acclimatization_start_date
    persist_auto_schedule_notice(study, shift)

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

    # 3) Şablon → baz zaman pencereleri (G4 ve sonrası biyolojik zincir olarak birlikte hareket eder)
    day0 = datetime.combine(acclimatization_start_date, time.min)
    planned: List[Tuple[TemplateStep, datetime, datetime, int]] = []
    for ts in template.steps:
        effective_day = ts.day + (offset_days if ts.day >= 4 else 0)
        start = day0 + timedelta(days=effective_day, hours=ts.start.hour, minutes=ts.start.minute)
        planned.append((ts, start, start + timedelta(minutes=ts.duration_minutes), effective_day))

    # 4) Rol → varsayılan personel
    planned_3 = [(ts, s, e) for ts, s, e, _ in planned]
    assignment, unfilled_roles = _assign_roles(db, study, planned_3, existing_steps, existing_assignees)

    # 5) Adımları oluştur (Esnek adımlarda boş saat dilimi arama + Biyolojik kilitli adımlarda yedek yetkin personel kontrolü)
    ext_usage = get_study_extraction_usage(study)
    new_steps: List[Tuple[TemplateStep, StudyStep]] = []
    for ts, start, end, _effective_day in planned:
        step_assignees: List[User] = []
        if ts.is_biological_fixed_time:
            for r in ts.roles:
                default_person = assignment.get(r)
                if default_person is None:
                    continue
                has_overlap = any(
                    default_person.id in existing_assignees.get(ex.id, set())
                    and _overlap_minutes(start, end, ex.planned_start, ex.planned_end) > 0
                    for ex in existing_steps
                )
                if has_overlap and r != UserRole.STUDY_DIRECTOR:
                    candidates = [
                        u for u in db.query(User).filter(User.role == r, User.is_active == True).order_by(User.id.asc()).all()  # noqa: E712
                        if is_eligible_lab_personnel(u)
                    ]
                    free_candidates = [
                        u for u in candidates
                        if all(
                            u.id not in existing_assignees.get(ex.id, set())
                            or _overlap_minutes(start, end, ex.planned_start, ex.planned_end) == 0
                            for ex in existing_steps
                        )
                    ]
                    if free_candidates:
                        chosen = min(
                            free_candidates,
                            key=lambda u: (calculate_personnel_workload(db, u.id, start.date())["total_minutes"], u.id),
                        )
                        step_assignees.append(chosen)
                        continue
                step_assignees.append(default_person)
        else:
            step_assignees = [assignment[r] for r in ts.roles if r in assignment]
            busy_pool = existing_steps + [s for _, s in new_steps]
            busy_map = dict(existing_assignees)
            for _, prior_s in new_steps:
                busy_map[prior_s.id] = {u.id for u in prior_s.assignees}
            start, end = _find_free_slot_for_flexible_step(
                target_day=start.date(),
                default_start=start,
                duration_minutes=ts.duration_minutes,
                assignees=step_assignees,
                busy_steps=busy_pool,
                busy_assignees_map=busy_map,
            )

        # FAZ 6.4 (Madde 6): G etiketi her zaman (step_date - g0_date).days ile birebir uyumlu
        computed_day = (start.date() - acclimatization_start_date).days
        is_extraction = ts.step_type == "Ekstraksiyon" or "Ekstraksiyon" in ts.name
        eq_id = water_bath.id if (is_extraction and ext_usage["uses_water_bath"]) else None
        step = StudyStep(
            study_id=study.id,
            step_order=ts.order,
            study_day=computed_day,
            step_name=ts.name,
            step_type=ts.step_type,
            planned_start=start,
            planned_end=end,
            is_biological_fixed_time=ts.is_biological_fixed_time,
            biological_tolerance_minutes=ts.tolerance_minutes,
            equipment_id=eq_id,
            status=StepStatus.PENDING,
        )
        step.assignees = step_assignees
        db.add(step)
        new_steps.append((ts, step))
    db.flush()

    # 6) Çakışma tespiti
    step_objs = [s for _, s in new_steps]
    findings = evaluate_study_conflicts(
        db=db,
        study=study,
        steps=step_objs,
        existing_steps=existing_steps,
        existing_assignees=existing_assignees,
        water_bath=water_bath,
        unfilled_roles=unfilled_roles,
        template=template,
    )

    # Diğer DRAFT çalışmaların bu çalışmayla ilişkili çakışmaları SUPERSEDED olduğu için onları da yeniden doğrula
    for other_study in others:
        if other_study.status == StudyStatus.DRAFT:
            revalidate_study_conflicts(db, other_study, preserve_weekend_approvals=True)

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
            "requested_day0": requested_g0.isoformat(),
            "auto_shifted": bool(shift.get('shifted')),
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
        steps=step_objs,
        existing_steps=existing_steps,
    )


def _safe_capacity_report(db: Session, study: Study, template: Any) -> Dict[str, Any]:
    """
    FAZ 8.1: Kafes + uzun süreli cihaz kapasite raporu.
    Hata durumunda sessizce None dönmez; 'verified: False' ve 'status: ERROR' içeren açık hata durumu döner.
    """
    try:
        report = build_capacity_report(db, study, template)
        if not isinstance(report, dict):
            raise RuntimeError("Geçersiz kapasite raporu formatı.")
        has_exceeded = bool(
            (report.get("cage") and report["cage"].get("level") == "EXCEEDED")
            or any(e.get("level") == "EXCEEDED" for e in (report.get("equipment") or []))
        )
        has_flex = bool(report.get("cage") and report["cage"].get("level") == "FLEX")
        report["verified"] = True
        report["status"] = "EXCEEDED" if has_exceeded else ("FLEX" if has_flex else "OK")
        report["error"] = None
        return report
    except Exception as exc:
        return {
            "status": "ERROR",
            "verified": False,
            "error": f"Kapasite doğrulanamadı: {exc}",
            "cage": None,
            "equipment": [],
            "first_free_g0": None,
        }


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

    cap_info = _safe_capacity_report(db, study, template)
    cap_unverified = not bool(cap_info and cap_info.get("verified") is True)
    active_findings = [(c, sids) for c, sids in findings if not c.is_resolved]
    critical_count = sum(1 for c, _ in active_findings if c.severity == ConflictSeverity.CRITICAL)
    warning_count = sum(1 for c, _ in active_findings if c.severity == ConflictSeverity.WARNING)
    cat_by_id = {
        item["id"]: item
        for item in enrich_conflicts_with_category(db, [c for c, _ in active_findings], include_resolutions=False)
    }
    bio_info = compute_biological_dependency_info(study, steps, template)
    bio_by_step = bio_info["by_step_id"]
    has_ext_step = any(
        (s.step_type == "Ekstraksiyon" or "Ekstraksiyon" in (s.step_name or ""))
        for s in steps
    ) or any(
        (ts.step_type == "Ekstraksiyon" or "Ekstraksiyon" in (ts.name or ""))
        for ts in (getattr(template, "steps", None) or [])
    )
    ext_usage = get_study_extraction_usage(study, has_extraction_step=has_ext_step)

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
        "extraction_info": ext_usage,
        "missing_extraction_info": ext_usage["missing_extraction_info"],
        "extraction_info_status": ext_usage["status"],
        "extraction_info_message": ext_usage["message"],
        "study_director_id": study.study_director_id,
        "study_director_name": study.study_director.full_name if study.study_director else None,
        "template": {"code": template.code, "standard": template.standard, "title": template.title},
        "acclimatization_start_date": acclimatization_start_date.isoformat(),
        "target_start_date": (study.target_start_date or acclimatization_start_date).isoformat(),
        "target_end_date": study.target_end_date.isoformat() if study.target_end_date else None,
        "protocol_approved_at": study.protocol_approved_at.isoformat() if study.protocol_approved_at else None,
        "extraction_start_offset_days": study.extraction_start_offset_days or 0,
        "auto_schedule_notice": get_auto_schedule_notice(study),
        "capacity_info": cap_info,
        "capacity_verified": not cap_unverified,
        "revision_proposals": bio_info["revision_proposals"],
        "ineligible_revision_steps": bio_info["ineligible_revision_steps"],
        "source_deviations": bio_info["source_deviations"],
        "biological_revisions": bio_info["biological_revisions"],
        "status": (
            "CONFLICTS_DETECTED"
            if (critical_count > 0 or cap_unverified)
            else ("WARNINGS_DETECTED" if warning_count > 0 else "SCHEDULED_CLEAN")
        ),
        "can_approve": (
            study.status == StudyStatus.DRAFT
            and critical_count == 0
            and not cap_unverified
            and len(steps) > 0
        ),
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
                "conflict_category": (cat_by_id.get(c.id) or {}).get("conflict_category", "CONFIRMED_CONFLICT"),
                "missing_info_badges": (cat_by_id.get(c.id) or {}).get("missing_info_badges", []),
                "missing_info_tags": (cat_by_id.get(c.id) or {}).get("missing_info_tags", []),
                "missing_info_codes": (cat_by_id.get(c.id) or {}).get("missing_info_codes", []),
                "study_code": study.study_code,
                "sample_id": (cat_by_id.get(c.id) or {}).get("sample_id"),
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
                "actual_start": s.actual_start.isoformat() if s.actual_start else None,
                "actual_end": s.actual_end.isoformat() if s.actual_end else None,
                "actual_reference_time": s.actual_reference_time.isoformat() if getattr(s, "actual_reference_time", None) else None,
                "planned_reference_time": (bio_by_step.get(s.id) or {}).get("planned_reference_time"),
                "requires_reference_time": (bio_by_step.get(s.id) or {}).get("requires_reference_time", False),
                "reference_time_role": (bio_by_step.get(s.id) or {}).get("reference_time_role"),
                "reference_time_label": (bio_by_step.get(s.id) or {}).get("reference_time_label"),
                "expected_start": (bio_by_step.get(s.id) or {}).get("expected_start", s.planned_start.isoformat()),
                "expected_end": (bio_by_step.get(s.id) or {}).get("expected_end", s.planned_end.isoformat()),
                "expected_reference_time": (bio_by_step.get(s.id) or {}).get("expected_reference_time"),
                "reference_deviation_minutes": (bio_by_step.get(s.id) or {}).get("deviation_minutes", 0),
                "exceeds_biological_tolerance": (bio_by_step.get(s.id) or {}).get("exceeds_tolerance", False),
                "requires_plan_revision": (bio_by_step.get(s.id) or {}).get("requires_revision", False),
                "revision_suggestion": (bio_by_step.get(s.id) or {}).get("revision_suggestion"),
                "eligible_for_revision": (bio_by_step.get(s.id) or {}).get("eligible_for_revision", False),
                "ineligible_reason": (bio_by_step.get(s.id) or {}).get("ineligible_reason"),
                "proposed_study_day": (bio_by_step.get(s.id) or {}).get("proposed_study_day", s.study_day),
                "expected_study_day": (bio_by_step.get(s.id) or {}).get("expected_study_day", s.study_day),
                "day_changed": (bio_by_step.get(s.id) or {}).get("day_changed", False),
                "expected_day_changed": (bio_by_step.get(s.id) or {}).get("expected_day_changed", False),
                "sd_revision_approved": (bio_by_step.get(s.id) or {}).get("sd_revision_approved", False),
                "sd_revision_decision": (bio_by_step.get(s.id) or {}).get("sd_revision_decision"),
                "duration_minutes": s.duration_minutes,
                "is_biological_fixed_time": s.is_biological_fixed_time,
                "biological_tolerance_minutes": s.biological_tolerance_minutes,
                "equipment_id": s.equipment_id,
                "status": s.status.value if s.status else "PENDING",
                "assignees": [person_dict(u) for u in s.assignees],
            }
            for s in steps
        ],
    }


def get_all_studies_calendar_details(
    db: Session,
    studies: List[Study],
    all_steps_orm: List[StudyStep],
) -> List[Dict[str, Any]]:
    """
    FAZ 8.4 — Toplu Master Takvim (/api/v1/planning/calendar) için N+1 sorgusu yapmadan
    tüm çalışmaların adımlarını ve açık çakışmalarını tek seferde bellekte birleştirir.
    """
    from app.services.templates import TEMPLATES

    water_bath = seed_default_equipment(db)
    active_techs = [
        u for u in db.query(User).filter(User.role == UserRole.TECHNICIAN, User.is_active == True).order_by(User.id.asc()).all()  # noqa: E712
        if is_eligible_lab_personnel(u)
    ]
    templates_map = {code: get_template(code, db=db) for code in TEMPLATES}
    default_tpl = templates_map.get(DEFAULT_TEMPLATE_CODE) or get_template(DEFAULT_TEMPLATE_CODE, db=db)

    steps_by_study: Dict[int, List[StudyStep]] = {s.id: [] for s in studies}
    step_by_id: Dict[int, StudyStep] = {}
    for st in all_steps_orm:
        step_by_id[st.id] = st
        if st.study_id in steps_by_study:
            steps_by_study[st.study_id].append(st)
    for sid in steps_by_study:
        steps_by_study[sid].sort(key=lambda x: x.step_order)

    open_conflicts = (
        db.query(Conflict)
        .filter(Conflict.is_resolved == False)  # noqa: E712
        .order_by(Conflict.id.asc())
        .all()
    )
    cat_by_id = {
        item["id"]: item
        for item in enrich_conflicts_with_category(db, open_conflicts, include_resolutions=False)
    }
    conflicts_by_study: Dict[int, List[Conflict]] = {s.id: [] for s in studies}
    for c in open_conflicts:
        if c.study_id in conflicts_by_study:
            conflicts_by_study[c.study_id].append(c)

    locked_codes = [s.study_code for s in studies if s.status in LOCKED_STUDY_STATUSES]
    draft_codes = [s.study_code for s in studies if s.status == StudyStatus.DRAFT]

    def person_dict(u: User) -> Dict[str, Any]:
        return {"id": u.id, "full_name": u.full_name, "role": u.role.value if hasattr(u.role, "value") else str(u.role)}

    results: List[Dict[str, Any]] = []
    for study in studies:
        tpl_code = getattr(study, "template_code", None) or DEFAULT_TEMPLATE_CODE
        template = templates_map.get(tpl_code) or default_tpl
        base_day0 = study.acclimatization_start_date or study.target_start_date or date.today()
        st_steps = steps_by_study.get(study.id, [])
        st_conflicts = conflicts_by_study.get(study.id, [])
        critical_count = sum(1 for c in st_conflicts if c.severity == ConflictSeverity.CRITICAL)
        warning_count = sum(1 for c in st_conflicts if c.severity == ConflictSeverity.WARNING)
        bio_info = compute_biological_dependency_info(study, st_steps, template)
        bio_by_step = bio_info["by_step_id"]

        results.append(
            {
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
                "acclimatization_start_date": base_day0.isoformat(),
                "target_start_date": (study.target_start_date or base_day0).isoformat(),
                "target_end_date": study.target_end_date.isoformat() if study.target_end_date else None,
                "protocol_approved_at": study.protocol_approved_at.isoformat() if study.protocol_approved_at else None,
                "extraction_start_offset_days": study.extraction_start_offset_days or 0,
                "auto_schedule_notice": get_auto_schedule_notice(study),
                "capacity_info": None,
                "revision_proposals": bio_info["revision_proposals"],
                "ineligible_revision_steps": bio_info["ineligible_revision_steps"],
                "source_deviations": bio_info["source_deviations"],
                "biological_revisions": bio_info["biological_revisions"],
                "status": (
                    "CONFLICTS_DETECTED"
                    if critical_count > 0
                    else ("WARNINGS_DETECTED" if warning_count > 0 else "SCHEDULED_CLEAN")
                ),
                "can_approve": study.status == StudyStatus.DRAFT and critical_count == 0 and len(st_steps) > 0,
                "total_conflicts": len(st_conflicts),
                "critical_conflicts": critical_count,
                "warning_conflicts": warning_count,
                "superseded_conflicts": 0,
                "conflicts": [
                    {
                        "id": c.id,
                        "type": c.conflict_type.value,
                        "severity": c.severity.value,
                        "title": c.title,
                        "description": c.description,
                        "step_id": c.step_id,
                        "step_ids": [c.step_id] if c.step_id else [],
                        "related_study_id": c.related_study_id,
                        "conflict_category": (cat_by_id.get(c.id) or {}).get("conflict_category", "CONFIRMED_CONFLICT"),
                        "missing_info_badges": (cat_by_id.get(c.id) or {}).get("missing_info_badges", []),
                        "missing_info_tags": (cat_by_id.get(c.id) or {}).get("missing_info_tags", []),
                        "missing_info_codes": (cat_by_id.get(c.id) or {}).get("missing_info_codes", []),
                        "study_code": study.study_code,
                        "sample_id": (cat_by_id.get(c.id) or {}).get("sample_id"),
                        "resolutions": build_conflict_resolutions(
                            db,
                            c,
                            study=study,
                            existing_steps=all_steps_orm,
                            fast_mode=True,
                            active_techs=active_techs,
                            water_bath=water_bath,
                            step_by_id=step_by_id,
                        ),
                    }
                    for c in st_conflicts
                ],
                "untouched_approved_studies": [c for c in locked_codes if c != study.study_code],
                "compared_draft_studies": [c for c in draft_codes if c != study.study_code],
                "total_new_steps": len(st_steps),
                "steps": [
                    {
                        "id": s.id,
                        "step_order": s.step_order,
                        "study_day": s.study_day,
                        "step_name": s.step_name,
                        "step_type": s.step_type,
                        "planned_start": s.planned_start.isoformat(),
                        "planned_end": s.planned_end.isoformat(),
                        "actual_start": s.actual_start.isoformat() if s.actual_start else None,
                        "actual_end": s.actual_end.isoformat() if s.actual_end else None,
                        "actual_reference_time": s.actual_reference_time.isoformat() if getattr(s, "actual_reference_time", None) else None,
                        "planned_reference_time": (bio_by_step.get(s.id) or {}).get("planned_reference_time"),
                        "requires_reference_time": (bio_by_step.get(s.id) or {}).get("requires_reference_time", False),
                        "reference_time_role": (bio_by_step.get(s.id) or {}).get("reference_time_role"),
                        "reference_time_label": (bio_by_step.get(s.id) or {}).get("reference_time_label"),
                        "expected_start": (bio_by_step.get(s.id) or {}).get("expected_start", s.planned_start.isoformat()),
                        "expected_end": (bio_by_step.get(s.id) or {}).get("expected_end", s.planned_end.isoformat()),
                        "expected_reference_time": (bio_by_step.get(s.id) or {}).get("expected_reference_time"),
                        "reference_deviation_minutes": (bio_by_step.get(s.id) or {}).get("deviation_minutes", 0),
                        "exceeds_biological_tolerance": (bio_by_step.get(s.id) or {}).get("exceeds_tolerance", False),
                        "requires_plan_revision": (bio_by_step.get(s.id) or {}).get("requires_revision", False),
                        "revision_suggestion": (bio_by_step.get(s.id) or {}).get("revision_suggestion"),
                        "eligible_for_revision": (bio_by_step.get(s.id) or {}).get("eligible_for_revision", False),
                        "ineligible_reason": (bio_by_step.get(s.id) or {}).get("ineligible_reason"),
                        "proposed_study_day": (bio_by_step.get(s.id) or {}).get("proposed_study_day", s.study_day),
                        "expected_study_day": (bio_by_step.get(s.id) or {}).get("expected_study_day", s.study_day),
                        "day_changed": (bio_by_step.get(s.id) or {}).get("day_changed", False),
                        "expected_day_changed": (bio_by_step.get(s.id) or {}).get("expected_day_changed", False),
                        "sd_revision_approved": (bio_by_step.get(s.id) or {}).get("sd_revision_approved", False),
                        "sd_revision_decision": (bio_by_step.get(s.id) or {}).get("sd_revision_decision"),
                        "duration_minutes": s.duration_minutes,
                        "is_biological_fixed_time": s.is_biological_fixed_time,
                        "biological_tolerance_minutes": s.biological_tolerance_minutes,
                        "equipment_id": s.equipment_id,
                        "status": s.status.value if s.status else "PENDING",
                        "assignees": [person_dict(u) for u in s.assignees],
                    }
                    for s in st_steps
                ],
            }
        )
    return results


def get_study_schedule_detail(db: Session, study: Study) -> Dict[str, Any]:
    """
    FAZ 6.3 — Veritabanında kayıtlı (DRAFT, APPROVED veya IN_PROGRESS) bir çalışmanın mevcut adımlarını,
    açık çakışmalarını ve tek tık çözüm önerilerini yeniden planlama yapmadan (salt-okunur) döner.
    """
    template = get_template(getattr(study, "template_code", None) or DEFAULT_TEMPLATE_CODE, db=db)
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


def _get_preview_snapshot_key(db: Session, study: Study) -> Tuple[int, int, str]:
    bind = db.get_bind()
    return (id(bind), study.id, study.study_code or "")


def _compute_proposed_target_end_date(
    study: Study,
    steps: List[StudyStep],
    proposals: List[Dict[str, Any]],
) -> Optional[date]:
    prop_by_id = {p.get("step_id"): p for p in proposals if p.get("step_id") is not None}
    end_dates: List[date] = []
    for s in steps:
        p = prop_by_id.get(s.id)
        exp_end_str = (p.get("expected_end") or p.get("proposed_planned_end")) if p else None
        if exp_end_str:
            end_dates.append(datetime.fromisoformat(exp_end_str).date())
        elif s.planned_end is not None:
            end_dates.append(s.planned_end.date())
    return max(end_dates, default=study.target_end_date)


def _build_biological_revision_snapshot(
    study: Study,
    steps: List[StudyStep],
    template: Any = None,
    proposals: Optional[List[Dict[str, Any]]] = None,
    proposed_target_end_date: Optional[date] = None,
) -> Dict[str, Any]:
    import hashlib

    resolved_tpl_code = resolve_template_code(getattr(study, "template_code", None) or DEFAULT_TEMPLATE_CODE)
    if template is None:
        try:
            template = get_template(resolved_tpl_code, db=None)
        except Exception:
            template = None
    if proposals is None:
        bio_info = compute_biological_dependency_info(study, steps, template)
        proposals = list(bio_info["revision_proposals"])
    if proposed_target_end_date is None:
        proposed_target_end_date = _compute_proposed_target_end_date(study, steps, proposals)

    raw_meta = study.dossier_metadata if isinstance(study.dossier_metadata, dict) else {}
    rev_count = len(raw_meta.get("biological_revisions") or [])
    acc_iso = study.acclimatization_start_date.isoformat() if study.acclimatization_start_date else ""
    tstart_iso = study.target_start_date.isoformat() if study.target_start_date else ""
    base_day0 = (
        study.acclimatization_start_date
        or study.target_start_date
        or (steps[0].planned_start.date() if steps and steps[0].planned_start else None)
    )
    day0_iso = base_day0.isoformat() if base_day0 else ""
    end_iso = study.target_end_date.isoformat() if study.target_end_date else ""
    prop_end_iso = proposed_target_end_date.isoformat() if proposed_target_end_date else ""
    tpl_code_val = getattr(template, "code", None) or resolved_tpl_code

    parts = [
        f"study:{study.id}:{study.status.value if hasattr(study.status, 'value') else study.status}:{tpl_code_val}:{day0_iso}:{acc_iso}:{tstart_iso}:{end_iso}:{prop_end_iso}:{rev_count}",
    ]
    step_snapshots: Dict[int, Dict[str, Any]] = {}
    source_refs: Dict[int, str] = {}
    for s in sorted(steps, key=lambda x: (x.step_order, x.id)):
        st_val = s.status.value if hasattr(s.status, "value") else str(s.status or "PENDING")
        p_start = s.planned_start.isoformat() if s.planned_start else ""
        p_end = s.planned_end.isoformat() if s.planned_end else ""
        a_start = s.actual_start.isoformat() if s.actual_start else ""
        a_end = s.actual_end.isoformat() if s.actual_end else ""
        a_ref = s.actual_reference_time.isoformat() if getattr(s, "actual_reference_time", None) else ""
        ass_str = ",".join(str(uid) for uid in sorted(s.assignee_ids))
        parts.append(
            f"step:{s.id}:{s.step_order}:{s.study_day}:{st_val}:{p_start}:{p_end}:{a_start}:{a_end}:{a_ref}:{s.equipment_id}:{ass_str}"
        )
        if a_ref:
            source_refs[s.step_order] = a_ref
        step_snapshots[s.id] = {
            "step_id": s.id,
            "step_order": s.step_order,
            "study_day": s.study_day,
            "status": st_val,
            "planned_start": p_start or None,
            "planned_end": p_end or None,
            "actual_start": a_start or None,
            "actual_end": a_end or None,
            "actual_reference_time": a_ref or None,
        }

    proposal_snapshots: List[Dict[str, Any]] = []
    for p in sorted(proposals, key=lambda x: (int(x.get("step_order") or 0), int(x.get("step_id") or 0))):
        p_sid = p.get("step_id")
        p_ord = p.get("step_order")
        p_start = p.get("expected_start") or p.get("proposed_planned_start") or ""
        p_end = p.get("expected_end") or p.get("proposed_planned_end") or ""
        p_day = p.get("proposed_study_day")
        parts.append(f"proposal:{p_sid}:{p_ord}:{p_start}:{p_end}:{p_day}")
        proposal_snapshots.append(
            {
                "step_id": p_sid,
                "step_order": p_ord,
                "expected_start": p_start or None,
                "expected_end": p_end or None,
                "proposed_study_day": p_day,
            }
        )

    token = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]
    return {
        "preview_token": token,
        "study_id": study.id,
        "study_status": study.status.value if hasattr(study.status, "value") else str(study.status),
        "template_code": tpl_code_val,
        "acclimatization_start_date": day0_iso or None,
        "current_target_end_date": end_iso or None,
        "proposed_target_end_date": prop_end_iso or None,
        "source_references": source_refs,
        "steps": step_snapshots,
        "proposals": proposal_snapshots,
    }


def _is_non_blocking_past_observation_violation(conflict: Conflict, revised_step_ids: set) -> bool:
    """
    Revize edilmeyen (daha önce gerçekleşmiş veya uygun olmayan) adımların geçmiş biyolojik
    pencere/eksik saat bulguları korunur, ancak kalan uygun PENDING adımların yeni saatlerindeki
    revizyonunu engellemez.
    """
    return bool(
        conflict.conflict_type == ConflictType.BIOLOGICAL_TIME_VIOLATION
        and conflict.step_id not in revised_step_ids
        and (
            "Gerçekleşen Gözlem Biyolojik Pencere İhlali" in (conflict.title or "")
            or "Eksik Biyolojik Gözlem Saati" in (conflict.title or "")
            or "Eksik Biyolojik Referans Saati" in (conflict.title or "")
            or "Bağımlı Biyolojik Adım Sapması" in (conflict.title or "")
        )
    )


def _evaluate_revision_candidate_obstacles(
    db: Session,
    study: Study,
    steps: List[StudyStep],
    proposals: List[Dict[str, Any]],
    source_deviations: List[Dict[str, Any]],
    template: Any,
) -> Dict[str, Any]:
    """
    Önerilen biyolojik revizyon saatlerini veritabanına hiçbir yazma (flush/commit/rollback) yapmadan
    ve çağıranın transaction durumunu kapatmadan (`no_autoflush` + bellek geri yükleme ile)
    simüle eder; personel çakışmalarını, 9 saat iş yükü aşımını, cihaz/oda/kafes kapasitesini
    ve eksik rol atamalarını döner.
    """
    import copy
    from sqlalchemy.orm.attributes import set_committed_value

    if isinstance(template, date) or template is None or not hasattr(template, "steps"):
        template = get_template(
            getattr(study, "template_code", None) or DEFAULT_TEMPLATE_CODE,
            db=db,
            commit_defaults=False,
        )

    orig_dirty = set(db.dirty)
    orig_target_end_date = study.target_end_date
    orig_meta_ref = study.dossier_metadata
    orig_meta = copy.deepcopy(study.dossier_metadata) if isinstance(study.dossier_metadata, dict) else study.dossier_metadata
    orig_step_state = {
        s.id: (s.planned_start, s.planned_end, s.study_day)
        for s in steps
    }
    step_by_id = {s.id: s for s in steps}
    revised_step_ids = {p["step_id"] for p in proposals}

    blocking_conflicts: List[Dict[str, Any]] = []
    warning_conflicts: List[Dict[str, Any]] = []
    cap_info: Dict[str, Any] = {}
    cap_verified = False
    proposed_end_date = orig_target_end_date

    orig_db_commit = db.commit
    orig_db_flush = db.flush
    orig_db_rollback = db.rollback

    def _forbid_commit(*_args, **_kwargs):
        raise RuntimeError("Önizleme simülasyonu sırasında db.commit() çağrılmasına izin verilmez.")

    def _forbid_flush(*_args, **_kwargs):
        raise RuntimeError("Önizleme simülasyonu sırasında db.flush() çağrılmasına izin verilmez.")

    def _forbid_rollback(*_args, **_kwargs):
        raise RuntimeError("Önizleme simülasyonu sırasında db.rollback() çağrılmasına izin verilmez.")

    with db.no_autoflush:
        db.commit = _forbid_commit  # type: ignore[method-assign]
        db.flush = _forbid_flush  # type: ignore[method-assign]
        db.rollback = _forbid_rollback  # type: ignore[method-assign]
        try:
            for prop in proposals:
                st_obj = step_by_id.get(prop["step_id"])
                if st_obj is not None:
                    sim_ps = datetime.fromisoformat(prop["expected_start"])
                    sim_pe = datetime.fromisoformat(prop["expected_end"])
                    sim_sd = int(prop["proposed_study_day"])
                    if st_obj in orig_dirty:
                        st_obj.planned_start = sim_ps
                        st_obj.planned_end = sim_pe
                        st_obj.study_day = sim_sd
                    else:
                        set_committed_value(st_obj, "planned_start", sim_ps)
                        set_committed_value(st_obj, "planned_end", sim_pe)
                        set_committed_value(st_obj, "study_day", sim_sd)

            if steps:
                proposed_end_date = max(
                    (s.planned_end.date() for s in steps if s.planned_end),
                    default=orig_target_end_date,
                )
                if study in orig_dirty:
                    study.target_end_date = proposed_end_date
                else:
                    set_committed_value(study, "target_end_date", proposed_end_date)

            sim_meta = copy.deepcopy(orig_meta) if isinstance(orig_meta, dict) else {}
            sim_revs = list(sim_meta.get("biological_revisions") or [])
            if isinstance(source_deviations, list):
                for src_dev in source_deviations:
                    if isinstance(src_dev, dict) and src_dev.get("actual_reference_time"):
                        sim_revs.append(
                            {
                                "source_step_id": src_dev.get("step_id") or src_dev.get("source_step_id"),
                                "source_step_order": src_dev.get("step_order") or src_dev.get("source_step_order"),
                                "source_actual_reference_time": src_dev.get("actual_reference_time"),
                                "approved_for_actual_reference_time": src_dev.get("actual_reference_time"),
                            }
                        )
            sim_meta["biological_revisions"] = sim_revs
            if study in orig_dirty:
                study.dossier_metadata = sim_meta
            else:
                set_committed_value(study, "dossier_metadata", sim_meta)

            cap_info = _safe_capacity_report(db, study, template)
            cap_verified = bool(cap_info and cap_info.get("verified") is True)

            water_bath = seed_default_equipment(db, commit=False)
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

            prev_approved = (
                db.query(Conflict)
                .filter(
                    Conflict.study_id == study.id,
                    Conflict.is_resolved == True,  # noqa: E712
                    Conflict.conflict_type == ConflictType.BIOLOGICAL_TIME_VIOLATION,
                    or_(
                        Conflict.resolution_notes.like("GLP Hafta Sonu Nöbetçi Personel Onayı%"),
                        Conflict.resolution_notes.like("Plan Onayı%"),
                    ),
                )
                .all()
            )
            approved_wk_steps = {c.step_id for c in prev_approved if c.step_id is not None}

            sim_findings = evaluate_study_conflicts(
                db=db,
                study=study,
                steps=steps,
                existing_steps=existing_steps,
                existing_assignees=existing_assignees,
                water_bath=water_bath,
                template=template,
                preserve_approved_weekend_step_ids=approved_wk_steps,
                persist_conflicts=False,
            )

            for c, sids in sim_findings:
                c_dict = {
                    "type": c.conflict_type.value if hasattr(c.conflict_type, "value") else str(c.conflict_type),
                    "severity": c.severity.value if hasattr(c.severity, "value") else str(c.severity),
                    "title": c.title,
                    "description": c.description,
                    "step_id": c.step_id,
                    "step_ids": sids,
                    "related_study_id": c.related_study_id,
                }
                if c.severity == ConflictSeverity.CRITICAL:
                    if not _is_non_blocking_past_observation_violation(c, revised_step_ids):
                        blocking_conflicts.append(c_dict)
                else:
                    warning_conflicts.append(c_dict)

            if not cap_verified:
                blocking_conflicts.append(
                    {
                        "type": ConflictType.ROOM_CAPACITY_EXCEEDED.value,
                        "severity": ConflictSeverity.CRITICAL.value,
                        "title": "Kapasite Doğrulama Hatası",
                        "description": (cap_info or {}).get("error")
                        or "Oda/kafes ve uzun süreli cihaz kapasitesi doğrulanamadı.",
                        "step_id": None,
                        "step_ids": [],
                        "related_study_id": None,
                    }
                )
        finally:
            db.commit = orig_db_commit  # type: ignore[method-assign]
            db.flush = orig_db_flush  # type: ignore[method-assign]
            db.rollback = orig_db_rollback  # type: ignore[method-assign]
            if study in orig_dirty:
                study.target_end_date = orig_target_end_date
                study.dossier_metadata = orig_meta_ref
            else:
                set_committed_value(study, "target_end_date", orig_target_end_date)
                set_committed_value(study, "dossier_metadata", orig_meta_ref)
            for s in steps:
                if s.id in orig_step_state:
                    orig_ps, orig_pe, orig_sd = orig_step_state[s.id]
                    if s in orig_dirty:
                        s.planned_start, s.planned_end, s.study_day = orig_ps, orig_pe, orig_sd
                    else:
                        set_committed_value(s, "planned_start", orig_ps)
                        set_committed_value(s, "planned_end", orig_pe)
                        set_committed_value(s, "study_day", orig_sd)

    return {
        "blocking_conflicts": blocking_conflicts,
        "warning_conflicts": warning_conflicts,
        "capacity_info": cap_info,
        "capacity_verified": cap_verified,
        "proposed_target_end_date": proposed_end_date,
    }


def preview_biological_revision(db: Session, study_id: int) -> Dict[str, Any]:
    """
    SD Onaylı Biyolojik Plan Revizyonu — Salt-Okunur Önizleme.
    Hiçbir adımın planlanan saatini veya çalışma durumunu değiştirmez,
    çağıranın bekleyen işlemlerini kaydetmez (commit/flush) veya geri almaz (rollback).
    """
    orig_db_commit = db.commit
    orig_db_flush = db.flush
    orig_db_rollback = db.rollback

    def _forbid_commit(*_args, **_kwargs):
        raise RuntimeError("Biyolojik revizyon önizlemesi sırasında db.commit() çağrılmasına izin verilmez.")

    def _forbid_flush(*_args, **_kwargs):
        raise RuntimeError("Biyolojik revizyon önizlemesi sırasında db.flush() çağrılmasına izin verilmez.")

    def _forbid_rollback(*_args, **_kwargs):
        raise RuntimeError("Biyolojik revizyon önizlemesi sırasında db.rollback() çağrılmasına izin verilmez.")

    with db.no_autoflush:
        db.commit = _forbid_commit  # type: ignore[method-assign]
        db.flush = _forbid_flush  # type: ignore[method-assign]
        db.rollback = _forbid_rollback  # type: ignore[method-assign]
        try:
            study = db.query(Study).filter(Study.id == study_id).first()
            if not study:
                raise LookupError(f"ID={study_id} olan çalışma bulunamadı.")

            steps = (
                db.query(StudyStep)
                .options(selectinload(StudyStep.assignees))
                .filter(StudyStep.study_id == study.id, StudyStep.status != StepStatus.CANCELLED)
                .order_by(StudyStep.step_order.asc())
                .all()
            )
            cancelled_steps = (
                db.query(StudyStep)
                .filter(StudyStep.study_id == study.id, StudyStep.status == StepStatus.CANCELLED)
                .order_by(StudyStep.step_order.asc())
                .all()
            )

            template = get_template(
                getattr(study, "template_code", None) or DEFAULT_TEMPLATE_CODE,
                db=db,
                commit_defaults=False,
            )
            base_day0 = study.acclimatization_start_date or study.target_start_date or date.today()
            bio_info = compute_biological_dependency_info(study, steps, template)

            proposals = list(bio_info["revision_proposals"])
            ineligible_steps = list(bio_info["ineligible_revision_steps"])
            source_deviations = list(bio_info["source_deviations"])
            biological_revisions = list(bio_info["biological_revisions"])

            # İptal edilmiş (CANCELLED) bağımlı biyolojik adımlar varsa onları da uygun olmayan adımlar listesine ekle
            ts_by_order = {ts.order: ts for ts in (getattr(template, "steps", None) or [])}
            step_by_order = {s.step_order: s for s in steps}
            for cs in cancelled_steps:
                ts = ts_by_order.get(cs.step_order)
                ref_order = getattr(ts, "reference_step_order", None) if ts else None
                offset_hours = getattr(ts, "reference_offset_hours", None) if ts else None
                if ref_order is not None and offset_hours is not None:
                    ref_step = step_by_order.get(ref_order)
                    has_ref = bool(ref_step and getattr(ref_step, "actual_reference_time", None) is not None)
                    _elig_ok, elig_reason = check_step_revision_eligibility(cs, 0, has_source_actual_reference=has_ref)
                    ineligible_steps.append(
                        {
                            "step_id": cs.id,
                            "step_order": cs.step_order,
                            "step_name": cs.step_name,
                            "status": StepStatus.CANCELLED.value,
                            "current_study_day": cs.study_day,
                            "proposed_study_day": cs.study_day,
                            "day_changed": False,
                            "current_planned_start": cs.planned_start.isoformat() if cs.planned_start else None,
                            "current_planned_end": cs.planned_end.isoformat() if cs.planned_end else None,
                            "expected_start": cs.planned_start.isoformat() if cs.planned_start else None,
                            "expected_end": cs.planned_end.isoformat() if cs.planned_end else None,
                            "actual_start": cs.actual_start.isoformat() if cs.actual_start else None,
                            "actual_end": cs.actual_end.isoformat() if cs.actual_end else None,
                            "actual_reference_time": (
                                cs.actual_reference_time.isoformat() if getattr(cs, "actual_reference_time", None) else None
                            ),
                            "reference_step_id": ref_step.id if ref_step else None,
                            "reference_step_order": ref_order,
                            "reference_step_name": ref_step.step_name if ref_step else None,
                            "actual_source_reference_time": (
                                ref_step.actual_reference_time.isoformat()
                                if (ref_step and getattr(ref_step, "actual_reference_time", None))
                                else None
                            ),
                            "deviation_minutes": 0,
                            "schedule_deviation_minutes": 0,
                            "biological_tolerance_minutes": int(cs.biological_tolerance_minutes or 0),
                            "eligible": False,
                            "ineligible_reason": elig_reason,
                        }
                    )

            sim_result = _evaluate_revision_candidate_obstacles(
                db=db,
                study=study,
                steps=steps,
                proposals=proposals,
                source_deviations=source_deviations,
                template=template,
            )

            blocking_conflicts = sim_result["blocking_conflicts"]
            warning_conflicts = sim_result["warning_conflicts"]
            cap_info = sim_result["capacity_info"]
            cap_verified = sim_result["capacity_verified"]
            proposed_end_date = sim_result["proposed_target_end_date"]

            snapshot = _build_biological_revision_snapshot(
                study,
                steps,
                template=template,
                proposals=proposals,
                proposed_target_end_date=proposed_end_date,
            )
            _LATEST_PREVIEW_SNAPSHOTS[_get_preview_snapshot_key(db, study)] = snapshot

            all_dependent_steps = sorted(
                proposals + ineligible_steps,
                key=lambda item: (item.get("step_order") or 0, item.get("step_id") or 0),
            )

            primary_source = source_deviations[0] if source_deviations else None
            has_blocking = bool(len(blocking_conflicts) > 0 or not cap_verified)
            study_status_eligible = study.status in (StudyStatus.APPROVED, StudyStatus.IN_PROGRESS)
            can_approve = bool(study_status_eligible and len(proposals) > 0 and not has_blocking)

            status_reason = None
            if not study_status_eligible:
                status_reason = f"Biyolojik plan revizyonu yalnızca APPROVED veya IN_PROGRESS durumundaki çalışmalarda uygulanabilir (Mevcut: {study.status.value})."
            elif not primary_source or not primary_source.get("actual_reference_time"):
                status_reason = "Henüz kaydedilmiş bir gerçek biyolojik referans saati bulunmamaktadır."
            elif len(proposals) == 0:
                if primary_source.get("sd_revision_approved"):
                    status_reason = "Bu biyolojik referans saati için uygun adımlar zaten revize edilerek onaylanmıştır."
                else:
                    status_reason = "Güncellenmeye uygun (PENDING ve gerçekleşen verisi olmayan) bekleyen bağımlı adım bulunmamaktadır."
            elif has_blocking:
                status_reason = f"Önerilen yeni saatlerde {len(blocking_conflicts)} kritik engel tespit edildiği için revizyon onaylanamaz."

            return {
                "study_id": study.id,
                "study_code": study.study_code,
                "study_status": study.status.value,
                "title": study.title,
                "study_director_id": study.study_director_id,
                "study_director_name": study.study_director.full_name if study.study_director else None,
                "acclimatization_start_date": base_day0.isoformat(),
                "current_target_end_date": study.target_end_date.isoformat() if study.target_end_date else None,
                "proposed_target_end_date": proposed_end_date.isoformat() if proposed_end_date else None,
                "target_end_date_changed": bool(proposed_end_date != study.target_end_date),
                "any_day_changed": any(bool(p.get("day_changed")) for p in proposals),
                "preview_token": snapshot["preview_token"],
                "source_reference": primary_source,
                "source_deviations": source_deviations,
                "biological_revisions": biological_revisions,
                "affected_steps": proposals,
                "revision_proposals": proposals,
                "ineligible_steps": ineligible_steps,
                "ineligible_revision_steps": ineligible_steps,
                "all_dependent_steps": all_dependent_steps,
                "blocking_conflicts": blocking_conflicts,
                "warning_conflicts": warning_conflicts,
                "capacity_info": cap_info,
                "capacity_verified": cap_verified,
                "has_blocking_obstacles": has_blocking,
                "can_approve_revision": can_approve,
                "status_reason": status_reason,
            }
        finally:
            db.commit = orig_db_commit  # type: ignore[method-assign]
            db.flush = orig_db_flush  # type: ignore[method-assign]
            db.rollback = orig_db_rollback  # type: ignore[method-assign]


def _check_biological_revision_authorization(study: Study, user: Optional[User]) -> None:
    if user is None:
        raise PermissionError("Biyolojik plan revizyonu onayı için oturum açmış yetkili kullanıcı gereklidir.")
    if getattr(user, "is_read_only", False):
        raise PermissionError("Salt-okunur (İzleme Modu) kullanıcılar biyolojik plan revizyonu onaylayamaz.")
    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role_val == UserRole.STUDY_DIRECTOR.value:
        if study.study_director_id is None or study.study_director_id != user.id:
            raise PermissionError(
                "Yalnızca çalışmanın atanmış Çalışma Yöneticisi (SD) veya yetkili yönetim (TFM/SYSADMIN) "
                "biyolojik plan revizyonunu onaylayabilir."
            )
        return
    if role_val in (UserRole.TFM.value, UserRole.SYSADMIN.value, UserRole.ADMIN.value):
        return
    raise PermissionError(
        f"'{role_val}' rolü biyolojik plan revizyonu onaylama yetkisine sahip değildir. "
        "Yalnızca atanmış Çalışma Yöneticisi (SD) veya TFM/SYSADMIN onaylayabilir."
    )


def _validate_snapshot_expectations(
    snapshot: Dict[str, Any],
    clean_token: str,
    expected_source_reference_time: Optional[Any] = None,
    expected_steps: Optional[List[Dict[str, Any]]] = None,
) -> None:
    if clean_token != snapshot["preview_token"]:
        raise RuntimeError(
            "Önizleme sonrasında çalışma adımları veya biyolojik referans saati değişti (stale preview). "
            "Lütfen revizyon önizlemesini yenileyip tekrar onaylayın."
        )
    if expected_source_reference_time is not None:
        exp_ref_dt = (
            datetime.fromisoformat(expected_source_reference_time)
            if isinstance(expected_source_reference_time, str)
            else expected_source_reference_time
        )
        exp_ref_iso = exp_ref_dt.isoformat() if hasattr(exp_ref_dt, "isoformat") else str(exp_ref_dt)
        current_refs = set(snapshot["source_references"].values())
        if exp_ref_iso not in current_refs:
            raise RuntimeError(
                "Önizlemedeki kaynak biyolojik referans saati güncel veritabanı durumuyla uyuşmuyor (stale preview). "
                "Lütfen önizlemeyi yenileyin."
            )
    if expected_steps is not None:
        step_map = snapshot["steps"]
        for exp_s in expected_steps:
            sid = exp_s.get("step_id") or exp_s.get("id")
            cur_s = step_map.get(sid)
            if not cur_s:
                raise RuntimeError("Önizlemedeki hedef adımlardan biri bulunamadı veya iptal edildi (stale preview).")
            for fld_exp, fld_cur in (
                ("current_planned_start", "planned_start"),
                ("planned_start", "planned_start"),
                ("current_planned_end", "planned_end"),
                ("planned_end", "planned_end"),
                ("status", "status"),
            ):
                if fld_exp in exp_s and exp_s[fld_exp] is not None:
                    val_exp = exp_s[fld_exp]
                    if hasattr(val_exp, "isoformat"):
                        val_exp = val_exp.isoformat()
                    if str(val_exp) != str(cur_s.get(fld_cur)):
                        raise RuntimeError(
                            f"Adım #{cur_s.get('step_order')} önizleme sonrasında değişti (stale preview). "
                            "Lütfen revizyon önizlemesini yenileyin."
                        )


def approve_biological_revision(
    db: Session,
    study_id: int,
    user: User,
    reason: Optional[str] = None,
    preview_token: Optional[str] = None,
    expected_source_reference_time: Optional[Any] = None,
    expected_steps: Optional[List[Dict[str, Any]]] = None,
    _fail_mid_transaction_for_test: bool = False,
) -> Dict[str, Any]:
    """
    SD Onaylı Biyolojik Plan Revizyonunu atomik olarak uygular:
      1) Yetki (atanmış SD veya TFM/SYSADMIN), zorunlu gerekçe (`reason`) ve zorunlu `preview_token` doğrulaması yapar.
      2) Çalışma durumunun `APPROVED` veya `IN_PROGRESS` olduğunu doğrular.
      3) Canlı veriyi süreç belleğine bağımlı olmadan kontrol ederek bayat önizleme (`stale preview`) ve
         mükerrer gönderimi (`idempotency`) engeller.
      4) Yalnızca uygun (`PENDING` ve gerçekleşen verisi olmayan) bağımlı adımların `planned_start`, `planned_end`
         ve `study_day` alanlarını günceller; kaynak adımın orijinal planını ve gerçek sapmasını korur.
      5) Hem simülasyonda hem de son `revalidate_study_conflicts` / kapasite doğrulamasında kritik personel çakışması,
         9 saat iş yükü aşımı, cihaz/oda/kafes kapasitesi aşımı, eksik zorunlu rol ataması veya kapasite doğrulama
         hatası varsa işlemi tamamen geri alır.
    """
    import copy
    from app.models.sample import SampleRecord

    caller_had_pending_tx = bool(db.new or db.dirty or db.deleted or db.in_nested_transaction())

    study = db.query(Study).filter(Study.id == study_id).first()
    if not study:
        raise LookupError(f"ID={study_id} olan çalışma bulunamadı.")

    _check_biological_revision_authorization(study, user)

    clean_reason = (reason or "").strip()
    if not clean_reason:
        raise ValueError("Biyolojik plan revizyonu onayı için gerekçe (reason) girilmesi zorunludur.")

    clean_token = (preview_token or "").strip()
    if not clean_token:
        raise ValueError(
            "Biyolojik plan revizyonu onayı için geçerli bir önizleme anahtarı (preview_token) zorunludur. "
            "Lütfen önce revizyon önizlemesini çalıştırın."
        )

    if study.status not in (StudyStatus.APPROVED, StudyStatus.IN_PROGRESS):
        raise RuntimeError(
            f"Biyolojik plan revizyonu yalnızca APPROVED veya IN_PROGRESS durumundaki çalışmalarda uygulanabilir "
            f"(Mevcut durum: {study.status.value})."
        )

    steps = (
        db.query(StudyStep)
        .options(selectinload(StudyStep.assignees))
        .filter(StudyStep.study_id == study.id, StudyStep.status != StepStatus.CANCELLED)
        .order_by(StudyStep.step_order.asc())
        .all()
    )
    template = get_template(getattr(study, "template_code", None) or DEFAULT_TEMPLATE_CODE, db=db)

    bio_info = compute_biological_dependency_info(study, steps, template)
    proposals = list(bio_info["revision_proposals"])
    source_deviations = list(bio_info["source_deviations"])

    # 1) Mükerrer gönderim (Idempotency) ve kaynak referans kontrolü
    if not source_deviations or not any(sd.get("actual_reference_time") for sd in source_deviations):
        raise RuntimeError("Bu çalışmada kaydedilmiş gerçek biyolojik referans saati bulunmamaktadır.")

    if not proposals:
        if any(sd.get("sd_revision_approved") for sd in source_deviations):
            raise RuntimeError(
                "Bu biyolojik referans saati için plan revizyonu zaten onaylanmış ve takvime işlenmiştir; "
                "mükerrer revizyon uygulanamaz."
            )
        raise RuntimeError(
            "Revize edilebilecek uygun (PENDING ve gerçekleşen verisi olmayan) bağımlı adım bulunmamaktadır."
        )

    # 2) Zorunlu preview_token ve bayat önizleme (Stale Preview) kontrolü (süreç belleğine bağımlı değildir)
    initial_snapshot = _build_biological_revision_snapshot(
        study,
        steps,
        template=template,
        proposals=proposals,
    )
    _validate_snapshot_expectations(
        initial_snapshot,
        clean_token,
        expected_source_reference_time=expected_source_reference_time,
        expected_steps=expected_steps,
    )

    # 3) Önerilen yeni saatlerde ön simülasyon kontrolü (kalıcı yazma yapmaz ve çağıranın transaction'ını kapatmaz)
    sim_result = _evaluate_revision_candidate_obstacles(
        db=db,
        study=study,
        steps=steps,
        proposals=proposals,
        source_deviations=source_deviations,
        template=template,
    )
    if sim_result["blocking_conflicts"] or not sim_result["capacity_verified"]:
        titles = ", ".join(c["title"] for c in sim_result["blocking_conflicts"][:3])
        raise RuntimeError(
            f"Önerilen yeni saatlerde kritik planlama/kapasite engeli bulunduğu için revizyon reddedildi: {titles}"
        )

    # 4) Atomik uygulama ve son doğrulama (simülasyon ile uygulama arasındaki eşzamanlı değişiklikleri yakalar)
    if not caller_had_pending_tx:
        # Okuma aşamasındaki snapshot'ı sonlandır ki başka bir Session simülasyon sırasında commit yaptıysa
        # yazma işlemi güncel veritabanı durumunu görsün.
        db.rollback()

    savepoint = db.begin_nested()
    try:
        db.expire_all()
        study = db.query(Study).filter(Study.id == study_id).first()
        if not study:
            raise LookupError(f"ID={study_id} olan çalışma bulunamadı.")
        if study.status not in (StudyStatus.APPROVED, StudyStatus.IN_PROGRESS):
            raise RuntimeError(
                f"Biyolojik plan revizyonu yalnızca APPROVED veya IN_PROGRESS durumundaki çalışmalarda uygulanabilir "
                f"(Mevcut durum: {study.status.value})."
            )

        steps = (
            db.query(StudyStep)
            .options(selectinload(StudyStep.assignees))
            .filter(StudyStep.study_id == study.id, StudyStep.status != StepStatus.CANCELLED)
            .order_by(StudyStep.step_order.asc())
            .all()
        )
        base_day0 = study.acclimatization_start_date or study.target_start_date or date.today()
        template = get_template(
            getattr(study, "template_code", None) or DEFAULT_TEMPLATE_CODE,
            db=db,
            commit_defaults=False,
        )

        live_bio_info = compute_biological_dependency_info(study, steps, template)
        proposals = list(live_bio_info["revision_proposals"])
        ineligible_steps = list(live_bio_info["ineligible_revision_steps"])
        source_deviations = list(live_bio_info["source_deviations"])

        # Simülasyon sonrasında kaynak referans, Gün 0, şablon veya adımlar eşzamanlı değiştiyse preview_token uyuşmaz -> 409
        live_snapshot = _build_biological_revision_snapshot(
            study,
            steps,
            template=template,
            proposals=proposals,
        )
        _validate_snapshot_expectations(
            live_snapshot,
            clean_token,
            expected_source_reference_time=expected_source_reference_time,
            expected_steps=expected_steps,
        )

        if not proposals:
            raise RuntimeError(
                "Uygulama anında güncellenmeye uygun (PENDING ve gerçekleşen verisi olmayan) bağımlı adım kalmadı."
            )

        orig_target_end_date = study.target_end_date
        orig_meta = (
            copy.deepcopy(study.dossier_metadata)
            if isinstance(study.dossier_metadata, dict)
            else study.dossier_metadata
        )
        sample_rec = db.query(SampleRecord).filter(SampleRecord.study_code == study.study_code).first()
        open_conflicts_before = (
            db.query(Conflict)
            .filter(Conflict.study_id == study.id, Conflict.is_resolved == False)  # noqa: E712
            .all()
        )

        step_by_id = {s.id: s for s in steps}
        revised_step_ids = {p["step_id"] for p in proposals}
        now = datetime.utcnow()

        old_step_values: List[Dict[str, Any]] = []
        new_step_values: List[Dict[str, Any]] = []

        for prop in proposals:
            st_obj = step_by_id.get(prop["step_id"])
            if st_obj is None:
                raise RuntimeError(f"Hedef adım (ID={prop['step_id']}) bulunamadı.")
            elig_ok, elig_reason = check_step_revision_eligibility(
                st_obj,
                prop["schedule_deviation_minutes"],
                has_source_actual_reference=True,
            )
            if not elig_ok:
                raise RuntimeError(
                    f"Adım #{st_obj.step_order} ({st_obj.step_name}) revizyona uygun değil: {elig_reason}"
                )

            old_step_values.append(
                {
                    "step_id": st_obj.id,
                    "step_order": st_obj.step_order,
                    "step_name": st_obj.step_name,
                    "study_day": st_obj.study_day,
                    "planned_start": st_obj.planned_start.isoformat(),
                    "planned_end": st_obj.planned_end.isoformat(),
                }
            )

            new_start = datetime.fromisoformat(prop["expected_start"])
            new_end = datetime.fromisoformat(prop["expected_end"])
            new_day = (new_start.date() - base_day0).days
            st_obj.planned_start = new_start
            st_obj.planned_end = new_end
            st_obj.study_day = new_day

            new_step_values.append(
                {
                    "step_id": st_obj.id,
                    "step_order": st_obj.step_order,
                    "step_name": st_obj.step_name,
                    "study_day": new_day,
                    "planned_start": new_start.isoformat(),
                    "planned_end": new_end.isoformat(),
                }
            )

        new_target_end_date = max(
            (s.planned_end.date() for s in steps if s.planned_end),
            default=study.target_end_date,
        )
        study.target_end_date = new_target_end_date
        if sample_rec is not None and new_target_end_date is not None:
            sample_rec.planned_end = new_target_end_date

        primary_source = source_deviations[0]
        revision_entry = {
            "revision_id": f"REV-{study.id}-{int(now.timestamp())}-{len((orig_meta or {}).get('biological_revisions', [])) + 1}",
            "source_step_id": primary_source.get("step_id"),
            "source_step_order": primary_source.get("step_order"),
            "source_step_name": primary_source.get("step_name"),
            "source_planned_reference_time": primary_source.get("planned_reference_time"),
            "source_actual_reference_time": primary_source.get("actual_reference_time"),
            "approved_for_actual_reference_time": primary_source.get("actual_reference_time"),
            "source_deviation_minutes": primary_source.get("deviation_minutes"),
            "approved_by_id": user.id,
            "approved_by_name": user.full_name,
            "approved_by_role": user.role.value if hasattr(user.role, "value") else str(user.role),
            "approved_at": now.isoformat(),
            "reason": clean_reason,
            "old_target_end_date": orig_target_end_date.isoformat() if orig_target_end_date else None,
            "new_target_end_date": new_target_end_date.isoformat() if new_target_end_date else None,
            "old_steps": old_step_values,
            "revised_steps": new_step_values,
            "skipped_ineligible_steps": [
                {
                    "step_id": item.get("step_id"),
                    "step_order": item.get("step_order"),
                    "step_name": item.get("step_name"),
                    "status": item.get("status"),
                    "reason": item.get("ineligible_reason"),
                }
                for item in ineligible_steps
            ],
        }

        updated_meta = copy.deepcopy(orig_meta) if isinstance(orig_meta, dict) else {}
        rev_list = list(updated_meta.get("biological_revisions") or [])
        rev_list.append(revision_entry)
        updated_meta["biological_revisions"] = rev_list
        updated_meta["last_biological_revision"] = revision_entry
        study.dossier_metadata = updated_meta

        # Kaynak adımın "Biyolojik Referans Saat Sapması" kaydını SD kararı ve gerekçesiyle çözüldü olarak işaretle
        resolution_note = (
            f"SD Biyolojik Plan Revizyon Onayı ({user.full_name}): {clean_reason} "
            f"[Kaynak Referans: {primary_source.get('actual_reference_time')}]"
        )
        for c in open_conflicts_before:
            if (
                c.conflict_type == ConflictType.BIOLOGICAL_TIME_VIOLATION
                and "Biyolojik Referans Saat Sapması" in (c.title or "")
            ):
                c.is_resolved = True
                c.resolved_by_id = user.id
                c.resolved_at = now
                c.resolution_notes = resolution_note

        db.flush()

        if _fail_mid_transaction_for_test:
            raise RuntimeError("Test amaçlı işlem ortası kontrollü hata (atomik rollback testi).")

        # Doğrulama yardımcılarının (revalidate_study_conflicts / _safe_capacity_report / get_template vb.)
        # erken db.commit() çağırarak henüz doğrulanmamış revizyonu kalıcılaştırmasını engelle
        orig_approve_commit = db.commit

        def _forbid_premature_commit(*_args, **_kwargs):
            raise RuntimeError("Biyolojik revizyon son doğrulaması tamamlanmadan db.commit() çağrılmasına izin verilmez.")

        db.commit = _forbid_premature_commit  # type: ignore[method-assign]
        try:
            # Çalışmanın çakışmalarını yeni plan saatleriyle yeniden doğrula
            final_findings = revalidate_study_conflicts(db, study, preserve_weekend_approvals=True)
            final_cap_info = _safe_capacity_report(db, study, template)
            final_cap_verified = bool(final_cap_info and final_cap_info.get("verified") is True)

            # Son revalidate_study_conflicts sonucundaki yeni kritik engeller commit öncesinde reddetme koşuludur
            final_blocking_titles: List[str] = []
            for c_fin, _sids_fin in final_findings:
                if c_fin.severity == ConflictSeverity.CRITICAL and not _is_non_blocking_past_observation_violation(
                    c_fin, revised_step_ids
                ):
                    final_blocking_titles.append(c_fin.title)
            if not final_cap_verified:
                final_blocking_titles.append(
                    (final_cap_info or {}).get("error") or "Kapasite Doğrulama Hatası"
                )
            if final_blocking_titles:
                raise RuntimeError(
                    f"Uygulama sırasında önerilen yeni saatlerde kritik planlama/kapasite engeli tespit edildiği için "
                    f"revizyon geri alındı: {', '.join(final_blocking_titles[:3])}"
                )

            # Bu çalışmayla ilişkili açık çakışması olan diğer çalışmaları da yeniden doğrula
            related_study_ids = {
                row[0]
                for row in db.query(Conflict.study_id)
                .filter(
                    Conflict.related_study_id == study.id,
                    Conflict.study_id != study.id,
                    Conflict.is_resolved == False,  # noqa: E712
                )
                .distinct()
                .all()
                if row[0] is not None
            }
            for rel_sid in related_study_ids:
                rel_study = db.query(Study).filter(Study.id == rel_sid).first()
                if rel_study and rel_study.status in COMPARED_STUDY_STATUSES:
                    revalidate_study_conflicts(db, rel_study, preserve_weekend_approvals=True)
        finally:
            db.commit = orig_approve_commit  # type: ignore[method-assign]

        db.add(
            AuditLog(
                user_id=user.id,
                entity_name="Study",
                entity_id=study.id,
                action="APPROVE_BIOLOGICAL_REVISION",
                old_values={
                    "study_code": study.study_code,
                    "source_step_id": primary_source.get("step_id"),
                    "source_step_order": primary_source.get("step_order"),
                    "source_planned_reference_time": primary_source.get("planned_reference_time"),
                    "source_actual_reference_time": primary_source.get("actual_reference_time"),
                    "target_end_date": orig_target_end_date.isoformat() if orig_target_end_date else None,
                    "steps": old_step_values,
                },
                new_values={
                    "study_code": study.study_code,
                    "source_step_id": primary_source.get("step_id"),
                    "source_step_order": primary_source.get("step_order"),
                    "source_actual_reference_time": primary_source.get("actual_reference_time"),
                    "source_deviation_minutes": primary_source.get("deviation_minutes"),
                    "target_end_date": new_target_end_date.isoformat() if new_target_end_date else None,
                    "steps": new_step_values,
                    "skipped_ineligible_steps": revision_entry["skipped_ineligible_steps"],
                    "approved_by_id": user.id,
                    "approved_by_name": user.full_name,
                },
                reason=clean_reason,
            )
        )
        db.flush()
        savepoint.commit()
        db.commit()
    except Exception:
        if savepoint.is_active:
            savepoint.rollback()
        if not caller_had_pending_tx:
            db.rollback()
        raise

    snap_key = _get_preview_snapshot_key(db, study)
    _LATEST_PREVIEW_SNAPSHOTS.pop(snap_key, None)

    res = get_study_schedule_detail(db, study)
    res["revision_applied"] = revision_entry
    return res



def apply_conflict_resolution(
    db: Session,
    conflict_id: int,
    action: str,
    user: User,
    target_user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    FAZ 6.2 & 6.4 — Kullanıcının çakışma kartındaki "Tek Tık Çözüm Butonu"na tıklamasıyla tetiklenen
    karar destek aksiyonlarını yürütür, takvim veya personel değiştiğinde çakışma motorunu yeniden
    çalıştırır (re-validation), AuditLog'a yazar ve güncellenmiş çalışma takvimini döner.
    """
    conflict = db.query(Conflict).filter(Conflict.id == conflict_id).first()
    if not conflict:
        raise ValueError(f"ID={conflict_id} olan çakışma kaydı bulunamadı.")
    study = db.query(Study).filter(Study.id == conflict.study_id).first()
    if not study:
        raise ValueError("Çakışmanın bağlı olduğu çalışma bulunamadı.")

    now = datetime.utcnow()
    template = get_template(getattr(study, "template_code", None) or DEFAULT_TEMPLATE_CODE, db=db)
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

        db.flush()
        revalidate_study_conflicts(db, study, preserve_weekend_approvals=True)
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
        offset = compute_friday_alignment_offset(base_day0, study.extraction_start_offset_days or 0)
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
            if backup and not is_eligible_lab_personnel(backup):
                raise ValueError("SYSADMIN, EXECUTIVE veya SALES rolündeki kullanıcılara biyolojik görev atanamaz.")
        else:
            techs = [
                u for u in db.query(User).filter(User.role == UserRole.TECHNICIAN, User.is_active == True).order_by(User.id.asc()).all()  # noqa: E712
                if is_eligible_lab_personnel(u)
            ]
            candidates = [u for u in techs if u.id not in current_ids] or techs
            backup = (
                min(candidates, key=lambda u: (calculate_personnel_workload(db, u.id, target_day)["total_minutes"], u.id))
                if candidates
                else None
            )

        if not backup:
            raise ValueError("Devredilecek aktif yedek teknisyen bulunamadı.")

        ts_by_order = {ts.order: ts for ts in template.steps}
        steps_to_update = (
            [step]
            if step
            else db.query(StudyStep).filter(StudyStep.study_id == study.id, StudyStep.status != StepStatus.CANCELLED).all()
        )
        others = db.query(Study).filter(Study.id != study.id, Study.status.in_(COMPARED_STUDY_STATUSES)).all()
        other_ids = [s.id for s in others]
        existing_steps = (
            db.query(StudyStep)
            .options(selectinload(StudyStep.assignees), selectinload(StudyStep.study))
            .filter(StudyStep.study_id.in_(other_ids), StudyStep.status != StepStatus.CANCELLED)
            .all()
            if other_ids
            else []
        )
        existing_assignees = {ex.id: {u.id for u in ex.assignees} for ex in existing_steps}

        for st in steps_to_update:
            ts_def = ts_by_order.get(st.step_order)
            requires_tech = (ts_def and UserRole.TECHNICIAN in ts_def.roles) or any(
                u.role == UserRole.TECHNICIAN for u in st.assignees
            )
            if requires_tech:
                non_techs = [u for u in st.assignees if u.role != UserRole.TECHNICIAN]
                st.assignees = non_techs + [backup]
            if not st.is_biological_fixed_time:
                dur = int((st.planned_end - st.planned_start).total_seconds() // 60) or 120
                new_s, new_e = _find_free_slot_for_flexible_step(
                    target_day=st.planned_start.date(),
                    default_start=st.planned_start,
                    duration_minutes=dur,
                    assignees=st.assignees,
                    busy_steps=existing_steps,
                    busy_assignees_map=existing_assignees,
                )
                st.planned_start = new_s
                st.planned_end = new_e

        note = (
            f"Yedek Teknisyen Devri ({user.full_name}): Görev iş yükü müsait olan "
            f"'{backup.full_name}' personeline devredildi ve çakışma denetimi yenilendi."
        )
        meta = dict(study.dossier_metadata or {})
        meta["technician_confirmed"] = True
        study.dossier_metadata = meta
        conflict.is_resolved = True
        conflict.resolved_by_id = user.id
        conflict.resolved_at = now
        conflict.resolution_notes = note
        db.flush()

        # FAZ 6.4 (Madde 3): Çözüm uygulandıktan sonra çalışmanın çakışmalarını yeniden doğrula
        revalidate_study_conflicts(db, study, preserve_weekend_approvals=True)

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

    elif action == "SHIFT_TO_NEXT_AVAILABLE_CAPACITY_DATE":
        free_g0 = find_first_free_g0(db, study, template, base_day0, study.extraction_start_offset_days or 0)
        if not free_g0:
            raise ValueError("Önümüzdeki 240 gün içinde kafes / cihaz kapasitesi uygun bir başlangıç tarihi bulunamadı.")
        new_g0 = date.fromisoformat(free_g0)
        res = schedule_new_study(
            db=db,
            study_id=study.id,
            acclimatization_start_date=new_g0,
            template_code=template.code,
            extraction_start_offset_days=study.extraction_start_offset_days or 0,
        )
        db.add(
            AuditLog(
                user_id=user.id,
                entity_name="Study",
                entity_id=study.id,
                action="SHIFT_TO_NEXT_AVAILABLE_CAPACITY_DATE",
                old_values={"day0": base_day0.isoformat()},
                new_values={"study_code": study.study_code, "day0": new_g0.isoformat()},
                reason=(
                    f"{user.full_name} kafes / uzun süreli cihaz kapasitesi nedeniyle Gün 0'ı "
                    f"{base_day0:%d.%m.%Y} → {new_g0:%d.%m.%Y} tarihine (ilk boşalan tarih) kaydırdı."
                ),
            )
        )
        db.commit()
        res["resolution_applied"] = {
            "action": action,
            "message": f"Gün 0 kapasitenin uygun olduğu ilk iş günü olan {new_g0:%d.%m.%Y} tarihine kaydırıldı.",
        }
        return res

    else:
        raise ValueError(f"Tanımsız çözüm aksiyonu: '{action}'")

    # Güncel çalışma durumunu döndür
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
    res = _format_schedule_response(
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
    res["resolution_applied"] = {"action": action, "message": "Çözüm başarıyla uygulandı ve denetim izine kaydedildi."}
    return res


# ---------------------------------------------------------------------------
# FAZ 9.2 — GEÇMİŞ GÖREVLERİN KAPATILMASI, ÇAKIŞMA KATEGORİZASYONU & RECOMPUTE
# ---------------------------------------------------------------------------
def sync_historical_completion_and_conflicts(
    db: Session,
    ref_date: date = REFERENCE_DATE,
    from_excel_import: bool = False,
    target_study_codes: Optional[set] = None,
) -> Dict[str, Any]:
    """
    Tarihsel tamamlanma ve geçmiş/demo kayıt kapsamı senkronizasyonu:
      - Devam eden (IN_PROGRESS / ONGOING) çalışmaların geçmiş tarihli tamamlanmamış görevleri
        ASLA otomatik olarak `StepStatus.COMPLETED` yapılmaz; gelecekteki görevleri korunur.
      - Bilinmeyen `actual_start` ve `actual_end` saatleri için `planned_start` / `planned_end`
        değerlerinden sahte gerçekleşme saati ASLA uydurulmaz.
      - Yalnızca açıkça `COMPLETED` olan çalışmalarda (ve ilk Excel içe aktarımında) ilgili adımlar
        tarihsel tamamlanmış (`[HISTORICAL_IMPORT_COMPLETED]`) olarak işaretlenir; aynı Excel tekrar
        içe aktarıldığında sahte yeni tamamlama üretilmez (`newly_completed_steps == 0`).
      - Geçmiş Excel/demo içe aktarımına ait olup ayrıntısı bilinmeyen (`< 2026-11-03`) adımlar
        `PENDING` olarak kalır, aktif çakışma hesabından hariç tutulur (`historical_excluded_steps`)
        ve doğrulanmış tamamlanan görev istatistiğine (`verified_completed_steps`) eklenmez.
    """
    import copy
    from app.models.sample import SampleRecord

    now = datetime.utcnow()
    samples = db.query(SampleRecord).all()
    sample_by_code = {s.study_code: s for s in samples if s.study_code}
    studies = db.query(Study).all()
    study_by_id = {s.id: s for s in studies}

    completed_studies_count = 0
    newly_completed_steps = 0

    for st in studies:
        sr = sample_by_code.get(st.study_code)
        meta = copy.deepcopy(st.dossier_metadata) if isinstance(st.dossier_metadata, dict) else {}
        in_import_scope = bool(
            from_excel_import and (target_study_codes is None or st.study_code in target_study_codes)
        )
        if in_import_scope and target_study_codes is not None:
            meta["historical_excel_import"] = True

        steps = (
            db.query(StudyStep)
            .filter(StudyStep.study_id == st.id, StudyStep.status != StepStatus.CANCELLED)
            .all()
        )
        is_explicit_completed = st.status == StudyStatus.COMPLETED or (
            in_import_scope and sr is not None and (sr.stored_status or "").upper() == "COMPLETED"
        )
        if is_explicit_completed:
            if st.status != StudyStatus.COMPLETED:
                st.status = StudyStatus.COMPLETED
            completed_studies_count += 1
            if meta.get("historical_synced_status") != "COMPLETED":
                for step in steps:
                    if step.status != StepStatus.COMPLETED:
                        step.status = StepStatus.COMPLETED
                        if step.actual_start is None and step.actual_end is None:
                            notes = step.deviation_notes or ""
                            if "[HISTORICAL_IMPORT_COMPLETED]" not in notes:
                                step.deviation_notes = (notes + " [HISTORICAL_IMPORT_COMPLETED]").strip()
                        newly_completed_steps += 1
                meta["historical_synced_status"] = "COMPLETED"
                meta["historical_sync_done"] = True
                meta["historical_excel_import"] = True
                st.dossier_metadata = meta
        elif in_import_scope and (
            target_study_codes is not None or meta.get("historical_excel_import") or meta.get("is_historical_demo")
        ):
            meta["historical_excel_import"] = True
            meta["historical_synced_status"] = (
                (sr.stored_status or "").upper()
                if (sr is not None and sr.stored_status)
                else st.status.value
            )
            meta["historical_sync_done"] = True
            st.dossier_metadata = meta

    db.flush()

    all_non_cancelled_steps = (
        db.query(StudyStep)
        .options(selectinload(StudyStep.study))
        .filter(StudyStep.status != StepStatus.CANCELLED)
        .all()
    )
    step_by_id = {s.id: s for s in all_non_cancelled_steps}
    open_conflicts = db.query(Conflict).filter(Conflict.is_resolved == False).all()  # noqa: E712
    resolved_past_conflicts = 0
    note = f"Tarihsel/demo kayıt (Referans: {ref_date:%d.%m.%Y}) — aktif çakışma kapsamı dışında kapatıldı"

    def _is_hist_study(st_obj: Optional[Study]) -> bool:
        if st_obj is None:
            return False
        m = st_obj.dossier_metadata if isinstance(st_obj.dossier_metadata, dict) else {}
        return bool(m.get("historical_excel_import") or m.get("is_historical_demo"))

    for c in open_conflicts:
        st = study_by_id.get(c.study_id)
        sr = sample_by_code.get(st.study_code) if st else None
        rel_st = study_by_id.get(c.related_study_id) if c.related_study_id else None
        rel_sr = sample_by_code.get(rel_st.study_code) if rel_st else None
        step = step_by_id.get(c.step_id) if c.step_id else None

        is_active_bio_violation = (
            st is not None
            and st.status != StudyStatus.COMPLETED
            and c.conflict_type == ConflictType.BIOLOGICAL_TIME_VIOLATION
            and any(
                kw in (c.title or "")
                for kw in (
                    "Biyolojik Referans Saat Sapması",
                    "Gerçekleşen Gözlem Biyolojik Pencere İhlali",
                    "Eksik Biyolojik Gözlem Saati",
                    "Eksik Biyolojik Referans Saati",
                    "Bağımlı Biyolojik Adım Sapması",
                )
            )
        )

        should_close = False
        if st and st.status == StudyStatus.COMPLETED:
            should_close = True
        elif rel_st and rel_st.status == StudyStatus.COMPLETED:
            should_close = True
        elif step is not None and (
            (step.status == StepStatus.COMPLETED and not is_active_bio_violation)
            or is_historical_unverified_step(step, st, sr, ref_date)
        ):
            should_close = True
        elif (
            st is not None
            and _is_hist_study(st)
            and sr is not None
            and (sr.stored_status or "").upper() == "ONGOING"
            and sr.experiment_end_date
            and sr.experiment_end_date < ref_date
        ):
            should_close = True
        elif (
            rel_st is not None
            and _is_hist_study(rel_st)
            and rel_sr is not None
            and (rel_sr.stored_status or "").upper() == "ONGOING"
            and rel_sr.experiment_end_date
            and rel_sr.experiment_end_date < ref_date
        ):
            should_close = True

        if should_close:
            c.is_resolved = True
            c.resolved_at = now
            c.resolution_notes = note
            resolved_past_conflicts += 1

    db.flush()

    verified_completed_steps = 0
    historical_completed_steps = 0
    historical_excluded_steps = 0
    for s in all_non_cancelled_steps:
        st = study_by_id.get(s.study_id) or getattr(s, "study", None)
        sr = sample_by_code.get(st.study_code) if st else None
        if s.status == StepStatus.COMPLETED:
            is_unverified_hist_comp = (
                s.actual_start is None
                and s.actual_end is None
                and ("[HISTORICAL_IMPORT_COMPLETED]" in (s.deviation_notes or "") or _is_hist_study(st))
            )
            if is_unverified_hist_comp:
                historical_completed_steps += 1
            else:
                verified_completed_steps += 1
        elif is_historical_unverified_step(s, st, sr, ref_date):
            historical_excluded_steps += 1

    return {
        "reference_date": ref_date.isoformat(),
        "completed_studies_count": db.query(Study).filter(Study.status == StudyStatus.COMPLETED).count(),
        "newly_completed_steps": newly_completed_steps,
        "verified_completed_steps": verified_completed_steps,
        "historical_completed_steps": historical_completed_steps,
        "historical_excluded_steps": historical_excluded_steps,
        "total_completed_steps": verified_completed_steps + historical_completed_steps,
        "total_pending_steps": db.query(StudyStep).filter(StudyStep.status == StepStatus.PENDING).count(),
        "resolved_past_conflicts": resolved_past_conflicts,
    }


def classify_conflict_record(
    conflict: Conflict,
    study: Optional[Study],
    sample: Optional[Any],
    related_study: Optional[Study],
    related_sample: Optional[Any],
    step: Optional[StudyStep],
    doc_study_codes: set,
) -> Dict[str, Any]:
    """
    FAZ 9.2 (Madde 2): Açık bir çakışmayı "Gerçek Çakışma" (`CONFIRMED_CONFLICT`) veya
    "Eksik Bilgi Sebebiyle Çakışma" (`MISSING_INFO`) olarak sınıflandırır ve sebep rozetlerini üretir.
    """
    reasons: List[Dict[str, str]] = []
    meta = (study.dossier_metadata or {}) if study else {}
    rel_meta = (related_study.dossier_metadata or {}) if related_study else {}
    title_str = conflict.title or ""

    if "Eksik Biyolojik Referans Saati" in title_str or "Eksik Biyolojik Gözlem Saati" in title_str:
        reasons.append(
            {
                "code": "MISSING_BIOLOGICAL_REFERENCE_TIME",
                "badge": "Biyolojik Referans / Gözlem Saati Eksik",
                "tag": "Eksik Bilgi: Biyolojik Referans veya Gözlem Saati Girilmedi",
            }
        )

    # 1) Excel'de Test Başlangıç Tarihi boş (`-`) olduğu için sistem tarafından tahmini tarihe yerleştirilmişse
    study_missing_start = (
        sample is not None
        and sample.experiment_start_date is None
        and not meta.get("start_date_confirmed")
    )
    rel_missing_start = (
        related_sample is not None
        and related_sample.experiment_start_date is None
        and not rel_meta.get("start_date_confirmed")
    )
    if study_missing_start or rel_missing_start:
        reasons.append(
            {
                "code": "MISSING_START_DATE",
                "badge": "Başlangıç Tarihi Eksik",
                "tag": "Eksik Bilgi: Başlangıç Tarihi Girilmedi (Excel'de Boş)",
            }
        )

    # 2) Saha teknisyeni belirtilmediği için sistem otomatik varsayılan teknisyen (`In Vivo Teknisyeni 1/2`) atamışsa
    if (
        conflict.conflict_type == ConflictType.PERSONNEL_OVERLAP
        and ("Teknisyen" in title_str or "invivo_" in (conflict.description or "").lower())
        and not meta.get("technician_confirmed")
    ):
        reasons.append(
            {
                "code": "DEFAULT_TECHNICIAN",
                "badge": "Teknisyen Ataması Varsayılan",
                "tag": "Eksik Bilgi: Saha Teknisyeni Atanmadı (Varsayılan Teknisyen)",
            }
        )

    # 3) TIIS / CoA PDF henüz yüklenmemişse veya ekstraksiyon saati/cihazı manuel teyit edilmemişse
    study_code = study.study_code if study else ""
    has_docs = bool(
        study_code in doc_study_codes
        or (sample is not None and bool(sample.document_autofill))
        or meta.get("equipment_time_confirmed")
    )
    if (
        not has_docs
        and "Biyolojik Referans Saat Sapması" not in title_str
        and "Bağımlı Biyolojik Adım Sapması" not in title_str
        and "Gerçekleşen Gözlem Biyolojik Pencere İhlali" not in title_str
        and "Eksik Biyolojik" not in title_str
        and (
            conflict.conflict_type == ConflictType.BIOLOGICAL_TIME_VIOLATION
            or (
                conflict.conflict_type == ConflictType.EQUIPMENT_OVERLAP
                and ("Su Banyosu" in title_str or (study is not None and (study.extraction_polar is None or study.extraction_non_polar is None)))
            )
        )
    ):
        reasons.append(
            {
                "code": "MISSING_TIIS_OR_EQUIPMENT",
                "badge": "TIIS PDF / Cihaz Bilgisi Eksik",
                "tag": "Eksik Bilgi: TIIS PDF / Cihaz & Saat Teyit Edilmedi",
            }
        )

    category = "MISSING_INFO" if reasons else "CONFIRMED_CONFLICT"
    return {
        "conflict_category": category,
        "missing_info_codes": [r["code"] for r in reasons],
        "missing_info_badges": [r["badge"] for r in reasons],
        "missing_info_tags": [r["tag"] for r in reasons],
        "study_code": study.study_code if study else None,
        "study_title": study.title if study else None,
        "sample_id": sample.id if sample else None,
        "related_study_code": related_study.study_code if related_study else None,
        "step_name": step.step_name if step else None,
        "planned_start": step.planned_start.isoformat() if (step and step.planned_start) else None,
    }


def enrich_conflicts_with_category(
    db: Session,
    conflicts: List[Conflict],
    include_resolutions: bool = False,
) -> List[Dict[str, Any]]:
    """
    Verilen Conflict ORM listesini tek sorgu kümesiyle zenginleştirerek `conflict_category`,
    `missing_info_badges`, `missing_info_tags`, `study_code`, `sample_id` ve isteğe bağlı `resolutions` döner.
    """
    if not conflicts:
        return []
    from app.models.document import Document
    from app.models.sample import SampleRecord

    studies = db.query(Study).all()
    study_by_id = {s.id: s for s in studies}
    samples = db.query(SampleRecord).all()
    sample_by_code = {s.study_code: s for s in samples if s.study_code}
    step_ids = {c.step_id for c in conflicts if c.step_id is not None}
    step_by_id = (
        {s.id: s for s in db.query(StudyStep).filter(StudyStep.id.in_(step_ids)).all()}
        if step_ids
        else {}
    )
    doc_codes = {
        row[0]
        for row in db.query(Document.dossier_key).filter(Document.dossier_key.isnot(None)).distinct().all()
        if row[0]
    }

    all_steps_orm: List[StudyStep] = []
    all_steps_by_id: Dict[int, StudyStep] = {}
    active_techs: List[User] = []
    water_bath: Optional[Equipment] = None
    if include_resolutions:
        water_bath = seed_default_equipment(db)
        active_techs = [
            u for u in db.query(User).filter(User.role == UserRole.TECHNICIAN, User.is_active == True).order_by(User.id.asc()).all()  # noqa: E712
            if is_eligible_lab_personnel(u)
        ]
        all_steps_orm = (
            db.query(StudyStep)
            .options(selectinload(StudyStep.assignees), selectinload(StudyStep.study))
            .filter(StudyStep.status != StepStatus.CANCELLED, StudyStep.status != StepStatus.COMPLETED)
            .all()
        )
        all_steps_by_id = {s.id: s for s in all_steps_orm}

    out: List[Dict[str, Any]] = []
    for c in conflicts:
        st = study_by_id.get(c.study_id)
        sr = sample_by_code.get(st.study_code) if st else None
        rel_st = study_by_id.get(c.related_study_id) if c.related_study_id else None
        rel_sr = sample_by_code.get(rel_st.study_code) if rel_st else None
        step = step_by_id.get(c.step_id) if c.step_id else None

        meta_info = classify_conflict_record(c, st, sr, rel_st, rel_sr, step, doc_codes)
        row: Dict[str, Any] = {
            "id": c.id,
            "conflict_type": c.conflict_type,
            "type": c.conflict_type.value if hasattr(c.conflict_type, "value") else str(c.conflict_type),
            "severity": c.severity,
            "title": c.title,
            "description": c.description,
            "study_id": c.study_id,
            "step_id": c.step_id,
            "related_study_id": c.related_study_id,
            "is_resolved": c.is_resolved,
            "resolved_by_id": c.resolved_by_id,
            "resolved_at": c.resolved_at,
            "resolution_notes": c.resolution_notes,
            "detected_at": c.detected_at,
            **meta_info,
        }
        if include_resolutions and st is not None and not c.is_resolved:
            row["resolutions"] = build_conflict_resolutions(
                db,
                c,
                study=st,
                existing_steps=all_steps_orm,
                fast_mode=True,
                active_techs=active_techs,
                water_bath=water_bath,
                step_by_id=all_steps_by_id,
            )
        else:
            row["resolutions"] = []
        out.append(row)
    return out


def recompute_all_conflicts(
    db: Session,
    user: Optional[User] = None,
    ref_date: date = REFERENCE_DATE,
) -> Dict[str, Any]:
    """
    Tüm çalışma çakışmalarını yeniden hesaplar:
      - Tamamlanmamış geçmiş görevleri otomatik olarak COMPLETED yapmaz ve sahte actual_start/actual_end üretmez.
      - Devam eden 72 saatlik cihaz rezervasyonlarını (kurulum adımı COMPLETED olsa bile) korur.
      - Eksik personel atamalarını, biyolojik referans gecikmelerini ve kapasite hatalarını denetler.
      - Kaymış beklenen biyolojik pencereleri çalışma oluşturma / ID sırasından bağımsız olarak her iki yönde değerlendirir.
      - Açık çakışmaları `CONFIRMED_CONFLICT` ve `MISSING_INFO` olarak sınıflandırıp özet döner.
    """
    from app.models.sample import SampleRecord

    sync_stats = sync_historical_completion_and_conflicts(db, ref_date=ref_date, from_excel_import=False)
    now = datetime.utcnow()

    prev_approved = (
        db.query(Conflict)
        .filter(
            Conflict.is_resolved == True,  # noqa: E712
            Conflict.conflict_type == ConflictType.BIOLOGICAL_TIME_VIOLATION,
            or_(
                Conflict.resolution_notes.like("GLP Hafta Sonu Nöbetçi Personel Onayı%"),
                Conflict.resolution_notes.like("Plan Onayı%"),
            ),
        )
        .all()
    )
    approved_wk_steps = {c.step_id for c in prev_approved if c.step_id is not None}

    superseded_note = f"RECOMPUTED: Tüm çakışmalar {now:%d.%m.%Y %H:%M} UTC itibarıyla yeniden hesaplandı."
    db.query(Conflict).filter(Conflict.is_resolved == False).update(  # noqa: E712
        {Conflict.is_resolved: True, Conflict.resolved_at: now, Conflict.resolution_notes: superseded_note},
        synchronize_session="fetch",
    )
    db.flush()

    water_bath = seed_default_equipment(db)
    studies = (
        db.query(Study)
        .filter(Study.status.notin_([StudyStatus.COMPLETED, StudyStatus.CANCELLED]))
        .order_by(Study.id.asc())
        .all()
    )
    sample_by_code = {s.study_code: s for s in db.query(SampleRecord).all() if s.study_code}

    steps_by_study_id: Dict[int, List[StudyStep]] = {}
    all_study_steps_flat: List[StudyStep] = []
    all_assignees_map: Dict[int, set] = {}
    studies_with_shifted_bio: set = set()

    for st in studies:
        st_steps = (
            db.query(StudyStep)
            .options(selectinload(StudyStep.assignees), selectinload(StudyStep.study))
            .filter(
                StudyStep.study_id == st.id,
                StudyStep.status != StepStatus.CANCELLED,
            )
            .order_by(StudyStep.step_order.asc())
            .all()
        )
        steps_by_study_id[st.id] = st_steps
        for s in st_steps:
            all_study_steps_flat.append(s)
            all_assignees_map[s.id] = {u.id for u in s.assignees}
            if getattr(s, "actual_reference_time", None) is not None:
                studies_with_shifted_bio.add(st.id)

    prior_steps: List[StudyStep] = []
    prior_study_ids: set = set()
    seen_workload_titles: set = set()

    for st in studies:
        study_steps = steps_by_study_id.get(st.id, [])
        if not study_steps:
            continue
        sr = sample_by_code.get(st.study_code)
        has_active_or_ref = any(
            (s.status != StepStatus.COMPLETED and not is_historical_unverified_step(s, st, sr, ref_date))
            or getattr(s, "actual_reference_time", None) is not None
            for s in study_steps
        )
        if has_active_or_ref:
            tpl = get_template(getattr(st, "template_code", None) or DEFAULT_TEMPLATE_CODE, db=db)
            extra_shifted_steps = [
                s for s in all_study_steps_flat
                if s.study_id != st.id
                and s.study_id in studies_with_shifted_bio
                and s.study_id not in prior_study_ids
            ]
            eval_existing_steps = prior_steps + extra_shifted_steps
            findings = evaluate_study_conflicts(
                db=db,
                study=st,
                steps=study_steps,
                existing_steps=eval_existing_steps,
                existing_assignees=all_assignees_map,
                water_bath=water_bath,
                template=tpl,
                preserve_approved_weekend_step_ids=approved_wk_steps,
            )
            # Aynı kişi-gün için 9 saat iş yükü aşımı uyarısını tekilleştir (aşımı tetikleyen son çalışmada tut)
            for c, _ in findings:
                if (c.title or "").startswith("9 Saat İş Yükü Aşımı:"):
                    if c.title in seen_workload_titles:
                        c.is_resolved = True
                        c.resolved_at = now
                        c.resolution_notes = "Aynı kişi-gün iş yükü aşımı ilgili günün ana çakışma kaydında birleştirildi."
                    else:
                        seen_workload_titles.add(c.title)

        for ps in study_steps:
            prior_steps.append(ps)
        prior_study_ids.add(st.id)

    db.flush()
    open_conflicts = db.query(Conflict).filter(Conflict.is_resolved == False).order_by(Conflict.id.asc()).all()  # noqa: E712
    enriched = enrich_conflicts_with_category(db, open_conflicts, include_resolutions=False)
    confirmed_count = sum(1 for item in enriched if item["conflict_category"] == "CONFIRMED_CONFLICT")
    missing_count = sum(1 for item in enriched if item["conflict_category"] == "MISSING_INFO")

    db.add(
        AuditLog(
            user_id=user.id if user else None,
            entity_name="Conflict",
            entity_id=0,
            action="RECOMPUTE_ALL_CONFLICTS",
            new_values={
                "reference_date": ref_date.isoformat(),
                "confirmed_conflicts": confirmed_count,
                "missing_info_conflicts": missing_count,
                "total_open_conflicts": len(enriched),
                **sync_stats,
            },
            reason=(
                f"{user.full_name if user else 'Sistem'}: Tüm çalışma çakışmaları yeniden hesaplandı — "
                f"{confirmed_count} gerçek çakışma, {missing_count} eksik bilgi kaynaklı olası çakışma."
            ),
        )
    )
    db.commit()
    return {
        "status": "success",
        "confirmed_conflicts": confirmed_count,
        "missing_info_conflicts": missing_count,
        "total_open_conflicts": len(enriched),
        **sync_stats,
    }

