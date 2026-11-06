"""Freeze only the facility clock; use real APIs and disposable SQLite."""

import atexit
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

TMP = tempfile.TemporaryDirectory(prefix="nanoglp_facility_date_")
os.environ["DATABASE_URL"] = f"sqlite:///{TMP.name}/test.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.database import Base, SessionLocal, engine

atexit.register(engine.dispose)
from app.main import app
from app.seed import reset_schema, seed_personnel, DEFAULT_PASSWORD
from app.models.sample import SampleRecord
from app.models.study import Study, StudyStatus
from app.models.study_step import StudyStep, StepStatus
from app.services import sample_service as ss
from app.services.scheduling_engine import is_historical_unverified_step, REFERENCE_DATE
from app.utils.facility_time import facility_today


def freeze(utc_iso):
    instant = datetime.fromisoformat(utc_iso).replace(tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    return patch("app.utils.facility_time.datetime", Clock)


def snapshot():
    with SessionLocal() as db:
        return {
            t.name: [
                dict(r)
                for r in db.execute(
                    t.select().order_by(*t.primary_key.columns)
                ).mappings()
            ]
            for t in Base.metadata.sorted_tables
        }


class LiveFacilityDate(unittest.TestCase):
    def setUp(self):
        reset_schema()
        self.db = SessionLocal()
        self.people = {u.username: u for u in seed_personnel(self.db)}
        self.client = TestClient(app, raise_server_exceptions=False)
        login = self.client.post(
            "/api/v1/auth/login",
            data={"username": "emine", "password": DEFAULT_PASSWORD},
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        self.serial = 0

    def tearDown(self):
        self.client.close()
        self.db.close()

    @classmethod
    def tearDownClass(cls):
        engine.dispose()

    def sample(self, due=None, status="ONGOING", **fields):
        self.serial += 1
        sample = SampleRecord(
            study_code=f"LIVE-{self.serial}",
            stored_status=status,
            raw_status_text=status,
            experiment_end_date=due,
            draft_report_date=due,
            final_report_date=due,
            workflow={
                "_contract": {"commitment_date": due.isoformat() if due else None}
            },
        )
        for key, value in fields.items():
            setattr(sample, key, value)
        self.db.add(sample)
        self.db.commit()
        return sample

    def request(self, path):
        response = self.client.get(path, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_utc_midnight_boundary_past_today_future_and_summary(self):
        rows = [self.sample(date(2026, 11, day)) for day in (4, 5, 6)]
        before = snapshot()
        with freeze("2026-11-04T22:30:00"):
            self.assertEqual(facility_today(), date(2026, 11, 5))
            samples = self.request("/api/v1/samples")
            by_code = {r["study_code"]: r for r in samples["items"]}
            for sample, overdue in zip(rows, (True, False, False)):
                row = by_code[sample.study_code]
                self.assertEqual(row["is_draft_report_overdue"], overdue)
                self.assertEqual(row["is_contract_deadline_exceeded"], overdue)
                self.assertEqual(
                    row["ongoing_phase"],
                    "IN_REPORTING_QA" if overdue else "IN_EXPERIMENT",
                )
                detail = self.request(f"/api/v1/samples/{sample.id}")
                self.assertEqual(
                    next(s for s in detail["workflow"] if s["no"] == 9)["overdue"], overdue
                )
            summary = self.request("/api/v1/planning/summary")
            self.assertEqual(summary["date"], "2026-11-05")
            for key, expected in (
                ("ongoing_in_reporting", 1),
                ("ongoing_in_experiment", 2),
                ("ongoing_overdue_draft", 1),
            ):
                self.assertEqual(summary[key], expected)
                self.assertEqual(summary[key], samples["summary"][key])
        self.assertEqual(before, snapshot())

    def test_sample_list_uses_one_day_even_if_clock_rolls_during_serialization(self):
        self.sample(date(2026, 11, 5))
        self.sample(date(2026, 11, 5))
        with patch("app.utils.facility_time.facility_now", side_effect=[
            datetime(2026, 11, 5, 23, 59), datetime(2026, 11, 6, 0, 1)
        ]) as clock:
            rows = self.request("/api/v1/samples")["items"]
            self.assertTrue(all(not row["is_draft_report_overdue"] for row in rows))
            self.assertEqual(clock.call_count, 1)

    def test_sequential_requests_cross_midnight_without_restart_or_writes(self):
        sample = self.sample(date(2026, 11, 4))
        before = snapshot()
        for instant, expected_day, overdue in (
            ("2026-11-04T20:59:00", "2026-11-04", False),
            ("2026-11-04T21:01:00", "2026-11-05", True),
        ):
            with freeze(instant):
                row = self.request(f"/api/v1/samples/{sample.id}")
                summary = self.request("/api/v1/planning/summary")
                self.assertEqual(row["is_draft_report_overdue"], overdue)
                self.assertEqual(row["is_contract_deadline_exceeded"], overdue)
                self.assertEqual(summary["date"], expected_day)
                self.assertEqual(summary["ongoing_overdue_draft"], int(overdue))
        self.assertEqual(before, snapshot())

    def test_missing_dates_completed_cancelled_and_future_plan_commitment(self):
        missing = self.sample()
        completed = self.sample(date(2026, 11, 4), status="COMPLETED")
        cancelled = self.sample(date(2026, 11, 4), status="CANCELLED")
        future_draft = self.sample(
            date(2026, 11, 6),
            draft_report_date=date(2026, 11, 7),
            final_report_date=date(2026, 11, 7),
        )
        future_final = self.sample(
            date(2026, 11, 6), final_report_date=date(2026, 11, 8)
        )
        with freeze("2026-11-04T22:30:00"):
            for sample in (missing, completed, cancelled):
                row = self.request(f"/api/v1/samples/{sample.id}")
                self.assertFalse(row["is_draft_report_overdue"])
                self.assertFalse(row["is_contract_deadline_exceeded"])
                self.assertFalse(row["is_overdue"])
            for sample in (future_draft, future_final):
                row = self.request(f"/api/v1/samples/{sample.id}")
                self.assertTrue(row["is_contract_deadline_exceeded"])
                self.assertFalse(row["is_draft_report_overdue"])
            summary = self.request("/api/v1/planning/summary")
            self.assertEqual(summary["ongoing_studies"], 3)
            self.assertEqual(summary["ongoing_overdue_draft"], 0)

    def test_arrival_and_computed_status_use_the_same_facility_day(self):
        arrival = [
            self.sample(status="EXPECTED", expected_arrival_date=date(2026, 11, day))
            for day in (4, 5, 6)
        ]
        started = self.sample(
            status="PLANNED", raw_status_text=None, planned_start=date(2026, 11, 5)
        )
        before = snapshot()
        with freeze("2026-11-04T22:30:00"):
            for sample, overdue in zip(arrival, (True, False, False)):
                row = self.request(f"/api/v1/samples/{sample.id}")
                self.assertEqual(row["is_overdue"], overdue)
            self.assertEqual(
                self.request(f"/api/v1/samples/{started.id}")["status"], "ONGOING"
            )
        self.assertEqual(before, snapshot())

    def test_historical_cutoff_and_operational_records_stay_fixed_as_time_advances(
        self,
    ):
        study = Study(
            study_code="HISTORY",
            title="History",
            test_item_name="Item",
            study_director_id=self.people["ezgi"].id,
            status=StudyStatus.IN_PROGRESS,
            dossier_metadata={
                "historical_excel_import": True,
                "biological_revisions": [{"id": "retain"}],
            },
            protocol_approved_at=datetime(2026, 11, 1, 8),
        )
        self.db.add(study)
        self.db.flush()
        steps = []
        for day, status in (
            (2, StepStatus.PENDING),
            (4, StepStatus.PENDING),
            (5, StepStatus.PENDING),
            (6, StepStatus.COMPLETED),
        ):
            step = StudyStep(
                study_id=study.id,
                step_name=f"Day {day}",
                status=status,
                planned_start=datetime(2026, 11, day, 0, 15),
                planned_end=datetime(2026, 11, day, 1),
            )
            step.assignees = [self.people["ezgi"]]
            if status == StepStatus.COMPLETED:
                step.actual_start = datetime(2026, 11, day, 0, 17)
                step.actual_end = datetime(2026, 11, day, 0, 58)
                step.actual_reference_time = datetime(2026, 11, day, 0, 30)
            self.db.add(step)
            steps.append(step)
        self.db.commit()
        before = snapshot()
        for instant, tasks_today in (
            ("2026-11-04T22:30:00", 1),
            ("2027-02-01T22:30:00", 0),
        ):
            with freeze(instant):
                summary = self.request("/api/v1/planning/summary")
                self.assertEqual(summary["todays_tasks"], tasks_today)
                self.assertEqual(summary["historical_excluded_tasks"], 1)
                self.assertEqual(summary["active_pending_tasks"], 2)
                self.assertEqual(summary["completed_tasks"], 1)
                self.assertTrue(is_historical_unverified_step(steps[0], study))
                self.assertFalse(is_historical_unverified_step(steps[1], study))
                visible = self.request("/api/v1/planning/steps?active_only=true")
                self.assertEqual({r["id"] for r in visible}, {steps[1].id, steps[2].id})
        self.assertEqual(REFERENCE_DATE, date(2026, 11, 3))
        self.assertEqual(before, snapshot())


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        engine.dispose()
        TMP.cleanup()
