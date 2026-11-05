"""Full replan must not erase execution evidence; only disposable SQLite is used."""

import os
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

TMP = tempfile.TemporaryDirectory(prefix="nanoglp_replan_guard_")
os.environ["DATABASE_URL"] = f"sqlite:///{TMP.name}/test.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.database import Base, SessionLocal, engine
from app.main import app
from app.seed import reset_schema, seed_personnel
from app.models.study import Study, StudyStatus
from app.models.study_step import StudyStep, StepStatus
from app.models.sample import SampleRecord
from app.models.conflict import Conflict, ConflictType, ConflictSeverity
from app.services.scheduling_engine import schedule_new_study
from app.services.sample_service import plan_sample

CASES = (
    (StepStatus.PENDING, "actual_start"),
    (StepStatus.PENDING, "actual_end"),
    (StepStatus.PENDING, "actual_reference_time"),
    (StepStatus.IN_PROGRESS, None),
    (StepStatus.COMPLETED, None),
)
START = date(2029, 1, 8)


def snapshot():
    # A new Session observes committed rows, not the caller's identity map.
    with SessionLocal() as session:
        return {
            t.name: [
                dict(r)
                for r in session.execute(
                    t.select().order_by(*t.primary_key.columns)
                ).mappings()
            ]
            for t in Base.metadata.sorted_tables
        }


class ReplanExecutionGuard(unittest.TestCase):
    def setUp(self):
        reset_schema()
        self.db = SessionLocal()
        self.people = {u.username: u for u in seed_personnel(self.db)}
        self.user = self.people["emine"]
        self.client = TestClient(app, raise_server_exceptions=False)
        from app.seed import DEFAULT_PASSWORD

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

    def fixture(self, status, actual, study_status=StudyStatus.DRAFT):
        self.serial += 1
        study = Study(
            study_code=f"GUARD-{self.serial}",
            title="Original title",
            test_item_name="Original item",
            test_item_batch="Original lot",
            sponsor_name="Original sponsor",
            study_director_id=self.people["ezgi"].id,
            status=study_status,
            template_code="ISO_10993_23_IC",
            target_start_date=date(2028, 12, 4),
            target_end_date=date(2028, 12, 14),
            acclimatization_start_date=date(2028, 12, 4),
            dossier_metadata={"biological_revisions": [{"note": "retain revision"}]},
        )
        self.db.add(study)
        self.db.flush()
        step = StudyStep(
            study_id=study.id,
            step_name="Original task",
            status=status,
            planned_start=datetime(2028, 12, 4, 9, 37),
            planned_end=datetime(2028, 12, 4, 10, 12),
        )
        if actual:
            setattr(step, actual, datetime(2028, 12, 4, 9, 42))
        step.assignees = [self.people["ezgi"], self.people["invivo_1"]]
        self.db.add(step)
        self.db.flush()
        sample = SampleRecord(
            study_code=study.study_code,
            test_item_name="Replacement item",
            lot_no="Replacement lot",
            sponsor_name="Replacement sponsor",
            study_director_name=self.user.full_name,
            template_code="ISO_10993_6_IMP",
            planned_start=date(2028, 12, 4),
            stored_status="PLANNED",
            workflow={
                "6": {"approvals": {"CY": {"by": "Original", "at": "2028-12-04T09:00"}}}
            },
        )
        self.db.add(sample)
        self.db.add_all(
            [
                Conflict(
                    study_id=study.id,
                    step_id=step.id,
                    conflict_type=ConflictType.PERSONNEL_OVERLAP,
                    severity=ConflictSeverity.WARNING,
                    title="Existing conflict",
                    description="Keep me",
                ),
                Conflict(
                    related_study_id=study.id,
                    conflict_type=ConflictType.EQUIPMENT_OVERLAP,
                    severity=ConflictSeverity.CRITICAL,
                    title="Related conflict",
                    description="Keep me too",
                ),
            ]
        )
        self.db.commit()
        return study, sample

    def changed_tables(self, before):
        after = snapshot()
        return [name for name in before if before[name] != after[name]]

    def assert_service_rejected(self, call, study):
        before = snapshot()
        error = None
        try:
            call()
        except PermissionError as exc:
            error = exc
        # Even if a caller commits after catching the error, no pending changes exist.
        self.db.commit()
        self.assertEqual(
            (error is not None, self.changed_tables(before)),
            (True, []),
            "Expected rejection and no committed changes (verified with a new Session)",
        )
        self.assertIn(study.study_code, str(error))
        self.assertIn("yeniden plan", str(error).lower())

    def assert_api_rejected(self, response, before, study):
        self.assertEqual(
            (response.status_code, self.changed_tables(before)),
            (409, []),
            "Expected HTTP 409 and no committed changes (verified with a new Session)",
        )
        self.assertIn(study.study_code, response.json()["detail"])
        self.assertIn("yeniden plan", response.json()["detail"].lower())

    def test_engine_rejects_each_execution_signal_without_mutation(self):
        for status, actual in CASES:
            with self.subTest(status=status, actual=actual):
                study, _ = self.fixture(status, actual)
                self.assert_service_rejected(
                    lambda: schedule_new_study(
                        self.db, study.id, START, template_code="ISO_10993_6_IMP"
                    ),
                    study,
                )

    def test_plan_sample_rejects_before_field_commit_even_with_allow_non_draft(self):
        for allow in (False, True):
            for status, actual in CASES:
                with self.subTest(allow_non_draft=allow, status=status, actual=actual):
                    study, sample = self.fixture(
                        status,
                        actual,
                        StudyStatus.APPROVED if allow else StudyStatus.DRAFT,
                    )
                    self.assert_service_rejected(
                        lambda: plan_sample(
                            self.db,
                            sample,
                            self.user,
                            start_date=START,
                            allow_non_draft=allow,
                            existing_study=study if allow else None,
                        ),
                        study,
                    )

    def test_planning_api_id_and_code_reject_before_dossier_commit(self):
        for selector in ("study_id", "study_code"):
            for status, actual in CASES:
                with self.subTest(selector=selector, status=status, actual=actual):
                    study, _ = self.fixture(status, actual)
                    before = snapshot()
                    response = self.client.post(
                        "/api/v1/planning/schedule-study",
                        headers=self.headers,
                        json={
                            selector: (
                                study.id if selector == "study_id" else study.study_code
                            ),
                            "acclimatization_start_date": START.isoformat(),
                            "template_code": "ISO_10993_6_IMP",
                            "title": "Replacement title",
                            "test_item_name": "Replacement item",
                            "test_item_batch": "Replacement lot",
                            "sponsor_name": "Replacement sponsor",
                            "study_director_id": self.user.id,
                            "dossier_metadata": {"replacement": True},
                        },
                    )
                    self.assert_api_rejected(response, before, study)

    def test_sample_api_rejects_without_mutation(self):
        for status, actual in CASES:
            with self.subTest(status=status, actual=actual):
                study, sample = self.fixture(status, actual)
                before = snapshot()
                response = self.client.post(
                    f"/api/v1/samples/{sample.id}/plan",
                    headers=self.headers,
                    json={"start_date": START.isoformat()},
                )
                self.assert_api_rejected(response, before, study)

    def test_planning_api_late_engine_rejection_must_not_commit_dossier(self):
        # Detect a fix placed only in the engine, after the API's early commit.
        study, _ = self.fixture(StepStatus.PENDING, "actual_reference_time")
        before = snapshot()
        with patch(
            "app.api.v1.planning.schedule_new_study",
            side_effect=PermissionError(
                f"{study.study_code}: yeniden planlama engellendi"
            ),
        ):
            response = self.client.post(
                "/api/v1/planning/schedule-study",
                headers=self.headers,
                json={
                    "study_id": study.id,
                    "acclimatization_start_date": START.isoformat(),
                    "title": "Replacement title",
                    "test_item_batch": "Replacement lot",
                },
            )
        self.assert_api_rejected(response, before, study)

    def test_plan_sample_late_engine_rejection_must_not_commit_fields(self):
        # allow_non_draft must not leave an APPROVED study downgraded to DRAFT.
        study, sample = self.fixture(StepStatus.COMPLETED, None, StudyStatus.APPROVED)
        with patch(
            "app.services.scheduling_engine.schedule_new_study",
            side_effect=PermissionError(
                f"{study.study_code}: yeniden planlama engellendi"
            ),
        ):
            self.assert_service_rejected(
                lambda: plan_sample(
                    self.db, sample, self.user, start_date=START, allow_non_draft=True
                ),
                study,
            )

    def test_unexecuted_drafts_still_replan_on_all_paths(self):
        for path in ("engine", "sample", "planning_api"):
            with self.subTest(path=path):
                study, sample = self.fixture(StepStatus.PENDING, None)
                if path == "engine":
                    schedule_new_study(self.db, study.id, START)
                elif path == "sample":
                    plan_sample(self.db, sample, self.user, start_date=START)
                else:
                    response = self.client.post(
                        "/api/v1/planning/schedule-study",
                        headers=self.headers,
                        json={
                            "study_id": study.id,
                            "acclimatization_start_date": START.isoformat(),
                        },
                    )
                    self.assertEqual(response.status_code, 200, response.text)
                with SessionLocal() as check:
                    steps = check.query(StudyStep).filter_by(study_id=study.id).all()
                    self.assertGreater(len(steps), 1)
                    self.assertTrue(all(s.step_name != "Original task" for s in steps))
                    self.assertTrue(all(s.status == StepStatus.PENDING for s in steps))
                    self.assertEqual(
                        check.get(Study, study.id).acclimatization_start_date, START
                    )


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        engine.dispose()
        TMP.cleanup()
