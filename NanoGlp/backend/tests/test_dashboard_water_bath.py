"""Calendar reservation transport for the dashboard; disposable SQLite only."""

import atexit
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

TMP = tempfile.TemporaryDirectory(prefix="nanoglp_dashboard_wb_")
os.environ["DATABASE_URL"] = f"sqlite:///{TMP.name}/test.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.database import Base, SessionLocal, engine

atexit.register(engine.dispose)
from app.main import app
from app.seed import (
    reset_schema,
    seed_personnel,
    seed_default_equipment,
    DEFAULT_PASSWORD,
)
from app.models.study import Study, StudyStatus
from app.models.study_step import StudyStep, StepStatus
from app.models.conflict import ConflictType
from app.services.scheduling_engine import (
    get_study_extraction_usage,
    evaluate_study_conflicts,
)

START = datetime(2029, 1, 1, 8)


class DashboardWaterBath(unittest.TestCase):
    def setUp(self):
        reset_schema()
        self.db = SessionLocal()
        self.people = {u.username: u for u in seed_personnel(self.db)}
        self.eq = seed_default_equipment(self.db)
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

    def study(
        self,
        status=StudyStatus.IN_PROGRESS,
        step_status=StepStatus.PENDING,
        start=START,
        polar=True,
        apolar=True,
        historical=False,
        extraction=True,
    ):
        self.serial += 1
        study = Study(
            study_code=f"WB-{self.serial}",
            title="Water bath",
            test_item_name="Item",
            study_director_id=self.people["ezgi"].id,
            status=status,
            template_code="ISO_10993_23_IC",
            extraction_polar=polar,
            extraction_non_polar=apolar,
            acclimatization_start_date=(start - timedelta(days=4)).date(),
            dossier_metadata={"historical_excel_import": True} if historical else {},
        )
        self.db.add(study)
        self.db.flush()
        step = StudyStep(
            study_id=study.id,
            step_name="Kurulum",
            step_type="Ekstraksiyon" if extraction else "Other",
            planned_start=start,
            planned_end=start + timedelta(minutes=90),
            status=step_status,
            equipment_id=self.eq.id,
        )
        self.db.add(step)
        self.db.commit()
        return study, step

    def calendar(self):
        response = self.client.get("/api/v1/planning/calendar", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return {s["study_id"]: s for s in response.json()["studies"]}

    def snapshot(self):
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

    def test_completed_setup_retains_72h_and_calendar_is_read_only(self):
        study, step = self.study()
        before = self.snapshot()
        original = self.calendar()[study.id]["water_bath_reservations"]
        self.assertEqual(before, self.snapshot())
        self.assertEqual(len(original), 1)
        reservation = original[0]
        self.assertEqual(reservation["equipment_code"], "EQ-WB-001")
        self.assertEqual(reservation["window_start"], START.isoformat())
        self.assertEqual(
            reservation["window_end"], (START + timedelta(hours=72)).isoformat()
        )
        step.status = StepStatus.COMPLETED
        self.db.commit()
        before = self.snapshot()
        self.assertEqual(original, self.calendar()[study.id]["water_bath_reservations"])
        self.assertEqual(before, self.snapshot())

    def test_usage_and_recorded_capacity_match_backend(self):
        self.eq.polar_capacity = 7
        self.eq.non_polar_capacity = 2
        self.db.commit()
        studies = [
            self.study(polar=polar, apolar=apolar)[0]
            for polar in (True, False, None)
            for apolar in (True, False, None)
        ]
        data = self.calendar()
        for study in studies:
            usage = get_study_extraction_usage(study)
            windows = data[study.id]["water_bath_reservations"]
            self.assertEqual(len(windows), int(usage["uses_water_bath"]))
            if windows:
                self.assertEqual(windows[0]["uses_polar"], usage["uses_polar"])
                self.assertEqual(windows[0]["uses_apolar"], usage["uses_apolar"])
        response = self.client.get("/api/v1/equipment", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        eq = next(e for e in response.json() if e["code"] == "EQ-WB-001")
        self.assertEqual((eq["polar_capacity"], eq["non_polar_capacity"]), (7, 2))

    def test_cancelled_completed_and_historical_scope_matches_engine(self):
        cancelled, _ = self.study(status=StudyStatus.CANCELLED)
        finished, _ = self.study(status=StudyStatus.COMPLETED)
        cancelled_step, _ = self.study(step_status=StepStatus.CANCELLED)
        old_unknown, _ = self.study(start=datetime(2026, 11, 2, 8), historical=True)
        old_regular, _ = self.study(start=datetime(2026, 11, 2, 8))
        boundary, _ = self.study(start=datetime(2026, 11, 3, 8), historical=True)
        historical_done, _ = self.study(
            start=datetime(2026, 11, 2, 8),
            historical=True,
            step_status=StepStatus.COMPLETED,
        )
        non_extraction, _ = self.study(extraction=False)
        data = self.calendar()
        self.assertNotIn(cancelled.id, data)
        for study in (finished, cancelled_step, old_unknown, non_extraction):
            self.assertEqual(data[study.id]["water_bath_reservations"], [])
        for study in (old_regular, boundary, historical_done):
            self.assertEqual(len(data[study.id]["water_bath_reservations"]), 1)

    def test_half_open_boundary_and_overload_agree_with_engine(self):
        first, setup = self.study(step_status=StepStatus.COMPLETED)
        target, target_step = self.study(start=START + timedelta(hours=72))

        def equipment_conflicts():
            return [
                c
                for c, _ in evaluate_study_conflicts(
                    self.db,
                    target,
                    [target_step],
                    [setup],
                    {setup.id: set()},
                    self.eq,
                    persist_conflicts=False,
                )
                if c.conflict_type == ConflictType.EQUIPMENT_OVERLAP
            ]

        self.assertEqual(equipment_conflicts(), [])
        data = self.calendar()
        self.assertEqual(
            data[first.id]["water_bath_reservations"][0]["window_end"],
            data[target.id]["water_bath_reservations"][0]["window_start"],
        )
        target_step.planned_start -= timedelta(hours=1)
        target_step.planned_end -= timedelta(hours=1)
        self.db.commit()
        self.assertTrue(any("Apolar" in c.title for c in equipment_conflicts()))
        self.assertEqual(
            self.calendar()[target.id]["water_bath_reservations"][0]["window_start"],
            target_step.planned_start.isoformat(),
        )


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        engine.dispose()
        TMP.cleanup()
