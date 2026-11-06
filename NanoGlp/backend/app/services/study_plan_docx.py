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
from datetime import date
from uuid import uuid4
from pathlib import Path
from typing import Any, Dict, List, Optional

from docx import Document as DocxDocument
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Pt, RGBColor
from sqlalchemy import String, or_
from sqlalchemy.orm import Session

from app.models.document import Document as DbDocument
from app.models.study import Study
from app.models.study_step import StepStatus, StudyStep
from app.models.user import UserRole
from app.services.document_parser import FIELD_CATEGORY_PRIORITY
from app.models.sample import SampleRecord

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "nanolab_ic_study_plan_template.docx"


def _val(primary: Any, fallback: Any = "TBD") -> str:
    for candidate in (primary, fallback):
        if candidate is None:
            continue
        text = str(candidate).strip()
        if text and text.upper() not in {"N/A", "TBD", "UNKNOWN", "BELİRTİLMEDİ", "BİLİNMİYOR", "-"}:
            return text
    return "TBD"


def _replace_span_in_paragraph(paragraph, start_idx: int, end_idx: int, replacement: str) -> None:
    """
    Paragrafın run'ları üzerindeki [start_idx, end_idx) karakter aralığını,
    ilk eşleşen run'ın yazı tipi / stil (rPr) özelliklerini bozmadan `replacement` ile değiştirir.
    """
    # Mutate text nodes, not Run.text: assigning Run.text removes drawings,
    # field codes and other non-text children that may share the same run.
    pos = 0
    inserted = False
    for run in paragraph.runs:
        for node in list(run._r):
            if node.tag == qn("w:t"):
                text = node.text or ""
                start, end = pos, pos + len(text)
                pos = end
                if end <= start_idx or start >= end_idx:
                    continue
                prefix = text[:max(0, start_idx - start)]
                suffix = text[end_idx - start:] if end_idx < end else ""
                node.text = prefix + (replacement if not inserted else "") + suffix
                node.set(qn("xml:space"), "preserve")
                inserted = True
            elif node.tag in (qn("w:tab"), qn("w:br"), qn("w:cr")):
                pos += 1


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


def _story_paragraphs(doc):
    """Include nested tables and every header/footer variant once."""
    from docx.text.paragraph import Paragraph
    stories = [doc.element.body]
    for section in doc.sections:
        for attr in ("header", "first_page_header", "even_page_header", "footer", "first_page_footer", "even_page_footer"):
            stories.append(getattr(section, attr)._element)
    seen = set()
    for story in stories:
        for element in story.xpath(".//w:p"):
            if element not in seen:
                seen.add(element)
                yield Paragraph(element, doc)


class _TemplateSlots:
    """Mark template slots before inserting data; never parse inserted values.

    A per-render namespace separates template provenance from literal XX in
    records. Text-node edits retain run styling, drawings and field codes.
    """

    def __init__(self, doc):
        self.prefix = f"\ue000{uuid4().hex}:"
        self.code = self.prefix + "study-code\ue001"
        self.pattern = re.compile(re.escape(self.prefix) + r"X{2,}\ue001")
        for paragraph in _story_paragraphs(doc):
            _replace_text_in_paragraph(paragraph, "Original X of X", "Original 1 of 2", count=-1)
            _replace_text_in_paragraph(paragraph, "GLP20XX-XXX", self.code, count=-1)
            # Positions belong to the pristine template, not to replacements.
            for match in reversed(list(re.finditer(r"(?<!\w)X{2,}(?!\w)", paragraph.text))):
                _replace_span_in_paragraph(paragraph, match.start(), match.end(),
                                           self.prefix + match.group() + "\ue001")

    def fill(self, paragraph, replacements):
        matches = list(self.pattern.finditer(paragraph.text))
        for match, value in reversed(list(zip(matches, replacements))):
            _replace_span_in_paragraph(paragraph, match.start(), match.end(), str(value))

    def fill_cell(self, cell, value):
        for paragraph in cell.paragraphs:
            if self.pattern.search(paragraph.text):
                self.fill(paragraph, [value])
                return

    def finish(self, doc, study_code):
        for paragraph in _story_paragraphs(doc):
            # Only the marked template slots are eligible for fallback.
            self.fill(paragraph, ["TBD"] * len(self.pattern.findall(paragraph.text)))
            _replace_text_in_paragraph(paragraph, self.code, study_code, count=-1)


def _extract_contact_parts(contact_raw: str) -> tuple[str, str]:
    """
    Sponsor iletişim metninden telefon ve e-posta bilgilerini ayrıştırır.
    """
    phone = "TBD"
    email = "TBD"
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
        assignees_str = ", ".join(u.full_name for u in st.assignees) if st.assignees else "TBD"
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
    from app.models.room_capacity import AnimalRoomCapacity
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
                    # Master şablonun referans şekli ve özgün kaynak açıklaması korunur.
                    pass  # Retain the original reference figure and image relationships.
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
        room = db.query(AnimalRoomCapacity).filter(AnimalRoomCapacity.room_code == tpl.animal_room).first()
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
    code = study.study_code
    # A JSON substring match is only a candidate filter; exact membership below
    # prevents DOCX-A from consuming DOCX-AB. Sponsor/TI are never join keys.
    candidates = db.query(DbDocument).filter(
        or_(DbDocument.dossier_key == code, DbDocument.primary_study_code == code,
            DbDocument.study_codes.cast(String).contains(code, autoescape=True)),
        DbDocument.status != "FAILED",
    ).order_by(DbDocument.uploaded_at.desc(), DbDocument.id.desc()).all() if code else []
    own_docs = [d for d in candidates if d.dossier_key == code or d.primary_study_code == code
                or (isinstance(d.study_codes, list) and code in d.study_codes)]
    dossier_fields = {}
    # Reuse category precedence without the aggregate dossier's demo bonuses,
    # inferred study mappings, or default personnel resolution.
    keys = {k for d in own_docs for k in (d.extracted_data or {})}
    for key in keys:
        eligible = [d for d in own_docs if (d.extracted_data or {}).get(key) not in (None, "", [])]
        priority = FIELD_CATEGORY_PRIORITY.get(key, ())
        def rank(doc):
            category = doc.doc_category or (doc.extracted_data or {}).get("doc_category")
            return priority.index(category) if category in priority else len(priority)
        if eligible:
            dossier_fields[key] = min(eligible, key=rank).extracted_data[key]
    sample = db.query(SampleRecord).filter(SampleRecord.study_code == code).first() if code else None
    def value(study_field, document_field, sample_field=None):
        recorded = getattr(study, study_field, None) if study_field else None
        sampled = getattr(sample, sample_field, None) if sample and sample_field else None
        return _val(recorded, _val(sampled, dossier_fields.get(document_field)))

    sd_name = _val(study.study_director.full_name if study.study_director else None)
    sd_phone = _val(study.study_director.phone if study.study_director else None)
    sd_email = _val(study.study_director.email if study.study_director else None)
    qa_name = _val(study.qa_officer.full_name if study.qa_officer else None)
    study_code = _val(code)
    sponsor_name = value("sponsor_name", "sponsor_name", "sponsor_name")
    sample_contacts = "; ".join(" ".join(str(c.get(k) or "") for k in ("name", "email", "phone"))
                                for c in (sample.contacts or []) if isinstance(c, dict)) if sample else None
    sponsor_contact = _val(study.sponsor_contact, _val(sample_contacts, dossier_fields.get("sponsor_contact")))
    sponsor_phone, sponsor_email = _extract_contact_parts(sponsor_contact)
    raw_item_name = study.test_item_name if study.test_item_name and "BELİRTİLMEDİ" not in study.test_item_name else None
    test_item_name = _val(raw_item_name, _val(sample.test_item_name if sample else None, dossier_fields.get("test_item_name")))
    intended_use = _val(dossier_fields.get("intended_use"))
    lot_batch = value("test_item_batch", "lot_batch_no", "lot_no")
    mfg_date = value("manufacture_date", "manufacture_date", "manufacture_date")
    exp_date = value("expiry_date", "expiry_date", "expiry_date")
    storage_cond = value("test_item_storage_condition", "storage_conditions", "storage_condition")

    polar_label = "polar (0.9% NaCl)"
    non_polar_label = "non-polar (Cottonseed oil)"
    extraction_ratio_label = "3.0 g/10 mL (0.2 g/mL)"
    extraction_temp_label = "37 ± 1"
    extraction_hours_label = "72 ± 2"

    animal_count_val = study.animal_count or dossier_fields.get("animal_count")
    animal_count_str = f"{animal_count_val} animals" if animal_count_val else "TBD"
    animal_source_str = _val(dossier_fields.get("animal_source"))
    diet_str = _val(dossier_fields.get("diet"))

    steps: List[StudyStep] = (
        db.query(StudyStep)
        .filter(StudyStep.study_id == study.id, StudyStep.status != StepStatus.CANCELLED)
        .order_by(StudyStep.step_order.asc())
        .all()
    )

    g0_date = study.acclimatization_start_date or study.target_start_date or (
        min(st.planned_start for st in steps).date() if steps else None)
    exp_end_date = study.target_end_date or (max(st.planned_end for st in steps).date() if steps else None)
    def date_text(value):
        return value.strftime("%d.%m.%Y") if value else "TBD"
    init_date_str = exp_start_str = date_text(g0_date)
    exp_end_str = date_text(exp_end_date)
    # There is no persisted study-completion plan field; do not invent end + 14d.
    study_comp_str = "TBD"
    assigned = {u.id: u for st in steps for u in st.assignees}
    personnel = [u for u in assigned.values() if u.id != study.study_director_id]
    study_personnel_names = _val(", ".join(u.full_name for u in personnel))
    personnel_phone = _val(", ".join(u.phone for u in personnel if u.phone))
    personnel_email = _val(", ".join(u.email for u in personnel if u.email))
    managers = [u for u in personnel if u.role in (UserRole.TFM, UserRole.EXECUTIVE)]
    management_name = _val(managers[0].full_name if len(managers) == 1 else None)

    doc = DocxDocument(str(TEMPLATE_PATH))

    # Convert example names only in their original approval-role fields, before
    # any real data is inserted. Identical names elsewhere are literal content.
    approval_role = ""
    in_approvals = False
    examples = {"Quality Assurance": "Name: Selin BOLCAN",
                "Management": "Name: Dr. Shivadasan ANOOP"}
    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if text == "STUDY PLAN AGREEMENT (APPROVALS)":
            in_approvals = True
        elif paragraph.style.name == "Heading 1":
            in_approvals = False
        if in_approvals and "(Signature and Date)" in text:
            approval_role = text.split(" (Signature and Date)", 1)[0]
        elif in_approvals and text == examples.get(approval_role):
            _replace_text_in_paragraph(paragraph, text, "Name: XXXXX")
    slots = _TemplateSlots(doc)

    # 2. Paragraflardaki Yer Tutucuların Doldurulması
    for p in doc.paragraphs:
        txt = p.text
        if not txt:
            continue

        # Pozitif kontrol için kayıtlı çalışma numarası yoksa örnek numara üretme.
        if "Sodium Lauryl Sulphate" in txt and slots.code in txt:
            _replace_text_in_paragraph(p, slots.code, "TBD")
            continue

        # Kapak STUDY NUMBER: GLP20XX-XXX -> study_code
        if slots.code in txt:
            _replace_text_in_paragraph(p, slots.code, study_code)
            continue

        # Kapak Başlığı & Bölüm 25 Onay Başlığı: Intracutaneous Reactivity Test of XXXXXXX Extract in New Zealand White Rabbits
        if "Intracutaneous Reactivity Test of" in txt and "Extract in New Zealand White Rabbits" in txt:
            slots.fill(p, [test_item_name])
            continue

        # Bölüm 1 (STUDY OBJECTIVE): intracutaneous injection of XXXXX and XXXXX extracts of the test item, XXXXXXXXXXXXXX
        if "intracutaneous injection of" in txt and "extracts of the test item" in txt:
            slots.fill(p, [polar_label, non_polar_label, test_item_name])
            continue

        # Bölüm 5.2 (Selection of Vehicle): the XXXX solvent as cottonseed oil and XXXXX solvent as normal saline
        if "solvent as cottonseed oil" in txt and "solvent as normal saline" in txt:
            slots.fill(p, ["non-polar", polar_label])
            continue

        # Bölüm 9.1 (Preparation of Test Item Extract)
        if "Preparation of the test item extract" in txt and "shaking water bath" in txt:
            slots.fill(
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
            slots.fill(p, [polar_label, "polar", non_polar_label, "non-polar"])
            continue

        # Bölüm 9.5 (Administration of Test Item - Anterior / Posterior)
        if "anterior part of the left trunk" in txt and "posterior part of the right trunk" in txt:
            slots.fill(p, ["polar", "polar", "non-polar", "non-polar"])
            continue

        # Bölüm 23 (Sponsor Representative): E-mail & Telephone
        if txt.strip().startswith("E-mail:") and slots.pattern.search(txt):
            slots.fill(p, [sponsor_email])
            continue
        if txt.strip().startswith("Telephone:") and slots.pattern.search(txt):
            slots.fill(p, [sponsor_phone])
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

        if slots.pattern.search(txt):
            if last_heading == "SPONSOR" and txt.startswith(slots.prefix):
                slots.fill(p, [sponsor_name])
            elif last_heading == "SPONSOR REPRESENTATIVE (MONITORING SCIENTIST)" and txt.startswith("Name:"):
                slots.fill(p, [_val(dossier_fields.get("sponsor_representative"))])
            elif last_heading == "STUDY PLAN AGREEMENT (APPROVALS)":
                if "Study Director" in last_signature_label and txt.startswith("Name:"):
                    slots.fill(p, [sd_name])
                elif "Quality Assurance" in last_signature_label and txt.startswith("Name:"):
                    slots.fill(p, [qa_name])
                elif "Management" in last_signature_label and txt.startswith("Name:"):
                    slots.fill(p, [management_name])
                elif "Sponsor" in last_signature_label and txt.startswith("Name:"):
                    slots.fill(p, [_val(dossier_fields.get("sponsor_representative"))])
                elif "Sponsor" in last_signature_label and txt.startswith(slots.prefix):
                    slots.fill(p, [sponsor_name])

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
                slots.fill_cell(row.cells[2], sched_map[label])

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
                    slots.fill_cell(row.cells[2], item_map[lbl])

        # Section 6.2 — Test System Details/Characterization
        elif first_cell == "Species":
            for row in t.rows:
                lbl = row.cells[0].text.strip()
                if lbl == "Source":
                    slots.fill_cell(row.cells[2], animal_source_str)
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
                        slots.fill(p, [diet_str])

        # Section 22 — LIST OF STUDY PERSONNEL (RESPONSIBILITIES)
        elif first_cell == "Personnel":
            for row in t.rows:
                role_lbl = row.cells[0].text.strip()
                if role_lbl == "Study Director":
                    for p in row.cells[1].paragraphs:
                        ptxt = p.text.strip()
                        if ptxt.startswith("Name:"):
                            slots.fill(p, [sd_name])
                        elif ptxt.startswith("Telephone:"):
                            slots.fill(p, [sd_phone])
                        elif ptxt.startswith("Email:"):
                            slots.fill(p, [sd_email])
                elif role_lbl == "Study Personnel":
                    for p in row.cells[1].paragraphs:
                        ptxt = p.text.strip()
                        if ptxt.startswith("Name:"):
                            slots.fill(p, [study_personnel_names])
                        elif ptxt.startswith("Telephone:"):
                            slots.fill(p, [personnel_phone])
                        elif ptxt.startswith("Email:"):
                            slots.fill(p, [personnel_email])

    # FAZ 8.1: ISO 10993-23 dışı şablonlar için başlık / standart / Annex A uyarlaması
    try:
        _adapt_for_template(db, doc, study, test_item_name)
    except Exception:
        pass

    slots.finish(doc, study_code)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
