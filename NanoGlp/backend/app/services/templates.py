"""
GLP ÇALIŞMA ŞABLONLARI (Study Templates)

Kullanıcı yalnızca "Aklimatizasyon Başlangıç Tarihi"ni (Gün 0) girer; şablondaki adımlar
gün ofsetlerine göre otomatik dizilir. Şablon motoru saatleri ASLA kendi kendine kaydırmaz.

⚠ SD DOĞRULAMASI GEREKEN VARSAYILANLAR
Gün numaraları, adım içerikleri, roller ve biyolojik kilit bilgisi Nanolab tarafından verilmiştir.
Aşağıdaki değerler ise sistem tarafından VARSAYILAN olarak atanmıştır ve protokole göre
Çalışma Yöneticisi (SD) tarafından teyit edilmelidir:
  * Başlangıç saatleri (`start`)
  * Personelin fiilen meşgul olduğu süreler (`duration_minutes`) → 9 saat iş yükü hesabına girer
  * Biyolojik tolerans pencereleri (`tolerance_minutes`)
"""
from dataclasses import dataclass
from datetime import time
from typing import Any, Dict, Tuple

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
# ISO 10993-23 — İNTRAKÜTANÖZ REAKTİVİTE TESTİ
#
# Biyolojik zincir (tek referans saate bağlı):
#   Gün 4 08:00–09:30  Ekstraksiyon kurulumu → ekstraksiyon ≈09:30'da başlar
#   Gün 7 ≈09:30       72 saatlik ekstraksiyon biter (uygulamadan hemen önce)
#   Gün 7 09:00–12:00  Tüy kesimi → enjeksiyon (referans ≈10:00) → 1. saat gözlemi
#   Gün 8/9/10 10:00   24. / 48. / 72. saat gözlemleri = enjeksiyon referansı + 24/48/72 sa
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

TEMPLATES: Dict[str, StudyTemplate] = {t.code: t for t in (ISO_10993_23_IC,)}
DEFAULT_TEMPLATE_CODE = ISO_10993_23_IC.code


def get_template(code: str) -> StudyTemplate:
    try:
        return TEMPLATES[code]
    except KeyError:
        raise ValueError(f"Tanımsız çalışma şablonu: '{code}'. Mevcut: {', '.join(TEMPLATES)}")
