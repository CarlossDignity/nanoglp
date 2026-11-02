from datetime import datetime
from sqlalchemy import Boolean, Column, Date, DateTime, Integer, JSON, String, Text
from app.database import Base

# 11 adımlı numune iş akışı tanımı (sıra, başlık, sorumlu rol etiketi, tür)
WORKFLOW_STEPS = [
    {"no": 1, "title": "Sponsor sözleşmesinin imzalanması", "owner": "Satış", "kind": "manual", "roles": ["SALES"]},
    {"no": 2, "title": "Etik kurul başvurusu", "owner": "Çalışma yöneticisi", "kind": "manual", "roles": ["STUDY_DIRECTOR"]},
    {"no": 3, "title": "Hayvan siparişi ve kabulü", "owner": "Çalışma yöneticisi", "kind": "manual", "roles": ["STUDY_DIRECTOR"]},
    {"no": 4, "title": "Test maddesinin kabulü ve arşiv", "owner": "TRM kabul", "kind": "auto_or_manual", "roles": ["TRM_KABUL", "TRM_ACCEPTANCE"]},
    {"no": 5, "title": "Taslak çalışma planı", "owner": "Çalışma yöneticisi", "kind": "auto", "roles": ["STUDY_DIRECTOR"]},
    {"no": 6, "title": "Çalışma planının onayı", "owner": "ÇY · KG · TBY", "kind": "approval", "roles": []},
    {"no": 7, "title": "Çalışmanın başlaması", "owner": "Test başlangıç tarihi", "kind": "auto", "roles": []},
    {"no": 8, "title": "Çalışmanın bitişi", "owner": "Test bitiş tarihi", "kind": "auto", "roles": []},
    {"no": 9, "title": "Taslak rapor gönderimi", "owner": "Çalışma yöneticisi", "kind": "manual", "roles": ["STUDY_DIRECTOR"]},
    {"no": 10, "title": "Ödemenin tamamlanması", "owner": "Satış", "kind": "manual", "roles": ["SALES"]},
    {"no": 11, "title": "Final rapor gönderimi", "owner": "ÇY · KG · TBY", "kind": "approval", "roles": []},
]

APPROVAL_ROLES = {
    "CY": {"label": "ÇY", "full": "Çalışma Yöneticisi", "roles": ["STUDY_DIRECTOR"]},
    "KG": {"label": "KG", "full": "Kalite Güvence", "roles": ["QA"]},
    "TBY": {"label": "TBY", "full": "Test Tesisi Yöneticisi", "roles": ["TFM"]},
}


class SampleRecord(Base):
    """FAZ 8.1 — Numune ve Çalışma Takip kaydı (1 satır = 1 GLP çalışması / numune talebi)."""

    __tablename__ = "sample_records"

    id = Column(Integer, primary_key=True, index=True)
    study_code = Column(String(100), unique=True, index=True, nullable=False)   # GLP2026-072
    template_code = Column(String(60), nullable=True)

    # a) Satış bilgileri
    requested_analysis = Column(String(255), nullable=True)
    test_item_name = Column(String(255), nullable=True)
    billing_company = Column(String(255), nullable=True)
    sponsor_name = Column(String(255), nullable=True)
    contacts = Column(JSON, nullable=True)            # [{"name": "...", "email": "..."}]
    quote_no = Column(String(100), nullable=True)
    sales_manager = Column(String(255), nullable=True)
    expected_arrival_date = Column(Date, nullable=True)

    # b) Numune kabul (TRM)
    sample_status = Column(String(30), nullable=True)  # Kabul edildi / Bekleniyor
    test_item_code = Column(String(60), index=True, nullable=True)   # TI-2026-0016
    istanbul_arrival_date = Column(Date, nullable=True)
    lab_arrival_date = Column(Date, nullable=True)
    received_quantity = Column(String(100), nullable=True)
    lot_no = Column(String(100), nullable=True)
    expiry_date = Column(String(50), nullable=True)
    storage_condition = Column(String(150), nullable=True)
    sample_note = Column(Text, nullable=True)
    # FAZ 8.2: TIIS / CoA / FM.083 belgelerinden otomatik doldurulabilen ek alanlar
    manufacture_date = Column(String(50), nullable=True)
    extraction_polar_solvent = Column(String(255), nullable=True)
    extraction_non_polar_solvent = Column(String(255), nullable=True)
    extraction_polar = Column(Boolean, nullable=True)
    extraction_non_polar = Column(Boolean, nullable=True)
    document_autofill = Column(JSON, nullable=True)   # son otomatik doldurma özeti (kaynak belgeler, alanlar)

    # Çalışma atamaları ve takvim
    study_director_name = Column(String(255), nullable=True)
    stored_status = Column(String(20), nullable=True)  # EXPECTED / PLANNED / ONGOING / COMPLETED / CANCELLED
    planned_start = Column(Date, nullable=True)
    planned_end = Column(Date, nullable=True)
    auto_schedule_notice = Column(Text, nullable=True)

    # FAZ 8.3: Study Status last version (2).xlsx ek alanları (Sıra No, GLP/NON-GLP, Lab, Hayvan/Sarf, Rapor ve Ödeme)
    serial_no = Column(Integer, index=True, nullable=True)
    glp_type = Column(String(20), nullable=True, default="GLP")          # GLP / NON-GLP
    test_laboratory = Column(String(120), nullable=True)                 # Biyouyumluluk / Kimyasal
    animal_consumable_status = Column(String(255), nullable=True)        # Hayvan/sarf malzeme temin durumu
    animal_procurement_date = Column(Date, nullable=True)                # Hayvan / Sarf Malzeme Temin tarihi
    experiment_start_date = Column(Date, nullable=True)                  # Fiili / Excel Çalışma Başlangıç Tarihi
    experiment_end_date = Column(Date, nullable=True)                    # Fiili / Excel Test Bitiş Tarihi
    draft_report_date = Column(Date, nullable=True)                      # Taslak Rapor Teslim Tarihi
    payment_status = Column(String(120), nullable=True)                  # Ödeme durumu (Yapıldı / Yapılmadı / ...)
    final_report_date = Column(Date, nullable=True)                      # Final Rapor Gönderim Tarihi
    raw_status_text = Column(String(120), nullable=True)                 # Excel "Çalışmanın son durumu" ham metin
    study_agreement_date = Column(Date, nullable=True)                   # Sponsor sözleşme tarihi

    # 11 adımlı iş akışı durumu: {"1": {"done": true, "done_at": "...", "done_by": "..."}, "6": {"approvals": {...}}}
    workflow = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
