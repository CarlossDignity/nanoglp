"""
FAZ 6.2 — OTOMATİK GLP STUDY PLAN TASLAĞI (.DOCX) ÜRETİCİ

Çalışmanın birleştirilmiş tüm dosya verilerini (Sponsor, İletişim, Test Maddesi, Lot No,
Üretim/SKT, Polar ve Apolar Ekstraksiyon Koşulları, Hayvan Türü/Sayısı, Aktif SD, TFM ve
Operasyonel Takvim Tablosu) içeren resmi kurumsal Word (.docx) belgesini üretir.
"""
import io
from datetime import datetime
from typing import Any, Dict, List, Optional

from docx import Document as DocxDocument
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor
from sqlalchemy.orm import Session

from app.models.document import Document as DbDocument
from app.models.study import Study
from app.models.study_step import StudyStep
from app.models.user import User, UserRole
from app.services.document_parser import aggregate_dossier


def _val(primary: Any, fallback: Any = "Belirtilmedi") -> str:
    if primary is not None and str(primary).strip() != "":
        return str(primary).strip()
    if fallback is not None and str(fallback).strip() != "":
        return str(fallback).strip()
    return "Belirtilmedi"


def _add_kv_table(doc: DocxDocument, rows_data: List[tuple]) -> None:
    table = doc.add_table(rows=len(rows_data), cols=2)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for idx, (label, value) in enumerate(rows_data):
        row = table.rows[idx]
        cell_k = row.cells[0]
        cell_v = row.cells[1]
        cell_k.width = Inches(2.4)
        cell_v.width = Inches(4.1)

        p_k = cell_k.paragraphs[0]
        run_k = p_k.add_run(str(label))
        run_k.bold = True
        run_k.font.size = Pt(9.5)

        p_v = cell_v.paragraphs[0]
        run_v = p_v.add_run(str(value))
        run_v.font.size = Pt(9.5)


def generate_study_plan_docx(db: Session, study: Study) -> bytes:
    """
    Verilen Study kaydı için kurumsal GLP Study Plan Taslağı (.docx) oluşturur ve byte olarak döner.
    Eğer Study üzerinde bazı dossier alanları boşsa, veritabanındaki çalışma dosyasından tamamlar.
    """
    all_docs = db.query(DbDocument).order_by(DbDocument.uploaded_at.desc(), DbDocument.id.desc()).all()
    active_sds = (
        db.query(User)
        .filter(User.role == UserRole.STUDY_DIRECTOR, User.is_active == True)  # noqa: E712
        .order_by(User.id.asc())
        .all()
    )
    tfm_user = (
        db.query(User)
        .filter(User.role == UserRole.TFM, User.is_active == True)  # noqa: E712
        .order_by(User.id.asc())
        .first()
    )
    qa_user = (
        db.query(User)
        .filter(User.role == UserRole.QA, User.is_active == True)  # noqa: E712
        .order_by(User.id.asc())
        .first()
    )

    dossier_fields: Dict[str, Any] = {}
    if all_docs:
        dossier = aggregate_dossier(all_docs, active_sds=active_sds)
        for k, entry in (dossier.get("fields") or {}).items():
            if entry and entry.get("value") is not None:
                dossier_fields[k] = entry.get("value")

    sd_name = (
        study.study_director.full_name
        if study.study_director
        else (active_sds[0].full_name if active_sds else "Ezgi Nur AKIN")
    )
    if sd_name.strip().lower() == "ezgi":
        sd_name = "Ezgi Nur AKIN"

    tfm_name = tfm_user.full_name if tfm_user else "Emine ARMUTOĞLU"
    if tfm_name.strip().lower() in ("emine", "emine armutoglu"):
        tfm_name = "Emine ARMUTOĞLU"

    qa_name = (
        study.qa_officer.full_name
        if study.qa_officer
        else (qa_user.full_name if qa_user else "Kalite Güvence Birimi (QA)")
    )

    sponsor_name = _val(study.sponsor_name, dossier_fields.get("sponsor_name"))
    sponsor_contact = _val(study.sponsor_contact, dossier_fields.get("sponsor_contact"))
    test_type = _val(study.test_type, dossier_fields.get("test_type") or "ISO 10993-23 İntrakütanöz Reaktivite Testi")
    guideline = _val(study.guideline, dossier_fields.get("guideline") or "ISO 10993-23:2021 & ISO 10993-12")

    test_item_name = _val(
        study.test_item_name if study.test_item_name and "BELİRTİLMEDİ" not in study.test_item_name else None,
        dossier_fields.get("test_item_name"),
    )
    lot_batch = _val(study.test_item_batch, dossier_fields.get("lot_batch_no"))
    mfg_date = _val(study.manufacture_date, dossier_fields.get("manufacture_date"))
    exp_date = _val(study.expiry_date, dossier_fields.get("expiry_date"))
    storage_cond = _val(study.test_item_storage_condition, dossier_fields.get("storage_conditions"))
    phys_state = _val(study.physical_state, dossier_fields.get("physical_state") or "Steril Jel / Çözelti / Tıbbi Cihaz")
    sterility = _val(study.sterility, dossier_fields.get("sterility") or "Steril")

    ex_polar = study.extraction_polar if study.extraction_polar is not None else dossier_fields.get("extraction_polar")
    ex_polar_solv = _val(study.extraction_polar_solvent, dossier_fields.get("extraction_polar_solvent") or "%0.9 NaCl")
    ex_apolar = (
        study.extraction_non_polar
        if study.extraction_non_polar is not None
        else dossier_fields.get("extraction_non_polar")
    )
    ex_apolar_solv = _val(
        study.extraction_non_polar_solvent, dossier_fields.get("extraction_non_polar_solvent") or "Cottonseed oil"
    )
    ex_ratio = _val(study.extraction_ratio, dossier_fields.get("extraction_ratio") or "3.0 g/10 ml")
    ex_cond = _val(study.extraction_conditions, dossier_fields.get("extraction_conditions") or "37 ± 1 °C, (72 ± 2) sa")

    animal_species = _val(
        study.animal_species_strain,
        dossier_fields.get("animal_species_strain") or "Oryctolagus cuniculus / New Zealand White (Yeni Zelanda Tavşanı)",
    )
    if "new zealand" in animal_species.lower() and "tavşan" not in animal_species.lower():
        animal_species = f"{animal_species} (Yeni Zelanda Tavşanı)"

    animal_count = _val(study.animal_count, dossier_fields.get("animal_count") or 6)
    animal_birth = _val(study.animal_birth_date, dossier_fields.get("animal_birth_date"))
    acclim_date = (
        study.acclimatization_start_date.strftime("%d.%m.%Y")
        if study.acclimatization_start_date
        else (
            study.target_start_date.strftime("%d.%m.%Y")
            if study.target_start_date
            else _val(dossier_fields.get("acclimatization_start_date"))
        )
    )

    doc = DocxDocument()

    # Üst Kurumsal Başlık
    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_org = title_p.add_run("NANOLAB LABORATUVAR HİZMETLERİ A.Ş. — EDİRNE GLP TEST TESİSİ\n")
    r_org.bold = True
    r_org.font.size = Pt(12)
    r_org.font.color.rgb = RGBColor(15, 23, 42)

    r_doc = title_p.add_run(f"GLP ÇALIŞMA PLANI TASLAĞI (STUDY PLAN DRAFT)\nÇalışma Kodu: {study.study_code}")
    r_doc.bold = True
    r_doc.font.size = Pt(14)
    r_doc.font.color.rgb = RGBColor(29, 78, 216)

    meta_p = doc.add_paragraph()
    meta_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r_meta = meta_p.add_run(
        f"Belge Üretim Tarihi: {datetime.utcnow():%d.%m.%Y %H:%M} UTC  |  Durum: {study.status.value}  |  OECD GLP & ISO 10993-23"
    )
    r_meta.font.size = Pt(8.5)
    r_meta.font.color.rgb = RGBColor(100, 116, 139)

    # 1. Bölüm: Çalışma Kimliği ve GLP Yönetimi
    h1 = doc.add_heading("1. ÇALIŞMA KİMLİĞİ, SPONSOR VE GLP SORUMLULARI", level=2)
    h1.runs[0].font.size = Pt(11)
    _add_kv_table(
        doc,
        [
            ("Çalışma Kodu (Study Code)", study.study_code),
            ("Çalışma Başlığı", study.title),
            ("Referans Standart / Kılavuz", f"{guideline} — {test_type}"),
            ("Test Tesisi Yöneticisi (TFM)", tfm_name),
            ("Çalışma Direktörü (Aktif SD)", sd_name),
            ("Kalite Güvence Birimi (QA)", qa_name),
            ("Sponsor / Müşteri Ünvanı", sponsor_name),
            ("Sponsor İletişim Bilgileri", sponsor_contact),
        ],
    )

    # 2. Bölüm: Test Maddesi (TIIS) Bilgileri
    h2 = doc.add_heading("2. TEST MADDESİ (TEST ITEM — TIIS) TANIMI", level=2)
    h2.runs[0].font.size = Pt(11)
    _add_kv_table(
        doc,
        [
            ("Test Maddesi Adı", test_item_name),
            ("Lot / Parti Numarası", lot_batch),
            ("Üretim Tarihi", mfg_date),
            ("Son Kullanma Tarihi (SKT)", exp_date),
            ("Saklama Koşulları", storage_cond),
            ("Fiziksel Hal ve Sterilite", f"{phys_state} / {sterility}"),
        ],
    )

    # 3. Bölüm: Ekstraksiyon Koşulları ve Cihaz Bilgisi
    h3 = doc.add_heading("3. EKSTRAKSİYON KOŞULLARI (ISO 10993-12) VE EKİPMAN", level=2)
    h3.runs[0].font.size = Pt(11)
    polar_str = f"Uygulanacak — Çözücü: {ex_polar_solv}" if ex_polar is not False else "Uygulanmayacak"
    apolar_str = f"Uygulanacak — Çözücü: {ex_apolar_solv}" if ex_apolar is not False else "Uygulanmayacak"
    _add_kv_table(
        doc,
        [
            ("Polar Ekstraksiyon", polar_str),
            ("Apolar (Non-Polar) Ekstraksiyon", apolar_str),
            ("Ekstraksiyon Oranı", ex_ratio),
            ("Sıcaklık ve Süre Koşulu", ex_cond),
            ("Kritik Ekstraksiyon Cihazı", "Çalkalamalı Su Banyosu 1 (Envanter Kodu: EQ-WB-001)"),
        ],
    )

    # 4. Bölüm: Test Sistemi (Hayvan Modeli ve Aklimatizasyon)
    h4 = doc.add_heading("4. TEST SİSTEMİ (HAYVAN MODELİ VE AKLİMATİZASYON — FM.083)", level=2)
    h4.runs[0].font.size = Pt(11)
    _add_kv_table(
        doc,
        [
            ("Hayvan Türü ve Irkı (Strain)", animal_species),
            ("Hayvan Sayısı", f"{animal_count} Yeni Zelanda Tavşanı"),
            ("Doğum Tarihi / Yaş Aralığı", animal_birth),
            ("Aklimatizasyon Başlangıç Tarihi (Gün 0)", str(acclim_date)),
        ],
    )

    # 5. Bölüm: Operasyonel Çalışma Takvimi Tablosu
    h5 = doc.add_heading("5. OPERASYONEL GLP ÇALIŞMA TAKVİMİ", level=2)
    h5.runs[0].font.size = Pt(11)

    steps: List[StudyStep] = (
        db.query(StudyStep)
        .filter(StudyStep.study_id == study.id)
        .order_by(StudyStep.step_order.asc())
        .all()
    )

    sched_table = doc.add_table(rows=1, cols=6)
    sched_table.style = "Table Grid"
    sched_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    headers = ("Gün", "Adım Adı", "Planlanan Başlangıç", "Bitiş", "Atanan Personel", "Biyolojik Kilit")
    for idx, text_h in enumerate(headers):
        cell = sched_table.rows[0].cells[idx]
        r = cell.paragraphs[0].add_run(text_h)
        r.bold = True
        r.font.size = Pt(8.5)

    for st in steps:
        row_cells = sched_table.add_row().cells
        assignees_str = ", ".join(u.full_name for u in st.assignees) if st.assignees else "Atanmadı"
        lock_str = (
            f"Kilitli (±{st.biological_tolerance_minutes} dk)"
            if st.is_biological_fixed_time
            else "Esnek"
        )
        vals = (
            f"G{st.study_day}",
            st.step_name,
            st.planned_start.strftime("%d.%m.%Y %H:%M"),
            st.planned_end.strftime("%d.%m.%Y %H:%M"),
            assignees_str,
            lock_str,
        )
        for idx, val in enumerate(vals):
            run = row_cells[idx].paragraphs[0].add_run(str(val))
            run.font.size = Pt(8.5)

    # 6. Bölüm: GLP Onay İmza Sirküleri
    h6 = doc.add_heading("6. GLP PROTOKOL ONAY İMZA SİRKÜLERİ", level=2)
    h6.runs[0].font.size = Pt(11)
    sig_table = doc.add_table(rows=4, cols=3)
    sig_table.style = "Table Grid"
    sig_headers = ("Rol / Ünvan", "Ad Soyad", "Tarih ve İmza")
    for idx, sh in enumerate(sig_headers):
        r = sig_table.rows[0].cells[idx].paragraphs[0].add_run(sh)
        r.bold = True
        r.font.size = Pt(9)

    sigs = [
        ("Çalışma Direktörü (Study Director - SD)", sd_name, "..... / ..... / 2026 — İmza:"),
        ("Test Tesisi Yöneticisi (TFM)", tfm_name, "..... / ..... / 2026 — İmza:"),
        ("Kalite Güvence Birimi (QA)", qa_name, "..... / ..... / 2026 — İmza:"),
    ]
    for r_idx, (role_lbl, person_nm, sig_line) in enumerate(sigs, start=1):
        sig_table.rows[r_idx].cells[0].paragraphs[0].add_run(role_lbl).font.size = Pt(9)
        sig_table.rows[r_idx].cells[1].paragraphs[0].add_run(person_nm).font.size = Pt(9)
        sig_table.rows[r_idx].cells[2].paragraphs[0].add_run(sig_line).font.size = Pt(9)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
