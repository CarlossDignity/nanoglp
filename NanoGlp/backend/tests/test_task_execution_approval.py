"""Real HTTP calls and fresh-session snapshots against disposable SQLite only."""

import atexit
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

TMP = tempfile.TemporaryDirectory(prefix="nanoglp_execution_approval_")
os.environ["DATABASE_URL"] = f"sqlite:///{TMP.name}/test.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.database import Base, SessionLocal, engine

atexit.register(engine.dispose)
from app.main import app
from app.seed import DEFAULT_PASSWORD, reset_schema, seed_personnel
from app.models.study import Study, StudyStatus
from app.models.study_step import StudyStep, StepStatus
from app.models.conflict import Conflict, ConflictType
from app.models.user import User


def snapshot():
    with SessionLocal() as db:
        return {
            table.name: [
                dict(row)
                for row in db.execute(
                    table.select().order_by(*table.primary_key.columns)
                ).mappings()
            ]
            for table in Base.metadata.sorted_tables
        }


class TaskExecutionApproval(unittest.TestCase):
    def setUp(self):
        self.enterContext(
            patch(
                "app.api.v1.planning._facility_now",
                return_value=datetime(2026, 11, 5, 12),
            )
        )
        reset_schema()
        with SessionLocal() as db:
            people = {u.username: u for u in seed_personnel(db)}
            self.sd_id = people["ezgi"].id
            self.tech_id = people["invivo_1"].id
        self.client = TestClient(app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        self.headers = {}
        for username in ("emine", "invivo_1", "invivo_2", "qa_user"):
            response = self.client.post(
                "/api/v1/auth/login",
                json={"username": username, "password": DEFAULT_PASSWORD},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.headers[username] = {
                "Authorization": "Bearer " + response.json()["access_token"]
            }

    def fixture(self, study_status, existing=False):
        with SessionLocal() as db:
            study = Study(
                study_code="EXEC-1",
                title="Approval gate",
                test_item_name="Item",
                study_director_id=self.sd_id,
                status=study_status,
            )
            step = StudyStep(
                study=study,
                step_name="Observation",
                planned_start=datetime(2026, 11, 5, 9),
                planned_end=datetime(2026, 11, 5, 13),
                status=StepStatus.PENDING,
                deviation_notes="Existing note",
            )
            step.assignees = [db.get(User, self.tech_id)]
            if existing:
                step.status = StepStatus.COMPLETED
                step.actual_start = datetime(2026, 11, 4, 9)
                step.actual_reference_time = datetime(2026, 11, 4, 10)
                step.actual_end = datetime(2026, 11, 4, 11)
                step.completed_by_id = self.tech_id
            db.add(study)
            db.flush()
            db.add(
                Conflict(
                    study_id=study.id,
                    step_id=step.id,
                    conflict_type=ConflictType.PERSONNEL_OVERLAP,
                    title="Existing conflict",
                    description="Must survive rejection",
                )
            )
            db.commit()
            return step.id

    def request(self, step_id, body, user="invivo_1"):
        return self.client.patch(
            f"/api/v1/planning/steps/{step_id}/status",
            json=body,
            headers=self.headers[user],
        )

    def test_closed_studies_reject_every_payload_without_any_write(self):
        bodies = [
            {"status": "IN_PROGRESS"},
            {"status": "PENDING"},
            {"actual_reference_time": "2026-11-04T10:00:00"},
            {"biological_reference_time": "2026-11-04T10:00:00"},
            {"reference_time": "2026-11-04T10:00:00"},
            {
                "status": "COMPLETED",
                "actual_start": "2026-11-04T09:00:00",
                "actual_end": "2026-11-04T11:00:00",
                "notes": "late",
            },
            {
                "status": "COMPLETED",
                "preserve_missing_actuals": True,
                "actual_start_unknown": True,
                "actual_end_unknown": True,
            },
            {"deviation_notes": "overwrite"},
            {"notes": "overwrite"},
            {"actual_start": "invalid"},
        ]
        step_id = self.fixture(StudyStatus.DRAFT, existing=True)
        for study_status in (
            StudyStatus.DRAFT,
            StudyStatus.COMPLETED,
            StudyStatus.CANCELLED,
        ):
            with SessionLocal() as db:
                db.get(StudyStep, step_id).study.status = study_status
                db.commit()
            for body in bodies:
                with self.subTest(study_status=study_status, body=body):
                    before = snapshot()
                    response = self.request(step_id, body)
                    self.assertEqual(response.status_code, 409, response.text)
                    self.assertIn("onay", response.json()["detail"].lower())
                    self.assertEqual(snapshot(), before)

    def test_draft_pending_cannot_start_or_record_reference(self):
        step_id = self.fixture(StudyStatus.DRAFT)
        for body in (
            {"status": "IN_PROGRESS"},
            {"actual_reference_time": "2026-11-05T10:00:00"},
        ):
            with self.subTest(body=body):
                before = snapshot()
                response = self.request(step_id, body)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(snapshot(), before)

    def test_existing_role_and_assignment_permissions_remain(self):
        step_id = self.fixture(StudyStatus.APPROVED)
        for user in ("qa_user", "invivo_2"):
            before = snapshot()
            self.assertEqual(
                self.request(step_id, {"status": "IN_PROGRESS"}, user).status_code, 403
            )
            self.assertEqual(snapshot(), before)

    def test_allowed_studies_normal_start_complete_and_reference(self):
        step_id = self.fixture(StudyStatus.APPROVED)
        for study_status in (StudyStatus.APPROVED, StudyStatus.IN_PROGRESS):
            with self.subTest(study_status=study_status):
                with SessionLocal() as db:
                    step = db.get(StudyStep, step_id)
                    step.study.status = study_status
                    step.status = StepStatus.PENDING
                    step.actual_start = step.actual_end = step.actual_reference_time = (
                        None
                    )
                    db.commit()
                started = self.request(step_id, {"status": "IN_PROGRESS"})
                self.assertEqual(started.status_code, 200, started.text)
                self.assertEqual(started.json()["actual_start"], "2026-11-05T12:00:00")
                ref = self.request(
                    step_id, {"actual_reference_time": "2026-11-05T12:00:00"}
                )
                self.assertEqual(ref.status_code, 200, ref.text)
                complete = self.request(step_id, {"status": "COMPLETED"})
                self.assertEqual(complete.status_code, 200, complete.text)
                with SessionLocal() as db:
                    step = db.get(StudyStep, step_id)
                    self.assertEqual(step.study.status, study_status)
                    self.assertEqual(step.status, StepStatus.COMPLETED)
                    self.assertEqual(step.actual_end, datetime(2026, 11, 5, 12))
                    self.assertEqual(
                        step.actual_reference_time, datetime(2026, 11, 5, 12)
                    )

    def test_allowed_late_records_and_unknown_times_preserve_validation(self):
        step_id = self.fixture(StudyStatus.APPROVED)
        for study_status in (StudyStatus.APPROVED, StudyStatus.IN_PROGRESS):
            for unknown in (False, True):
                with self.subTest(study_status=study_status, unknown=unknown):
                    with SessionLocal() as db:
                        step = db.get(StudyStep, step_id)
                        step.study.status = study_status
                        step.status = StepStatus.PENDING
                        step.actual_start = step.actual_end = (
                            step.actual_reference_time
                        ) = None
                        db.commit()
                    before = snapshot()
                    bad = self.request(
                        step_id,
                        {
                            "status": "COMPLETED",
                            "actual_start": "2026-11-04T11:00:00",
                            "actual_end": "2026-11-04T09:00:00",
                        },
                    )
                    self.assertEqual(bad.status_code, 422)
                    self.assertEqual(snapshot(), before)
                    body = {
                        "status": "COMPLETED",
                        "actual_reference_time": "2026-11-04T10:00:00",
                        "deviation_notes": "Late entry",
                    }
                    if unknown:
                        body.update(
                            preserve_missing_actuals=True,
                            actual_start_unknown=True,
                            actual_end_unknown=True,
                        )
                    else:
                        body.update(
                            actual_start="2026-11-04T09:00:00",
                            actual_end="2026-11-04T11:00:00",
                        )
                    response = self.request(step_id, body)
                    self.assertEqual(response.status_code, 200, response.text)
                    with SessionLocal() as db:
                        step = db.get(StudyStep, step_id)
                        self.assertEqual(
                            step.actual_start,
                            None if unknown else datetime(2026, 11, 4, 9),
                        )
                        self.assertEqual(
                            step.actual_end,
                            None if unknown else datetime(2026, 11, 4, 11),
                        )
                        self.assertEqual(
                            step.actual_reference_time, datetime(2026, 11, 4, 10)
                        )
                        self.assertEqual(step.deviation_notes, "Late entry")
                        self.assertEqual(step.study.status, study_status)

    @classmethod
    def tearDownClass(cls):
        engine.dispose()


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        engine.dispose()
        TMP.cleanup()
