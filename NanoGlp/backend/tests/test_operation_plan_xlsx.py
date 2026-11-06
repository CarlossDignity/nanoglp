"""Real XLSX HTTP downloads; no live database or planning mutations."""

import io
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

TMP = tempfile.TemporaryDirectory(prefix="nanoglp_operation_xlsx_")
os.environ["DATABASE_URL"] = f"sqlite:///{TMP.name}/test.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from app.database import Base, SessionLocal, engine
from app.main import app
from app.seed import reset_schema, seed_personnel, DEFAULT_PASSWORD
from app.models.study import Study, StudyStatus
from app.models.study_step import StudyStep, StepStatus
from app.models.conflict import Conflict, ConflictType
from app.models.user import User, UserRole
from app.services.scheduling_engine import calculate_personnel_workload, REFERENCE_DATE


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


class OperationPlanXlsx(unittest.TestCase):
    def setUp(self):
        reset_schema()
        self.db = SessionLocal()
        self.addCleanup(self.db.close)
        self.people = {u.username: u for u in seed_personnel(self.db)}
        self.client = TestClient(app, raise_server_exceptions=False)
        self.addCleanup(self.client.close)
        self.headers = {}
        for name in ("emine", "qa_user", "invivo_1"):
            r = self.client.post(
                "/api/v1/auth/login",
                json={"username": name, "password": DEFAULT_PASSWORD},
            )
            self.assertEqual(r.status_code, 200, r.text)
            self.headers[name] = {"Authorization": "Bearer " + r.json()["access_token"]}
        self.serial = 0

    def step(
        self,
        start="2026-11-05T09:00:00",
        end="2026-11-05T10:30:00",
        status=StudyStatus.DRAFT,
        assignees=(),
        step_status=StepStatus.PENDING,
        name="Görev",
        code=None,
        **actuals,
    ):
        self.serial += 1
        study = Study(
            study_code=code or f"XLS-{self.serial}",
            title="Export fixture",
            test_item_name="Item",
            study_director_id=self.people["ezgi"].id,
            status=status,
            extraction_polar=True,
            extraction_non_polar=True,
        )
        step = StudyStep(
            study=study,
            step_name=name,
            step_type="Ekstraksiyon",
            study_day=4,
            planned_start=datetime.fromisoformat(start),
            planned_end=datetime.fromisoformat(end),
            status=step_status,
            deviation_notes="Existing operational note",
            **actuals,
        )
        step.assignees = [self.people[u] for u in assignees]
        self.db.add(study)
        self.db.commit()
        return step

    def download(self, target="2026-11-05", view="daily", code=None, user="emine"):
        params = {"target_date": target, "view": view}
        if code is not None:
            params["study_code"] = code
        before = snapshot()
        r = self.client.get(
            "/api/v1/planning/export-excel", params=params, headers=self.headers[user]
        )
        self.assertEqual(
            r.status_code, 200, r.text[:300] if r.status_code != 200 else ""
        )
        self.assertEqual(
            snapshot(), before, "Every table must remain identical in a new Session"
        )
        self.assertIn("spreadsheetml.sheet", r.headers["content-type"])
        self.assertTrue(r.content.startswith(b"PK"))
        wb = load_workbook(io.BytesIO(r.content))
        self.addCleanup(wb.close)
        ws = wb["Operasyon Planı"]
        rows = list(ws.iter_rows(min_row=9, values_only=True))
        return ws, rows, r

    def test_daily_filter_status_people_and_plan_times(self):
        draft = self.step(name="Atanmamış görev")
        approved = self.step(
            status=StudyStatus.APPROVED,
            assignees=("ezgi", "invivo_1"),
            step_status=StepStatus.COMPLETED,
            name="Kurulum",
            actual_start=datetime(2026, 11, 4, 7),
            actual_end=datetime(2026, 11, 4, 8),
            actual_reference_time=datetime(2026, 11, 4, 7, 30),
        )
        self.step(status=StudyStatus.CANCELLED)
        self.step(step_status=StepStatus.CANCELLED)
        ws, rows, _ = self.download()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][9], "Atanmamış")
        self.assertEqual(rows[0][10], "TASLAK (DRAFT)")
        self.assertEqual(rows[1][10], "Onaylı (APPROVED)")
        self.assertEqual(rows[1][11], "Tamamlandı (COMPLETED)")
        self.assertEqual(rows[1][3], 4)
        self.assertEqual(
            rows[1][4:9],
            (
                datetime(2026, 11, 5, 9),
                datetime(2026, 11, 5, 10, 30),
                datetime(2026, 11, 5, 9),
                datetime(2026, 11, 5, 10, 30),
                90,
            ),
        )
        for person in approved.assignees:
            self.assertIn(person.full_name, rows[1][9])
        self.assertIn("gerçekleşmeler dahil değildir", ws["A4"].value)
        self.assertIn("cihaz rezervasyonu eklenmez", ws["A6"].value)
        self.assertEqual(ws.freeze_panes, "E9")
        self.assertEqual(ws["E9"].number_format, "dd.mm.yyyy hh:mm")
        ws, filtered, _ = self.download(code=approved.study.study_code)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0][1], approved.study.study_code)
        self.assertIn(approved.study.study_code, ws["A3"].value)
        self.assertNotEqual(filtered[0][1], draft.study.study_code)

    def test_week_normalizes_to_monday_clips_and_splits_half_open_intervals(self):
        self.step("2026-11-01T23:00:00", "2026-11-02T01:00:00", name="Previous week")
        self.step("2026-11-03T23:00:00", "2026-11-04T02:00:00", name="Overnight")
        self.step("2026-11-08T23:00:00", "2026-11-09T01:00:00", name="Next week")
        self.step("2026-11-01T22:00:00", "2026-11-02T00:00:00", name="Ends at boundary")
        self.step(
            "2026-11-09T00:00:00", "2026-11-09T02:00:00", name="Starts at boundary"
        )
        ws, rows, r = self.download("2026-11-08", "weekly")
        self.assertIn("2026-11-02 – 2026-11-08", ws["A2"].value)
        self.assertIn("weekly-2026-11-02.xlsx", r.headers["content-disposition"])
        self.assertEqual(
            [x[2] for x in rows],
            ["Previous week", "Overnight", "Overnight", "Next week"],
        )
        self.assertEqual([x[8] for x in rows], [60, 60, 120, 60])
        self.assertEqual(rows[0][6], datetime(2026, 11, 2))
        self.assertEqual(rows[-1][7], datetime(2026, 11, 9))
        self.assertEqual(
            rows[-1][5], datetime(2026, 11, 9, 1)
        )  # original plan retained
        daily_rows = []
        for n in range(7):
            _, day_rows, _ = self.download(
                (date(2026, 11, 2) + timedelta(days=n)).isoformat()
            )
            daily_rows.extend(row for row in day_rows if isinstance(row[0], datetime))
        self.assertEqual(daily_rows, rows)

    def test_setup_duration_is_not_72_hour_reservation_and_matches_read_only_workload(
        self,
    ):
        s = self.step(assignees=("invivo_1", "invivo_2"))
        _, rows, _ = self.download()
        self.assertEqual(len(rows), 1, "Multiple assignees do not duplicate task rows")
        self.assertEqual(rows[0][8], 90)
        for person in s.assignees:
            wl = calculate_personnel_workload(self.db, person.id, date(2026, 11, 5))
            self.assertEqual(wl["total_minutes"], rows[0][8])
        self.assertNotEqual(rows[0][8], 72 * 60)

    def test_empty_period_and_unknown_filter_still_produce_clear_workbook(self):
        self.step()
        for target, view, code in [
            ("2026-12-01", "daily", None),
            ("2026-12-03", "weekly", None),
            ("2026-11-05", "daily", "NO-SUCH-STUDY"),
        ]:
            with self.subTest(target=target, view=view, code=code):
                ws, rows, _ = self.download(target, view, code)
                self.assertIn("görev bulunmuyor", rows[0][0])
                self.assertEqual(ws["B8"].value, "Çalışma kodu")
                self.assertIn(code or "Tüm çalışmalar", ws["A3"].value)

    def test_historical_calendar_scope_and_completed_reporting_studies_preserved(self):
        self.assertEqual(REFERENCE_DATE, date(2026, 11, 3))
        for status in (
            StudyStatus.COMPLETED,
            StudyStatus.REPORTING,
            StudyStatus.IN_PROGRESS,
        ):
            self.step("2026-11-02T09:00:00", "2026-11-02T10:00:00", status=status)
        _, rows, _ = self.download("2026-11-02")
        self.assertEqual(len(rows), 3, "No new active-only/historical date exclusion")
        self.assertEqual(
            {r[10].split("(")[1].strip(")") for r in rows},
            {"COMPLETED", "REPORTING", "IN_PROGRESS"},
        )

    def test_downloads_are_read_only_with_existing_conflicts_and_actuals(self):
        s = self.step(
            status=StudyStatus.IN_PROGRESS,
            assignees=("invivo_1",),
            actual_start=datetime(2026, 11, 5, 9),
            actual_reference_time=datetime(2026, 11, 5, 10),
        )
        self.db.add(
            Conflict(
                study_id=s.study_id,
                step_id=s.id,
                conflict_type=ConflictType.PERSONNEL_OVERLAP,
                title="Existing conflict",
                description="Must remain exactly as stored",
            )
        )
        self.db.commit()
        before = snapshot()
        with patch(
            "app.api.v1.planning.revalidate_study_conflicts",
            side_effect=AssertionError("No revalidation"),
        ):
            for view in ("daily", "weekly"):
                self.download(view=view, user="qa_user")  # read-only user can download
        self.assertEqual(snapshot(), before)

    def test_permissions_and_request_validation(self):
        before = snapshot()
        url = "/api/v1/planning/export-excel"
        params = {"target_date": "2026-11-05", "view": "daily"}
        self.assertEqual(self.client.get(url, params=params).status_code, 401)
        self.assertEqual(
            self.client.get(
                url, params=params, headers=self.headers["invivo_1"]
            ).status_code,
            403,
        )
        for bad in (
            {},
            {"target_date": "bad", "view": "daily"},
            {"target_date": "2026-11-05", "view": "monthly"},
            {"target_date": "9999-12-31", "view": "weekly"},
        ):
            self.assertEqual(
                self.client.get(
                    url, params=bad, headers=self.headers["emine"]
                ).status_code,
                422,
            )
        self.assertEqual(snapshot(), before)

    def test_user_values_stay_literal_text_in_excel(self):
        self.step(code="=1+1", name='=HYPERLINK("https://example.invalid")')
        ws, rows, _ = self.download(code="=1+1")
        self.assertEqual(rows[0][1], "=1+1")
        self.assertEqual(ws["B9"].data_type, "s")
        self.assertEqual(ws["C9"].data_type, "s")


if __name__ == "__main__":
    unittest.main()
