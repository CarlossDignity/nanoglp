"""
GLP ÇALIŞMA ŞABLONLARI (Study Templates) — FAZ 6.4

Kullanıcı yalnızca "Aklimatizasyon Başlangıç Tarihi"ni (Gün 0) girer; şablondaki adımlar
gün ofsetlerine göre otomatik dizilir.
FAZ 6.4 ile birlikte görev süreleri ve biyolojik tolerans pencereleri veritabanındaki
`system_calibrations` tablosundan dinamik olarak okunur (Settings.jsx ekranından kalibre edilebilir).
"""
from dataclasses import dataclass, replace
from datetime import time
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from app.models.user import UserRole


@dataclass(frozen=True)
class TemplateStep:
    order: int
    day: int                       # Gün 0'a göre ofset
    name: str
    step_type: str
    start: time                    # Gün içindeki planlanan başlangıç saati
    duration_minutes: int          # Personelin fiilen meşgul olduğu süre (cihazda bekleme dahil DEĞİL)
    roles: Tuple[UserRole, ...]    # Adımda görev alması zorunlu roller
    is_biological_fixed_time: bool = False
    tolerance_minutes: int = 0
    note: str = ""


@dataclass(frozen=True)
class StudyTemplate:
    code: str
    standard: str
    title: str
    description: str
    steps: Tuple[TemplateStep, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "standard": self.standard,
            "title": self.title,
            "description": self.description,
            "steps": [
                {
                    "order": s.order,
                    "day": s.day,
                    "name": s.name,
                    "step_type": s.step_type,
                    "start": s.start.strftime("%H:%M"),
                    "duration_minutes": s.duration_minutes,
                    "roles": [r.value for r in s.roles],
                    "is_biological_fixed_time": s.is_biological_fixed_time,
                    "tolerance_minutes": s.tolerance_minutes,
                    "note": s.note,
                }
                for s in self.steps
            ],
        }


# ---------------------------------------------------------------------------
# 1) ISO 10993-23 — İNTRAKÜTANÖZ REAKTİVİTE TESTİ (GLP2026-026)
# ---------------------------------------------------------------------------
ISO_10993_23_IC = StudyTemplate(
    code="ISO_10993_23_IC",
    standard="ISO 10993-23",
    title="İntrakütanöz Reaktivite Testi",
    description="Polar ve non-polar ekstraktların intradermal uygulaması; 24/48/72. saat gözlem ve skorlama.",
    steps=(
        TemplateStep(
            order=1, day=0,
            name="Veteriner Muayenesi ve Aklimatizasyona Alma",
            step_type="Aklimatizasyon",
            start=time(9, 0), duration_minutes=120,
            roles=(UserRole.TFM,),
        ),
        TemplateStep(
            order=2, day=4,
            name="72 Saatlik Ekstraksiyon Kurulumu",
            step_type="Ekstraksiyon",
            start=time(8, 0), duration_minutes=90,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=30,
            note="Ekstraksiyon kurulum bitiminde başlar; 72 saat sonra Gün 7 uygulamasından hemen önce tamamlanır.",
        ),
        TemplateStep(
            order=3, day=7,
            name="Tüy Kesimi, İntradermal Uygulama (Polar/Non-Polar) ve 1. Saat Gözlemi",
            step_type="Uygulama",
            start=time(9, 0), duration_minutes=180,
            roles=(UserRole.STUDY_DIRECTOR, UserRole.TECHNICIAN),
            is_biological_fixed_time=True, tolerance_minutes=15,
            note="Enjeksiyon referans saati ≈10:00; 24/48/72. saat gözlemleri bu saate sabitlenir.",
        ),
        TemplateStep(
            order=4, day=8,
            name="24. Saat Gözlemi ve Skorlama",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=60,
        ),
        TemplateStep(
            order=5, day=9,
            name="48. Saat Gözlemi ve Skorlama",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=60,
        ),
        TemplateStep(
            order=6, day=10,
            name="72. Saat Gözlemi, Skorlama ve Ötenazi",
            step_type="Gözlem / Terminasyon",
            start=time(10, 0), duration_minutes=120,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=60,
        ),
    ),
)

# ---------------------------------------------------------------------------
# 2) ISO 10993-5 — IN VITRO SİTOTOKSİSİTE TESTİ (GLP2026-024)
# ---------------------------------------------------------------------------
ISO_10993_5_CYTO = StudyTemplate(
    code="ISO_10993_5_CYTO",
    standard="ISO 10993-5",
    title="In Vitro Sitotoksisite Testi",
    description="L929 memeli fibroblast hücre hattı üzerinde ekstrakt yöntemiyle in vitro sitotoksisite ve MTT canlılık analizi.",
    steps=(
        TemplateStep(
            order=1, day=0,
            name="L929 Hücre Kültürü Pasajlama ve 96 Kuyucuklu Plak Ekimi",
            step_type="Hazırlık",
            start=time(9, 0), duration_minutes=90,
            roles=(UserRole.TECHNICIAN,),
        ),
        TemplateStep(
            order=2, day=4,
            name="Ekstraksiyon Kurulumu (ISO 10993-12 Kültür Besiyeri)",
            step_type="Ekstraksiyon",
            start=time(8, 30), duration_minutes=90,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=30,
            note="37 ± 1 °C'de 24/72 saatlik ekstraksiyon süreci başlatılır.",
        ),
        TemplateStep(
            order=3, day=7,
            name="Hücrelere Ekstrakt Dozlaması ve CO2 İnkübatörüne Alma",
            step_type="Uygulama",
            start=time(9, 30), duration_minutes=120,
            roles=(UserRole.STUDY_DIRECTOR, UserRole.TECHNICIAN),
            is_biological_fixed_time=True, tolerance_minutes=15,
        ),
        TemplateStep(
            order=4, day=8,
            name="24. Saat Mikroskobik Morfoloji Değerlendirmesi ve MTT Spektrofotometrik Okuma",
            step_type="Gözlem / Terminasyon",
            start=time(10, 0), duration_minutes=120,
            roles=(UserRole.STUDY_DIRECTOR, UserRole.TECHNICIAN),
            is_biological_fixed_time=True, tolerance_minutes=30,
        ),
    ),
)

# ---------------------------------------------------------------------------
# 3) ISO 10993-10 — SENSİTİZASYON TESTİ (GLP2026-031)
# ---------------------------------------------------------------------------
ISO_10993_10_SENS = StudyTemplate(
    code="ISO_10993_10_SENS",
    standard="ISO 10993-10",
    title="Sensitizasyon Testi (GPMT)",
    description="Kobay maksimizasyon testi (GPMT) ile intradermal/topikal indüksiyon, challenge ve 24/48s duyarlılık skorlaması.",
    steps=(
        TemplateStep(
            order=1, day=0,
            name="Veteriner Muayenesi ve Aklimatizasyona Alma (Kobay)",
            step_type="Aklimatizasyon",
            start=time(9, 0), duration_minutes=120,
            roles=(UserRole.TFM,),
        ),
        TemplateStep(
            order=2, day=4,
            name="72 Saatlik Ekstraksiyon Kurulumu",
            step_type="Ekstraksiyon",
            start=time(8, 0), duration_minutes=90,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=30,
        ),
        TemplateStep(
            order=3, day=7,
            name="İndüksiyon Fazı (İntradermal / Topikal Uygulama)",
            step_type="Uygulama",
            start=time(9, 0), duration_minutes=180,
            roles=(UserRole.STUDY_DIRECTOR, UserRole.TECHNICIAN),
            is_biological_fixed_time=True, tolerance_minutes=15,
        ),
        TemplateStep(
            order=4, day=8,
            name="24. Saat Eritem ve Ödem Skorlama Gözlemi (Magnusson-Kligman)",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=60,
        ),
        TemplateStep(
            order=5, day=9,
            name="48. Saat Duyarlılık Gözlemi, Skorlama ve Çalışma Sonlandırma",
            step_type="Gözlem / Terminasyon",
            start=time(10, 0), duration_minutes=90,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=60,
        ),
    ),
)

# ---------------------------------------------------------------------------
# 4) ISO 10993-11 — AKUT SİSTEMİK TOKSİSİTE TESTİ (GLP2026-034)
# ---------------------------------------------------------------------------
ISO_10993_11_ACUTE = StudyTemplate(
    code="ISO_10993_11_ACUTE",
    standard="ISO 10993-11",
    title="Akut Sistemik Toksisite Testi",
    description="Polar ve apolar ekstraktların sistemik (IV/IP) uygulanması; 4/24/48/72. saat klinik toksisite, tartım ve nekropsi.",
    steps=(
        TemplateStep(
            order=1, day=0,
            name="Veteriner Muayenesi ve Aklimatizasyona Alma",
            step_type="Aklimatizasyon",
            start=time(9, 0), duration_minutes=120,
            roles=(UserRole.TFM,),
        ),
        TemplateStep(
            order=2, day=4,
            name="72 Saatlik Ekstraksiyon Kurulumu",
            step_type="Ekstraksiyon",
            start=time(8, 0), duration_minutes=90,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=30,
        ),
        TemplateStep(
            order=3, day=7,
            name="Sistemik Dozlama (IV / IP Uygulama) ve 4. Saat Klinik Gözlem",
            step_type="Uygulama",
            start=time(9, 0), duration_minutes=180,
            roles=(UserRole.STUDY_DIRECTOR, UserRole.TECHNICIAN),
            is_biological_fixed_time=True, tolerance_minutes=15,
        ),
        TemplateStep(
            order=4, day=8,
            name="24. Saat Klinik Toksisite ve Vücut Ağırlığı Gözlemi",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=60,
        ),
        TemplateStep(
            order=5, day=9,
            name="48. Saat Klinik Toksisite Gözlemi",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=60,
        ),
        TemplateStep(
            order=6, day=10,
            name="72. Saat Gözlemi, Tartım ve Nekropsi / Terminasyon",
            step_type="Gözlem / Terminasyon",
            start=time(10, 0), duration_minutes=120,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=60,
        ),
    ),
)

TEMPLATES: Dict[str, StudyTemplate] = {
    t.code: t
    for t in (
        ISO_10993_23_IC,
        ISO_10993_5_CYTO,
        ISO_10993_10_SENS,
        ISO_10993_11_ACUTE,
    )
}
DEFAULT_TEMPLATE_CODE = ISO_10993_23_IC.code


def _parse_hhmm(val: str, fallback: time) -> time:
    try:
        parts = str(val).strip().split(":")
        return time(int(parts[0]), int(parts[1]))
    except Exception:
        return fallback


def ensure_default_calibrations(db: Session) -> List[Any]:
    """
    Veritabanındaki `system_calibrations` tablosunu kontrol eder; şablon adımları eksikse
    varsayılan kalibrasyon kayıtlarını oluşturur.
    """
    from app.models.calibration import SystemCalibration

    existing = db.query(SystemCalibration).order_by(SystemCalibration.id.asc()).all()
    existing_keys = {(c.template_code, c.step_order) for c in existing}
    added = False
    for tpl in TEMPLATES.values():
        for st in tpl.steps:
            if (tpl.code, st.order) not in existing_keys:
                row = SystemCalibration(
                    template_code=tpl.code,
                    step_order=st.order,
                    study_day=st.day,
                    step_name=st.name,
                    category=st.step_type,
                    start_time=st.start.strftime("%H:%M"),
                    duration_minutes=st.duration_minutes,
                    tolerance_minutes=st.tolerance_minutes,
                    is_biological_fixed_time=st.is_biological_fixed_time,
                )
                db.add(row)
                added = True
    if added:
        db.commit()
        existing = db.query(SystemCalibration).order_by(SystemCalibration.id.asc()).all()
    return existing


def get_template(code: str, db: Optional[Session] = None) -> StudyTemplate:
    try:
        base_tpl = TEMPLATES[code]
    except KeyError:
        raise ValueError(f"Tanımsız çalışma şablonu: '{code}'. Mevcut: {', '.join(TEMPLATES)}")

    if db is None:
        return base_tpl

    try:
        from app.models.calibration import SystemCalibration

        ensure_default_calibrations(db)
        cal_rows = (
            db.query(SystemCalibration)
            .filter(SystemCalibration.template_code == base_tpl.code)
            .order_by(SystemCalibration.step_order.asc())
            .all()
        )
        if not cal_rows:
            return base_tpl
        cal_by_order = {c.step_order: c for c in cal_rows}
        updated_steps: List[TemplateStep] = []
        for s in base_tpl.steps:
            cal = cal_by_order.get(s.order)
            if cal is not None:
                updated_steps.append(
                    replace(
                        s,
                        name=cal.step_name or s.name,
                        step_type=cal.category or s.step_type,
                        start=_parse_hhmm(cal.start_time, s.start),
                        duration_minutes=max(1, int(cal.duration_minutes or s.duration_minutes)),
                        tolerance_minutes=max(0, int(cal.tolerance_minutes if cal.tolerance_minutes is not None else s.tolerance_minutes)),
                        is_biological_fixed_time=bool(
                            cal.is_biological_fixed_time if cal.is_biological_fixed_time is not None else s.is_biological_fixed_time
                        ),
                    )
                )
            else:
                updated_steps.append(s)
        return replace(base_tpl, steps=tuple(updated_steps))
    except Exception:
        return base_tpl


def get_all_templates_calibrated(db: Optional[Session] = None) -> List[StudyTemplate]:
    return [get_template(code, db=db) for code in TEMPLATES]
