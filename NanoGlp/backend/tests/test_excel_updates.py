"""Excel refresh contract; every run owns a disposable SQLite database."""

import atexit
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

atexit.register(engine.dispose)
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
        # Live indicators must not depend on the machine's calendar date.
        self.enterContext(patch("app.utils.facility_time.facility_now", return_value=datetime(2026, 11, 5, 12)))
        reset_schema()
        self.db = SessionLocal()
        self.user = seed_personnel(self.db)[1]

    def tearDown(self):
        self.db.close()

    @classmethod
    def tearDownClass(cls):
        engine.dispose()

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

    def refresh_workbook(self, director="Ezgi Nur AKIN", marker="-", approval="-"):
        from openpyxl import load_workbook

        w = load_workbook(io.BytesIO(workbook()))
        w.active.cell(8, 1).value = 4
        w.active.cell(8, 4).value = director
        flow = w.create_sheet("NUMUNE İŞ AKIŞI")
        flow.cell(5, 1, "Company")
        flow.cell(5, 2, "Intracutaneous Reactivity")
        for c in range(3, 18):
            flow.cell(5, c, "-")
        flow.cell(5, 4).value = marker
        flow.cell(5, 8).value = approval
        b = io.BytesIO()
        w.save(b)
        return b.getvalue()

    def test_sd_only_refresh_moves_assignees_and_detects_new_conflict(self):
        from app.models.conflict import Conflict, ConflictType

        self.load(self.refresh_workbook())
        study = self.db.query(Study).one()
        old_sd = study.study_director_id
        director = ss.match_study_director(self.db, "Ayşe Özgür", include_inactive=True)
        steps = self.db.query(StudyStep).filter_by(study_id=study.id).all()
        assigned = next(
            step for step in steps if old_sd in [u.id for u in step.assignees]
        )
        before = {
            step.id: (
                [u.id for u in step.assignees],
                step.planned_start,
                step.planned_end,
            )
            for step in steps
        }
        other = Study(
            study_code="SD-BUSY",
            title="Other study",
            test_item_name="Other",
            study_director_id=director.id,
            status=StudyStatus.APPROVED,
        )
        self.db.add(other)
        self.db.flush()
        busy = StudyStep(
            study_id=other.id,
            step_name="Director busy",
            planned_start=assigned.planned_start,
            planned_end=assigned.planned_end,
            status=StepStatus.PENDING,
        )
        busy.assignees = [director]
        self.db.add(busy)
        self.db.commit()
        content = self.refresh_workbook(director="Ayşe Özgür")
        result = self.load(content)
        self.assertEqual(result["auto_scheduled"], 0)
        self.assertEqual(study.study_director_id, director.id)
        for step in self.db.query(StudyStep).filter_by(study_id=study.id):
            old_ids, start, end = before[step.id]
            self.assertEqual(
                {u.id for u in step.assignees},
                {director.id if uid == old_sd else uid for uid in old_ids},
            )
            self.assertEqual((step.planned_start, step.planned_end), (start, end))
        conflicts = (
            self.db.query(Conflict)
            .filter_by(
                study_id=study.id,
                related_study_id=other.id,
                conflict_type=ConflictType.PERSONNEL_OVERLAP,
                is_resolved=False,
            )
            .all()
        )
        self.assertTrue(conflicts)
        self.assertTrue(any(director.full_name in c.description for c in conflicts))
        conflict_ids = [c.id for c in self.db.query(Conflict).all()]
        repeated = self.load(content)
        self.assertEqual((repeated["updated"], repeated["auto_scheduled"]), (0, 0))
        self.assertEqual(conflict_ids, [c.id for c in self.db.query(Conflict).all()])

    def test_sd_refresh_keeps_each_operational_protection(self):
        self.load(self.refresh_workbook())
        study = self.db.query(Study).one()
        sample = self.db.query(SampleRecord).one()
        step = self.db.query(StudyStep).first()
        before = {s.id: [u.id for u in s.assignees] for s in self.db.query(StudyStep)}
        old_sd = study.study_director_id
        for protection in ("approved", "started", "signed", "actual"):
            with self.subTest(protection=protection):
                study.status = StudyStatus.DRAFT
                sample.workflow = {
                    k: v for k, v in (sample.workflow or {}).items() if k != "6"
                }
                step.actual_start = None
                if protection == "approved":
                    study.status = StudyStatus.APPROVED
                if protection == "started":
                    study.status = StudyStatus.IN_PROGRESS
                if protection == "signed":
                    sample.workflow = dict(
                        sample.workflow,
                        **{
                            "6": {
                                "approvals": {
                                    "CY": {"by": "Real", "at": "2026-12-01T09:12:00"}
                                }
                            }
                        },
                    )
                if protection == "actual":
                    step.actual_start = datetime(2026, 12, 7, 9, 12)
                self.db.commit()
                self.load(self.refresh_workbook(director="Ayşe Özgür"))
                self.assertEqual(study.study_director_id, old_sd)
                self.assertEqual(
                    before,
                    {
                        s.id: [u.id for u in s.assignees]
                        for s in self.db.query(StudyStep)
                    },
                )

    def test_workflow_refresh_reaches_api_and_preserves_user_actions(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.seed import DEFAULT_PASSWORD

        self.load(self.refresh_workbook())
        sample = self.db.query(SampleRecord).one()
        client = TestClient(app)
        login = client.post(
            "/api/v1/auth/login",
            json={"username": self.user.username, "password": DEFAULT_PASSWORD},
        )
        self.assertEqual(login.status_code, 200)
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}

        def flow():
            response = client.get(f"/api/v1/samples/{sample.id}", headers=headers)
            self.assertEqual(response.status_code, 200)
            return {row["no"]: row for row in response.json()["workflow"]}

        self.assertFalse(flow()[2]["done"])
        content = self.refresh_workbook(marker="+", approval="+")
        self.load(content)
        updated = flow()
        self.assertTrue(updated[2]["done"])
        self.assertTrue(updated[6]["done"])
        for n in (2, 6):
            self.assertIsNone(updated[n]["done_by"])
            self.assertIsNone(updated[n]["done_at"])
        self.assertTrue(all(not a["signed"] for a in updated[6]["approvals"]))
        self.assertEqual(self.load(content)["updated"], 0)
        self.load(self.refresh_workbook())
        self.assertFalse(flow()[2]["done"])
        self.assertFalse(flow()[6]["done"])
        # Real API actions replace Excel ownership, including undo/revoke.
        for n, data in (
            (2, {"action": "complete"}),
            (6, {"action": "sign", "approver": "TBY"}),
        ):
            self.assertEqual(
                client.post(
                    f"/api/v1/samples/{sample.id}/workflow/{n}",
                    headers=headers,
                    json=data,
                ).status_code,
                200,
            )
        self.db.expire_all()
        real = {k: sample.workflow[k] for k in ("2", "6")}
        self.load(content)
        self.assertEqual(real, {k: sample.workflow[k] for k in ("2", "6")})
        for n, data in (
            (2, {"action": "undo"}),
            (6, {"action": "revoke", "approver": "TBY"}),
        ):
            self.assertEqual(
                client.post(
                    f"/api/v1/samples/{sample.id}/workflow/{n}",
                    headers=headers,
                    json=data,
                ).status_code,
                200,
            )
        self.load(self.refresh_workbook())
        result = self.load(content)
        self.assertFalse(flow()[2]["done"])
        self.assertFalse(flow()[6]["done"])
        self.assertEqual(sample.workflow["2"], {"done": False})
        self.assertEqual(sample.workflow["6"], {"approvals": {}})
        repeated = self.load(content)
        self.assertEqual((repeated["updated"], repeated["auto_scheduled"]), (0, 0))


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        engine.dispose()
        TMP.cleanup()
