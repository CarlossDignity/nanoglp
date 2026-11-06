import atexit
import io, os, sys, tempfile, unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from docx import Document
from sqlalchemy import inspect, text, create_engine

TMP = tempfile.TemporaryDirectory(prefix="nanoglp_contact_")
os.environ["DATABASE_URL"] = f"sqlite:///{TMP.name}/test.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import SessionLocal, engine

atexit.register(engine.dispose)
from app.main import app, _ensure_sqlite_columns
from app.seed import reset_schema, seed_personnel, DEFAULT_PASSWORD
from app.models.study import Study
from app.models.study_step import StudyStep, StepStatus
from app.services.study_plan_docx import generate_study_plan_docx
from fastapi.testclient import TestClient


class PersonnelContactTests(unittest.TestCase):
    def setUp(self):
        reset_schema()
        self.db = SessionLocal()
        self.addCleanup(self.db.close)
        self.people = {u.username: u for u in seed_personnel(self.db)}
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.headers = {}
        for name in ("admin", "ezgi", "emine", "qa_user", "invivo_1"):
            r = self.client.post(
                "/api/v1/auth/login",
                json={"username": name, "password": DEFAULT_PASSWORD},
            )
            self.assertEqual(r.status_code, 200)
            self.headers[name] = {"Authorization": "Bearer " + r.json()["access_token"]}

    def test_partial_contact_validation_authorization_and_login(self):
        u = self.people["invivo_1"]
        previous = (u.hashed_password, u.role)
        url = f"/api/v1/personnel/{u.id}/contact"
        r = self.client.patch(
            url,
            json={"email": "person@example.com", "phone": "+90 555 123 45 67"},
            headers=self.headers["ezgi"],
        )
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.patch(url, json={"phone": None}, headers=self.headers["ezgi"])
        self.assertEqual(r.json()["email"], "person@example.com")
        self.assertIsNone(r.json()["phone"])
        for body in (
            {"role": "SYSADMIN"},
            {"password": "secret"},
            {"email": "bad"},
            {"phone": "x" * 61},
        ):
            self.assertEqual(
                self.client.patch(
                    url, json=body, headers=self.headers["ezgi"]
                ).status_code,
                422,
            )
        self.people["ezgi"].email = "duplicate@example.com"
        self.db.commit()
        self.assertEqual(
            self.client.patch(
                url,
                json={"email": "DUPLICATE@example.com"},
                headers=self.headers["emine"],
            ).status_code,
            400,
        )
        for name in ("qa_user", "invivo_1"):
            self.assertEqual(
                self.client.patch(
                    url, json={"phone": "123"}, headers=self.headers[name]
                ).status_code,
                403,
            )
        for endpoint in (
            "/api/v1/personnel",
            "/api/v1/planning/workload",
            "/api/v1/planning/workload-weekly",
        ):
            r = self.client.get(endpoint, headers=self.headers["emine"])
            self.assertEqual(r.status_code, 200)
            rows = r.json() if isinstance(r.json(), list) else r.json()["personnel"]
            row = next(p for p in rows if p.get("id", p.get("personnel_id")) == u.id)
            self.assertIn("phone", row)
            self.assertEqual(row["email"], "person@example.com")
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/login",
                json={"email": "person@example.com", "password": DEFAULT_PASSWORD},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.patch(
                url, json={"email": ""}, headers=self.headers["ezgi"]
            ).status_code,
            200,
        )
        self.db.refresh(u)
        self.assertIsNone(u.email)
        self.assertEqual((u.hashed_password, u.role), previous)

    def test_users_api_contact_partial_and_clear(self):
        u = self.people["invivo_1"]
        url = f"/api/v1/users/{u.id}"
        before = (u.role, u.hashed_password, u.full_name)
        r = self.client.put(
            url,
            json={"email": "user@example.com", "phone": "123"},
            headers=self.headers["admin"],
        )
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.put(url, json={"phone": ""}, headers=self.headers["admin"])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(r.json()["phone"])
        self.assertEqual(r.json()["email"], "user@example.com")
        r = self.client.put(url, json={"email": None}, headers=self.headers["admin"])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(r.json()["email"])
        self.db.refresh(u)
        self.assertEqual((u.role, u.hashed_password, u.full_name), before)

    def test_docx_contacts_dedup_tbd_and_unchanged_objective(self):
        sd, tech = self.people["ezgi"], self.people["invivo_1"]
        study = Study(
            study_code="CONTACT-1",
            title="Contact",
            test_item_name="LOT-XX123",
            study_director_id=sd.id,
        )
        self.db.add(study)
        self.db.flush()
        for i in range(3):
            step = StudyStep(
                study_id=study.id,
                step_name="Test",
                step_order=i + 1,
                planned_start=datetime(2026, 11, 5, 9),
                planned_end=datetime(2026, 11, 5, 10),
                status=StepStatus.CANCELLED if i == 2 else StepStatus.PENDING,
            )
            step.assignees = [self.people["invivo_2"]] if i == 2 else [sd, tech]
            self.db.add(step)
        self.db.commit()
        before = Document(io.BytesIO(generate_study_plan_docx(self.db, study)))
        sd.phone = "SD-XX"
        sd.email = "director@example.com"
        tech.phone = "TECH-XX"
        tech.email = "technician@example.com"
        self.people["invivo_2"].phone = "CANCELLED-PHONE"
        self.db.commit()
        after = Document(io.BytesIO(generate_study_plan_docx(self.db, study)))
        table = next(
            t for t in after.tables if t.cell(0, 0).text.strip() == "Personnel"
        )
        content = "\n".join(c.text for r in table.rows for c in r.cells)
        for value in (
            "SD-XX",
            "director@example.com",
            "TECH-XX",
            "technician@example.com",
        ):
            self.assertIn(value, content)
        self.assertEqual(content.count("TECH-XX"), 1)
        self.assertNotIn("CANCELLED-PHONE", content)
        self.assertEqual(
            [p.text for p in before.paragraphs], [p.text for p in after.paragraphs]
        )
        for value in ("polar (0.9% NaCl)", "non-polar (Cottonseed oil)"):
            self.assertIn(value, "\n".join(p.text for p in after.paragraphs))
        sd.phone = tech.phone = None
        self.db.commit()
        missing = Document(io.BytesIO(generate_study_plan_docx(self.db, study)))
        table = next(
            t for t in missing.tables if t.cell(0, 0).text.strip() == "Personnel"
        )
        self.assertIn("Telephone: TBD", table.rows[1].cells[1].text)

    def test_old_schema_addition_repeatable(self):
        old = create_engine(f"sqlite:///{TMP.name}/old.db")
        with old.begin() as c:
            c.execute(
                text(
                    "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, email TEXT, full_name TEXT)"
                )
            )
            c.execute(
                text(
                    "INSERT INTO users VALUES (1,'legacy','old@example.com','Legacy User')"
                )
            )
        with patch("app.main.engine", old), patch(
            "app.main.seed_default_equipment"
        ), patch("app.main.ensure_default_calibrations"), patch(
            "app.main.ensure_default_role_permissions"
        ), patch(
            "app.main.seed_sample_tracking"
        ), patch(
            "app.main._migrate_faz84_yigit_and_cleanups"
        ):
            _ensure_sqlite_columns()
            _ensure_sqlite_columns()
        self.assertIn("phone", [c["name"] for c in inspect(old).get_columns("users")])
        with old.connect() as c:
            self.assertEqual(
                c.execute(
                    text("SELECT username,email,full_name,phone FROM users")
                ).one(),
                ("legacy", "old@example.com", "Legacy User", None),
            )
        old.dispose()


if __name__ == "__main__":
    unittest.main()
