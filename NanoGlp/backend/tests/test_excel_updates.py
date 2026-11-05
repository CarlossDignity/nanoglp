"""Excel refresh contract; every run owns a disposable SQLite database."""

import io
import os
import sys
import tempfile
import unittest
from datetime import date, datetime
from unittest.mock import patch
from pathlib import Path

TMP = tempfile.TemporaryDirectory(prefix="nanoglp_excel_")
os.environ["DATABASE_URL"] = f"sqlite:///{TMP.name}/test.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openpyxl import Workbook
from app.database import SessionLocal, engine
from app.seed import reset_schema, seed_personnel
from app.models.sample import SampleRecord
from app.models.study import Study, StudyStatus
from app.models.study_step import StudyStep, StepStatus
from app.services import sample_service as ss


def workbook(code="GLP2026-901", lot="LOT-A", duplicate=False, blank=False):
    w = Workbook()
    s = w.active
    s.title = "GLP Medikal"
    values = {
        1: 1,
        2: "Intracutaneous Reactivity",
        3: "Item",
        4: "Ezgi Nur AKIN",
        5: "Company",
        8: code,
        13: "TI-SHARED",
        18: date(2026, 12, 7),
        25: "Planlanan",
        28: lot,
    }
    s.cell(7, 28, "Lot No")
    for c, v in values.items():
        s.cell(8, c, v)
    if blank:
        s.cell(8, 3).value = None
    if duplicate:
        for c, v in values.items():
            s.cell(9, c, v)
    b = io.BytesIO()
    w.save(b)
    return b.getvalue()


class ExcelUpdates(unittest.TestCase):
    def setUp(self):
        reset_schema()
        self.db = SessionLocal()
        self.user = seed_personnel(self.db)[1]

    def tearDown(self):
        self.db.close()

    def load(self, data=None, **kw):
        return ss.import_study_status_workbook(
            self.db, data or workbook(), self.user, **kw
        )

    def test_repeat_preserves_steps_and_new_once(self):
        self.load()
        ids = [s.id for s in self.db.query(StudyStep)]
        r = self.load()
        self.assertEqual(r["updated"], 0)
        self.assertEqual(r["created"], 0)
        self.assertEqual(ids, [s.id for s in self.db.query(StudyStep)])

    def test_approved_actual_and_workflow_preserved(self):
        self.load()
        st = self.db.query(Study).one()
        s = self.db.query(SampleRecord).one()
        st.status = StudyStatus.APPROVED
        st.protocol_approved_at = datetime(2026, 11, 1)
        s.workflow = {
            "6": {"approvals": {"CY": {"by": "Real", "at": "2026-11-01T09:31:00"}}}
        }
        step = self.db.query(StudyStep).first()
        step.actual_start = datetime(2026, 11, 2, 9, 31)
        step.status = StepStatus.IN_PROGRESS
        self.db.commit()
        old = s.workflow.copy()
        sid = step.id
        r = self.load(workbook(lot="LOT-B"))
        self.assertEqual(st.status, StudyStatus.APPROVED)
        self.assertEqual(s.workflow["6"], old["6"])
        self.assertEqual(
            self.db.get(StudyStep, sid).actual_start, datetime(2026, 11, 2, 9, 31)
        )
        self.assertEqual(s.lot_no, "LOT-B")
        self.assertEqual(st.test_item_batch, "LOT-B")
        self.assertGreater(r["review_required"], 0)

    def test_duplicate_rejected_atomically(self):
        try:
            r = self.load(workbook(duplicate=True))
        except ValueError:
            pass
        else:
            self.assertTrue(r["errors"])
        self.assertEqual(self.db.query(SampleRecord).count(), 0)

    def test_blank_preserves_value(self):
        self.load(auto_schedule=False)
        r = self.load(workbook(blank=True), auto_schedule=False)
        self.assertEqual(self.db.query(SampleRecord).one().test_item_name, "Item")
        self.assertGreater(r["review_required"], 0)

    def test_marker_has_no_signature_or_time(self):
        wf = ss._build_workflow_from_markers(
            ["+"] * 11, None, None, None, None, None, None, None, None
        )
        for item in wf.values():
            self.assertNotIn("approvals", item)
            self.assertNotIn("done_by", item)
            self.assertNotIn("done_at", item)

    def test_failure_rolls_back_all(self):
        with patch.object(
            ss, "plan_sample", side_effect=RuntimeError("injected failure")
        ):
            with self.assertRaises(RuntimeError):
                self.load()
        self.assertEqual(self.db.query(SampleRecord).count(), 0)

    def test_same_ti_distinct_studies_missing_row_preserved(self):
        self.load(auto_schedule=False)
        self.load(workbook("GLP2026-902"), auto_schedule=False)
        self.assertEqual(self.db.query(SampleRecord).count(), 2)

    def test_deadline_updates_without_touching_approved_schedule(self):
        self.load()
        st = self.db.query(Study).one()
        sample = self.db.query(SampleRecord).one()
        st.status = StudyStatus.IN_PROGRESS
        step = self.db.query(StudyStep).first()
        step.actual_reference_time = datetime(2026, 12, 7, 11, 23)
        self.db.commit()
        before = [
            {c.name: getattr(x, c.name) for c in StudyStep.__table__.columns}
            for x in self.db.query(StudyStep)
        ]
        from openpyxl import load_workbook

        w = load_workbook(io.BytesIO(workbook()))
        ws = w.active
        ws.cell(8, 18).value = date(2027, 1, 4)
        ws.cell(8, 23).value = date(2027, 2, 1)
        b = io.BytesIO()
        w.save(b)
        r = self.load(b.getvalue())
        self.assertEqual(sample.final_report_date, date(2027, 2, 1))
        self.assertNotEqual(st.target_start_date, date(2027, 1, 4))
        self.assertEqual(
            sample.workflow["_excel_source"]["planned_start"], "2027-01-04"
        )
        self.assertGreater(r["review_required"], 0)
        self.assertEqual(
            before,
            [
                {c.name: getattr(x, c.name) for c in StudyStep.__table__.columns}
                for x in self.db.query(StudyStep)
            ],
        )
        self.assertEqual(self.load(b.getvalue())["updated"], 0)

    def test_deleted_column_does_not_shift_fields(self):
        from app.services.excel_refresh import HEADERS
        from openpyxl import load_workbook

        w = load_workbook(io.BytesIO(workbook()))
        ws = w.active
        for c, h in HEADERS["glp"].items():
            ws.cell(7, c, h)
        b = io.BytesIO()
        w.save(b)
        self.load(b.getvalue(), auto_schedule=False)
        ws.delete_cols(3)
        b = io.BytesIO()
        w.save(b)
        self.load(b.getvalue(), auto_schedule=False)
        sample = self.db.query(SampleRecord).one()
        self.assertEqual(sample.test_item_name, "Item")
        self.assertEqual(sample.billing_company, "Company")
        self.assertEqual(sample.lot_no, "LOT-A")

    def test_official_unnamed_note_columns_follow_status(self):
        from app.services.excel_refresh import HEADERS
        from openpyxl import load_workbook

        w = load_workbook(io.BytesIO(workbook()))
        for c, h in HEADERS["glp"].items():
            w.active.cell(7, c, h)
        w.active.cell(8, 26, "Changed source note")
        w.active.delete_cols(3)
        b = io.BytesIO()
        w.save(b)
        self.load(b.getvalue(), auto_schedule=False)
        self.assertEqual(
            self.db.query(SampleRecord).one().sample_note, "Changed source note"
        )

    def test_full_workbook_repeat_is_noop(self):
        content = (
            Path(__file__).resolve().parents[2] / "Study Status last version (2).xlsx"
        ).read_bytes()
        first = self.load(content)
        self.assertEqual(first["created"], 93)
        snapshot = [
            {c.name: getattr(x, c.name) for c in StudyStep.__table__.columns}
            for x in self.db.query(StudyStep)
        ]
        second = self.load(content)
        self.assertEqual(second["updated"], 0)
        self.assertEqual(second["unchanged"], 93)
        self.assertEqual(second["auto_scheduled"], 0)
        self.assertEqual(
            snapshot,
            [
                {c.name: getattr(x, c.name) for c in StudyStep.__table__.columns}
                for x in self.db.query(StudyStep)
            ],
        )

    def test_late_failure_rolls_back_helper_commits(self):
        original = ss.plan_sample

        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("after scheduling helper commits")

        with patch.object(ss, "plan_sample", side_effect=fail):
            with self.assertRaises(RuntimeError):
                self.load()
        self.assertEqual(self.db.query(SampleRecord).count(), 0)
        self.assertEqual(self.db.query(Study).count(), 0)
        self.assertEqual(self.db.query(StudyStep).count(), 0)

    def test_normalized_existing_codes_share_one_study(self):
        self.load(auto_schedule=False)
        sample = self.db.query(SampleRecord).one()
        study = self.db.query(Study).one()
        sample.study_code = " glp2026-901 "
        self.db.commit()
        from openpyxl import load_workbook

        w = load_workbook(io.BytesIO(workbook()))
        w.active.cell(8, 18).value = date(2027, 1, 4)
        b = io.BytesIO()
        w.save(b)
        self.load(b.getvalue())
        self.assertEqual(self.db.query(Study).count(), 1)
        self.assertEqual(self.db.query(SampleRecord).count(), 1)
        self.assertGreater(
            self.db.query(StudyStep).filter_by(study_id=study.id).count(), 0
        )

    def test_imported_approval_serialization_has_no_fake_signatures(self):
        self.load(auto_schedule=False)
        sample = self.db.query(SampleRecord).one()
        study = self.db.query(Study).one()
        sample.workflow = ss._build_workflow_from_markers(
            ["+"] * 11, None, None, None, None, None, None, None, None
        )
        steps = ss.build_stepper(sample, study, False, ss.sample_permissions(self.user))
        for step in steps:
            self.assertIsNone(step["done_by"])
            self.assertIsNone(step["done_at"])
            for approval in step.get("approvals", []):
                self.assertFalse(approval["signed"])
                self.assertIsNone(approval["by"])
                self.assertIsNone(approval["at"])

    def test_actual_on_draft_prevents_replanning(self):
        self.load()
        study = self.db.query(Study).one()
        step = self.db.query(StudyStep).first()
        step.actual_reference_time = datetime(2026, 12, 7, 12, 34)
        self.db.commit()
        sid = step.id
        from openpyxl import load_workbook

        w = load_workbook(io.BytesIO(workbook()))
        w.active.cell(8, 18).value = date(2027, 1, 4)
        b = io.BytesIO()
        w.save(b)
        self.assertEqual(self.load(b.getvalue())["auto_scheduled"], 0)
        self.assertEqual(
            self.db.get(StudyStep, sid).actual_reference_time,
            datetime(2026, 12, 7, 12, 34),
        )


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        engine.dispose()
        TMP.cleanup()
