"""Real PUT and DOCX contract for manual shared facts; disposable SQLite only."""

import io
import os
import sys
import tempfile
import unittest
import zipfile
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

TMP = tempfile.TemporaryDirectory(prefix="nanoglp_sample_sync_")
os.environ["DATABASE_URL"] = f"sqlite:///{TMP.name}/test.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docx import Document
from lxml import etree
from fastapi.testclient import TestClient
from sqlalchemy import event
from app.database import Base, SessionLocal, engine
from app.main import app
from app.seed import reset_schema, seed_personnel, DEFAULT_PASSWORD
from app.models.sample import SampleRecord
from app.models.study import Study, StudyStatus
from app.models.user import User
from app.models.study_step import StudyStep, StepStatus
from app.models.conflict import Conflict, ConflictType
from app.services import sample_service as ss
from app.services.excel_refresh import SHARED


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


def operational(snapshot_data):
    return {
        name: [
            {
                k: v
                for k, v in row.items()
                if not (
                    name == "studies"
                    and k in set(SHARED.values()) | {"sponsor_contact", "updated_at"}
                    or name == "sample_records"
                    and k in set(SHARED) | {"contacts", "updated_at"}
                )
            }
            for row in rows
        ]
        for name, rows in snapshot_data.items()
        if name != "audit_logs"
    }


class SampleStudySync(unittest.TestCase):
    def setUp(self):
        # Live indicators must not depend on the machine's calendar date.
        self.enterContext(patch("app.utils.facility_time.facility_now", return_value=datetime(2026, 11, 5, 12)))
        reset_schema()
        self.db = SessionLocal()
        self.people = {u.username: u for u in seed_personnel(self.db)}
        self.client = TestClient(app, raise_server_exceptions=False)
        self.headers = self.login("emine")
        self.a, self.sa = self.pair("SYNC-A", StudyStatus.APPROVED)
        self.b, self.sb = self.pair("SYNC-B", StudyStatus.IN_PROGRESS)

    def login(self, username):
        response = self.client.post(
            "/api/v1/auth/login",
            data={"username": username, "password": DEFAULT_PASSWORD},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": "Bearer " + response.json()["access_token"]}

    def tearDown(self):
        self.client.close()
        self.db.close()

    def pair(self, code, status):
        study = Study(
            study_code=code,
            title="Original title",
            test_item_name="Old product",
            sponsor_name="Old sponsor",
            test_item_batch="OLD-LOT",
            test_type="Old analysis",
            manufacture_date="01.2026",
            expiry_date="01.2028",
            test_item_storage_condition="Old storage",
            sponsor_contact="Old Person <old@example.test>",
            study_director_id=self.people["ezgi"].id,
            template_code="ISO_10993_23_IC",
            status=status,
            target_start_date=date(2028, 12, 4),
            target_end_date=date(2028, 12, 14),
            acclimatization_start_date=date(2028, 12, 4),
            protocol_approved_at=datetime(2028, 12, 1, 8, 15),
            dossier_metadata={"biological_revisions": [{"id": "retain"}]},
        )
        self.db.add(study)
        self.db.flush()
        step = StudyStep(
            study_id=study.id,
            step_name="Original step",
            status=StepStatus.COMPLETED,
            planned_start=datetime(2028, 12, 4, 9, 37),
            planned_end=datetime(2028, 12, 4, 10, 12),
            actual_start=datetime(2028, 12, 4, 9, 38),
            actual_end=datetime(2028, 12, 4, 10, 15),
            actual_reference_time=datetime(2028, 12, 4, 9, 42),
        )
        step.assignees = [self.people["ezgi"], self.people["invivo_1"]]
        self.db.add(step)
        self.db.flush()
        self.db.add(
            Conflict(
                study_id=study.id,
                step_id=step.id,
                conflict_type=ConflictType.PERSONNEL_OVERLAP,
                title="Keep conflict",
                description="Keep details",
            )
        )
        sample = SampleRecord(
            study_code=code,
            test_item_code="TI-SHARED",
            test_item_name="Old product",
            sponsor_name="Old sponsor",
            lot_no="OLD-LOT",
            requested_analysis="Old analysis",
            manufacture_date="01.2026",
            expiry_date="01.2028",
            storage_condition="Old storage",
            contacts=[{"name": "Old Person", "email": "old@example.test"}],
            template_code="ISO_10993_23_IC",
            study_director_name="Ezgi Nur AKIN",
            planned_start=date(2028, 12, 2),
            planned_end=date(2028, 12, 12),
            lab_arrival_date=date(2028, 12, 1),
            stored_status="EXPECTED",
            workflow={
                "6": {"approvals": {"CY": {"by": "Actual", "at": "2028-12-01T08:15"}}}
            },
        )
        self.db.add(sample)
        self.db.commit()
        return study, sample

    def put(self, data, sample=None, headers=None):
        return self.client.put(
            f"/api/v1/samples/{(sample or self.sa).id}",
            headers=headers or self.headers,
            json=data,
        )

    def docx(self, study=None):
        response = self.client.get(
            f"/api/v1/studies/{(study or self.a).id}/export-study-plan",
            headers=self.headers,
        )
        self.assertEqual(
            response.status_code,
            200,
            response.text[:200] if response.status_code != 200 else "",
        )
        doc = Document(io.BytesIO(response.content))
        fields = {
            r.cells[0].text.strip(): r.cells[2].text.strip()
            for t in doc.tables
            for r in t.rows
            if len(r.cells) == 3
        }
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            text = "\n".join(
                "".join(etree.fromstring(z.read(n)).itertext())
                for n in z.namelist()
                if n.startswith("word/") and n.endswith(".xml")
            )
        return fields, text

    def test_shared_values_match_in_sample_study_and_word(self):
        before = operational(snapshot())
        payload = dict(
            sponsor_name="EXXON Sponsor",
            test_item_name="XXL Product",
            lot_no=" LOT-XX123 ",
            manufacture_date="02.2026",
            expiry_date="02.2029",
            storage_condition="New storage",
            requested_analysis="Corrected analysis",
            contacts=[{"name": "New Person", "email": "new@example.test"}],
        )
        response = self.put(payload)
        self.assertEqual(response.status_code, 200, response.text)
        with SessionLocal() as db:
            study, sample = db.get(Study, self.a.id), db.get(SampleRecord, self.sa.id)
            for src, dest in SHARED.items():
                self.assertEqual(getattr(study, dest), payload[src].strip(), src)
                self.assertEqual(getattr(sample, src), payload[src].strip(), src)
            self.assertEqual(study.sponsor_contact, "New Person <new@example.test>")
        self.assertEqual(before, operational(snapshot()))
        fields, text = self.docx()
        for label, value in {
            "LOT Number": "LOT-XX123",
            "Name of the test item": "XXL Product",
            "Date of Manufacture": "02.2026",
            "Date of Expiry": "02.2029",
            "Storage condition": "New storage",
        }.items():
            self.assertEqual(fields[label], value)
        self.assertIn("EXXON Sponsor", text)
        self.assertIn("new@example.test", text)
        self.assertNotIn("OLD-LOT", text)

    def test_only_sent_fields_change_and_repeated_save_does_not_plan(self):
        before = snapshot()
        with patch.object(
            ss, "plan_sample", side_effect=AssertionError("must not plan")
        ), patch(
            "app.services.scheduling_engine.schedule_new_study",
            side_effect=AssertionError("must not plan"),
        ):
            response = self.put({"lot_no": "UPDATED"})
            self.assertEqual(response.status_code, 200, response.text)
            after = snapshot()
            for table in before:
                if table == "audit_logs":
                    continue
                ignored = (
                    {"updated_at", "lot_no"}
                    if table == "sample_records"
                    else (
                        {"updated_at", "test_item_batch"}
                        if table == "studies"
                        else set()
                    )
                )
                self.assertEqual(
                    [
                        {k: v for k, v in r.items() if k not in ignored}
                        for r in before[table]
                    ],
                    [
                        {k: v for k, v in r.items() if k not in ignored}
                        for r in after[table]
                    ],
                    table,
                )
            repeat = self.put({"lot_no": "UPDATED"})
            self.assertEqual(repeat.status_code, 200, repeat.text)
            self.assertEqual(after, snapshot())

    def test_related_scope_off_and_on_uses_each_study_and_existing_trm_scope(self):
        isolated, isolated_sample = self.pair("SYNC-C", StudyStatus.DRAFT)
        isolated_sample.test_item_code = "TI-OTHER"
        self.db.commit()
        for enabled, expected_b in ((False, "OLD-LOT"), (True, "SHARED-LOT")):
            with self.subTest(apply_to_related=enabled):
                response = self.put(
                    {
                        "lot_no": "SHARED-LOT",
                        "sponsor_name": "Only A Sponsor",
                        "apply_to_related": enabled,
                    }
                )
                self.assertEqual(response.status_code, 200, response.text)
                with SessionLocal() as db:
                    self.assertEqual(
                        db.get(Study, self.a.id).test_item_batch, "SHARED-LOT"
                    )
                    self.assertEqual(
                        db.get(Study, self.b.id).test_item_batch, expected_b
                    )
                    self.assertEqual(
                        db.get(SampleRecord, self.sb.id).lot_no, expected_b
                    )
                    self.assertEqual(
                        db.get(Study, self.b.id).sponsor_name, "Old sponsor"
                    )
                    self.assertEqual(
                        db.get(Study, isolated.id).test_item_batch, "OLD-LOT"
                    )
                self.assertEqual(
                    response.json()["propagated_to"], ["SYNC-B"] if enabled else []
                )
                self.assertEqual(self.docx(self.b)[0]["LOT Number"], expected_b)

    def test_normalized_code_and_missing_study(self):
        self.a.study_code = " sync- a "
        self.db.commit()
        response = self.put({"lot_no": "NORMALIZED"})
        self.assertEqual(response.status_code, 200, response.text)
        with SessionLocal() as db:
            self.assertEqual(db.get(Study, self.a.id).test_item_batch, "NORMALIZED")
        self.assertEqual(self.docx()[0]["LOT Number"], "NORMALIZED")
        sample = SampleRecord(study_code="NO-STUDY", test_item_code="TI-SHARED")
        self.db.add(sample)
        self.db.commit()
        before = snapshot()
        response = self.put(
            {"lot_no": "ONLY-SAMPLE", "test_item_name": None}, sample=sample
        )
        self.assertEqual(response.status_code, 200, response.text)
        after = snapshot()
        self.assertEqual(before["studies"], after["studies"])
        self.assertEqual(before["study_steps"], after["study_steps"])

    def test_explicit_clears_nullable_fields_and_rejects_required_name_atomically(self):
        payload = dict(
            lot_no=" ",
            sponsor_name=None,
            manufacture_date="",
            expiry_date=None,
            storage_condition="",
            requested_analysis=None,
            contacts=[],
        )
        response = self.put(payload)
        self.assertEqual(response.status_code, 200, response.text)
        with SessionLocal() as db:
            study = db.get(Study, self.a.id)
            for src, dest in SHARED.items():
                if src in payload:
                    self.assertIsNone(getattr(study, dest), src)
            self.assertIsNone(study.sponsor_contact)
            self.assertEqual(study.test_item_name, "Old product")
        self.assertEqual(self.docx()[0]["LOT Number"], "TBD")
        for blank in (None, "", "  "):
            with self.subTest(blank=blank):
                before = snapshot()
                response = self.put(
                    {
                        "test_item_name": blank,
                        "lot_no": "MUST-ROLL-BACK",
                        "apply_to_related": True,
                    }
                )
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(before, snapshot())

    def test_failure_in_response_serialization_rolls_back_all_records(self):
        before = snapshot()
        with patch.object(
            ss,
            "serialize_sample",
            side_effect=RuntimeError("injected serialization failure"),
        ):
            response = self.put({"lot_no": "ROLLBACK", "apply_to_related": True})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(before, snapshot())

    def test_database_failure_on_related_study_rolls_back_all_records(self):
        before = snapshot()

        def fail_update(mapper, connection, target):
            if target.id == self.b.id and target.test_item_batch == "ROLLBACK":
                raise RuntimeError("injected related-study persistence failure")

        event.listen(Study, "before_update", fail_update)
        try:
            response = self.put({"lot_no": "ROLLBACK", "apply_to_related": True})
        finally:
            event.remove(Study, "before_update", fail_update)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(before, snapshot())

    def test_sent_field_can_repair_study_drift_without_touching_omitted_fields(self):
        self.a.test_item_batch = "STALE-STUDY-LOT"
        self.a.sponsor_name = "Unsent old sponsor"
        self.db.commit()
        response = self.put({"lot_no": "OLD-LOT"})
        self.assertEqual(response.status_code, 200, response.text)
        with SessionLocal() as db:
            self.assertEqual(db.get(Study, self.a.id).test_item_batch, "OLD-LOT")
            self.assertEqual(
                db.get(Study, self.a.id).sponsor_name, "Unsent old sponsor"
            )
        before = snapshot()
        response = self.put({"lot_no": "OLD-LOT"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(before, snapshot())

    def test_ambiguous_normalized_study_code_rejects_without_partial_changes(self):
        self.pair(" sync- a ", StudyStatus.DRAFT)
        before = snapshot()
        response = self.put({"lot_no": "AMBIGUOUS", "apply_to_related": True})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(before, snapshot())

    def test_existing_edit_permissions_are_enforced(self):
        sales = User(
            username="sync_sales",
            full_name="Sales",
            role="SALES",
            hashed_password=self.people["emine"].hashed_password,
        )
        trm = User(
            username="sync_trm",
            full_name="Acceptance",
            role="TRM_KABUL",
            hashed_password=self.people["emine"].hashed_password,
        )
        self.db.add_all([sales, trm])
        self.db.commit()
        sales_headers, trm_headers = self.login(sales.username), self.login(
            trm.username
        )
        before = snapshot()
        for headers, payload in (
            (sales_headers, {"lot_no": "DENIED"}),
            (trm_headers, {"sponsor_name": "DENIED"}),
        ):
            response = self.put(payload, headers=headers)
            self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(before, snapshot())
        self.assertEqual(
            self.put(
                {"sponsor_name": "Sales correction"}, headers=sales_headers
            ).status_code,
            200,
        )
        self.assertEqual(
            self.put({"lot_no": "TRM correction"}, headers=trm_headers).status_code, 200
        )
        with SessionLocal() as db:
            self.assertEqual(db.get(Study, self.a.id).sponsor_name, "Sales correction")
            self.assertEqual(db.get(Study, self.a.id).test_item_batch, "TRM correction")


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        engine.dispose()
        TMP.cleanup()
