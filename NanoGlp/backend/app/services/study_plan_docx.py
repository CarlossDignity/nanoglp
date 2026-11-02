"""
FAZ 6.5 — ORİJİNAL NANOLAB GLP STUDY PLAN ŞABLONU (.DOCX) ÜRETİCİ

`backend/app/templates/nanolab_ic_study_plan_template.docx` resmi Nanolab şablonunu açar;
Nanolab logosunu, Figure-1 görselini, yazı tiplerini ve sayfa yapısını %100 koruyarak
paragraflardaki, tablo hücrelerindeki ve altbilgilerdeki (footer) tüm `XX...` / `GLP20XX-XXX`
yer tutucularını çalışmanın gerçek verileriyle (Dossier + Study + Schedule) doldurur.
Ayrıca Bölüm 4 (STUDY SCHEDULE - TENTATIVE) tablosunun hemen altına çalışmanın planlanan
adımlarının Gün Kodu, Tarih, Saat ve Sorumlu Personelini gösteren Operasyonel Takvim Tablosunu ekler.
"""
import io
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from docx import Document as DocxDocument
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Pt, RGBColor
from sqlalchemy.orm import Session

from app.models.document import Document as DbDocument
from app.models.study import Study
from app.models.study_step import StepStatus, StudyStep
from app.models.user import User, UserRole
from app.services.document_parser import aggregate_dossier

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "nanolab_ic_study_plan_template.docx"


def _val(primary: Any, fallback: Any = "N/A") -> str:
    if primary is not None and str(primary).strip() != "":
        return str(primary).strip()
    if fallback is not None and str(fallback).strip() != "":
        return str(fallback).strip()
    return "N/A"


def _replace_span_in_paragraph(paragraph, start_idx: int, end_idx: int, replacement: str) -> None:
    """
    Paragrafın run'ları üzerindeki [start_idx, end_idx) karakter aralığını,
    ilk eşleşen run'ın yazı tipi / stil (rPr) özelliklerini bozmadan `replacement` ile değiştirir.
    """
    runs = paragraph.runs
    if not runs:
        paragraph.text = (
            paragraph.text[:start_idx] + replacement + paragraph.text[end_idx:]
        )
        return

    pos = 0
    first_handled = False
    for r in runs:
        r_len = len(r.text)
        c_start = pos
        c_end = pos + r_len
        pos = c_end

        if c_end <= start_idx or c_start >= end_idx:
            continue

        if not first_handled:
            prefix = r.text[: max(0, start_idx - c_start)]
            suffix = r.text[end_idx - c_start :] if end_idx <= c_end else ""
            r.text = prefix + replacement + suffix
            first_handled = True
        else:
            if end_idx >= c_end:
                r.text = ""
            else:
                r.text = r.text[end_idx - c_start :]


def _replace_text_in_paragraph(paragraph, old_text: str, new_text: str, count: int = 1) -> int:
    """
    `old_text` birden fazla run'a bölünmüş olsa bile paragrafta bulup `new_text` ile değiştirir.
    """
    replaced = 0
    search_from = 0
    while count < 0 or replaced < count:
        full_text = "".join(r.text for r in paragraph.runs) if paragraph.runs else paragraph.text
        idx = full_text.find(old_text, search_from)
        if idx < 0:
            break
        _replace_span_in_paragraph(paragraph, idx, idx + len(old_text), new_text)
        search_from = idx + len(new_text)
        replaced += 1
    return replaced


def _replace_x_tokens_in_paragraph(paragraph, replacements: List[str]) -> None:
    """
    Paragraftaki `X{2,}` (en az 2 ardışık büyük X) yer tutucu bloklarını soldan sağa sırayla
    `replacements` listesindeki değerlerle (run formatını koruyarak) değiştirir.
    """
    for rep in replacements:
        full_text = "".join(r.text for r in paragraph.runs) if paragraph.runs else paragraph.text
        m = re.search(r"X{2,}", full_text)
        if not m:
            break
        _replace_span_in_paragraph(paragraph, m.start(), m.end(), str(rep))


def _set_cell_x_value(cell, value: str) -> None:
    """
    Tablo hücresindeki `X{2,}` yer tutucusunu (ve sonundaki fazla boşlukları) `value` ile değiştirir.
    """
    for p in cell.paragraphs:
        full_text = "".join(r.text for r in p.runs) if p.runs else p.text
        m = re.search(r"X{2,}\s*", full_text)
        if m:
            _replace_span_in_paragraph(p, m.start(), m.end(), str(value))
            return


def _extract_contact_parts(contact_raw: str) -> tuple[str, str]:
    """
    Sponsor iletişim metninden telefon ve e-posta bilgilerini ayrıştırır.
    """
    phone = "+90 541 630 36 36"
    email = "elisatibbi@gmail.com.tr"
    if contact_raw:
        m_mail = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", contact_raw)
        if m_mail:
            email = m_mail.group(0)
        m_phone = re.search(r"(\+?\d[\d\s()-]{8,}\d)", contact_raw)
        if m_phone:
            phone = m_phone.group(1).strip()
    return phone, email


def _insert_operational_schedule_table(doc: DocxDocument, anchor_table, steps: List[StudyStep], g0_date: Optional[date]) -> None:
    """
    Bölüm 4 (STUDY SCHEDULE - TENTATIVE) tablosunun hemen altına çalışmanın planlanan
    adımlarının Gün Kodu, Operasyonel Adım, Tarih, Saat ve Sorumlu Personelini gösteren
    kurumsal Operasyonel Takvim Tablosunu ekler.
    """
    if not steps:
        return

    caption_p = doc.add_paragraph()
    cap_run = caption_p.add_run("Operational Study Schedule (Planned Steps & Assigned Personnel):")
    cap_run.bold = True
    cap_run.font.name = "Arial"
    cap_run.font.size = Pt(9.5)

    sched_table = doc.add_table(rows=1, cols=5)
    tbl_pr = sched_table._tbl.tblPr
    tbl_borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        '<w:top w:val="single" w:sz="4" w:space="0" w:color="64748B"/>'
        '<w:left w:val="single" w:sz="4" w:space="0" w:color="64748B"/>'
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="64748B"/>'
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="64748B"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
        "</w:tblBorders>"
    )
    tbl_pr.append(tbl_borders)

    headers = ("Day Code", "Operational Step", "Date", "Time Window", "Responsible Personnel")
    hdr_cells = sched_table.rows[0].cells
    for idx, text_h in enumerate(headers):
        p = hdr_cells[idx].paragraphs[0]
        r = p.add_run(text_h)
        r.bold = True
        r.font.name = "Arial"
        r.font.size = Pt(8.5)

    for st in steps:
        row_cells = sched_table.add_row().cells
        assignees_str = ", ".join(u.full_name for u in st.assignees) if st.assignees else "Unassigned"
        day_offset = (st.planned_start.date() - g0_date).days if g0_date else st.study_day
        vals = (
            f"G{day_offset}",
            st.step_name,
            st.planned_start.strftime("%d.%m.%Y"),
            f"{st.planned_start.strftime('%H:%M')} - {st.planned_end.strftime('%H:%M')}",
            assignees_str,
        )
        for idx, val in enumerate(vals):
            p = row_cells[idx].paragraphs[0]
            r = p.add_run(str(val))
            r.font.name = "Arial"
            r.font.size = Pt(8.5)

    # Tabloyu ve başlığını Bölüm 4 tablosunun (anchor_table) hemen altına taşı
    anchor_table._tbl.addnext(sched_table._tbl)
    anchor_table._tbl.addnext(caption_p._p)


# ---------------------------------------------------------------------------
# FAZ 8.2 — ISO 10993-23 dışı şablonlar için Bölüm 1, 5–11, istatistik, veri derleme ve rapor metinleri
# ---------------------------------------------------------------------------
def _set_paragraph_text(p, text: str) -> None:
    """Paragrafın ilk run biçimini koruyarak tüm metni `text` ile değiştirir."""
    runs = p.runs
    if not runs:
        p.add_run(text)
        return
    runs[0].text = text
    for r in runs[1:]:
        r.text = ""


def _set_cell_text(cell, text: str) -> None:
    paras = cell.paragraphs
    if not paras:
        return
    _set_paragraph_text(paras[0], text)
    for extra in paras[1:]:
        extra._p.getparent().remove(extra._p)


def _apply_tokens(text: str, ctx: Dict[str, str]) -> str:
    for k, v in ctx.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def _grid_table(doc: DocxDocument, headers: List[str], rows: List[List[str]]):
    tbl = doc.add_table(rows=1, cols=len(headers))
    tbl._tbl.tblPr.append(
        parse_xml(
            f'<w:tblBorders {nsdecls("w")}>'
            '<w:top w:val="single" w:sz="4" w:space="0" w:color="64748B"/>'
            '<w:left w:val="single" w:sz="4" w:space="0" w:color="64748B"/>'
            '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="64748B"/>'
            '<w:right w:val="single" w:sz="4" w:space="0" w:color="64748B"/>'
            '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
            '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="CBD5E1"/>'
            "</w:tblBorders>"
        )
    )
    for i, h in enumerate(headers):
        run = tbl.rows[0].cells[i].paragraphs[0].add_run(h)
        run.bold = True
        run.font.name = "Arial"
        run.font.size = Pt(9)
    for row in rows:
        cells = tbl.add_row().cells
        for i, val in enumerate(row):
            run = cells[i].paragraphs[0].add_run(str(val))
            run.font.name = "Arial"
            run.font.size = Pt(8.5)
    return tbl


def _doc_blocks(doc: DocxDocument):
    """Gövde öğelerini (paragraf / tablo) H1-H2 bağlamıyla birlikte sırayla döner."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    h1 = h2 = ""
    blocks = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.split("}")[1]
        if tag == "p":
            p = Paragraph(child, doc)
            style = p.style.name if p.style is not None else ""
            txt = p.text.strip()
            if style == "Heading 1":
                h1, h2 = txt, ""
            elif style == "Heading 2":
                h2 = txt
            blocks.append(("p", p, h1, h2, style, txt))
        elif tag == "tbl":
            blocks.append(("t", Table(child, doc), h1, h2, "", ""))
    return blocks


def _adapt_for_template(db: Session, doc: DocxDocument, study: Study, test_item_name: str) -> None:
    """
    FAZ 8.1 + 8.2 — ISO 10993-23 dışındaki şablonlar (ISO 10993-6 İmplantasyon, -5 Sitotoksisite, -10 Sensitizasyon,
    -11 Akut Sistemik) için kapak/onay başlığı, standart adı ve ilgili tüm bölümlerin (Objective, Materials & Methods,
    Test System, Animal Welfare, HADYEK, Experimental Design, Observations, Pathology, Statistics, Data Compilation,
    Report, References) metinlerini şablon koduna göre dinamik olarak değiştirir; Annex A ekler.
    """
    from app.models.room_capacity import ensure_default_room_capacities
    from app.services.study_plan_content import TEMPLATE_CONTENT
    from app.services.templates import TEMPLATES, resolve_template_code

    tpl = TEMPLATES.get(resolve_template_code(study.template_code))
    if tpl is None or tpl.code == "ISO_10993_23_IC":
        return
    content = TEMPLATE_CONTENT.get(tpl.code, {})
    title_en = tpl.docx_title_en or tpl.title
    species_en = tpl.docx_species_en or tpl.species_label

    polar = f"polar ({study.extraction_polar_solvent})" if study.extraction_polar_solvent else "polar (0.9% NaCl)"
    non_polar = (
        f"non-polar ({study.extraction_non_polar_solvent})"
        if study.extraction_non_polar_solvent
        else "non-polar (Cottonseed oil)"
    )
    ctx = {
        "TEST_ITEM": test_item_name,
        "TITLE": title_en,
        "STANDARD": tpl.standard,
        "POLAR": polar,
        "NONPOLAR": non_polar,
        "RATIO": study.extraction_ratio or "3.0 g/10 mL (0.2 g/mL)",
        "TEMP": "37 ± 1",
        "HOURS": "72 ± 2",
        "N_ANIMALS": tpl.cage_count or "N/A",
        "CAGES": tpl.cage_count,
    }
    sections = content.get("sections", {})
    handled_ctx = set()
    blocks = _doc_blocks(doc)

    # 1) Bölüm bazlı içerik değişimi (orijinal H1/H2 bağlamına göre)
    for kind, obj, h1, h2, style, txt in blocks:
        H1 = h1.upper()
        try:
            if kind == "p":
                if style == "Heading 2":
                    sec = sections.get(h2)
                    if sec and sec[0]:
                        _set_paragraph_text(obj, sec[0])
                    continue
                if style == "Heading 1" or not txt:
                    continue

                if H1.startswith("STUDY OBJECTIVE") and content.get("objective") and ("objective", 1) not in handled_ctx:
                    _set_paragraph_text(obj, _apply_tokens(content["objective"], ctx))
                    handled_ctx.add(("objective", 1))
                elif H1.startswith("REFERENCES") and "ISO 10993-23:2021" in txt and content.get("reference"):
                    _set_paragraph_text(obj, content["reference"])
                elif H1.startswith("ANIMAL WELFARE") and content.get("welfare"):
                    n = sum(1 for k in handled_ctx if k[0] == "welfare")
                    if n < len(content["welfare"]):
                        _set_paragraph_text(obj, content["welfare"][n])
                        handled_ctx.add(("welfare", n))
                elif H1.startswith("HADYEK") and content.get("hadyek") and ("hadyek", 1) not in handled_ctx:
                    _set_paragraph_text(obj, content["hadyek"])
                    handled_ctx.add(("hadyek", 1))
                elif H1.startswith("STATISTICAL") and content.get("statistics") and ("stat", 1) not in handled_ctx:
                    _set_paragraph_text(obj, _apply_tokens(content["statistics"], ctx))
                    handled_ctx.add(("stat", 1))
                elif H1.startswith("DATA COMPILATION") and content.get("data_compilation") and ("data", 1) not in handled_ctx:
                    _set_paragraph_text(obj, _apply_tokens(content["data_compilation"], ctx))
                    handled_ctx.add(("data", 1))
                elif H1.startswith("REPORT") and not H1.startswith("REPORTING"):
                    new_line = (content.get("report_lines") or {}).get(txt)
                    if new_line:
                        _set_paragraph_text(obj, new_line)
                elif txt.startswith("Grading System for") and content.get("grading"):
                    _set_paragraph_text(obj, content["grading"]["title"])
                elif h2 in sections and sections[h2][1] and (h1, h2) not in handled_ctx:
                    _set_paragraph_text(obj, _apply_tokens(sections[h2][1], ctx))
                    handled_ctx.add((h1, h2))
            else:
                first = obj.rows[0].cells[0].text.strip() if obj.rows else ""
                if first == "Species" and content.get("test_system"):
                    _fill_label_table(obj, content["test_system"], ctx)
                elif first == "Location" and content.get("housing") is not None:
                    _fill_label_table(obj, content["housing"], ctx)
                elif first == "Intracutaneous Reaction" and content.get("grading"):
                    g = content["grading"]
                    new_tbl = _grid_table(doc, g["headers"], g["rows"])
                    obj._tbl.addprevious(new_tbl._tbl)
                    foot = doc.add_paragraph()
                    fr = foot.add_run(g["footnote"])
                    fr.italic = True
                    fr.font.name = "Arial"
                    fr.font.size = Pt(8.5)
                    new_tbl._tbl.addnext(foot._p)
                    obj._tbl.getparent().remove(obj._tbl)
                elif H1.startswith("EXPERIMENTAL DESIGN") and first == "":
                    # Enjeksiyon bölgeleri şekil tablosu (Figure-1: ISO 10993-23) bu şablonlarda geçerli değil
                    obj._tbl.getparent().remove(obj._tbl)
        except Exception:
            continue

    # 2) Genel metin değişimleri (başlık, standart adı, kılavuz başlığı)
    part_phrase = content.get("part_phrase")
    for p in doc.paragraphs:
        txt = p.text
        if "Intracutaneous Reactivity Test of" in txt:
            _replace_text_in_paragraph(p, "Intracutaneous Reactivity Test of", f"{title_en} of")
            _replace_text_in_paragraph(p, "Extract in New Zealand White Rabbits", f"in {species_en}")
        if part_phrase and "Part 23 Tests for Irritation" in p.text:
            _replace_text_in_paragraph(p, "Part 23 Tests for Irritation", part_phrase, count=-1)
        if "ISO 10993-23" in p.text:
            _replace_text_in_paragraph(p, "ISO 10993-23", tpl.standard, count=-1)

    # 3) Annex A — şablona özgü test tasarımı özeti
    room_txt = "None (in vitro study — no animal room required)"
    if tpl.animal_room:
        room = next((r for r in ensure_default_room_capacities(db) if r.room_code == tpl.animal_room), None)
        room_txt = (
            f"{room.room_label} ({tpl.animal_room}) — {tpl.cage_count} cage(s); physical capacity "
            f"{room.physical_cages}, system planning capacity {room.planning_capacity}"
            if room is not None
            else f"{tpl.animal_room} — {tpl.cage_count} cage(s)"
        )
    eq_txt = "; ".join(
        f"{code} (Day {day}, {hhmm}, {hours} h)" for code, day, hhmm, hours in tpl.equipment_windows
    ) or (", ".join(tpl.equipment_codes) if tpl.equipment_codes else "N/A")
    last_day = max((ts.day for ts in tpl.steps), default=0)

    head = doc.add_paragraph()
    hr = head.add_run(f"ANNEX A — TEMPLATE-SPECIFIC TEST DESIGN ({tpl.standard})")
    hr.bold = True
    hr.font.name = "Arial"
    hr.font.size = Pt(10.5)
    annex = _grid_table(
        doc,
        ["Item", "Value"],
        [
            ["Test", f"{title_en} — {tpl.standard}"],
            ["Test item", test_item_name],
            ["Test system", species_en],
            [
                "Animal number & cohorts",
                f"{tpl.animal_count} per cohort × {tpl.cohorts} cohort(s) (max {tpl.max_animals} animals)"
                if tpl.max_animals > 0
                else "0 (In vitro / Analytical)",
            ],
            ["Animal room / cages", room_txt],
            [
                "Standard durations & TAT",
                f"Quarantine {tpl.quarantine_days}d · Acclimatization {tpl.acclimatization_days}d · "
                f"Experiment {tpl.experiment_days}d · QA Audit {tpl.qa_audit_days}d · Report {tpl.report_days}d "
                f"(TAT: {tpl.tat_without_quarantine_days}d / {tpl.tat_with_quarantine_days}d with quarantine)",
            ],
            ["Fate of animals / Reuse policy", tpl.animal_fate_en or tpl.animal_fate_tr or "N/A"],
            ["Planned duration", f"Day 0 – Day {last_day} ({len(tpl.steps)} operational steps; see schedule above)"],
            ["24-72 h bottleneck equipment", eq_txt],
        ],
    )
    note = doc.add_paragraph()
    nr = note.add_run(
        f"NOTE: Sections 1 and 5–11 of this draft were generated automatically for {tpl.standard} from the Nanolab master "
        f"Study Plan template and the template-specific GLP text library. The Study Director must review and confirm all "
        f"sections (group sizes, doses, observation periods) before approval."
    )
    nr.italic = True
    nr.font.name = "Arial"
    nr.font.size = Pt(8.5)


def _fill_label_table(table, mapping: Dict[str, str], ctx: Dict[str, str]) -> None:
    """Etiket | : | değer biçimli tablolarda etiketi eşleşen satırların değer hücresini değiştirir."""
    for row in table.rows:
        cells = row.cells
        label = cells[0].text.strip()
        for key, val in mapping.items():
            if label == key or (key.endswith(":") and label.startswith(key)):
                target = cells[2] if len(cells) >= 3 and cells[2]._tc is not cells[0]._tc else cells[0]
                _set_cell_text(target, _apply_tokens(val, ctx))
                break


def generate_study_plan_docx(db: Session, study: Study) -> bytes:
    """
    Verilen Study kaydı için `nanolab_ic_study_plan_template.docx` şablonunu kullanarak
    resmi Nanolab GLP Study Plan (.docx) belgesini oluşturur ve byte olarak döner.
    """
    all_docs = (
        db.query(DbDocument)
        .filter(DbDocument.dossier_key != "DOSSIER-REF-ARCHIVE")
        .order_by(DbDocument.uploaded_at.desc(), DbDocument.id.desc())
        .all()
    )
    active_sds = (
        db.query(User)
        .filter(User.role == UserRole.STUDY_DIRECTOR, User.is_active == True)  # noqa: E712
        .order_by(User.id.asc())
        .all()
    )
    # FAZ 8.2: Çalışmanın kendi klasörüne (dossier_key = study_code) yüklenmiş TIIS/CoA/FM.083 belgeleri varsa yalnızca onları kullan
    own_docs = [d for d in all_docs if (d.dossier_key or '') == (study.study_code or '')]
    if own_docs:
        all_docs = own_docs
    tfm_user = (
        db.query(User)
        .filter(User.role == UserRole.TFM, User.is_active == True)  # noqa: E712
        .order_by(User.id.asc())
        .first()
    )

    dossier_fields: Dict[str, Any] = {}
    if all_docs:
        dossier = aggregate_dossier(all_docs, active_sds=active_sds)
        for k, entry in (dossier.get("fields") or {}).items():
            if isinstance(entry, dict) and entry.get("value") is not None:
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

    study_code = _val(study.study_code, "GLP2026-026")
    sponsor_name = _val(study.sponsor_name, dossier_fields.get("sponsor_name") or "ELISA TIBBI GEREÇLER SAN A.Ş.")
    sponsor_contact = _val(
        study.sponsor_contact,
        dossier_fields.get("sponsor_contact") or "Phone: +90 541 630 36 36, Email: elisatibbi@gmail.com.tr",
    )
    sponsor_phone, sponsor_email = _extract_contact_parts(sponsor_contact)

    raw_item_name = (
        study.test_item_name
        if study.test_item_name and "BELİRTİLMEDİ" not in study.test_item_name
        else None
    )
    test_item_name = _val(raw_item_name, dossier_fields.get("test_item_name") or "Hyaluronik Asit HA 30 mg/ml")
    intended_use = "Medical Device / Intra-articular or Dermal Filler"
    lot_batch = _val(study.test_item_batch, dossier_fields.get("lot_batch_no") or "EDC-NO-230586")
    mfg_date = _val(study.manufacture_date, dossier_fields.get("manufacture_date") or "11.2025")
    exp_date = _val(study.expiry_date, dossier_fields.get("expiry_date") or "11.2027")

    raw_storage = _val(study.test_item_storage_condition, dossier_fields.get("storage_conditions") or "")
    if not raw_storage or "serin" in raw_storage.lower() or "kuru" in raw_storage.lower() or raw_storage == "N/A":
        storage_cond = "Room Temperature (15-25 °C)"
    else:
        storage_cond = raw_storage

    polar_label = "polar (0.9% NaCl)"
    non_polar_label = "non-polar (Cottonseed oil)"
    extraction_ratio_label = "3.0 g/10 mL (0.2 g/mL)"
    extraction_temp_label = "37 ± 1"
    extraction_hours_label = "72 ± 2"

    animal_count_val = study.animal_count or dossier_fields.get("animal_count") or 6
    animal_count_str = (
        f"3 animals (or {animal_count_val} animals as per TIIS/FM.083)"
        if int(animal_count_val) != 3
        else "3 animals"
    )
    animal_source_str = "Certified Laboratory Animal Breeder (Ministry of Agriculture Approved)"
    diet_str = "standard laboratory pelleted feed (certified producer)"

    steps: List[StudyStep] = (
        db.query(StudyStep)
        .filter(StudyStep.study_id == study.id, StudyStep.status != StepStatus.CANCELLED)
        .order_by(StudyStep.step_order.asc())
        .all()
    )

    g0_date: date = (
        study.acclimatization_start_date
        or study.target_start_date
        or (steps[0].planned_start.date() if steps else date(2026, 7, 30))
    )
    exp_end_date: date = (
        steps[-1].planned_end.date()
        if steps
        else (study.target_end_date or (g0_date + timedelta(days=10)))
    )
    study_comp_date: date = exp_end_date + timedelta(days=14)

    init_date_str = g0_date.strftime("%d.%m.%Y")
    exp_start_str = g0_date.strftime("%d.%m.%Y")
    exp_end_str = exp_end_date.strftime("%d.%m.%Y")
    study_comp_str = study_comp_date.strftime("%d.%m.%Y")

    # Çalışmaya atanan personel listesi (TFM + In Vivo Teknisyenleri)
    assigned_names: List[str] = []
    if tfm_name:
        assigned_names.append(f"{tfm_name} (TFM)")
    for st in steps:
        for u in st.assignees:
            if u.full_name and u.full_name != sd_name and u.full_name != tfm_name:
                if u.full_name not in assigned_names:
                    assigned_names.append(u.full_name)
    if len(assigned_names) == 1:
        assigned_names.append("In Vivo Teknisyeni 1")
    study_personnel_names = ", ".join(assigned_names)

    doc = DocxDocument(str(TEMPLATE_PATH))

    # 1. Altbilgiler (Footers): GLP20XX-XXX -> study_code, Original X of X -> Original 1 of 2
    for sec in doc.sections:
        for attr in ("footer", "first_page_footer", "even_page_footer", "header", "first_page_header", "even_page_header"):
            hf = getattr(sec, attr, None)
            if not hf:
                continue
            for p in hf.paragraphs:
                _replace_text_in_paragraph(p, "GLP20XX-XXX", study_code)
                _replace_text_in_paragraph(p, "Original X of X", "Original 1 of 2")

    # 2. Paragraflardaki Yer Tutucuların Doldurulması
    for p in doc.paragraphs:
        txt = p.text
        if not txt:
            continue

        # Bölüm 5.3 Positive Control: Study No. GLP20XX-XXX -> GLP2026-PC01 (Ref)
        if "Sodium Lauryl Sulphate" in txt and "GLP20XX-XXX" in txt:
            _replace_text_in_paragraph(p, "GLP20XX-XXX", "GLP2026-PC01 (Ref)")
            continue

        # Kapak STUDY NUMBER: GLP20XX-XXX -> study_code
        if "GLP20XX-XXX" in txt:
            _replace_text_in_paragraph(p, "GLP20XX-XXX", study_code)
            continue

        # Kapak Başlığı & Bölüm 25 Onay Başlığı: Intracutaneous Reactivity Test of XXXXXXX Extract in New Zealand White Rabbits
        if "Intracutaneous Reactivity Test of" in txt and "Extract in New Zealand White Rabbits" in txt:
            _replace_x_tokens_in_paragraph(p, [test_item_name])
            continue

        # Bölüm 1 (STUDY OBJECTIVE): intracutaneous injection of XXXXX and XXXXX extracts of the test item, XXXXXXXXXXXXXX
        if "intracutaneous injection of" in txt and "extracts of the test item" in txt:
            _replace_x_tokens_in_paragraph(p, [polar_label, non_polar_label, test_item_name])
            continue

        # Bölüm 5.2 (Selection of Vehicle): the XXXX solvent as cottonseed oil and XXXXX solvent as normal saline
        if "solvent as cottonseed oil" in txt and "solvent as normal saline" in txt:
            _replace_x_tokens_in_paragraph(p, ["non-polar", polar_label])
            continue

        # Bölüm 9.1 (Preparation of Test Item Extract)
        if "Preparation of the test item extract" in txt and "shaking water bath" in txt:
            _replace_x_tokens_in_paragraph(
                p,
                [
                    test_item_name,
                    polar_label,
                    non_polar_label,
                    extraction_ratio_label,
                    extraction_temp_label,
                    extraction_hours_label,
                ],
            )
            continue

        # Bölüm 9.3 (Route of Administration)
        if "will be administered intracutaneously; similarly, the" in txt:
            _replace_x_tokens_in_paragraph(p, [polar_label, "polar", non_polar_label, "non-polar"])
            continue

        # Bölüm 9.5 (Administration of Test Item - Anterior / Posterior)
        if "anterior part of the left trunk" in txt and "posterior part of the right trunk" in txt:
            _replace_x_tokens_in_paragraph(p, ["polar", "polar", "non-polar", "non-polar"])
            continue

        # Bölüm 23 (Sponsor Representative): E-mail & Telephone
        if txt.strip().startswith("E-mail:") and "XX" in txt:
            _replace_x_tokens_in_paragraph(p, [sponsor_email])
            continue
        if txt.strip().startswith("Telephone:") and "XX" in txt:
            _replace_x_tokens_in_paragraph(p, [sponsor_phone])
            continue

    # İsim ve Sponsor satırlarını bağlamına (önceki başlığa) göre doldur
    last_heading = ""
    last_signature_label = ""
    for p in doc.paragraphs:
        txt = p.text.strip()
        if not txt:
            continue
        if txt in (
            "SPONSOR",
            "SPONSOR REPRESENTATIVE (MONITORING SCIENTIST)",
            "STUDY PLAN AGREEMENT (APPROVALS)",
        ):
            last_heading = txt
        if "(Signature and Date)" in txt:
            last_signature_label = txt

        if re.search(r"X{2,}", txt):
            if last_heading == "SPONSOR" and txt.startswith("XX"):
                _replace_x_tokens_in_paragraph(p, [sponsor_name])
            elif last_heading == "SPONSOR REPRESENTATIVE (MONITORING SCIENTIST)" and txt.startswith("Name:"):
                _replace_x_tokens_in_paragraph(p, [f"{sponsor_name} — Sponsor Representative"])
            elif last_heading == "STUDY PLAN AGREEMENT (APPROVALS)":
                if "Study Director" in last_signature_label and txt.startswith("Name:"):
                    _replace_x_tokens_in_paragraph(p, [sd_name])
                elif "Sponsor" in last_signature_label and txt.startswith("Name:"):
                    _replace_x_tokens_in_paragraph(p, [sponsor_name])
                elif "Sponsor" in last_signature_label and txt.startswith("XX"):
                    _replace_x_tokens_in_paragraph(p, [sponsor_name])

    # 3. Tablolardaki Yer Tutucuların Doldurulması
    # Table[1]: Section 4 — STUDY SCHEDULE (TENTATIVE)
    if len(doc.tables) > 1:
        t_sched = doc.tables[1]
        sched_map = {
            "Study Initiation Date": init_date_str,
            "Experiment Start Date": exp_start_str,
            "Experiment Completion Date": exp_end_str,
            "Study Completion Date": study_comp_str,
        }
        for row in t_sched.rows:
            label = row.cells[0].text.strip()
            if label in sched_map:
                _set_cell_x_value(row.cells[2], sched_map[label])

        # Bölüm 4 tablosunun hemen altına Operasyonel Takvim Tablosunu ekle
        _insert_operational_schedule_table(doc, t_sched, steps, g0_date)

    # Table[2]: Section 5.1 — Test item details
    for t in doc.tables:
        first_cell = t.rows[0].cells[0].text.strip() if t.rows else ""
        if first_cell == "Name of the test item":
            item_map = {
                "Name of the test item": test_item_name,
                "Intended Use": intended_use,
                "LOT Number": lot_batch,
                "Storage condition": storage_cond,
                "Date of Manufacture": mfg_date,
                "Date of Expiry": exp_date,
            }
            for row in t.rows:
                lbl = row.cells[0].text.strip()
                if lbl in item_map:
                    _set_cell_x_value(row.cells[2], item_map[lbl])

        # Section 6.2 — Test System Details/Characterization
        elif first_cell == "Species":
            for row in t.rows:
                lbl = row.cells[0].text.strip()
                if lbl == "Source":
                    _set_cell_x_value(row.cells[2], animal_source_str)
                elif lbl == "Number of animals":
                    for p in row.cells[2].paragraphs:
                        if "3 animals" in p.text:
                            _replace_text_in_paragraph(p, "3 animals", animal_count_str)

        # Section 6.3 — Housing (Diet and water)
        elif first_cell == "Location":
            for row in t.rows:
                lbl = row.cells[0].text.strip()
                if lbl == "Diet and water":
                    for p in row.cells[2].paragraphs:
                        _replace_x_tokens_in_paragraph(p, [diet_str])

        # Section 22 — LIST OF STUDY PERSONNEL (RESPONSIBILITIES)
        elif first_cell == "Personnel":
            for row in t.rows:
                role_lbl = row.cells[0].text.strip()
                if role_lbl == "Study Director":
                    for p in row.cells[1].paragraphs:
                        ptxt = p.text.strip()
                        if ptxt.startswith("Name:"):
                            _replace_x_tokens_in_paragraph(p, [sd_name])
                        elif ptxt.startswith("Telephone:"):
                            _replace_x_tokens_in_paragraph(p, ["+90 (284) 226 02 18"])
                        elif ptxt.startswith("Email:"):
                            _replace_x_tokens_in_paragraph(p, ["ezgi.akin@nanolab.com.tr"])
                elif role_lbl == "Study Personnel":
                    for p in row.cells[1].paragraphs:
                        ptxt = p.text.strip()
                        if ptxt.startswith("Name:"):
                            _replace_x_tokens_in_paragraph(p, [study_personnel_names])
                        elif ptxt.startswith("Telephone:"):
                            _replace_x_tokens_in_paragraph(p, ["+90 (284) 226 02 18"])
                        elif ptxt.startswith("Email:"):
                            _replace_x_tokens_in_paragraph(p, ["glp@nanolab.com.tr"])

    # FAZ 8.1: ISO 10993-23 dışı şablonlar için başlık / standart / Annex A uyarlaması
    try:
        _adapt_for_template(db, doc, study, test_item_name)
    except Exception:
        pass

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
