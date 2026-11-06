import atexit
import io, os, sys, tempfile, unittest, zipfile
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from lxml import etree
from openpyxl import Workbook

TMP = tempfile.TemporaryDirectory(prefix="nanoglp_animal_")
os.environ["DATABASE_URL"] = f"sqlite:///{TMP.name}/test.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.database import SessionLocal, engine

atexit.register(engine.dispose)
from app.main import app
from app.seed import reset_schema, seed_personnel, DEFAULT_PASSWORD
from app.models.sample import SampleRecord
from app.models.study import Study
from app.models.study_step import StudyStep
from app.services import sample_service as ss
from app.services.study_plan_docx import generate_study_plan_docx


def doc_parts(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return {
            n: (
                etree.tostring(etree.fromstring(z.read(n)), method="c14n")
                if n.endswith(".xml")
                else z.read(n)
            )
            for n in z.namelist()
            if n.startswith("word/")
        }


class AnimalOrderTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(
            patch(
                "app.utils.facility_time.facility_now",
                return_value=datetime(2026, 11, 6, 12),
            )
        )
        reset_schema()
        self.db = SessionLocal()
        self.addCleanup(self.db.close)
        self.people = {u.username: u for u in seed_personnel(self.db)}
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.h = {}
        for name in ("ezgi", "emine", "qa_user"):
            r = self.client.post(
                "/api/v1/auth/login",
                json={"username": name, "password": DEFAULT_PASSWORD},
            )
            self.h[name] = {"Authorization": "Bearer " + r.json()["access_token"]}
        self.sample = SampleRecord(
            study_code="GLP2026-901",
            workflow={},
            planned_start=date(2026, 12, 1),
            animal_consumable_status="Karantina",
        )
        self.study = Study(
            study_code=self.sample.study_code,
            title="Animal",
            test_item_name="Item",
            acclimatization_start_date=date(2026, 12, 7),
            target_end_date=date(2026, 12, 20),
            study_director_id=self.people["ezgi"].id,
        )
        self.db.add_all([self.sample, self.study])
        self.db.flush()
        self.db.add(
            StudyStep(
                study_id=self.study.id,
                step_name="Fixed",
                planned_start=datetime(2026, 12, 7, 9),
                planned_end=datetime(2026, 12, 7, 10),
            )
        )
        self.db.commit()

    def call(self, body, user="ezgi", code=200):
        r = self.client.post(
            f"/api/v1/samples/{self.sample.id}/workflow/3",
            headers=self.h[user],
            json=body,
        )
        self.assertEqual(r.status_code, code, r.text)
        self.db.expire_all()
        return r

    def state(self):
        with SessionLocal() as db:
            return db.get(SampleRecord, self.sample.id).workflow["3"]

    def test_two_users_idempotency_undo_and_no_plan_or_docx_change(self):
        before = doc_parts(generate_study_plan_docx(self.db, self.study))
        self.call({"action": "order"})
        state = self.state()
        self.assertEqual(state["order_date"], "2026-11-06")
        self.assertEqual(state["expected_delivery_date"], "2026-11-21")
        self.assertFalse(state["done"])
        self.call({"action": "order"}, user="emine")
        self.assertEqual(self.state(), state)
        self.call({"action": "order", "estimated_delivery_days": 2}, code=409)
        self.call({"action": "complete"}, code=409)
        r = self.call(
            {"action": "receive", "received_date": "2026-11-06"}, user="emine"
        )
        state = self.state()
        self.assertEqual(state["ordered_by_id"], self.people["ezgi"].id)
        self.assertEqual(state["received_by_id"], self.people["emine"].id)
        row = next(s for s in r.json()["workflow"] if s["no"] == 3)
        self.assertTrue(row["done"])
        self.assertEqual(len(r.json()["workflow"]), 11)
        self.call({"action": "receive", "received_date": "2026-11-06"})
        self.assertEqual(self.state(), state)
        after = doc_parts(generate_study_plan_docx(self.db, self.study))
        self.assertEqual(before, after)
        self.assertEqual(self.sample.planned_start, date(2026, 12, 1))
        self.assertEqual(self.sample.animal_consumable_status, "Karantina")
        self.call({"action": "undo"})
        state = self.state()
        self.assertFalse(state["done"])
        self.assertNotIn("received_date", state)
        self.assertIn("order_date", state)
        self.call({"action": "undo"})
        self.assertNotIn("order_date", self.state())
        self.assertEqual(len(self.state()["history"]), 2)
        self.assertEqual(self.sample.planned_start, date(2026, 12, 1))
        self.assertIsNone(self.sample.planned_end)
        self.assertEqual(self.study.acclimatization_start_date, date(2026, 12, 7))

    def test_validation_permissions_and_legacy_compatibility(self):
        self.call({"action": "receive", "received_date": "2026-11-06"}, code=409)
        self.call({"action": "complete"}, code=409)
        self.call({"action": "order", "estimated_delivery_days": -1}, code=422)
        self.call({"action": "order", "order_date": "2026-11-07"}, code=422)
        self.call({"action": "order"}, user="qa_user", code=403)
        self.call({"action": "order", "order_date": "2026-11-05"})
        for d in ("2026-11-04", "2026-11-07", "invalid"):
            self.call({"action": "receive", "received_date": d}, code=422)
        legacy = {"source": "excel", "marker": "+", "done": True}
        self.sample.workflow = {"3": legacy}
        self.db.commit()
        self.call({"action": "complete"})
        self.assertEqual(self.state(), legacy)
        data = ss.serialize_sample(
            self.db,
            self.sample,
            ss.sample_permissions(self.people["ezgi"]),
            sync_schedule_dates=False,
        )
        row = next(s for s in data["workflow"] if s["no"] == 3)
        self.assertTrue(row["done"])
        self.assertIsNone(row["animal_order"])

    def test_excel_refresh_preserves_order_and_receipt(self):
        self.call({"action": "order"})
        self.call({"action": "receive", "received_date": "2026-11-06"}, user="emine")
        before = self.state()
        w = Workbook()
        s = w.active
        s.title = "GLP Medikal"
        s.cell(8, 8, self.sample.study_code)
        s.cell(8, 3, "Item")
        s.cell(8, 25, "Planlanan")
        s.cell(8, 1, 4)
        s.cell(8, 5, "Company")
        s.cell(8, 2, "Intracutaneous")
        wf = w.create_sheet("NUMUNE İŞ AKIŞI")
        wf.cell(5, 1, "Company")
        wf.cell(5, 2, "Intracutaneous")
        wf.cell(5, 5, "-")
        # Import twice, including explicit workflow source markers using the same refresh implementation.
        b = io.BytesIO()
        w.save(b)
        for _ in range(2):
            ss.import_study_status_workbook(
                self.db, b.getvalue(), self.people["emine"], auto_schedule=False
            )
            self.db.commit()
            self.db.expire_all()
            self.assertEqual(self.state(), before)
            self.assertEqual(
                self.sample.workflow["_excel_source"]["workflow_markers"]["3"][
                    "marker"
                ],
                "-",
            )


if __name__ == "__main__":
    unittest.main()
