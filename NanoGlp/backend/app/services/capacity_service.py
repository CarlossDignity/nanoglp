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


def _collect_others(
    db: Session, study: Study, template_override: Optional[StudyTemplate] = None
) -> List[Dict[str, Any]]:
    """Kıyas kümesi: onaylı + yürütülen + diğer taslak çalışmaların şablon, Gün 0, bitiş ve ekstraksiyon ofseti bilgisi."""
    out: List[Dict[str, Any]] = []
    others = db.query(Study).filter(Study.id != study.id, Study.status.in_(_ACTIVE_STATUSES)).all()
    for o in others:
        if template_override is not None and resolve_template_code(o.template_code) == template_override.code:
            tpl: Optional[StudyTemplate] = template_override
        else:
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
    room: AnimalRoomCapacity,
    tpl: StudyTemplate,
    others: List[Dict[str, Any]],
    g0: date,
    offset: int,
    end_date: Optional[date] = None,
) -> Dict[str, Any]:
    default_end = g0 + timedelta(days=_span_days(tpl, offset))
    start, end = g0, (max(default_end, end_date) if end_date is not None else default_end)
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
# 3) 24-72+ SAATLİK UZUN SÜRELİ CİHAZLAR VE EŞZAMANLI TEPE KULLANIM (SWEEP-LINE)
# ---------------------------------------------------------------------------
def compute_peak_concurrent_details(
    window_start: datetime,
    window_end: datetime,
    other_intervals: List[Tuple[Any, ...]],
) -> Dict[str, Any]:
    """
    Yarı-açık aralık kuralına (`[start, end)`) göre `[window_start, window_end)` hedef penceresi
    içinde herhangi bir `t` anında aynı anda aktif olan maksimum eşzamanlı kullanım sayısını
    (sweep-line / tepe eşzamanlı yük — `peak_concurrent_usage`) hesaplar.

    Bitiş ve başlangıç sınırlarında:
      - Bir rezervasyon tam `09:00`'da bitiyor ve diğeri `09:00`'da başlıyorsa (`end_1 == start_2`),
        yarı-açık `[start, end)` kuralı gereği aynı `t` anında aktif sayılmazlar.
      - Hedef pencerenin farklı bölümleriyle kesişen ancak birbiriyle hiç çakışmayan iki çalışma
        doğrudan toplanmaz; tepe noktadaki gerçek eşzamanlı sayı (`peak_other`) alınır.
    """
    if window_end is None or window_start is None or window_end <= window_start:
        return {
            "peak_other": 0,
            "peak_total": 1,
            "peak_concurrent_usage": 1,
            "peak_items": [],
            "overlapping_items": [],
            "peak_time": window_start,
        }

    clamped: List[Tuple[datetime, datetime, Any, Any]] = []
    overlapping_items: List[Any] = []
    seen_overlap_keys: set = set()

    for idx, entry in enumerate(other_intervals):
        if isinstance(entry, dict):
            o_start = entry.get("start") or entry.get("window_start") or entry.get("planned_start")
            o_end = entry.get("end") or entry.get("window_end") or entry.get("planned_end")
            item = entry.get("item", entry)
            key = entry.get("key", idx)
        else:
            o_start = entry[0]
            o_end = entry[1]
            item = entry[2] if len(entry) > 2 else entry
            key = entry[3] if len(entry) > 3 else (item if isinstance(item, (int, str)) else idx)

        if o_start is None or o_end is None or o_end <= o_start:
            continue

        c_start = max(window_start, o_start)
        c_end = min(window_end, o_end)
        # Yarı-açık [start, end) kesişim koşulu: max(start) < min(end)
        if c_start < c_end:
            clamped.append((c_start, c_end, item, key))
            if key not in seen_overlap_keys:
                seen_overlap_keys.add(key)
                overlapping_items.append(item)

    if not clamped:
        return {
            "peak_other": 0,
            "peak_total": 1,
            "peak_concurrent_usage": 1,
            "peak_items": [],
            "overlapping_items": [],
            "peak_time": window_start,
        }

    # Sweep-line aday noktaları: yarı-açık aralıklarda eşzamanlı maksimum küme her zaman
    # aktif aralıklardan birinin sol uç noktasında (c_start) gerçekleşir.
    # Aynı anda biten (-1) aralıklar `c_s <= t < c_e` koşulundaki `< c_e` sayesinde
    # tam `t == c_e` anında otomatik olarak kapsam dışı kalır.
    candidate_times = sorted({window_start} | {c_s for c_s, _, _, _ in clamped})
    peak_other = 0
    peak_items: List[Any] = []
    peak_time: datetime = window_start

    for t in candidate_times:
        active_items: List[Any] = []
        active_keys: set = set()
        for c_s, c_e, item, key in clamped:
            if c_s <= t < c_e and key not in active_keys:
                active_keys.add(key)
                active_items.append(item)
        if len(active_keys) > peak_other:
            peak_other = len(active_keys)
            peak_items = active_items
            peak_time = t

    peak_total = 1 + peak_other
    return {
        "peak_other": peak_other,
        "peak_total": peak_total,
        "peak_concurrent_usage": peak_total,
        "peak_items": peak_items,
        "overlapping_items": overlapping_items,
        "peak_time": peak_time,
    }


def peak_concurrent_usage(
    window_start: Any,
    window_end: Optional[datetime] = None,
    other_intervals: Optional[List[Tuple[Any, ...]]] = None,
    include_self: bool = True,
) -> int:
    """
    Bir `[window_start, window_end)` hedef aralığındaki (veya doğrudan aralık listesi verildiğinde
    tüm zaman eksenindeki) maksimum eşzamanlı kullanım sayısını (`peak_concurrent_usage`) döner.
    """
    if window_end is None and other_intervals is None and isinstance(window_start, (list, tuple)):
        intervals = list(window_start)
        events: List[Tuple[datetime, int]] = []
        for entry in intervals:
            s, e = (entry[0], entry[1]) if not isinstance(entry, dict) else (entry["start"], entry["end"])
            if s is not None and e is not None and e > s:
                events.append((s, 1))
                events.append((e, -1))
        events.sort(key=lambda ev: (ev[0], ev[1]))
        cur = 0
        best = 0
        for _t, delta in events:
            cur += delta
            if cur > best:
                best = cur
        return best

    details = compute_peak_concurrent_details(window_start, window_end, list(other_intervals or []))
    return details["peak_total"] if include_self else details["peak_other"]


def _equipment_window(tpl_win: Tuple[str, int, str, int], g0: date, offset: int) -> Tuple[datetime, datetime]:
    code, day, hhmm, hours = tpl_win
    hh, mm = (int(x) for x in hhmm.split(":"))
    eff_day = day + (offset if day >= 4 else 0)
    start = datetime.combine(g0 + timedelta(days=eff_day), time(hh, mm))
    return start, start + timedelta(hours=hours)


def _equipment_eval(
    db: Session, tpl: StudyTemplate, others: List[Dict[str, Any]], g0: date, offset: int
) -> List[Dict[str, Any]]:
    from app.seed import LONG_DURATION_EQUIPMENT

    default_eq_map = {c[0]: (c[1], c[3]) for c in LONG_DURATION_EQUIPMENT}
    results: List[Dict[str, Any]] = []
    for win in tpl.equipment_windows:
        code = win[0]
        eq = db.query(Equipment).filter(Equipment.code == code).first()
        if eq is None:
            if code in default_eq_map:
                eq_name, default_cap = default_eq_map[code]
                cap = int(default_cap or 1)
            else:
                continue
        else:
            eq_name = eq.name
            default_cap = default_eq_map.get(code, (eq.name, 1))[1]
            cap = int(eq.max_concurrent_studies or default_cap or 1)
        start, end = _equipment_window(win, g0, offset)
        other_intervals: List[Tuple[datetime, datetime, str, str]] = []
        for o in others:
            for ow in o["tpl"].equipment_windows:
                if ow[0] != code:
                    continue
                os_, oe = _equipment_window(ow, o["g0"], o["offset"])
                other_intervals.append((os_, oe, o["study"].study_code, o["study"].study_code))
        peak_info = compute_peak_concurrent_details(start, end, other_intervals)
        used = peak_info["peak_total"]
        concurrent = list(peak_info["peak_items"])
        results.append(
            {
                "kind": "EQUIPMENT",
                "equipment_code": code,
                "equipment_name": eq_name,
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "hours": win[3],
                "capacity": cap,
                "used": used,
                "peak_concurrent_usage": used,
                "concurrent_studies": concurrent,
                "overlapping_studies": list(peak_info["overlapping_items"]),
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
    db: Session,
    study: Study,
    template: Optional[StudyTemplate] = None,
    commit_defaults: bool = False,
) -> Dict[str, Any]:
    """Planlama yanıtında gösterilecek kafes + uzun süreli cihaz kapasite raporu (engellemeyen bilgi etiketleri dahil)."""
    tpl = template or _tpl_for(study.template_code)
    g0 = study.acclimatization_start_date or study.target_start_date
    report: Dict[str, Any] = {"cage": None, "equipment": [], "first_free_g0": None}
    if tpl is None or g0 is None:
        return report
    offset = study.extraction_start_offset_days or 0
    others = _collect_others(db, study, template_override=template)
    if tpl.animal_room and tpl.cage_count > 0:
        rooms = {r.room_code: r for r in ensure_default_room_capacities(db, commit=commit_defaults)}
        room = rooms.get(tpl.animal_room)
        if room is not None:
            cage = _cage_eval(room, tpl, others, g0, offset, end_date=study.target_end_date)
            cage["message"] = _cage_message(cage)
            report["cage"] = cage
    report["equipment"] = _equipment_eval(db, tpl, others, g0, offset)
    needs_redirect = (report["cage"] and report["cage"]["level"] == "EXCEEDED") or any(
        e["level"] == "EXCEEDED" for e in report["equipment"]
    )
    if needs_redirect:
        report["first_free_g0"] = find_first_free_g0(db, study, tpl, g0, offset, commit_defaults=commit_defaults)
        if report["cage"] and report["cage"]["level"] == "EXCEEDED":
            report["cage"]["first_free_date"] = report["first_free_g0"]
    return report


def find_first_free_g0(
    db: Session,
    study: Study,
    tpl: StudyTemplate,
    from_g0: date,
    offset: int,
    max_days: int = 240,
    commit_defaults: bool = False,
) -> Optional[str]:
    """Kafes (≤ Planlama Kapasitesi) ve uzun süreli cihaz kapasitesi uygun olan ilk Gün 0 (iş günü) tarihini bulur."""
    others = _collect_others(db, study, template_override=tpl)
    rooms = {r.room_code: r for r in ensure_default_room_capacities(db, commit=commit_defaults)}
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


evaluate_study_capacity_conflicts = evaluate_capacity_conflicts


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
