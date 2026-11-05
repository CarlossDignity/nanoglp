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
    # Biyolojik referans olay ve bağımlı gözlem modellemesi
    is_biological_reference: bool = False
    reference_event_time: Optional[time] = None
    reference_step_order: Optional[int] = None
    reference_offset_hours: Optional[int] = None


@dataclass(frozen=True)
class StudyTemplate:
    code: str
    standard: str
    title: str
    description: str
    steps: Tuple[TemplateStep, ...]
    # FAZ 8.1 — Kafes (hayvan odası) ve 24-72s uzun süreli cihaz metaverisi
    animal_room: str = ""                       # RABBIT_ROOM / RAT_ROOM / GUINEA_PIG_ROOM / MOUSE_ROOM ("" = hayvan yok)
    cage_count: int = 0                         # Çalışmanın gerektirdiği kafes sayısı
    species_label: str = ""
    equipment_codes: Tuple[str, ...] = ()       # Bilgi amaçlı: kullanılan 24-72s darboğaz cihazları
    # (cihaz kodu, Gün ofseti, "HH:MM", süre saat) — motorun kapasite denetimi uyguladığı pencereler
    equipment_windows: Tuple[Tuple[str, int, str, int], ...] = ()
    docx_title_en: str = ""
    docx_species_en: str = ""
    # FAZ 8.3 — IN VIVO TEST SÜRELERİ ve TEKRAR KULLANIM (Study Status last version (2).xlsx Sekme 2 & 3)
    animal_count: int = 0
    cohorts: int = 1
    max_animals: int = 0
    quarantine_days: int = 0
    acclimatization_days: int = 0
    experiment_days: int = 0
    qa_audit_days: int = 0
    report_days: int = 0
    tat_without_quarantine_days: int = 0
    tat_with_quarantine_days: int = 0
    reuse_allowed: bool = False
    animal_fate_tr: str = ""
    animal_fate_en: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "standard": self.standard,
            "title": self.title,
            "description": self.description,
            "animal_room": self.animal_room,
            "cage_count": self.cage_count,
            "species_label": self.species_label,
            "equipment_codes": list(self.equipment_codes),
            "animal_count": self.animal_count,
            "cohorts": self.cohorts,
            "max_animals": self.max_animals,
            "quarantine_days": self.quarantine_days,
            "acclimatization_days": self.acclimatization_days,
            "experiment_days": self.experiment_days,
            "qa_audit_days": self.qa_audit_days,
            "report_days": self.report_days,
            "tat_without_quarantine_days": self.tat_without_quarantine_days,
            "tat_with_quarantine_days": self.tat_with_quarantine_days,
            "reuse_allowed": self.reuse_allowed,
            "animal_fate_tr": self.animal_fate_tr,
            "animal_fate_en": self.animal_fate_en,
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
                    "is_biological_reference": s.is_biological_reference,
                    "reference_event_time": s.reference_event_time.strftime("%H:%M") if s.reference_event_time else None,
                    "reference_step_order": s.reference_step_order,
                    "reference_offset_hours": s.reference_offset_hours,
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
            is_biological_fixed_time=True, tolerance_minutes=120,
            note="Ekstraksiyon kurulum bitiminde başlar; 72 saat sonra Gün 7 uygulamasından hemen önce tamamlanır (±2 saat tolerans).",
        ),
        TemplateStep(
            order=3, day=7,
            name="Tüy Kesimi, İntradermal Uygulama (Polar/Non-Polar) ve 1. Saat Gözlemi",
            step_type="Uygulama",
            start=time(9, 0), duration_minutes=180,
            roles=(UserRole.STUDY_DIRECTOR, UserRole.TECHNICIAN),
            is_biological_fixed_time=True, tolerance_minutes=15,
            note="Enjeksiyon referans saati ≈10:00; 24/48/72. saat gözlemleri bu saate sabitlenir.",
            is_biological_reference=True,
            reference_event_time=time(10, 0),
        ),
        TemplateStep(
            order=4, day=8,
            name="24. Saat Gözlemi ve Skorlama",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=120,
            reference_step_order=3,
            reference_offset_hours=24,
        ),
        TemplateStep(
            order=5, day=9,
            name="48. Saat Gözlemi ve Skorlama",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=120,
            reference_step_order=3,
            reference_offset_hours=48,
        ),
        TemplateStep(
            order=6, day=10,
            name="72. Saat Gözlemi, Skorlama ve Ötenazi",
            step_type="Gözlem / Terminasyon",
            start=time(10, 0), duration_minutes=120,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=120,
            reference_step_order=3,
            reference_offset_hours=72,
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
            is_biological_reference=True,
            reference_event_time=time(10, 0),
        ),
        TemplateStep(
            order=4, day=8,
            name="24. Saat Mikroskobik Morfoloji Değerlendirmesi ve MTT Spektrofotometrik Okuma",
            step_type="Gözlem / Terminasyon",
            start=time(10, 0), duration_minutes=120,
            roles=(UserRole.STUDY_DIRECTOR, UserRole.TECHNICIAN),
            is_biological_fixed_time=True, tolerance_minutes=30,
            reference_step_order=3,
            reference_offset_hours=24,
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
            is_biological_reference=True,
            reference_event_time=time(10, 0),
        ),
        TemplateStep(
            order=4, day=8,
            name="24. Saat Eritem ve Ödem Skorlama Gözlemi (Magnusson-Kligman)",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=60,
            reference_step_order=3,
            reference_offset_hours=24,
        ),
        TemplateStep(
            order=5, day=9,
            name="48. Saat Duyarlılık Gözlemi, Skorlama ve Çalışma Sonlandırma",
            step_type="Gözlem / Terminasyon",
            start=time(10, 0), duration_minutes=90,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=60,
            reference_step_order=3,
            reference_offset_hours=48,
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
            is_biological_reference=True,
            reference_event_time=time(10, 0),
        ),
        TemplateStep(
            order=4, day=8,
            name="24. Saat Klinik Toksisite ve Vücut Ağırlığı Gözlemi",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=60,
            reference_step_order=3,
            reference_offset_hours=24,
        ),
        TemplateStep(
            order=5, day=9,
            name="48. Saat Klinik Toksisite Gözlemi",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=60,
            reference_step_order=3,
            reference_offset_hours=48,
        ),
        TemplateStep(
            order=6, day=10,
            name="72. Saat Gözlemi, Tartım ve Nekropsi / Terminasyon",
            step_type="Gözlem / Terminasyon",
            start=time(10, 0), duration_minutes=120,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=60,
            reference_step_order=3,
            reference_offset_hours=72,
        ),
    ),
)

# ---------------------------------------------------------------------------
# 5) ISO 10993-6 — İMPLANTASYON TESTİ (DERİ ALTI) — FAZ 8.1 (GLP2026-072)
# ---------------------------------------------------------------------------
ISO_10993_6_IMP = StudyTemplate(
    code="ISO_10993_6_IMP",
    standard="ISO 10993-6",
    title="İmplantasyon Testi (Deri Altı / Subkutan)",
    description=(
        "Yeni Zelanda tavşanlarında deri altı (subkutan) implantasyon; 24/48/72. saat ve haftalık klinik gözlem, "
        "28. gün terminasyon, nekropsi ve implant bölgesi makroskopik/histopatolojik numune alımı."
    ),
    steps=(
        TemplateStep(
            order=1, day=0,
            name="Veteriner Muayenesi ve Aklimatizasyona Alma (Tavşan)",
            step_type="Aklimatizasyon",
            start=time(9, 0), duration_minutes=120,
            roles=(UserRole.TFM,),
        ),
        TemplateStep(
            order=2, day=4,
            name="Test Maddesi Hazırlığı, Sterilite Kontrolü ve İmplant Alanı Hazırlığı",
            step_type="Hazırlık",
            start=time(8, 30), duration_minutes=90,
            roles=(UserRole.TECHNICIAN,),
        ),
        TemplateStep(
            order=3, day=7,
            name="Tüy Kesimi, Deri Altı İmplantasyon ve 1. Saat Klinik Gözlem",
            step_type="Uygulama",
            start=time(9, 0), duration_minutes=180,
            roles=(UserRole.STUDY_DIRECTOR, UserRole.TECHNICIAN),
            is_biological_fixed_time=True, tolerance_minutes=15,
            note="İmplantasyon referans saati ≈10:00; 24/48/72. saat gözlemleri bu saate sabitlenir.",
            is_biological_reference=True,
            reference_event_time=time(10, 0),
        ),
        TemplateStep(
            order=4, day=8,
            name="24. Saat Klinik Gözlem ve İmplant Bölgesi Skorlaması",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=120,
            reference_step_order=3,
            reference_offset_hours=24,
        ),
        TemplateStep(
            order=5, day=9,
            name="48. Saat Klinik Gözlem ve İmplant Bölgesi Skorlaması",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=120,
            reference_step_order=3,
            reference_offset_hours=48,
        ),
        TemplateStep(
            order=6, day=10,
            name="72. Saat Klinik Gözlem ve İmplant Bölgesi Skorlaması",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=120,
            reference_step_order=3,
            reference_offset_hours=72,
        ),
        TemplateStep(
            order=7, day=14,
            name="7. Gün Haftalık Klinik Gözlem ve Vücut Ağırlığı",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=120,
        ),
        TemplateStep(
            order=8, day=21,
            name="14. Gün Haftalık Klinik Gözlem ve Vücut Ağırlığı",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=120,
        ),
        TemplateStep(
            order=9, day=28,
            name="21. Gün Haftalık Klinik Gözlem ve Vücut Ağırlığı",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=120,
        ),
        TemplateStep(
            order=10, day=35,
            name="28. Gün Son Gözlem, Terminal Tartım, Ötenazi, Nekropsi ve Histopatoloji Numune Alımı",
            step_type="Gözlem / Terminasyon",
            start=time(9, 0), duration_minutes=240,
            roles=(UserRole.STUDY_DIRECTOR, UserRole.TECHNICIAN),
            is_biological_fixed_time=True, tolerance_minutes=120,
        ),
    ),
)

# ---------------------------------------------------------------------------
# 6) ISO 10993-11 / USP 151 — PİROJENİTE TESTİ (FAZ 8.3)
# ---------------------------------------------------------------------------
ISO_10993_11_PYRO = StudyTemplate(
    code="ISO_10993_11_PYRO",
    standard="ISO 10993-11 / USP 151",
    title="Pirojenite Testi (Tavşan Pirojen Testi)",
    description="Yeni Zelanda tavşanlarında polar ekstraktın intravenöz uygulanması; bazal ve 1/2/3. saat rektal vücut sıcaklığı takibi.",
    steps=(
        TemplateStep(
            order=1, day=0,
            name="Veteriner Muayenesi ve Aklimatizasyona Alma (Tavşan)",
            step_type="Aklimatizasyon",
            start=time(9, 0), duration_minutes=90,
            roles=(UserRole.TFM,),
        ),
        TemplateStep(
            order=2, day=2,
            name="Pirojensiz Cam Malzeme ve Ekstraksiyon Kurulumu",
            step_type="Ekstraksiyon",
            start=time(8, 30), duration_minutes=90,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=60,
        ),
        TemplateStep(
            order=3, day=5,
            name="Bazal Rektal Sıcaklık Ölçümü, IV Uygulama ve 1–3. Saat Pirojen Takibi",
            step_type="Uygulama",
            start=time(9, 0), duration_minutes=240,
            roles=(UserRole.STUDY_DIRECTOR, UserRole.TECHNICIAN),
            is_biological_fixed_time=True, tolerance_minutes=15,
        ),
        TemplateStep(
            order=4, day=6,
            name="24. Saat Klinik Gözlem ve Çalışma Sonlandırma",
            step_type="Gözlem / Terminasyon",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=60,
        ),
    ),
)

# ---------------------------------------------------------------------------
# 7) ISO 10993-4 — HEMOLİTİK ETKİ / HEMOLİZ TESTİ (FAZ 8.3)
# ---------------------------------------------------------------------------
ISO_10993_4_HEMO = StudyTemplate(
    code="ISO_10993_4_HEMO",
    standard="ISO 10993-4",
    title="Hemolitik Etki (Hemoliz) Testi",
    description="Tavşan kanı ile doğrudan ve ekstrakt teması yöntemiyle in vitro / ex vivo hemoliz indeksi ve spektrofotometrik hemoglobin tayini.",
    steps=(
        TemplateStep(
            order=1, day=0,
            name="Donör Tavşan Veteriner Kontrolü ve Ekstraksiyon Hazırlığı",
            step_type="Hazırlık",
            start=time(9, 0), duration_minutes=90,
            roles=(UserRole.TECHNICIAN,),
        ),
        TemplateStep(
            order=2, day=1,
            name="Tavşan Kanı Alımı, İnkübasyon ve Spektrofotometrik Hemoliz İndeksi Okuması",
            step_type="Uygulama",
            start=time(9, 30), duration_minutes=180,
            roles=(UserRole.STUDY_DIRECTOR, UserRole.TECHNICIAN),
            is_biological_fixed_time=True, tolerance_minutes=30,
        ),
    ),
)

# ---------------------------------------------------------------------------
# 8) ISO 10993-11 — SUBAKUT SİSTEMİK TOKSİSİTE TESTİ (14G / 28G) (FAZ 8.3)
# ---------------------------------------------------------------------------
ISO_10993_11_SUBACUTE = StudyTemplate(
    code="ISO_10993_11_SUBACUTE",
    standard="ISO 10993-11",
    title="Subakut Sistemik Toksisite Testi (14 / 28 Gün)",
    description="Kemirgenlerde (Fare/Rat) tekrarlanan dozlama/uygulama sonrası günlük klinik gözlem, haftalık tartım, hematoloji/biyokimya ve tam nekropsi/histopatoloji.",
    steps=(
        TemplateStep(
            order=1, day=0,
            name="Veteriner Muayenesi ve Aklimatizasyona Alma (Fare / Rat)",
            step_type="Aklimatizasyon",
            start=time(9, 0), duration_minutes=120,
            roles=(UserRole.TFM,),
        ),
        TemplateStep(
            order=2, day=4,
            name="Ekstraksiyon Kurulumu ve Doz Hazırlığı",
            step_type="Ekstraksiyon",
            start=time(8, 30), duration_minutes=90,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=60,
        ),
        TemplateStep(
            order=3, day=7,
            name="Subakut Sistemik Dozlama Başlangıcı ve Klinik Gözlem",
            step_type="Uygulama",
            start=time(9, 0), duration_minutes=180,
            roles=(UserRole.STUDY_DIRECTOR, UserRole.TECHNICIAN),
            is_biological_fixed_time=True, tolerance_minutes=30,
        ),
        TemplateStep(
            order=4, day=14,
            name="7. Gün Haftalık Klinik Gözlem ve Vücut Ağırlığı",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=90,
            roles=(UserRole.TECHNICIAN,),
        ),
        TemplateStep(
            order=5, day=21,
            name="14. Gün Haftalık Klinik Gözlem ve Vücut Ağırlığı",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=90,
            roles=(UserRole.TECHNICIAN,),
        ),
        TemplateStep(
            order=6, day=28,
            name="Terminal Kan Alımı, Ötenazi, Tam Nekropsi ve Histopatoloji",
            step_type="Gözlem / Terminasyon",
            start=time(9, 0), duration_minutes=240,
            roles=(UserRole.STUDY_DIRECTOR, UserRole.TECHNICIAN),
            is_biological_fixed_time=True, tolerance_minutes=120,
        ),
    ),
)

# ---------------------------------------------------------------------------
# 9) ISO 10993-11 — SUBKRONİK SİSTEMİK TOKSİSİTE TESTİ (90 GÜN) (FAZ 8.3)
# ---------------------------------------------------------------------------
ISO_10993_11_SUBCHRONIC = StudyTemplate(
    code="ISO_10993_11_SUBCHRONIC",
    standard="ISO 10993-11",
    title="Subkronik Sistemik Toksisite Testi (90 Gün)",
    description="Rat/Farelerde 90 günlük subkronik sistemik maruziyet, haftalık klinik ve tartım takibi, hematoloji, klinik biyokimya ve tam nekropsi/histopatoloji.",
    steps=(
        TemplateStep(
            order=1, day=0,
            name="Veteriner Muayenesi ve Aklimatizasyona Alma (Rat / Fare)",
            step_type="Aklimatizasyon",
            start=time(9, 0), duration_minutes=120,
            roles=(UserRole.TFM,),
        ),
        TemplateStep(
            order=2, day=4,
            name="Test Maddesi / Ekstrakt Hazırlığı",
            step_type="Ekstraksiyon",
            start=time(8, 30), duration_minutes=90,
            roles=(UserRole.TECHNICIAN,),
        ),
        TemplateStep(
            order=3, day=7,
            name="Subkronik Uygulama Başlangıcı ve 1. Gün Gözlemi",
            step_type="Uygulama",
            start=time(9, 0), duration_minutes=180,
            roles=(UserRole.STUDY_DIRECTOR, UserRole.TECHNICIAN),
            is_biological_fixed_time=True, tolerance_minutes=30,
        ),
        TemplateStep(
            order=4, day=35,
            name="4. Hafta Ara Klinik Gözlem ve Vücut Ağırlığı",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=90,
            roles=(UserRole.TECHNICIAN,),
        ),
        TemplateStep(
            order=5, day=63,
            name="8. Hafta Ara Klinik Gözlem ve Vücut Ağırlığı",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=90,
            roles=(UserRole.TECHNICIAN,),
        ),
        TemplateStep(
            order=6, day=97,
            name="90. Gün Terminal Kan Alımı, Ötenazi, Nekropsi ve Organ Ağırlıkları",
            step_type="Gözlem / Terminasyon",
            start=time(9, 0), duration_minutes=240,
            roles=(UserRole.STUDY_DIRECTOR, UserRole.TECHNICIAN),
            is_biological_fixed_time=True, tolerance_minutes=120,
        ),
    ),
)

# ---------------------------------------------------------------------------
# 10) ISO 10993-6 — İMPLANTASYON TESTİ (3 AY / 13 HAFTA) (FAZ 8.3)
# ---------------------------------------------------------------------------
ISO_10993_6_IMP_13W = StudyTemplate(
    code="ISO_10993_6_IMP_13W",
    standard="ISO 10993-6",
    title="İmplantasyon Testi (3 Ay / 13 Hafta)",
    description="13 haftalık (90–100 gün) subkutan/kas içi implantasyon; klinik gözlem, terminal nekropsi ve histopatolojik lokal doku reaksiyonu değerlendirmesi.",
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
            name="Test Maddesi ve İmplant Alanı Hazırlığı",
            step_type="Hazırlık",
            start=time(8, 30), duration_minutes=90,
            roles=(UserRole.TECHNICIAN,),
        ),
        TemplateStep(
            order=3, day=7,
            name="Cerrahi İmplantasyon ve 1. Saat Klinik Gözlem",
            step_type="Uygulama",
            start=time(9, 0), duration_minutes=180,
            roles=(UserRole.STUDY_DIRECTOR, UserRole.TECHNICIAN),
            is_biological_fixed_time=True, tolerance_minutes=15,
        ),
        TemplateStep(
            order=4, day=8,
            name="24. Saat İmplant Bölgesi Gözlemi",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=120,
        ),
        TemplateStep(
            order=5, day=35,
            name="4. Hafta Klinik Gözlem ve Vücut Ağırlığı",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
        ),
        TemplateStep(
            order=6, day=63,
            name="8. Hafta Klinik Gözlem ve Vücut Ağırlığı",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
        ),
        TemplateStep(
            order=7, day=98,
            name="13. Hafta Terminal Gözlem, Ötenazi, Nekropsi ve Histopatoloji",
            step_type="Gözlem / Terminasyon",
            start=time(9, 0), duration_minutes=240,
            roles=(UserRole.STUDY_DIRECTOR, UserRole.TECHNICIAN),
            is_biological_fixed_time=True, tolerance_minutes=120,
        ),
    ),
)

# ---------------------------------------------------------------------------
# 11) ISO 10993-6 — İMPLANTASYON TESTİ (6 AY / 26 HAFTA) (FAZ 8.3)
# ---------------------------------------------------------------------------
ISO_10993_6_IMP_26W = StudyTemplate(
    code="ISO_10993_6_IMP_26W",
    standard="ISO 10993-6",
    title="İmplantasyon Testi (6 Ay / 26 Hafta)",
    description="26 haftalık (180–200 gün) uzun süreli implantasyon; periyodik klinik gözlem, terminal nekropsi ve histopatolojik lokal doku değerlendirmesi.",
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
            name="Test Maddesi ve İmplant Alanı Hazırlığı",
            step_type="Hazırlık",
            start=time(8, 30), duration_minutes=90,
            roles=(UserRole.TECHNICIAN,),
        ),
        TemplateStep(
            order=3, day=7,
            name="Cerrahi İmplantasyon ve 1. Saat Klinik Gözlem",
            step_type="Uygulama",
            start=time(9, 0), duration_minutes=180,
            roles=(UserRole.STUDY_DIRECTOR, UserRole.TECHNICIAN),
            is_biological_fixed_time=True, tolerance_minutes=15,
        ),
        TemplateStep(
            order=4, day=8,
            name="24. Saat İmplant Bölgesi Gözlemi",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
            is_biological_fixed_time=True, tolerance_minutes=120,
        ),
        TemplateStep(
            order=5, day=63,
            name="8. Hafta Klinik Gözlem ve Vücut Ağırlığı",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
        ),
        TemplateStep(
            order=6, day=126,
            name="17. Hafta Klinik Gözlem ve Vücut Ağırlığı",
            step_type="Gözlem",
            start=time(10, 0), duration_minutes=60,
            roles=(UserRole.TECHNICIAN,),
        ),
        TemplateStep(
            order=7, day=189,
            name="26. Hafta Terminal Gözlem, Ötenazi, Nekropsi ve Histopatoloji",
            step_type="Gözlem / Terminasyon",
            start=time(9, 0), duration_minutes=240,
            roles=(UserRole.STUDY_DIRECTOR, UserRole.TECHNICIAN),
            is_biological_fixed_time=True, tolerance_minutes=120,
        ),
    ),
)

# ---------------------------------------------------------------------------
# 12) FİZİKSEL-KİMYASAL NON-GLP MONOGRAM TESTİ (FAZ 8.3)
# ---------------------------------------------------------------------------
PHYS_CHEM_MONO = StudyTemplate(
    code="PHYS_CHEM_MONO",
    standard="EP / USP Monograf",
    title="Fiziksel-Kimyasal Monogram Testler (Non-GLP)",
    description="Farmakope (EP/USP) monografına uygun fiziksel-kimyasal analiz, safsızlık/kalıntı tayini ve raporlama (hayvan kullanılmaz).",
    steps=(
        TemplateStep(
            order=1, day=0,
            name="Numune Hazırlığı, Çözelti ve Standart Kurulumu",
            step_type="Hazırlık",
            start=time(9, 0), duration_minutes=120,
            roles=(UserRole.STUDY_DIRECTOR,),
        ),
        TemplateStep(
            order=2, day=2,
            name="Enstrümantal / Kimyasal Monogram Analizi ve Kromatografik Okuma",
            step_type="Uygulama",
            start=time(9, 30), duration_minutes=180,
            roles=(UserRole.STUDY_DIRECTOR,),
        ),
        TemplateStep(
            order=3, day=4,
            name="Veri Değerlendirme, Hesaplama ve Fiziksel-Kimyasal Raporlama",
            step_type="Gözlem / Terminasyon",
            start=time(10, 0), duration_minutes=120,
            roles=(UserRole.STUDY_DIRECTOR,),
        ),
    ),
)

# ---------------------------------------------------------------------------
# FAZ 8.1 & 8.3 — Şablon metaverisi: kafes (oda) gereksinimi, IN VIVO TEST SÜRELERİ ve TEKRAR KULLANIM
# ---------------------------------------------------------------------------
_REUSE_TR_RABBIT = "Üretim / İrritasyon / İmplantasyon (Veteriner hekim kontrolü ve HADYEK onayı ile)"
_REUSE_EN_RABBIT = "Breeding / Irritation / Implantation (subject to Veterinarian examination and HADYEK approval)"
_REUSE_TR_GP = "Üretim / Diğer hassasiyet çalışmaları (Veteriner hekim kontrolü ve HADYEK onayı ile)"
_REUSE_EN_GP = "Breeding / Other sensitization studies (subject to Veterinarian examination and HADYEK approval)"
_NECROPSY_TR = "Nekropsi (Tekrar kullanım yok — ötenazi ve patolojik inceleme)"
_NECROPSY_EN = "Necropsy (No reuse — euthanasia and pathological examination)"

_TEMPLATE_META: Dict[str, Dict[str, Any]] = {
    "ISO_10993_23_IC": dict(
        animal_room="RABBIT_ROOM", cage_count=3, species_label="Tavşan (NZW) — 3 hayvan / 3 kafes",
        equipment_codes=("EQ-WB-001",),
        docx_title_en="Intracutaneous Reactivity Test", docx_species_en="New Zealand White Rabbits",
        animal_count=3, cohorts=1, max_animals=3,
        quarantine_days=7, acclimatization_days=5, experiment_days=14, qa_audit_days=5, report_days=2,
        tat_without_quarantine_days=26, tat_with_quarantine_days=33,
        reuse_allowed=True, animal_fate_tr=_REUSE_TR_RABBIT, animal_fate_en=_REUSE_EN_RABBIT,
    ),
    "ISO_10993_6_IMP": dict(
        animal_room="RABBIT_ROOM", cage_count=3, species_label="Tavşan (NZW) / Rat — 3 kafes (4 hafta)",
        equipment_codes=(),
        docx_title_en="Subcutaneous Implantation Test", docx_species_en="New Zealand White Rabbits",
        animal_count=3, cohorts=1, max_animals=10,
        quarantine_days=7, acclimatization_days=5, experiment_days=35, qa_audit_days=5, report_days=2,
        tat_without_quarantine_days=47, tat_with_quarantine_days=54,
        reuse_allowed=False, animal_fate_tr=_NECROPSY_TR, animal_fate_en=_NECROPSY_EN,
    ),
    "ISO_10993_5_CYTO": dict(
        animal_room="", cage_count=0, species_label="Hayvan yok — L929 hücre hattı (0 kafes)",
        equipment_codes=("EQ-OVN-001", "EQ-INC-001"),
        equipment_windows=(("EQ-OVN-001", 4, "08:30", 24), ("EQ-INC-001", 7, "09:30", 24)),
        docx_title_en="In Vitro Cytotoxicity Test", docx_species_en="L929 Mouse Fibroblast Cell Line",
        animal_count=0, cohorts=0, max_animals=0,
        quarantine_days=0, acclimatization_days=0, experiment_days=8, qa_audit_days=3, report_days=2,
        tat_without_quarantine_days=13, tat_with_quarantine_days=13,
        reuse_allowed=False, animal_fate_tr="In vitro hücre kültürü (hayvan kullanılmaz)", animal_fate_en="In vitro cell culture (no animals used)",
    ),
    "ISO_10993_10_SENS": dict(
        animal_room="GUINEA_PIG_ROOM", cage_count=3, species_label="Kobay (Guinea pig) — 15 hayvan (max 30) / 3–5 kafes",
        equipment_codes=("EQ-WB-001",),
        docx_title_en="Skin Sensitization Test (Guinea Pig Maximization)", docx_species_en="Guinea Pigs",
        animal_count=15, cohorts=1, max_animals=30,
        quarantine_days=7, acclimatization_days=5, experiment_days=24, qa_audit_days=5, report_days=2,
        tat_without_quarantine_days=36, tat_with_quarantine_days=43,
        reuse_allowed=True, animal_fate_tr=_REUSE_TR_GP, animal_fate_en=_REUSE_EN_GP,
    ),
    "ISO_10993_11_ACUTE": dict(
        animal_room="MOUSE_ROOM", cage_count=2, species_label="Kemirgen (Fare / Rat) — 20 hayvan (4 kohort) / 2–4 kafes",
        equipment_codes=("EQ-WB-001",),
        docx_title_en="Acute Systemic Toxicity Test", docx_species_en="Mice",
        animal_count=5, cohorts=4, max_animals=20,
        quarantine_days=7, acclimatization_days=5, experiment_days=4, qa_audit_days=5, report_days=2,
        tat_without_quarantine_days=16, tat_with_quarantine_days=23,
        reuse_allowed=False, animal_fate_tr=_NECROPSY_TR, animal_fate_en=_NECROPSY_EN,
    ),
    "ISO_10993_11_PYRO": dict(
        animal_room="RABBIT_ROOM", cage_count=5, species_label="Tavşan (NZW) — 5 hayvan / 5 kafes",
        equipment_codes=("EQ-WB-001",),
        docx_title_en="Material-Mediated Pyrogenicity Test", docx_species_en="New Zealand White Rabbits",
        animal_count=5, cohorts=1, max_animals=5,
        quarantine_days=7, acclimatization_days=5, experiment_days=6, qa_audit_days=5, report_days=2,
        tat_without_quarantine_days=18, tat_with_quarantine_days=25,
        reuse_allowed=True, animal_fate_tr=_REUSE_TR_RABBIT, animal_fate_en=_REUSE_EN_RABBIT,
    ),
    "ISO_10993_4_HEMO": dict(
        animal_room="RABBIT_ROOM", cage_count=1, species_label="Tavşan (Donör Kan) — 3 hayvan / 1 kafes",
        equipment_codes=(),
        docx_title_en="Hemolysis (Haemocompatibility) Test", docx_species_en="New Zealand White Rabbit Blood",
        animal_count=3, cohorts=1, max_animals=3,
        quarantine_days=0, acclimatization_days=5, experiment_days=1, qa_audit_days=1, report_days=1,
        tat_without_quarantine_days=8, tat_with_quarantine_days=15,
        reuse_allowed=True, animal_fate_tr=_REUSE_TR_RABBIT, animal_fate_en=_REUSE_EN_RABBIT,
    ),
    "ISO_10993_11_SUBACUTE": dict(
        animal_room="RAT_ROOM", cage_count=4, species_label="Rat / Fare — 40 hayvan (4 kohort) / 4 kafes",
        equipment_codes=("EQ-WB-001",),
        docx_title_en="Subacute Systemic Toxicity Test (14/28 Days)", docx_species_en="Wistar Rats / Mice",
        animal_count=10, cohorts=4, max_animals=40,
        quarantine_days=7, acclimatization_days=5, experiment_days=21, qa_audit_days=5, report_days=2,
        tat_without_quarantine_days=33, tat_with_quarantine_days=40,
        reuse_allowed=False, animal_fate_tr=_NECROPSY_TR, animal_fate_en=_NECROPSY_EN,
    ),
    "ISO_10993_11_SUBCHRONIC": dict(
        animal_room="RAT_ROOM", cage_count=8, species_label="Rat / Fare — 80 hayvan (4 kohort) / 8 kafes",
        equipment_codes=("EQ-WB-001",),
        docx_title_en="Subchronic Systemic Toxicity Test (90 Days)", docx_species_en="Wistar Rats",
        animal_count=20, cohorts=4, max_animals=80,
        quarantine_days=7, acclimatization_days=5, experiment_days=90, qa_audit_days=10, report_days=3,
        tat_without_quarantine_days=108, tat_with_quarantine_days=115,
        reuse_allowed=False, animal_fate_tr=_NECROPSY_TR, animal_fate_en=_NECROPSY_EN,
    ),
    "ISO_10993_6_IMP_13W": dict(
        animal_room="RABBIT_ROOM", cage_count=4, species_label="Tavşan / Rat — 10 hayvan (3 ay / 13 hafta) / 4 kafes",
        equipment_codes=(),
        docx_title_en="Subcutaneous / Muscle Implantation Test (13 Weeks)", docx_species_en="New Zealand White Rabbits",
        animal_count=5, cohorts=2, max_animals=10,
        quarantine_days=7, acclimatization_days=5, experiment_days=90, qa_audit_days=10, report_days=3,
        tat_without_quarantine_days=108, tat_with_quarantine_days=115,
        reuse_allowed=False, animal_fate_tr=_NECROPSY_TR, animal_fate_en=_NECROPSY_EN,
    ),
    "ISO_10993_6_IMP_26W": dict(
        animal_room="RABBIT_ROOM", cage_count=4, species_label="Tavşan / Rat — 10 hayvan (6 ay / 26 hafta) / 4 kafes",
        equipment_codes=(),
        docx_title_en="Subcutaneous / Muscle Implantation Test (26 Weeks)", docx_species_en="New Zealand White Rabbits",
        animal_count=5, cohorts=2, max_animals=10,
        quarantine_days=7, acclimatization_days=5, experiment_days=182, qa_audit_days=10, report_days=3,
        tat_without_quarantine_days=195, tat_with_quarantine_days=202,
        reuse_allowed=False, animal_fate_tr=_NECROPSY_TR, animal_fate_en=_NECROPSY_EN,
    ),
    "PHYS_CHEM_MONO": dict(
        animal_room="", cage_count=0, species_label="Hayvan yok — Fiziksel-Kimyasal Analiz (0 kafes)",
        equipment_codes=(),
        docx_title_en="Physical-Chemical Pharmacopoeial Monograph Testing", docx_species_en="In Vitro / Analytical System (Non-GLP)",
        animal_count=0, cohorts=0, max_animals=0,
        quarantine_days=0, acclimatization_days=0, experiment_days=5, qa_audit_days=1, report_days=1,
        tat_without_quarantine_days=7, tat_with_quarantine_days=7,
        reuse_allowed=False, animal_fate_tr="Kimyasal analiz (hayvan kullanılmaz)", animal_fate_en="Analytical testing (no animals used)",
    ),
}

ISO_10993_23_IC = replace(ISO_10993_23_IC, **_TEMPLATE_META["ISO_10993_23_IC"])
ISO_10993_6_IMP = replace(ISO_10993_6_IMP, **_TEMPLATE_META["ISO_10993_6_IMP"])
ISO_10993_5_CYTO = replace(ISO_10993_5_CYTO, **_TEMPLATE_META["ISO_10993_5_CYTO"])
ISO_10993_10_SENS = replace(ISO_10993_10_SENS, **_TEMPLATE_META["ISO_10993_10_SENS"])
ISO_10993_11_ACUTE = replace(ISO_10993_11_ACUTE, **_TEMPLATE_META["ISO_10993_11_ACUTE"])
ISO_10993_11_PYRO = replace(ISO_10993_11_PYRO, **_TEMPLATE_META["ISO_10993_11_PYRO"])
ISO_10993_4_HEMO = replace(ISO_10993_4_HEMO, **_TEMPLATE_META["ISO_10993_4_HEMO"])
ISO_10993_11_SUBACUTE = replace(ISO_10993_11_SUBACUTE, **_TEMPLATE_META["ISO_10993_11_SUBACUTE"])
ISO_10993_11_SUBCHRONIC = replace(ISO_10993_11_SUBCHRONIC, **_TEMPLATE_META["ISO_10993_11_SUBCHRONIC"])
ISO_10993_6_IMP_13W = replace(ISO_10993_6_IMP_13W, **_TEMPLATE_META["ISO_10993_6_IMP_13W"])
ISO_10993_6_IMP_26W = replace(ISO_10993_6_IMP_26W, **_TEMPLATE_META["ISO_10993_6_IMP_26W"])
PHYS_CHEM_MONO = replace(PHYS_CHEM_MONO, **_TEMPLATE_META["PHYS_CHEM_MONO"])

TEMPLATES: Dict[str, StudyTemplate] = {
    t.code: t
    for t in (
        ISO_10993_23_IC,
        ISO_10993_5_CYTO,
        ISO_10993_10_SENS,
        ISO_10993_11_ACUTE,
        ISO_10993_6_IMP,
        ISO_10993_11_PYRO,
        ISO_10993_4_HEMO,
        ISO_10993_11_SUBACUTE,
        ISO_10993_11_SUBCHRONIC,
        ISO_10993_6_IMP_13W,
        ISO_10993_6_IMP_26W,
        PHYS_CHEM_MONO,
    )
}
DEFAULT_TEMPLATE_CODE = ISO_10993_23_IC.code

# FAZ 8.1 & 8.3 — Kullanıcı tarafı kısa kodlar mevcut veritabanı kayıtlarını bozmadan kanonik koda çözülür.
TEMPLATE_ALIASES: Dict[str, str] = {
    "ISO_10993_5_CYT": "ISO_10993_5_CYTO",
    "ISO_10993_11_SYS": "ISO_10993_11_ACUTE",
    "USP_151_PYRO": "ISO_10993_11_PYRO",
    "ISO_10993_4": "ISO_10993_4_HEMO",
}


def resolve_template_code(code: Optional[str]) -> str:
    """Takma adları (ISO_10993_5_CYT, ISO_10993_11_SYS) kanonik şablon koduna çevirir; 'ALL' aynen döner."""
    c = (code or "").strip().upper()
    return TEMPLATE_ALIASES.get(c, c)


def _parse_hhmm(val: str, fallback: time) -> time:
    try:
        parts = str(val).strip().split(":")
        return time(int(parts[0]), int(parts[1]))
    except Exception:
        return fallback


def ensure_default_calibrations(db: Session, commit: bool = True) -> List[Any]:
    """
    Veritabanındaki `system_calibrations` tablosunu kontrol eder; şablon adımları eksikse
    `commit=True` (ve aktif bir iç transaction yoksa) varsayılan kalibrasyon kayıtlarını oluşturur.
    Salt-okunur / doğrulama / önizleme akışlarında (`commit=False` veya `db.in_nested_transaction()`)
    Session üzerine hiçbir kayıt eklemez (`db.add` / `db.commit` yapmaz) ve eksik satırları
    bellek içi geçici (transient) nesneler olarak tamamlayıp döner.
    """
    from app.models.calibration import SystemCalibration

    can_persist = bool(commit and not db.in_nested_transaction())
    with db.no_autoflush:
        existing = db.query(SystemCalibration).order_by(SystemCalibration.id.asc()).all()
    existing_keys = {(c.template_code, c.step_order) for c in existing}
    missing_rows: List[SystemCalibration] = []
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
                missing_rows.append(row)
                if can_persist:
                    db.add(row)
    if not missing_rows:
        return existing
    if can_persist:
        db.commit()
        return db.query(SystemCalibration).order_by(SystemCalibration.id.asc()).all()
    return list(existing) + missing_rows


def get_template(code: str, db: Optional[Session] = None, commit_defaults: bool = False) -> StudyTemplate:
    code = resolve_template_code(code)
    try:
        base_tpl = TEMPLATES[code]
    except KeyError:
        raise ValueError(f"Tanımsız çalışma şablonu: '{code}'. Mevcut: {', '.join(TEMPLATES)}")

    if db is None:
        return base_tpl

    try:
        from app.models.calibration import SystemCalibration

        if commit_defaults and not db.in_nested_transaction():
            ensure_default_calibrations(db, commit=True)
        with db.no_autoflush:
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


def get_all_templates_calibrated(db: Optional[Session] = None, commit_defaults: bool = False) -> List[StudyTemplate]:
    return [get_template(code, db=db, commit_defaults=commit_defaults) for code in TEMPLATES]
