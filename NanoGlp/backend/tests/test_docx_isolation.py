"""Inspect real DOCX parts; all database state is disposable."""

import io
import os
import sys
import tempfile
import unittest
import zipfile
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from lxml import etree
from docx import Document

TMP = tempfile.TemporaryDirectory(prefix="nanoglp_docx_")
os.environ["DATABASE_URL"] = f"sqlite:///{TMP.name}/test.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import Base, SessionLocal, engine
import app.models
from app.models.study import Study, StudyStatus
from app.models.study_step import StudyStep, StepStatus
from app.models.user import User, UserRole
from app.models.document import Document as DbDocument
from app.models.sample import SampleRecord
from app.services import study_plan_docx as export


def xml_text(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return "\n".join(
            "".join(etree.fromstring(z.read(n)).itertext())
            for n in z.namelist()
            if n.startswith("word/") and n.endswith(".xml")
        )


def media(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return {
            n: z.read(n)
            for n in z.namelist()
            if n.startswith("word/media/") and not n.endswith("/")
        }


class DocxIsolation(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.db = SessionLocal()
        self.sd = User(
            username="assigned",
            full_name="Assigned Director",
            email="assigned@example.test",
            role=UserRole.STUDY_DIRECTOR,
        )
        self.qa = User(username="qa", full_name="Assigned QA", role=UserRole.QA)
        self.db.add_all([self.sd, self.qa])
        self.db.flush()
        self.a = Study(
            study_code="DOCX-A",
            title="A",
            test_item_name="",
            study_director_id=self.sd.id,
            qa_officer_id=self.qa.id,
            template_code="ISO_10993_23_IC",
            status=StudyStatus.DRAFT,
        )
        self.db.add(self.a)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def document(self, code="DOCX-B", **links):
        doc = DbDocument(
            original_filename="other.pdf",
            stored_filename="other.pdf",
            size_bytes=1,
            sha256="a" * 64,
            dossier_key=code,
            extracted_data={
                "sponsor_name": "Foreign Sponsor",
                "sponsor_contact": "foreign@example.test +90 555 111 22 33",
                "test_item_name": "Foreign Product",
                "lot_batch_no": "FOREIGN-LOT",
                "manufacture_date": "FOREIGN-MFG",
                "expiry_date": "FOREIGN-EXP",
                "acclimatization_start_date": "2029-05-21",
            },
        )
        for k, v in links.items():
            setattr(doc, k, v)
        self.db.add(doc)
        self.db.commit()
        return doc

    def output(self):
        return export.generate_study_plan_docx(self.db, self.a)

    def test_unrelated_docs_and_demo_values_never_fill_missing_fields(self):
        self.document()
        text = xml_text(self.output())
        for value in (
            "Foreign Sponsor",
            "Foreign Product",
            "FOREIGN-LOT",
            "FOREIGN-MFG",
            "FOREIGN-EXP",
            "foreign@example.test",
            "ELISA TIBBI",
            "EDC-NO-230586",
            "Hyaluronik Asit",
            "30.07.2026",
            "11.2025",
            "11.2027",
            "ezgi.akin@",
            "Selin BOLCAN",
            "Dr. Shivadasan ANOOP",
        ):
            self.assertNotIn(value, text)
        doc = Document(io.BytesIO(self.output()))
        for table in doc.tables:
            for row in table.rows:
                if row.cells[0].text.strip() in (
                    "LOT Number",
                    "Date of Manufacture",
                    "Date of Expiry",
                    "Study Initiation Date",
                    "Experiment Start Date",
                    "Experiment Completion Date",
                    "Study Completion Date",
                ):
                    self.assertEqual(row.cells[2].text.strip(), "TBD")
        self.assertIn("Assigned Director", text)
        self.assertIn("assigned@example.test", text)
        self.assertIn("Assigned QA", text)

    def test_explicit_links_and_record_precedence(self):
        for link in (
            {"dossier_key": "DOCX-A"},
            {"primary_study_code": "DOCX-A"},
            {"study_codes": ["DOCX-A", "DOCX-B"]},
        ):
            with self.subTest(link=link):
                self.db.query(DbDocument).delete()
                self.db.commit()
                self.document(**link)
                text = xml_text(self.output())
                for v in (
                    "Foreign Sponsor",
                    "Foreign Product",
                    "FOREIGN-LOT",
                    "FOREIGN-MFG",
                    "FOREIGN-EXP",
                ):
                    self.assertIn(v, text)
                self.assertNotIn("21.05.2029", text)
        self.a.test_item_name = "Recorded Product"
        self.a.test_item_batch = "RECORDED-LOT"
        self.db.commit()
        text = xml_text(self.output())
        self.assertIn("RECORDED-LOT", text)
        self.assertNotIn("FOREIGN-LOT", text)

    def test_shared_sponsor_ti_and_partial_codes_are_not_links(self):
        self.a.sponsor_name = "Shared Sponsor"
        self.db.add_all(
            [
                SampleRecord(study_code="DOCX-A", test_item_code="TI-SHARED"),
                SampleRecord(
                    study_code="DOCX-B",
                    test_item_code="TI-SHARED",
                    lot_no="OTHER-SAMPLE-LOT",
                ),
            ]
        )
        self.db.commit()
        d = self.document(study_codes=["DOCX-AB"])
        d.extracted_data = dict(
            d.extracted_data, sponsor_name="Shared Sponsor", test_item_code="TI-SHARED"
        )
        self.db.commit()
        text = xml_text(self.output())
        for v in ("Foreign Product", "FOREIGN-LOT", "OTHER-SAMPLE-LOT"):
            self.assertNotIn(v, text)

    def test_real_x_values_are_preserved_in_records_and_linked_documents(self):
        for source in ("record", "document"):
            with self.subTest(source=source):
                if source == "record":
                    self.a.test_item_name = "EXXON XXL Product"
                    self.a.sponsor_name = "EXXON XXL Sponsor"
                    self.a.test_item_batch = "LOT-XX123"
                    self.db.commit()
                else:
                    self.a.test_item_name = self.a.sponsor_name = (
                        self.a.test_item_batch
                    ) = ""
                    d = self.document(code="DOCX-A")
                    d.extracted_data = {
                        "test_item_name": "EXXON XXL Product",
                        "sponsor_name": "EXXON XXL Sponsor",
                        "lot_batch_no": "LOT-XX123",
                    }
                    self.db.commit()
                doc = Document(io.BytesIO(self.output()))
                cells = {
                    r.cells[0].text.strip(): r.cells[2].text.strip()
                    for t in doc.tables
                    for r in t.rows
                    if len(r.cells) == 3
                }
                self.assertEqual(cells["LOT Number"], "LOT-XX123")
                self.assertEqual(cells["Name of the test item"], "EXXON XXL Product")
                self.assertEqual(cells["Date of Manufacture"], "TBD")
                self.assertIn(
                    "EXXON XXL Sponsor", [p.text.strip() for p in doc.paragraphs]
                )
                preparation = next(
                    p.text
                    for p in doc.paragraphs
                    if "Preparation of the test item extract" in p.text
                )
                self.assertIn("EXXON XXL Product", preparation)
                self.assertIn("polar (0.9% NaCl)", preparation)
                self.assertIn("non-polar (Cottonseed oil)", preparation)
                self.assertNotIn("ETBDON", preparation)

    def test_real_assignee_names_matching_template_examples_are_preserved(self):
        self.sd.full_name = "Selin BOLCAN"
        colleague = User(
            username="tech",
            full_name="Dr. Shivadasan ANOOP",
            email="tech@example.test",
            role=UserRole.TECHNICIAN,
        )
        step = StudyStep(
            study_id=self.a.id,
            step_name="Existing",
            planned_start=datetime(2027, 1, 4, 9),
            planned_end=datetime(2027, 1, 4, 10),
            status=StepStatus.PENDING,
        )
        step.assignees = [self.sd, colleague]
        self.db.add(step)
        self.db.commit()
        doc = Document(io.BytesIO(self.output()))
        personnel = next(
            t for t in doc.tables if t.cell(0, 0).text.strip() == "Personnel"
        )
        roles = {r.cells[0].text.strip(): r.cells[1].text for r in personnel.rows}
        self.assertIn("Name: Selin BOLCAN", roles["Study Director"])
        self.assertIn("Name: Dr. Shivadasan ANOOP", roles["Study Personnel"])
        paragraphs = [p.text.strip() for p in doc.paragraphs]
        for role, expected in (
            ("Study Director", "Selin BOLCAN"),
            ("Quality Assurance", "Assigned QA"),
            ("Management", "TBD"),
        ):
            i = next(
                i
                for i, p in enumerate(paragraphs)
                if p.startswith(role + " (Signature")
            )
            self.assertEqual(paragraphs[i + 1], "Name: " + expected)
        schedule = next(
            t
            for t in doc.tables
            if any("Existing" in c.text for r in t.rows for c in r.cells)
        )
        self.assertIn("Selin BOLCAN", schedule.cell(1, 4).text)
        self.assertIn("Dr. Shivadasan ANOOP", schedule.cell(1, 4).text)

    def test_template_roles_and_missing_slots_are_distinct_from_literal_data(self):
        template = Document(str(export.TEMPLATE_PATH))
        template.sections[0].header.add_paragraph("Reference author: Selin BOLCAN")
        template.sections[0].footer.add_paragraph(
            "Reference author: Dr. Shivadasan ANOOP"
        )
        missing = template.sections[0].header.add_paragraph("Missing: ")
        run = missing.add_run("XXXXX")
        run.bold = True
        run.italic = True
        template.sections[0].header.add_paragraph("Reference product: EXXON XXL")
        path = Path(TMP.name) / "roles.docx"
        template.save(path)
        self.a.test_item_batch = "XX"
        self.a.test_item_name = "GLP20XX-XXX Original X of X"
        self.db.commit()
        with patch.object(export, "TEMPLATE_PATH", path):
            blob = self.output()
        doc = Document(io.BytesIO(blob))
        cells = {
            r.cells[0].text.strip(): r.cells[2].text.strip()
            for t in doc.tables
            for r in t.rows
            if len(r.cells) == 3
        }
        self.assertEqual(cells["LOT Number"], "XX")
        self.assertEqual(cells["Name of the test item"], "GLP20XX-XXX Original X of X")
        self.assertEqual(cells["Date of Expiry"], "TBD")
        text = xml_text(blob)
        for value in (
            "Reference author: Selin BOLCAN",
            "Reference author: Dr. Shivadasan ANOOP",
            "Reference product: EXXON XXL",
            "Missing: TBD",
        ):
            self.assertIn(value, text)
        filled = next(
            p for p in doc.sections[0].header.paragraphs if p.text == "Missing: TBD"
        )
        self.assertTrue(filled.runs[1].bold)
        self.assertTrue(filled.runs[1].italic)
        self.assertEqual(media(blob), media(path.read_bytes()))

    def test_media_nested_tables_and_headers_are_preserved(self):
        template = Document(str(export.TEMPLATE_PATH))
        template.sections[0].header.add_paragraph("Unknown header: XXXXX")
        table = template.sections[0].footer.add_table(rows=1, cols=1, width=1000000)
        table.cell(0, 0).text = "Unknown footer: XXXXX"
        nested = template.tables[2].cell(0, 2).add_table(rows=1, cols=1)
        nested.cell(0, 0).text = "Unknown nested: XXXXX"
        path = Path(TMP.name) / "template.docx"
        template.save(path)
        with patch.object(export, "TEMPLATE_PATH", path):
            blob = self.output()
        text = xml_text(blob)
        for v in ("Unknown header: TBD", "Unknown footer: TBD", "Unknown nested: TBD"):
            self.assertIn(v, text)
        self.assertEqual(media(blob), media(path.read_bytes()))
        self.assertIn("Figure-1", text)
        self.assertIn("ISO 10993-23", text)

    def test_export_does_not_mutate_operational_state(self):
        self.a.target_start_date = date(2027, 1, 4)
        self.a.target_end_date = date(2027, 1, 14)
        self.a.protocol_approved_at = datetime(2026, 12, 3, 9, 1)
        self.a.dossier_metadata = {"biological_revisions": [{"note": "retain"}]}
        step = StudyStep(
            study_id=self.a.id,
            step_name="Existing",
            planned_start=datetime(2027, 1, 4, 9, 37),
            planned_end=datetime(2027, 1, 4, 10, 12),
            actual_start=datetime(2027, 1, 4, 9, 40),
            actual_reference_time=datetime(2027, 1, 4, 9, 45),
            status=StepStatus.IN_PROGRESS,
        )
        step.assignees = [self.sd]
        self.db.add(step)
        self.db.add(
            SampleRecord(
                study_code="DOCX-A",
                workflow={
                    "6": {
                        "approvals": {
                            "CY": {"by": "Actual", "at": "2026-12-03T09:01:00"}
                        }
                    }
                },
            )
        )
        self.db.commit()

        def snapshot():
            return {
                table.name: [
                    dict(row) for row in self.db.execute(table.select()).mappings()
                ]
                for table in Base.metadata.sorted_tables
            }

        before = snapshot()
        blob = self.output()
        self.db.commit()
        self.assertEqual(before, snapshot())
        text = xml_text(blob)
        self.assertIn("09:37", text)
        self.assertIn("10:12", text)
        self.assertIn("04.01.2027", text)

    def test_non_ic_export_is_read_only_and_keeps_template_protocol(self):
        self.a.template_code = "ISO_10993_6_IMP"
        self.db.commit()
        before = {
            t.name: [dict(r) for r in self.db.execute(t.select()).mappings()]
            for t in Base.metadata.sorted_tables
        }
        blob = self.output()
        self.db.commit()
        after = {
            t.name: [dict(r) for r in self.db.execute(t.select()).mappings()]
            for t in Base.metadata.sorted_tables
        }
        self.assertEqual(before, after)
        self.assertIn("ISO 10993-6", xml_text(blob))
        self.assertIn("ANNEX A", xml_text(blob))
        self.assertEqual(media(blob), media(export.TEMPLATE_PATH.read_bytes()))

    def test_sample_download_without_schedule_does_not_plan(self):
        from app.api.v1.endpoints.samples import download_study_plan

        sample = SampleRecord(study_code=self.a.study_code, stored_status="PLANNED")
        self.db.add(sample)
        self.db.commit()
        response = download_study_plan(sample.id, self.db, self.sd)
        self.assertIn("TBD", xml_text(response.body))
        self.assertEqual(self.db.query(StudyStep).count(), 0)
        self.assertIsNone(self.a.target_start_date)
        self.assertIsNone(self.a.target_end_date)

    def test_placeholder_in_picture_run_preserves_image_relationship(self):
        template = Document(str(export.TEMPLATE_PATH))
        paragraph = template.sections[0].header.add_paragraph()
        run = paragraph.add_run("XX")
        picture = next(iter(media(export.TEMPLATE_PATH.read_bytes()).values()))
        run.add_picture(io.BytesIO(picture))
        paragraph.add_run("XXX")
        path = Path(TMP.name) / "mixed-run.docx"
        template.save(path)

        def drawings(blob):
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                return sum(
                    len(etree.fromstring(z.read(n)).xpath('//*[local-name()="blip"]'))
                    for n in z.namelist()
                    if n.startswith("word/") and n.endswith(".xml")
                )

        with patch.object(export, "TEMPLATE_PATH", path):
            blob = self.output()
        self.assertEqual(drawings(blob), drawings(path.read_bytes()))
        self.assertEqual(media(blob), media(path.read_bytes()))
        header = Document(io.BytesIO(blob)).sections[0].header
        self.assertEqual(header.paragraphs[-1].text, "TBD")


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        engine.dispose()
        TMP.cleanup()
