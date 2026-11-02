"""
FAZ 8.1 — Kapasite, Kısıtlama ve Uzun Süreli Cihaz Motoru

1) Test Kısıtlama Takvimi (Blackout): Gün 0 kısıtlama aralığındaysa `restricted_until + 1` (ilk iş günü) tarihine öteler.
2) Kafes Kapasitesi: Sistem Planlama Kapasitesi = Fiziksel Kafes × (1 + Dr. Anoop Esneklik % / 100).
     - Doluluk ≤ Fiziksel Kafes            → OK
     - Fiziksel < Doluluk ≤ Planlama Kap.  → FLEX  (engellemez; yalnızca bilgi etiketi)
     - Doluluk > Planlama Kapasitesi       → EXCEEDED (kapasite uyarısı + ilk boşalan tarihe yönlendirme)
3) 24-72+ saatlik darboğaz cihazları (EQ-WB-001 su banyosu mevcut motorda; EQ-INC-001 CO2 inkübatör,
   EQ-OVN-001 etüv/inkübatör burada) eşzamanlı çalışma kapasitesi denetimi. 15 dakikalık kısa cihazlar dahil değildir.
"""
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.conflict import Conflict, ConflictSeverity, ConflictType
from app.models.equipment import Equipment
from app.models.room_capacity import (
    FACILITY_AVAILABLE_ANIMALS,
    FACILITY_AVAILABLE_ANIMALS_SUMMARY,
    AnimalRoomCapacity,
    ensure_default_room_capacities,
)
from app.models.study import Study, StudyStatus
from app.models.test_restriction import TestRestriction
from app.services.templates import TEMPLATES, StudyTemplate, resolve_template_code

AUTO_NOTICE_PREFIX = "OTOMATİK TARİH PLANLAMASI:"
_ACTIVE_STATUSES = (StudyStatus.APPROVED, StudyStatus.IN_PROGRESS, StudyStatus.DRAFT)


def _d(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def next_business_day(d: date) -> date:
    """Hafta sonuna denk gelen tarihi sonraki Pazartesi'ye taşır."""
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _tpl_for(code: Optional[str]) -> Optional[StudyTemplate]:
    return TEMPLATES.get(resolve_template_code(code)) if code else None


# ---------------------------------------------------------------------------
# 1) TEST KISITLAMA TAKVİMİ
# ---------------------------------------------------------------------------
def _restriction_matches(r: TestRestriction, template_code: str, g0: date) -> bool:
    if not r.is_active:
        return False
    rc = resolve_template_code(r.template_code)
    if rc != "ALL" and rc != resolve_template_code(template_code):
        return False
    return r.restricted_from <= g0 <= r.restricted_until


def apply_restriction_shift(db: Session, template_code: str, requested_g0: date) -> Dict[str, Any]:
    """
    Talep edilen Gün 0 bir kısıtlama aralığındaysa Gün 0'ı `restricted_until + 1 gün` (ilk iş günü) tarihine öteler.
    Ötelenen tarih başka bir kısıtlamaya denk gelirse zincirleme olarak tekrar öteler.
    """
    restrictions = db.query(TestRestriction).filter(TestRestriction.is_active == True).all()  # noqa: E712
    g0 = requested_g0
    applied: List[TestRestriction] = []
    for _ in range(25):
        hit = [r for r in restrictions if _restriction_matches(r, template_code, g0)]
        if not hit:
            break
        worst = max(hit, key=lambda r: r.restricted_until)
        applied.append(worst)
        g0 = next_business_day(worst.restricted_until + timedelta(days=1))
    if not applied:
        return {"g0": requested_g0, "shifted": False, "notice": None, "restrictions": []}

    sentences = [
        (
            f"{AUTO_NOTICE_PREFIX} {r.test_name}, '{r.reason}' nedeniyle {_d(r.restricted_until)} tarihine kadar "
            f"kısıtlı olduğu için başlangıç tarihi otomatik olarak {_d(final)} tarihine planlanmıştır."
        )
        for r, final in _chain_finals(applied, requested_g0)
    ]
    return {
        "g0": g0,
        "shifted": True,
        "requested_g0": requested_g0,
        "notice": " ".join(sentences),
        "restrictions": [
            {"id": r.id, "test_name": r.test_name, "reason": r.reason, "restricted_until": r.restricted_until.isoformat()}
            for r in applied
        ],
    }


def _chain_finals(applied: List[TestRestriction], requested_g0: date) -> List[Tuple[TestRestriction, date]]:
    """Her kısıtlama için, o kısıtlamanın ötelediği Yeni Gün 0 tarihini döner."""
    out = []
    for r in applied:
        out.append((r, next_business_day(r.restricted_until + timedelta(days=1))))
    return out


def persist_auto_schedule_notice(study: Study, shift: Dict[str, Any]) -> None:
    """Otomatik tarih bilgisini çalışma kaydına (dossier_metadata + description) yazar; ötelenmediyse eski notu temizler."""
    meta = dict(study.dossier_metadata or {})
    lines = [ln for ln in (study.description or "").splitlines() if not ln.strip().startswith(AUTO_NOTICE_PREFIX)]
    if shift.get("shifted"):
        meta["auto_schedule_notice"] = {
            "text": shift["notice"],
            "requested_start_date": shift["requested_g0"].isoformat(),
            "new_start_date": shift["g0"].isoformat(),
            "restrictions": shift["restrictions"],
        }
        lines.append(shift["notice"])
    else:
        existing = meta.get("auto_schedule_notice")
        if existing and existing.get("new_start_date") == shift["g0"].isoformat():
            # Aynı (zaten ötelenmiş) Gün 0 ile yeniden planlama (çakışma çözümü vb.) → notu koru
            if existing.get("text") and existing["text"] not in lines:
                lines.append(existing["text"])
        else:
            meta.pop("auto_schedule_notice", None)
    study.dossier_metadata = meta or None
    study.description = "\n".join(lines).strip() or None


def get_auto_schedule_notice(study: Study) -> Optional[Dict[str, Any]]:
    return (study.dossier_metadata or {}).get("auto_schedule_notice")


# ---------------------------------------------------------------------------
# 2) KAFES KAPASİTESİ
# ---------------------------------------------------------------------------
def _span_days(tpl: StudyTemplate, offset_days: int = 0) -> int:
    return max((ts.day for ts in tpl.steps), default=0) + max(0, offset_days)


def _collect_others(db: Session, study: Study) -> List[Dict[str, Any]]:
    """Kıyas kümesi: onaylı + yürütülen + diğer taslak çalışmaların şablon, Gün 0, bitiş ve ekstraksiyon ofseti bilgisi."""
    out: List[Dict[str, Any]] = []
    others = db.query(Study).filter(Study.id != study.id, Study.status.in_(_ACTIVE_STATUSES)).all()
    for o in others:
        tpl = _tpl_for(o.template_code)
        g0 = o.acclimatization_start_date or o.target_start_date
        if tpl is None or g0 is None:
            continue
        offset = o.extraction_start_offset_days or 0
        end = o.target_end_date or (g0 + timedelta(days=_span_days(tpl, offset)))
        out.append({"study": o, "tpl": tpl, "g0": g0, "end": end, "offset": offset})
    return out


def _daily_cage_usage(others: List[Dict[str, Any]], room_code: str, start: date, end: date) -> Dict[date, int]:
    usage: Dict[date, int] = {}
    for o in others:
        tpl: StudyTemplate = o["tpl"]
        if tpl.animal_room != room_code or tpl.cage_count <= 0:
            continue
        lo, hi = max(start, o["g0"]), min(end, o["end"])
        d = lo
        while d <= hi:
            usage[d] = usage.get(d, 0) + tpl.cage_count
            d += timedelta(days=1)
    return usage


def _cage_eval(
    room: AnimalRoomCapacity, tpl: StudyTemplate, others: List[Dict[str, Any]], g0: date, offset: int
) -> Dict[str, Any]:
    start, end = g0, g0 + timedelta(days=_span_days(tpl, offset))
    usage = _daily_cage_usage(others, tpl.animal_room, start, end)
    peak_other = max(usage.values(), default=0)
    peak_total = peak_other + tpl.cage_count
    physical = int(room.physical_cages)
    planning = int(room.planning_capacity)
    if peak_total > planning:
        level = "EXCEEDED"
    elif peak_total > physical:
        level = "FLEX"
    else:
        level = "OK"
    return {
        "kind": "CAGE",
        "room_code": room.room_code,
        "room_label": room.room_label,
        "species_label": room.species_label,
        "required": tpl.cage_count,
        "peak_other": peak_other,
        "peak_total": peak_total,
        "physical": physical,
        "flexibility_pct": float(room.flexibility_pct),
        "planning_capacity": planning,
        "level": level,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
    }


# ---------------------------------------------------------------------------
# 3) 24-72+ SAATLİK UZUN SÜRELİ CİHAZLAR
# ---------------------------------------------------------------------------
def _equipment_window(tpl_win: Tuple[str, int, str, int], g0: date, offset: int) -> Tuple[datetime, datetime]:
    code, day, hhmm, hours = tpl_win
    hh, mm = (int(x) for x in hhmm.split(":"))
    eff_day = day + (offset if day >= 4 else 0)
    start = datetime.combine(g0 + timedelta(days=eff_day), time(hh, mm))
    return start, start + timedelta(hours=hours)


def _equipment_eval(
    db: Session, tpl: StudyTemplate, others: List[Dict[str, Any]], g0: date, offset: int
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for win in tpl.equipment_windows:
        code = win[0]
        eq = db.query(Equipment).filter(Equipment.code == code).first()
        if eq is None:
            continue
        cap = int(eq.max_concurrent_studies or 1)
        start, end = _equipment_window(win, g0, offset)
        concurrent: List[str] = []
        for o in others:
            for ow in o["tpl"].equipment_windows:
                if ow[0] != code:
                    continue
                os_, oe = _equipment_window(ow, o["g0"], o["offset"])
                if min(end, oe) > max(start, os_):
                    concurrent.append(o["study"].study_code)
        used = 1 + len(concurrent)
        results.append(
            {
                "kind": "EQUIPMENT",
                "equipment_code": code,
                "equipment_name": eq.name,
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "hours": win[3],
                "capacity": cap,
                "used": used,
                "concurrent_studies": concurrent,
                "level": "EXCEEDED" if used > cap else "OK",
            }
        )
    return results


# ---------------------------------------------------------------------------
# BİRLEŞİK RAPOR VE ÇAKIŞMA ÜRETİMİ
# ---------------------------------------------------------------------------
def _cage_message(c: Dict[str, Any]) -> str:
    base = (
        f"{c['room_label']}: bu çalışma {c['required']} kafes gerektiriyor; en yoğun gün doluluğu "
        f"{c['peak_total']} / Fiziksel {c['physical']} · Planlama Kapasitesi {c['planning_capacity']} "
        f"(Dr. Anoop esneklik %{c['flexibility_pct']:g})."
    )
    if c["level"] == "FLEX":
        return "Bilgi: Fiziksel kafes sayısı aşılıyor, Dr. Anoop esneklik payı kullanılıyor. " + base
    if c["level"] == "EXCEEDED":
        return "Kapasite uyarısı: Sistem Planlama Kapasitesi aşıldı. " + base
    return base


def build_capacity_report(
    db: Session, study: Study, template: Optional[StudyTemplate] = None
) -> Dict[str, Any]:
    """Planlama yanıtında gösterilecek kafes + uzun süreli cihaz kapasite raporu (engellemeyen bilgi etiketleri dahil)."""
    tpl = template or _tpl_for(study.template_code)
    g0 = study.acclimatization_start_date or study.target_start_date
    report: Dict[str, Any] = {"cage": None, "equipment": [], "first_free_g0": None}
    if tpl is None or g0 is None:
        return report
    offset = study.extraction_start_offset_days or 0
    others = _collect_others(db, study)
    if tpl.animal_room and tpl.cage_count > 0:
        rooms = {r.room_code: r for r in ensure_default_room_capacities(db)}
        room = rooms.get(tpl.animal_room)
        if room is not None:
            cage = _cage_eval(room, tpl, others, g0, offset)
            cage["message"] = _cage_message(cage)
            report["cage"] = cage
    report["equipment"] = _equipment_eval(db, tpl, others, g0, offset)
    needs_redirect = (report["cage"] and report["cage"]["level"] == "EXCEEDED") or any(
        e["level"] == "EXCEEDED" for e in report["equipment"]
    )
    if needs_redirect:
        report["first_free_g0"] = find_first_free_g0(db, study, tpl, g0, offset)
        if report["cage"] and report["cage"]["level"] == "EXCEEDED":
            report["cage"]["first_free_date"] = report["first_free_g0"]
    return report


def find_first_free_g0(
    db: Session, study: Study, tpl: StudyTemplate, from_g0: date, offset: int, max_days: int = 240
) -> Optional[str]:
    """Kafes (≤ Planlama Kapasitesi) ve uzun süreli cihaz kapasitesi uygun olan ilk Gün 0 (iş günü) tarihini bulur."""
    others = _collect_others(db, study)
    rooms = {r.room_code: r for r in ensure_default_room_capacities(db)}
    room = rooms.get(tpl.animal_room) if tpl.animal_room else None
    restrictions = db.query(TestRestriction).filter(TestRestriction.is_active == True).all()  # noqa: E712
    cand = from_g0
    for _ in range(max_days):
        cand = next_business_day(cand + timedelta(days=1))
        if any(_restriction_matches(r, tpl.code, cand) for r in restrictions):
            continue
        if room is not None and tpl.cage_count > 0 and _cage_eval(room, tpl, others, cand, offset)["level"] == "EXCEEDED":
            continue
        if any(e["level"] == "EXCEEDED" for e in _equipment_eval(db, tpl, others, cand, offset)):
            continue
        return cand.isoformat()
    return None


def evaluate_capacity_conflicts(
    db: Session, study: Study, steps: List[Any], template: Optional[StudyTemplate] = None
) -> List[Tuple[Conflict, List[int]]]:
    """
    Çakışma motoruna eklenen FAZ 8.1 denetimleri. Kaydedilmemiş (db.add edilmemiş) Conflict nesneleri döner.
    FLEX seviyesi çakışma ÜRETMEZ (yalnızca bilgi etiketi); EXCEEDED seviyesi CRITICAL kapasite uyarısı üretir.
    """
    tpl = template or _tpl_for(study.template_code)
    if tpl is None or not steps:
        return []
    report = build_capacity_report(db, study, tpl)
    anchor = steps[0]
    findings: List[Tuple[Conflict, List[int]]] = []

    cage = report.get("cage")
    if cage and cage["level"] == "EXCEEDED":
        ff = report.get("first_free_g0")
        findings.append(
            (
                Conflict(
                    conflict_type=ConflictType.ROOM_CAPACITY_EXCEEDED,
                    severity=ConflictSeverity.CRITICAL,
                    title=f"Hayvan Odası Kafes Kapasitesi Aşıldı: {cage['room_label']} (Planlama Kapasitesi: {cage['planning_capacity']})",
                    description=(
                        f"{cage['message']} Dönem: {cage['window_start']} – {cage['window_end']}."
                        + (f" İlk uygun başlangıç tarihi: {ff}." if ff else "")
                    ),
                    study_id=study.id,
                    step_id=anchor.id,
                ),
                [anchor.id],
            )
        )

    ts_by_code = {w[0]: w for w in tpl.equipment_windows}
    for eq in report.get("equipment", []):
        if eq["level"] != "EXCEEDED":
            continue
        win = ts_by_code.get(eq["equipment_code"])
        target = anchor
        if win is not None:
            win_day = datetime.fromisoformat(eq["window_start"]).date()
            for s in steps:
                if s.planned_start.date() == win_day:
                    target = s
                    break
        ff = report.get("first_free_g0")
        findings.append(
            (
                Conflict(
                    conflict_type=ConflictType.EQUIPMENT_OVERLAP,
                    severity=ConflictSeverity.CRITICAL,
                    title=(
                        f"Uzun Süreli Cihaz Kapasite Aşımı: {eq['equipment_name']} ({eq['equipment_code']}, "
                        f"{eq['hours']} saat) — Max: {eq['capacity']}"
                    ),
                    description=(
                        f"'{eq['equipment_name']}' cihazında {eq['window_start'][:16].replace('T', ' ')} – "
                        f"{eq['window_end'][:16].replace('T', ' ')} ({eq['hours']} saatlik pencere) eşzamanlı çalışma "
                        f"kapasitesi ({eq['capacity']}) aşıldı; çakışan çalışmalar: "
                        f"{', '.join(eq['concurrent_studies']) or '—'}."
                        + (f" İlk uygun başlangıç tarihi: {ff}." if ff else "")
                    ),
                    study_id=study.id,
                    step_id=target.id,
                ),
                [target.id],
            )
        )
    return findings


def is_capacity_conflict(conflict: Conflict) -> bool:
    return conflict.conflict_type == ConflictType.ROOM_CAPACITY_EXCEEDED or (
        conflict.conflict_type == ConflictType.EQUIPMENT_OVERLAP and "Uzun Süreli Cihaz" in (conflict.title or "")
    )


# ---------------------------------------------------------------------------
# AYARLAR EKRANI İÇİN ODA DOLULUK ÖZETİ
# ---------------------------------------------------------------------------
def room_capacity_overview(db: Session) -> List[Dict[str, Any]]:
    rooms = ensure_default_room_capacities(db)
    today = date.today()
    dummy = Study(id=-1)
    others = _collect_others(db, dummy)
    out = []
    for r in rooms:
        usage = _daily_cage_usage(others, r.room_code, today - timedelta(days=30), today + timedelta(days=120))
        current = usage.get(today, 0)
        peak = max(usage.values(), default=0)
        level = "EXCEEDED" if peak > r.planning_capacity else "FLEX" if peak > r.physical_cages else "OK"
        out.append(
            {
                "id": r.id,
                "room_code": r.room_code,
                "room_label": r.room_label,
                "species_label": r.species_label,
                "physical_cages": int(r.physical_cages),
                "flexibility_pct": float(r.flexibility_pct),
                "planning_capacity": int(r.planning_capacity),
                "available_animals": FACILITY_AVAILABLE_ANIMALS.get(r.room_code, 0),
                "current_used": current,
                "peak_used": peak,
                "level": level,
            }
        )
    return out
