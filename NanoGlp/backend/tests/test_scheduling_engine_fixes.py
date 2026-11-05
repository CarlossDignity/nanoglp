"""
Planlama Motoru (Scheduling Engine) İlk Düzeltme Turu — Kabul ve Regresyon Testleri

İncelenen 5 bulguyu izole geçici SQLite veritabanında doğrular (canlı veritabanına dokunmaz):
1. Yeniden doğrulamada eksik personel uyarılarının kaybolması
2. Ekstraksiyon kurulumunun tamamlanmasıyla cihaz rezervasyonunun erken düşmesi
3. Gerçekleşen gecikmenin biyolojik bağımlılıklara yansımaması
4. Yeniden hesaplamanın geçmiş görevleri gerçekleşmiş gibi tamamlaması
5. Kapasite kontrolündeki hataların sessizce yutulması
"""
import io
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from unittest.mock import patch

_TMP_DIR = tempfile.mkdtemp(prefix="nanoglp_sched_fixes_")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_TMP_DIR, "test_fixes.db")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import Workbook  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.conflict import Conflict, ConflictSeverity, ConflictType  # noqa: E402
from app.models.equipment import Equipment  # noqa: E402
from app.models.sample import SampleRecord  # noqa: E402
from app.models.study import Study, StudyStatus  # noqa: E402
from app.models.study_step import StepStatus, StudyStep  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.seed import DEFAULT_PASSWORD, reset_schema, seed_personnel  # noqa: E402
import app.services.scheduling_engine as se  # noqa: E402
from app.services.scheduling_engine import (  # noqa: E402
    calculate_personnel_workload,
    recompute_all_conflicts,
    revalidate_study_conflicts,
    schedule_new_study,
)

assert "nanoglp_sched_fixes_" in settings.DATABASE_URL, "Test canlı veritabanını hedefleyemez!"


def _login_headers(client: TestClient, username: str = "emine", password: str = DEFAULT_PASSWORD) -> dict:
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


class SchedulingEngineFixRound1Tests(unittest.TestCase):
    def setUp(self):
        # Live indicators must not depend on the machine's calendar date.
        self.enterContext(patch("app.utils.facility_time.facility_now", return_value=datetime(2026, 11, 5, 12)))
        reset_schema()
        self.db = SessionLocal()
        self.people = {u.username: u for u in seed_personnel(self.db)}
        self.client = TestClient(app, raise_server_exceptions=False)
        self.h_tfm = _login_headers(self.client, "emine")
        self.h_sd = _login_headers(self.client, "ezgi")
        self.h_tech1 = _login_headers(self.client, "invivo_1")

    def tearDown(self):
        self.db.close()

    @classmethod
    def tearDownClass(cls):
        engine.dispose()
        shutil.rmtree(_TMP_DIR, ignore_errors=True)

    # ------------------------------------------------------------------
    # 1. Yeniden doğrulamada eksik personel uyarılarının kaybolması
    # ------------------------------------------------------------------
    def test_1_missing_personnel_preserved_on_revalidation_and_blocks_approval(self):
        # Tüm aktif teknisyenleri pasife al
        for u in self.db.query(User).filter(User.role == UserRole.TECHNICIAN).all():
            u.is_active = False
        self.db.commit()

        sd = self.people["ezgi"]
        s1 = Study(
            study_code="FIX1-S1",
            title="Fix 1 Study 1",
            test_item_name="Test Item 1",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
        )
        self.db.add(s1)
        self.db.commit()

        monday = date(2026, 11, 2)
        res1 = schedule_new_study(self.db, s1.id, monday)
        self.assertFalse(res1["can_approve"], "Eksik teknisyen varken ilk planlamada can_approve False olmalı")
        self.assertTrue(
            any(c["type"] == "QUALIFICATION_MISMATCH" and c["severity"] == "CRITICAL" for c in res1["conflicts"]),
            "İlk planlamada CRITICAL QUALIFICATION_MISMATCH üretilmeli",
        )

        # Doğrudan yeniden doğrulama (revalidate_study_conflicts)
        revalidate_study_conflicts(self.db, s1)
        self.db.commit()
        open_after_reval = (
            self.db.query(Conflict)
            .filter(
                Conflict.study_id == s1.id,
                Conflict.is_resolved == False,  # noqa: E712
                Conflict.conflict_type == ConflictType.QUALIFICATION_MISMATCH,
                Conflict.severity == ConflictSeverity.CRITICAL,
            )
            .count()
        )
        self.assertGreaterEqual(
            open_after_reval,
            1,
            "revalidate_study_conflicts sonrasında eksik personel CRITICAL çakışması korunmalı",
        )

        # İkinci taslak çalışma eklendiğinde (otomatik revalidate tetikler)
        s2 = Study(
            study_code="FIX1-S2",
            title="Fix 1 Study 2",
            test_item_name="Test Item 2",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
        )
        self.db.add(s2)
        self.db.commit()
        schedule_new_study(self.db, s2.id, date(2026, 11, 9))

        open_after_s2 = (
            self.db.query(Conflict)
            .filter(
                Conflict.study_id == s1.id,
                Conflict.is_resolved == False,  # noqa: E712
                Conflict.conflict_type == ConflictType.QUALIFICATION_MISMATCH,
                Conflict.severity == ConflictSeverity.CRITICAL,
            )
            .count()
        )
        self.assertGreaterEqual(
            open_after_s2,
            1,
            "Başka bir taslak çalışma planlandıktan sonra da s1'in eksik personel uyarısı açık kalmalı",
        )

        # Toplu yeniden hesaplama (recompute_all_conflicts)
        recompute_all_conflicts(self.db)
        open_after_recompute = (
            self.db.query(Conflict)
            .filter(
                Conflict.study_id == s1.id,
                Conflict.is_resolved == False,  # noqa: E712
                Conflict.conflict_type == ConflictType.QUALIFICATION_MISMATCH,
                Conflict.severity == ConflictSeverity.CRITICAL,
            )
            .count()
        )
        self.assertGreaterEqual(
            open_after_recompute,
            1,
            "recompute_all_conflicts sonrasında da eksik personel CRITICAL çakışması açık kalmalı",
        )

        # Plan onayı reddedilmeli (409)
        app_resp = self.client.post(f"/api/v1/planning/studies/{s1.id}/approve", headers=self.h_tfm)
        self.assertEqual(app_resp.status_code, 409, "Eksik personel varken plan onaylanamamalı (409)")

        # Çakışma tablosundan kayıt silinse bile /approve güncel doğrulama çalıştırıp reddetmeli
        self.db.query(Conflict).filter(Conflict.study_id == s1.id).delete()
        self.db.commit()
        app_resp2 = self.client.post(f"/api/v1/planning/studies/{s1.id}/approve", headers=self.h_tfm)
        self.assertEqual(
            app_resp2.status_code,
            409,
            "Onay uç noktası güncel doğrulama çalıştırmalı ve eksik personel varsa 409 dönmeli",
        )

        # Teknisyen tekrar aktif edilip yeniden planlandığında eksik rol kalmamalı ve onay 200 dönmeli
        self.people["invivo_1"].is_active = True
        self.db.commit()
        schedule_new_study(self.db, s1.id, date(2026, 11, 2))
        app_resp_ok = self.client.post(f"/api/v1/planning/studies/{s1.id}/approve", headers=self.h_tfm)
        self.assertEqual(
            app_resp_ok.status_code,
            200,
            "Eksik personel giderildikten sonra plan onayı 200 OK dönmeli",
        )

    # ------------------------------------------------------------------
    # 2. Ekstraksiyon kurulumunun tamamlanmasıyla cihaz rezervasyonunun erken düşmesi
    # ------------------------------------------------------------------
    def test_2_water_bath_reservation_persists_after_setup_step_completed(self):
        wb = self.db.query(Equipment).filter(Equipment.code == "EQ-WB-001").first()
        wb.polar_capacity = 1
        wb.non_polar_capacity = 1
        self.db.commit()

        sd = self.people["ezgi"]
        s1 = Study(
            study_code="FIX2-WB1",
            title="Water Bath Study 1",
            test_item_name="Polymer A",
            study_director_id=sd.id,
            status=StudyStatus.APPROVED,
            extraction_polar=True,
            extraction_non_polar=True,
        )
        self.db.add(s1)
        self.db.commit()

        # s1 için G0 = 2026-11-02 (Pzt) -> G4 Ekstraksiyon = 2026-11-06 (Cum) 08:00 .. 2026-11-09 (Pzt) 08:00 (72s)
        s1.status = StudyStatus.DRAFT
        self.db.commit()
        schedule_new_study(self.db, s1.id, date(2026, 11, 2))
        s1.status = StudyStatus.IN_PROGRESS
        ex_step_1 = (
            self.db.query(StudyStep)
            .filter(StudyStep.study_id == s1.id, StudyStep.step_order == 2)
            .first()
        )
        # 90 dakikalık kurulum adımı tamamlandı olarak işaretlenir, ancak 72 saatlik su banyosu süreci devam etmektedir
        ex_step_1.status = StepStatus.COMPLETED
        ex_step_1.actual_start = ex_step_1.planned_start
        ex_step_1.actual_end = ex_step_1.planned_end
        self.db.commit()

        # Uzun süreli cihaz bekleme süresi (72s) personel iş yüküne EKLENMEMELİ (sadece 90 dk kurulum)
        tech_id = ex_step_1.assignees[0].id
        wl_day4 = calculate_personnel_workload(self.db, tech_id, date(2026, 11, 6))
        self.assertEqual(wl_day4["total_minutes"], 90, "Personel iş yükü 72 saat değil yalnızca 90 dk olmalı")

        # Aynı 72 saatlik pencereye düşen 2. çalışma (G0 = 2026-11-03 Sal -> G4 = 2026-11-07 Cmt 08:00)
        s2 = Study(
            study_code="FIX2-WB2",
            title="Water Bath Study 2",
            test_item_name="Polymer B",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
            extraction_polar=True,
            extraction_non_polar=True,
        )
        self.db.add(s2)
        self.db.commit()
        res2 = schedule_new_study(self.db, s2.id, date(2026, 11, 3))
        self.assertTrue(
            any(c["type"] == "EQUIPMENT_OVERLAP" for c in res2["conflicts"]),
            "İlk çalışmanın kurulum adımı COMPLETED olsa bile 72s pencere içinde ikinci çalışma EQUIPMENT_OVERLAP üretmeli",
        )

        # Yeniden doğrulama (revalidate_study_conflicts) aynı sonucu üretmeli
        revalidate_study_conflicts(self.db, s2)
        self.db.commit()
        eq_conf_reval = (
            self.db.query(Conflict)
            .filter(
                Conflict.study_id == s2.id,
                Conflict.is_resolved == False,  # noqa: E712
                Conflict.conflict_type == ConflictType.EQUIPMENT_OVERLAP,
            )
            .count()
        )
        self.assertGreaterEqual(eq_conf_reval, 1, "revalidate_study_conflicts sonrasında EQUIPMENT_OVERLAP korunmalı")

        # Toplu yeniden hesaplama (recompute_all_conflicts) aynı sonucu üretmeli
        recompute_all_conflicts(self.db)
        eq_conf_recompute = (
            self.db.query(Conflict)
            .filter(
                Conflict.study_id == s2.id,
                Conflict.is_resolved == False,  # noqa: E712
                Conflict.conflict_type == ConflictType.EQUIPMENT_OVERLAP,
            )
            .count()
        )
        self.assertGreaterEqual(eq_conf_recompute, 1, "recompute_all_conflicts sonrasında EQUIPMENT_OVERLAP korunmalı")

        # s2'yi iptal edip 72 saatlik rezervasyonun TAM BİTİŞ SAATİNDE (2026-11-09 08:00 -> G0 = 2026-11-05 Per) başlayan 3. çalışmayı test et
        s2.status = StudyStatus.CANCELLED
        self.db.commit()

        s3 = Study(
            study_code="FIX2-WB3",
            title="Water Bath Study 3 Boundary",
            test_item_name="Polymer C",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
            extraction_polar=True,
            extraction_non_polar=True,
        )
        self.db.add(s3)
        self.db.commit()
        # G0 = 2026-11-05 -> G4 = 2026-11-09 08:00 (s1'in 2026-11-06 08:00 + 72s = 2026-11-09 08:00 bitişiyle tam sınırda)
        res3 = schedule_new_study(self.db, s3.id, date(2026, 11, 5))
        self.assertFalse(
            any(c["type"] == "EQUIPMENT_OVERLAP" for c in res3["conflicts"]),
            "72 saatlik rezervasyonun tam bitiş saatinde (08:00) başlayan çalışma bu rezervasyonla çakışmamalı",
        )

    # ------------------------------------------------------------------
    # 3. Gerçekleşen gecikmenin biyolojik bağımlılıklara yansımaması
    # ------------------------------------------------------------------
    def test_3_biological_reference_delay_propagates_to_dependent_steps_without_silent_mutation(self):
        sd = self.people["ezgi"]
        # Zamanında gerçekleşen uygulama kontrolü için çalışma 1
        s_ontime = Study(
            study_code="FIX3-ONTIME",
            title="On-Time Bio Study",
            test_item_name="Saline",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
        )
        self.db.add(s_ontime)
        self.db.commit()
        schedule_new_study(self.db, s_ontime.id, date(2026, 11, 2))
        self.client.post(f"/api/v1/planning/studies/{s_ontime.id}/approve", headers=self.h_tfm)

        ref_step_ontime = (
            self.db.query(StudyStep)
            .filter(StudyStep.study_id == s_ontime.id, StudyStep.step_order == 3)
            .first()
        )
        # Görev 09:00'da başlar, referans enjeksiyon saati tam planlandığı gibi 10:00'da gerçekleşir
        resp_ontime = self.client.patch(
            f"/api/v1/planning/steps/{ref_step_ontime.id}/status",
            headers=self.h_sd,
            json={
                "status": "COMPLETED",
                "actual_start": "2026-11-09T09:00:00",
                "actual_end": "2026-11-09T12:00:00",
                "actual_reference_time": "2026-11-09T10:00:00",
            },
        )
        self.assertEqual(resp_ontime.status_code, 200)
        ontime_conflicts = (
            self.db.query(Conflict)
            .filter(Conflict.study_id == s_ontime.id, Conflict.is_resolved == False)  # noqa: E712
            .all()
        )
        self.assertEqual(
            len(ontime_conflicts),
            0,
            "Zamanında (10:00) gerçekleşen referans uygulamada gereksiz sapma çakışması üretilmemeli",
        )

        # Birleşik adımda actual_start (09:00) verilip referans saat verilmezse actual_start referans saat sanılmamalı, eksik bilgi üretilmeli
        s_missing_ref = Study(
            study_code="FIX3-NOREF",
            title="Missing Ref Time Study",
            test_item_name="Catheter",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
        )
        self.db.add(s_missing_ref)
        self.db.commit()
        schedule_new_study(self.db, s_missing_ref.id, date(2026, 11, 16))
        ref_step_noref = (
            self.db.query(StudyStep)
            .filter(StudyStep.study_id == s_missing_ref.id, StudyStep.step_order == 3)
            .first()
        )
        resp_noref = self.client.patch(
            f"/api/v1/planning/steps/{ref_step_noref.id}/status",
            headers=self.h_sd,
            json={
                "status": "COMPLETED",
                "actual_start": "2026-11-23T09:00:00",
                "actual_end": "2026-11-23T12:00:00",
            },
        )
        self.assertEqual(resp_noref.status_code, 200)
        self.assertIsNone(
            resp_noref.json().get("actual_reference_time"),
            "Referans olay saati verilmediğinde actual_start (09:00) referans saat olarak uydurulmamalı",
        )
        noref_conflicts = (
            self.db.query(Conflict)
            .filter(Conflict.study_id == s_missing_ref.id, Conflict.is_resolved == False)  # noqa: E712
            .all()
        )
        self.assertTrue(
            any("Referans" in c.title for c in noref_conflicts),
            "Referans olay saati girilmeden tamamlanan birleşik adımda eksik referans saati uyarısı üretilmeli",
        )

        # Şimdi: Referans uygulama saati 10:00 planlanan çalışmada gerçekleşen referans saati 13:00 olarak güncelle
        s_delayed = Study(
            study_code="FIX3-DELAY",
            title="Delayed Bio Study",
            test_item_name="Implant Gel",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
        )
        self.db.add(s_delayed)
        self.db.commit()
        # G0 = 2026-12-07 (Pzt) -> G7 Uygulama = 2026-12-14 (Pzt), G8=15.12, G9=16.12, G10=17.12
        schedule_new_study(self.db, s_delayed.id, date(2026, 12, 7))
        self.client.post(f"/api/v1/planning/studies/{s_delayed.id}/approve", headers=self.h_tfm)

        steps_before = (
            self.db.query(StudyStep)
            .filter(StudyStep.study_id == s_delayed.id)
            .order_by(StudyStep.step_order)
            .all()
        )
        planned_snapshot = [(s.step_order, s.planned_start, s.planned_end) for s in steps_before]
        ref_step = next(s for s in steps_before if s.step_order == 3)
        obs24_step = next(s for s in steps_before if s.step_order == 4)
        assigned_tech = obs24_step.assignees[0]

        # 24. saat gözleminin kayacağı 13:00-13:45 saatine aynı teknisyen için başka bir onaylı görev ekle (yeni personel çakışması testi)
        s_blocker = Study(
            study_code="FIX3-BLOCKER",
            title="Blocker Study at 13:00",
            test_item_name="Blocker",
            study_director_id=sd.id,
            status=StudyStatus.APPROVED,
        )
        self.db.add(s_blocker)
        self.db.commit()
        blocker_step = StudyStep(
            study_id=s_blocker.id,
            step_order=1,
            study_day=1,
            step_name="13:00 Çakışan Görev",
            planned_start=datetime(2026, 12, 15, 13, 0),
            planned_end=datetime(2026, 12, 15, 14, 0),
            status=StepStatus.PENDING,
        )
        blocker_step.assignees = [assigned_tech]
        self.db.add(blocker_step)
        self.db.commit()

        # Gerçekleşen referans saati 13:00 olarak güncelle
        patch_resp = self.client.patch(
            f"/api/v1/planning/steps/{ref_step.id}/status",
            headers=self.h_sd,
            json={
                "status": "COMPLETED",
                "actual_start": "2026-12-14T12:00:00",
                "actual_end": "2026-12-14T15:00:00",
                "actual_reference_time": "2026-12-14T13:00:00",
                "notes": "Enjeksiyon 13:00'te tamamlandı",
            },
        )
        self.assertEqual(patch_resp.status_code, 200, patch_resp.text)
        body = patch_resp.json()

        # 1) Onaylanmış plan saatleri (planned_start / planned_end) sessizce DEĞİŞTİRİLMEMİŞ olmalı
        self.db.expire_all()
        steps_after = (
            self.db.query(StudyStep)
            .filter(StudyStep.study_id == s_delayed.id)
            .order_by(StudyStep.step_order)
            .all()
        )
        self.assertEqual(
            [(s.step_order, s.planned_start, s.planned_end) for s in steps_after],
            planned_snapshot,
            "Onaylanmış planın planned_start ve planned_end değerleri sessizce değiştirilmemeli",
        )

        # 2) 24/48/72 saatlik bağımlı adımlar için beklenen referans saatler 13:00 olarak hesaplanmalı
        dep_list = body.get("dependent_steps") or []
        self.assertEqual(len(dep_list), 3, "24, 48 ve 72 saatlik 3 bağımlı adım dönmeli")
        expected_starts = {d["offset_hours"]: datetime.fromisoformat(d["expected_start"]) for d in dep_list}
        self.assertEqual(expected_starts[24], datetime(2026, 12, 15, 13, 0))
        self.assertEqual(expected_starts[48], datetime(2026, 12, 16, 13, 0))
        self.assertEqual(expected_starts[72], datetime(2026, 12, 17, 13, 0))
        self.assertTrue(all(d["exceeds_tolerance"] and d["requires_revision"] for d in dep_list))

        # 3) Tolerans dışı sapma (BIOLOGICAL_TIME_VIOLATION) ve 13:00'teki yeni personel çakışması (PERSONNEL_OVERLAP) üretilmeli
        open_delayed_conflicts = (
            self.db.query(Conflict)
            .filter(Conflict.study_id == s_delayed.id, Conflict.is_resolved == False)  # noqa: E712
            .all()
        )
        c_types = {c.conflict_type for c in open_delayed_conflicts}
        self.assertIn(
            ConflictType.BIOLOGICAL_TIME_VIOLATION,
            c_types,
            "Tolerans dışı referans gecikmesi BIOLOGICAL_TIME_VIOLATION üretmeli",
        )
        self.assertIn(
            ConflictType.PERSONNEL_OVERLAP,
            c_types,
            "Kaymış beklenen pencerede (13:00) oluşan yeni personel çakışması PERSONNEL_OVERLAP olarak tespit edilmeli",
        )

    # ------------------------------------------------------------------
    # 4. Yeniden hesaplamanın geçmiş görevleri gerçekleşmiş gibi tamamlaması
    # ------------------------------------------------------------------
    def test_4_recompute_does_not_auto_complete_past_steps_or_fabricate_actual_times(self):
        sd = self.people["ezgi"]
        # Planlanan tarihi geçmiş (Ekim 2026 < 03.11.2026) ama tamamlanmamış bir çalışma ve SampleRecord oluştur
        sr = SampleRecord(
            study_code="FIX4-PAST",
            glp_type="GLP",
            stored_status="ONGOING",
            planned_start=date(2026, 10, 5),
            experiment_start_date=date(2026, 10, 5),
            experiment_end_date=date(2026, 10, 15),
        )
        self.db.add(sr)
        s_past = Study(
            study_code="FIX4-PAST",
            title="Past Unfinished Study",
            test_item_name="Test Material",
            study_director_id=sd.id,
            status=StudyStatus.IN_PROGRESS,
            acclimatization_start_date=date(2026, 10, 5),
        )
        self.db.add(s_past)
        self.db.commit()

        # Adım 1: Gerçekten tamamlanmış ve gerçek saatleri girilmiş adım
        real_start = datetime(2026, 10, 5, 9, 15)
        real_end = datetime(2026, 10, 5, 11, 5)
        step_done = StudyStep(
            study_id=s_past.id,
            step_order=1,
            study_day=0,
            step_name="Tamamlanmış Geçmiş Adım",
            planned_start=datetime(2026, 10, 5, 9, 0),
            planned_end=datetime(2026, 10, 5, 11, 0),
            status=StepStatus.COMPLETED,
            actual_start=real_start,
            actual_end=real_end,
        )
        step_done.assignees = [ self.people["emine"] ]
        self.db.add(step_done)

        # Adım 2: Planlanan tarihi geçmiş (2026-10-09) ama TAMAMLANMAMIŞ (PENDING) ve teknisyeni eksik (çakışmalı) adım
        step_unexecuted = StudyStep(
            study_id=s_past.id,
            step_order=2,
            study_day=4,
            step_name="72 Saatlik Ekstraksiyon Kurulumu",
            step_type="Ekstraksiyon",
            planned_start=datetime(2026, 10, 9, 8, 0),
            planned_end=datetime(2026, 10, 9, 9, 30),
            is_biological_fixed_time=True,
            biological_tolerance_minutes=30,
            status=StepStatus.PENDING,
            actual_start=None,
            actual_end=None,
        )
        # Bilerek teknisyen atamıyoruz ki çakışma oluşsun ve açık kalsın
        self.db.add(step_unexecuted)
        self.db.commit()

        # Genel çakışma yeniden hesaplamasını çalıştır
        recompute_all_conflicts(self.db)
        self.db.expire_all()

        step_done_after = self.db.query(StudyStep).filter(StudyStep.id == step_done.id).first()
        step_unexec_after = self.db.query(StudyStep).filter(StudyStep.id == step_unexecuted.id).first()

        # 1) Tamamlanmamış geçmiş adım PENDING kalmalı, actual_start ve actual_end uydurulmamalı
        self.assertEqual(
            step_unexec_after.status,
            StepStatus.PENDING,
            "Planlanan tarihi geçmiş ama tamamlanmamış adım recompute sonrasında COMPLETED yapılmamalı",
        )
        self.assertIsNone(step_unexec_after.actual_start, "Bilinmeyen actual_start için planned_start kopyalanmamalı")
        self.assertIsNone(step_unexec_after.actual_end, "Bilinmeyen actual_end için planned_end kopyalanmamalı")

        # 2) İlgili çakışma açık kalmalı
        open_confs = (
            self.db.query(Conflict)
            .filter(Conflict.study_id == s_past.id, Conflict.is_resolved == False)  # noqa: E712
            .all()
        )
        self.assertGreaterEqual(len(open_confs), 1, "Tamamlanmamış geçmiş adımın çakışması kapatılmamalı")

        # 3) Gerçekten tamamlanmış adımın COMPLETED durumu ve gerçek saatleri korunmalı
        self.assertEqual(step_done_after.status, StepStatus.COMPLETED)
        self.assertEqual(step_done_after.actual_start, real_start)
        self.assertEqual(step_done_after.actual_end, real_end)

        # 4) Tarihsel Excel içe aktarımında açıkça tamamlanmış kayıtlar desteklenmeye devam etmeli (sahte actual_start üretmeden)
        s_excel_done = Study(
            study_code="FIX4-EXCEL-DONE",
            title="Excel Completed Study",
            test_item_name="Excel Item",
            study_director_id=sd.id,
            status=StudyStatus.COMPLETED,
        )
        self.db.add(s_excel_done)
        self.db.commit()
        step_excel = StudyStep(
            study_id=s_excel_done.id,
            step_order=1,
            study_day=0,
            step_name="Excel Biten Adım",
            planned_start=datetime(2026, 8, 10, 9, 0),
            planned_end=datetime(2026, 8, 10, 11, 0),
            status=StepStatus.PENDING,
        )
        self.db.add(step_excel)
        self.db.commit()

        se.sync_historical_completion_and_conflicts(self.db, from_excel_import=True)
        self.db.expire_all()
        step_excel_after = self.db.query(StudyStep).filter(StudyStep.id == step_excel.id).first()
        self.assertEqual(step_excel_after.status, StepStatus.COMPLETED)
        self.assertIsNone(
            step_excel_after.actual_start,
            "Excel içe aktarımında dahi bilinmeyen actual_start için planned_start uydurulmamalı",
        )
        self.assertIsNone(
            step_excel_after.actual_end,
            "Excel içe aktarımında dahi bilinmeyen actual_end için planned_end uydurulmamalı",
        )

    # ------------------------------------------------------------------
    # 5. Kapasite kontrolündeki hataların sessizce yutulması
    # ------------------------------------------------------------------
    def test_5_capacity_check_exception_surfaces_error_and_blocks_clean_or_approval(self):
        sd = self.people["ezgi"]
        s_cap = Study(
            study_code="FIX5-CAP",
            title="Capacity Failure Study",
            test_item_name="Cap Item",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
        )
        self.db.add(s_cap)
        self.db.commit()

        monday = date(2026, 11, 2)
        with patch(
            "app.services.scheduling_engine.evaluate_capacity_conflicts",
            side_effect=RuntimeError("Simüle edilen kapasite servisi hatası"),
        ), patch(
            "app.services.scheduling_engine.build_capacity_report",
            side_effect=RuntimeError("Simüle edilen kapasite servisi hatası"),
        ):
            res_err = schedule_new_study(self.db, s_cap.id, monday)
            self.assertNotEqual(
                res_err["status"],
                "SCHEDULED_CLEAN",
                "Kapasite kontrolü hata verdiğinde plan SCHEDULED_CLEAN olamamalı",
            )
            self.assertFalse(
                res_err["can_approve"],
                "Kapasite doğrulanamadığında can_approve False olmalı",
            )
            self.assertIsNotNone(res_err["capacity_info"], "capacity_info None olarak sessizce dönmemeli")
            self.assertFalse(
                res_err["capacity_info"].get("verified", True),
                "capacity_info.verified False olmalı",
            )
            self.assertEqual(res_err["capacity_info"].get("status"), "ERROR")
            self.assertTrue(
                any(
                    c["severity"] == "CRITICAL" and "Kapasite Doğrulanamadı" in c["title"]
                    for c in res_err["conflicts"]
                ),
                "Kapasite doğrulama hatası CRITICAL bir çakışma/uyarı olarak görünür olmalı",
            )

            # Onay uç noktası (POST /approve) 409 ile reddetmeli
            app_err = self.client.post(f"/api/v1/planning/studies/{s_cap.id}/approve", headers=self.h_tfm)
            self.assertEqual(app_err.status_code, 409, "Kapasitesi doğrulanamamış plan onaylanamamalı (409)")

        # Kapasite servisi normale döndüğünde yeniden doğrulama hatayı temizlemeli ve doğru sonucu üretmeli
        revalidate_study_conflicts(self.db, s_cap)
        self.db.commit()
        detail_ok = self.client.get(f"/api/v1/planning/studies/{s_cap.id}/schedule", headers=self.h_tfm).json()
        self.assertEqual(detail_ok["status"], "SCHEDULED_CLEAN")
        self.assertTrue(detail_ok["can_approve"])
        self.assertTrue(detail_ok["capacity_info"]["verified"])
        self.assertEqual(detail_ok["capacity_info"]["status"], "OK")

        app_ok = self.client.post(f"/api/v1/planning/studies/{s_cap.id}/approve", headers=self.h_tfm)
        self.assertEqual(app_ok.status_code, 200, "Kapasite servisi düzelip doğrulandıktan sonra plan onaylanabilmeli")

    # ------------------------------------------------------------------
    # 6. Geçmiş demo ve Excel kayıtlarının temizlik kapsamı, devam eden
    #    çalışmaların korunması ve doğrulanmamış geçmiş istatistiği
    # ------------------------------------------------------------------
    def test_6_historical_cleanup_scope_ongoing_preservation_and_unverified_stats(self):
        sd = self.people["ezgi"]
        tech1 = self.people["invivo_1"]

        # (a) Canlı devam eden çalışma: geçmişte kalmış açık (tamamlanmamış) adımı ve gelecekteki adımı var
        sr_live = SampleRecord(
            study_code="FIX6-LIVE-ONGOING",
            glp_type="GLP",
            stored_status="ONGOING",
            planned_start=date(2026, 10, 12),
            experiment_start_date=date(2026, 10, 12),
            experiment_end_date=date(2026, 11, 20),
        )
        self.db.add(sr_live)
        st_live = Study(
            study_code="FIX6-LIVE-ONGOING",
            title="Live Ongoing Study",
            test_item_name="Live Item",
            study_director_id=sd.id,
            status=StudyStatus.IN_PROGRESS,
            acclimatization_start_date=date(2026, 10, 12),
            extraction_polar=True,
            extraction_non_polar=False,
        )
        self.db.add(st_live)
        self.db.commit()

        live_past_step = StudyStep(
            study_id=st_live.id,
            step_order=1,
            study_day=4,
            step_name="72 Saatlik Ekstraksiyon Kurulumu",
            step_type="Ekstraksiyon",
            planned_start=datetime(2026, 10, 16, 9, 0),
            planned_end=datetime(2026, 10, 16, 10, 30),
            is_biological_fixed_time=True,
            biological_tolerance_minutes=30,
            status=StepStatus.PENDING,
        )
        # Teknisyen atanmamış -> açık çakışma üretmeli ve korunmalı
        self.db.add(live_past_step)

        live_future_step = StudyStep(
            study_id=st_live.id,
            step_order=2,
            study_day=14,
            step_name="14. Gün Gözlem",
            planned_start=datetime(2026, 11, 18, 10, 0),
            planned_end=datetime(2026, 11, 18, 11, 0),
            status=StepStatus.PENDING,
        )
        live_future_step.assignees = [tech1]
        self.db.add(live_future_step)
        self.db.commit()
        revalidate_study_conflicts(self.db, st_live)
        self.db.commit()

        # (b) Excel'den içe aktarılmış devam eden (ONGOING) geçmiş çalışma:
        #     Excel'de adım detayı bilinmediği için < 2026-11-03 adımı aktif çakışmadan hariç tutulmalı
        #     AMA otomatik COMPLETED yapılmamalı ve gelecekteki adımı korunmalı!
        sr_hist_ongoing = SampleRecord(
            study_code="FIX6-EXCEL-ONGOING",
            glp_type="GLP",
            stored_status="ONGOING",
            planned_start=date(2026, 9, 7),
            experiment_start_date=date(2026, 9, 7),
            experiment_end_date=date(2026, 11, 25),
        )
        self.db.add(sr_hist_ongoing)
        st_hist_ongoing = Study(
            study_code="FIX6-EXCEL-ONGOING",
            title="Excel Ongoing Study",
            test_item_name="Excel Ongoing Item",
            study_director_id=sd.id,
            status=StudyStatus.IN_PROGRESS,
            acclimatization_start_date=date(2026, 9, 7),
            dossier_metadata={"historical_excel_import": True},
            extraction_polar=True,
            extraction_non_polar=False,
        )
        self.db.add(st_hist_ongoing)
        self.db.commit()

        hist_past_step = StudyStep(
            study_id=st_hist_ongoing.id,
            step_order=1,
            study_day=4,
            step_name="72 Saatlik Ekstraksiyon Kurulumu",
            step_type="Ekstraksiyon",
            planned_start=datetime(2026, 9, 11, 9, 0),
            planned_end=datetime(2026, 9, 11, 10, 30),
            is_biological_fixed_time=True,
            biological_tolerance_minutes=30,
            status=StepStatus.PENDING,
        )
        self.db.add(hist_past_step)

        hist_future_step = StudyStep(
            study_id=st_hist_ongoing.id,
            step_order=2,
            study_day=60,
            step_name="Gelecek Gözlem Adımı",
            planned_start=datetime(2026, 11, 20, 10, 0),
            planned_end=datetime(2026, 11, 20, 11, 0),
            status=StepStatus.PENDING,
        )
        hist_future_step.assignees = [tech1]
        self.db.add(hist_future_step)
        self.db.commit()

        # (c) Excel'de açıkça COMPLETED (Biten) olan çalışma
        sr_hist_done = SampleRecord(
            study_code="FIX6-EXCEL-DONE",
            glp_type="GLP",
            stored_status="COMPLETED",
            planned_start=date(2026, 8, 3),
            experiment_start_date=date(2026, 8, 3),
            experiment_end_date=date(2026, 8, 13),
        )
        self.db.add(sr_hist_done)
        st_hist_done = Study(
            study_code="FIX6-EXCEL-DONE",
            title="Excel Completed Study",
            test_item_name="Excel Completed Item",
            study_director_id=sd.id,
            status=StudyStatus.COMPLETED,
            dossier_metadata={"historical_excel_import": True},
        )
        self.db.add(st_hist_done)
        self.db.commit()

        hist_done_step = StudyStep(
            study_id=st_hist_done.id,
            step_order=1,
            study_day=0,
            step_name="Biten Çalışma Adımı",
            planned_start=datetime(2026, 8, 3, 9, 0),
            planned_end=datetime(2026, 8, 3, 11, 0),
            status=StepStatus.PENDING,
        )
        self.db.add(hist_done_step)
        self.db.commit()

        # Excel içe aktarım senkronizasyonu (yalnızca Excel kapsamındaki çalışmaları hedeflemeli)
        try:
            sync1 = se.sync_historical_completion_and_conflicts(
                self.db,
                from_excel_import=True,
                target_study_codes={"FIX6-EXCEL-ONGOING", "FIX6-EXCEL-DONE"},
            )
        except TypeError:
            sync1 = se.sync_historical_completion_and_conflicts(self.db, from_excel_import=True)
        self.db.commit()
        self.db.expire_all()

        # 1) Canlı devam eden çalışmanın geçmiş açık görevi COMPLETED yapılmamalı ve çakışması açık kalmalı
        live_past_after = self.db.query(StudyStep).filter(StudyStep.id == live_past_step.id).first()
        live_future_after = self.db.query(StudyStep).filter(StudyStep.id == live_future_step.id).first()
        self.assertEqual(live_past_after.status, StepStatus.PENDING)
        self.assertEqual(live_future_after.status, StepStatus.PENDING)
        self.assertIsNone(live_past_after.actual_start)
        self.assertIsNone(live_past_after.actual_end)
        live_open_confs = (
            self.db.query(Conflict)
            .filter(Conflict.study_id == st_live.id, Conflict.is_resolved == False)  # noqa: E712
            .all()
        )
        self.assertGreaterEqual(len(live_open_confs), 1, "Canlı çalışmanın geçmiş açık görevinin çakışması korunmalı")

        # 2) Excel ONGOING çalışmasının geçmiş adımı COMPLETED yapılmamalı, gelecekteki adımı korunmalı,
        #    ancak geçmiş belirsiz adımı aktif çakışmalardan hariç tutulmalı
        hist_past_after = self.db.query(StudyStep).filter(StudyStep.id == hist_past_step.id).first()
        hist_future_after = self.db.query(StudyStep).filter(StudyStep.id == hist_future_step.id).first()
        self.assertEqual(
            hist_past_after.status,
            StepStatus.PENDING,
            "Tamamlanmamış (ONGOING) Excel çalışmasının geçmiş tarihli adımı otomatik COMPLETED yapılmamalı",
        )
        self.assertEqual(hist_future_after.status, StepStatus.PENDING, "Gelecekteki görev korunmalı")
        self.assertIsNone(hist_past_after.actual_start)
        self.assertIsNone(hist_past_after.actual_end)
        revalidate_study_conflicts(self.db, st_hist_ongoing)
        self.db.commit()
        hist_ongoing_confs = (
            self.db.query(Conflict)
            .filter(
                Conflict.study_id == st_hist_ongoing.id,
                Conflict.step_id == hist_past_step.id,
                Conflict.is_resolved == False,  # noqa: E712
            )
            .all()
        )
        self.assertEqual(
            len(hist_ongoing_confs),
            0,
            "Ayrıntısı bilinmeyen geçmiş Excel/demo adımı aktif çakışma hesabından hariç tutulmalı",
        )

        # 3) Excel'de açıkça COMPLETED olan çalışmanın adımı COMPLETED olmalı ama actual_start/end uydurulmamalı
        hist_done_after = self.db.query(StudyStep).filter(StudyStep.id == hist_done_step.id).first()
        self.assertEqual(hist_done_after.status, StepStatus.COMPLETED)
        self.assertIsNone(hist_done_after.actual_start)
        self.assertIsNone(hist_done_after.actual_end)

        # 4) Geçmiş/doğrulanmamış kayıtların aktif çakışmadan çıkarılması doğrulanmış completed_tasks istatistiğine eklenmemeli
        sum_resp = self.client.get("/api/v1/planning/summary", headers=self.h_tfm).json()
        self.assertEqual(
            sum_resp["completed_tasks"],
            0,
            "Doğrulanmış gerçekleşme saati olmayan geçmiş/hariç tutulan kayıtlar completed_tasks istatistiğine eklenmemeli",
        )
        self.assertGreaterEqual(sum_resp.get("historical_excluded_tasks", 0), 1)
        self.assertGreaterEqual(sum_resp.get("historical_completed_tasks", 0), 1)

        # 5) Aynı Excel tekrar içe aktarıldığında sahte yeni tamamlamalar oluşmamalı
        sync2 = se.sync_historical_completion_and_conflicts(
            self.db,
            from_excel_import=True,
            target_study_codes={"FIX6-EXCEL-ONGOING", "FIX6-EXCEL-DONE"},
        )
        self.assertEqual(sync2["newly_completed_steps"], 0, "Tekrar içe aktarımda sahte yeni tamamlama oluşmamalı")

    # ------------------------------------------------------------------
    # 7. Kaynak adımın ve bağımlı gözlemin toleranslarının ayrılması
    # ------------------------------------------------------------------
    def test_7_source_step_and_dependent_observation_tolerances_separated(self):
        sd = self.people["ezgi"]
        s_tol = Study(
            study_code="FIX7-TOL",
            title="Tolerance Separation Study",
            test_item_name="Tol Item",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
            extraction_polar=True,
            extraction_non_polar=False,
        )
        self.db.add(s_tol)
        self.db.commit()
        schedule_new_study(self.db, s_tol.id, date(2026, 12, 7))
        s_tol.status = StudyStatus.IN_PROGRESS
        self.db.commit()

        steps = (
            self.db.query(StudyStep)
            .filter(StudyStep.study_id == s_tol.id)
            .order_by(StudyStep.step_order.asc())
            .all()
        )
        day7 = next(s for s in steps if s.study_day == 7)
        day8 = next(s for s in steps if s.study_day == 8)
        day9 = next(s for s in steps if s.study_day == 9)
        day10 = next(s for s in steps if s.study_day == 10)

        # Senaryo A: Kaynak toleransı ±15 dk, bağımlı gözlem toleransı ±120 dk, referans gecikmesi +30 dk
        day7.biological_tolerance_minutes = 15
        day8.biological_tolerance_minutes = 120
        day9.biological_tolerance_minutes = 120
        day10.biological_tolerance_minutes = 120
        self.db.commit()
        planned_ref_dt = datetime.combine(day7.planned_start.date(), time(10, 0))

        # Tam sınır içi / sınır değeri kontrolü (+15 dk: kaynak toleransı sınırında)
        day7.actual_reference_time = planned_ref_dt + timedelta(minutes=15)
        self.db.commit()
        bio_at_boundary = se.compute_biological_dependency_info(s_tol, steps)
        d7_info_bound = bio_at_boundary["by_step_id"][day7.id]
        self.assertFalse(d7_info_bound["exceeds_tolerance"], "+15 dk gecikme ±15 dk kaynak toleransı sınırında (aşım değil)")
        self.assertTrue(all(not d["exceeds_tolerance"] for d in bio_at_boundary["revision_proposals"]))

        # +30 dk gecikme: kaynak toleransını (±15 dk) aşar, ancak gözlem toleransını (±120 dk) AŞMAZ
        day7.actual_reference_time = planned_ref_dt + timedelta(minutes=30)
        self.db.commit()
        bio_30 = se.compute_biological_dependency_info(s_tol, steps)
        d7_info_30 = bio_30["by_step_id"][day7.id]
        self.assertTrue(d7_info_30["exceeds_tolerance"], "+30 dk gecikme ±15 dk kaynak toleransını aşmalı")
        for d in bio_30["revision_proposals"]:
            self.assertEqual(d["tolerance_minutes"], 120, "Bağımlı gözlem kendi ±120 dk toleransını raporlamalı")
            self.assertFalse(
                d["exceeds_tolerance"],
                "Kaynak adım toleransı (±15 dk) aşıldı diye ±120 dk toleranslı bağımlı gözlem tolerans aşımı sayılmamalı",
            )
            self.assertTrue(
                d["requires_revision"],
                "Beklenen pencere planlanan pencereden kaydığı için revizyon önerisi yine üretilmeli",
            )

        # Senaryo B: Kaynak toleransı ±60 dk, bağımlı gözlem toleransı ±15 dk, referans gecikmesi +30 dk
        day7.biological_tolerance_minutes = 60
        day8.biological_tolerance_minutes = 15
        self.db.commit()
        bio_rev = se.compute_biological_dependency_info(s_tol, steps)
        self.assertFalse(bio_rev["by_step_id"][day7.id]["exceeds_tolerance"], "+30 dk gecikme ±60 dk kaynak toleransı içinde")
        dep24 = bio_rev["by_step_id"][day8.id]
        self.assertTrue(
            dep24["exceeds_tolerance"],
            "Bağımlı adımın kendi ±15 dk toleransı kaynak adımın ±60 dk toleransından bağımsız değerlendirilmeli (+30 dk > ±15 dk)",
        )

    # ------------------------------------------------------------------
    # 8. Gözlemin gerçek yapılma zamanının (actual_reference_time) denetlenmesi
    # ------------------------------------------------------------------
    def test_8_dependent_observation_actual_reference_time_verification(self):
        sd = self.people["ezgi"]
        s_obs = Study(
            study_code="FIX8-OBS",
            title="Observation Actual Time Verification",
            test_item_name="Obs Item",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
            extraction_polar=True,
            extraction_non_polar=False,
        )
        self.db.add(s_obs)
        self.db.commit()
        schedule_new_study(self.db, s_obs.id, date(2026, 12, 7))
        s_obs.status = StudyStatus.IN_PROGRESS
        self.db.commit()

        steps = (
            self.db.query(StudyStep)
            .filter(StudyStep.study_id == s_obs.id)
            .order_by(StudyStep.step_order.asc())
            .all()
        )
        day7 = next(s for s in steps if s.study_day == 7)   # 2026-12-14 10:00
        day8 = next(s for s in steps if s.study_day == 8)   # 2026-12-15 10:00 (+24s, ±120 dk)
        day9 = next(s for s in steps if s.study_day == 9)   # 2026-12-16 10:00 (+48s, ±120 dk)

        # (a) Referans zamanında (10:00), ancak 24. saat gözlemi gerçekte 12:30'da (+150 dk > ±120 dk) yapıldı
        resp_ref = self.client.patch(
            f"/api/v1/planning/steps/{day7.id}/status",
            headers=self.h_tfm,
            json={
                "status": "COMPLETED",
                "actual_start": "2026-12-14T09:50:00",
                "actual_reference_time": "2026-12-14T10:00:00",
                "actual_end": "2026-12-14T11:30:00",
            },
        )
        self.assertEqual(resp_ref.status_code, 200)

        resp_obs_late = self.client.patch(
            f"/api/v1/planning/steps/{day8.id}/status",
            headers=self.h_tfm,
            json={
                "status": "COMPLETED",
                "actual_start": "2026-12-15T12:15:00",
                "actual_reference_time": "2026-12-15T12:30:00",
                "actual_end": "2026-12-15T13:00:00",
            },
        )
        self.assertEqual(resp_obs_late.status_code, 200)
        open_confs_a = (
            self.db.query(Conflict)
            .filter(Conflict.study_id == s_obs.id, Conflict.step_id == day8.id, Conflict.is_resolved == False)  # noqa: E712
            .all()
        )
        self.assertTrue(
            any(
                c.conflict_type == ConflictType.BIOLOGICAL_TIME_VIOLATION
                and "Gerçekleşen Gözlem Biyolojik Pencere İhlali" in (c.title or "")
                for c in open_confs_a
            ),
            "Referans zamanında olsa bile 24s gözlemi gerçekte tolerans dışında (12:30, +150 dk > ±120 dk) yapıldığında BIOLOGICAL_TIME_VIOLATION yakalanmalı",
        )

        # (b) Referans gecikmeli (13:00), gözlem yeni beklenen zamanda (13:05, beklenen 13:00'e göre +5 dk <= ±30 dk) yapıldı:
        #     Gözlem için sahte uygulama/gerçekleşme ihlali üretilmemeli; kaynak sapması korunmalı!
        self.client.patch(
            f"/api/v1/planning/steps/{day7.id}/status",
            headers=self.h_tfm,
            json={
                "status": "COMPLETED",
                "actual_start": "2026-12-14T12:45:00",
                "actual_reference_time": "2026-12-14T13:00:00",
                "actual_end": "2026-12-14T14:00:00",
            },
        )
        resp_obs_ontime_shifted = self.client.patch(
            f"/api/v1/planning/steps/{day8.id}/status",
            headers=self.h_tfm,
            json={
                "status": "COMPLETED",
                "actual_start": "2026-12-15T12:55:00",
                "actual_reference_time": "2026-12-15T13:05:00",
                "actual_end": "2026-12-15T13:35:00",
            },
        )
        self.assertEqual(resp_obs_ontime_shifted.status_code, 200)
        open_confs_day8_b = (
            self.db.query(Conflict)
            .filter(Conflict.study_id == s_obs.id, Conflict.step_id == day8.id, Conflict.is_resolved == False)  # noqa: E712
            .all()
        )
        self.assertFalse(
            any("Gerçekleşen Gözlem Biyolojik Pencere İhlali" in (c.title or "") for c in open_confs_day8_b),
            "Referans geciktiğinde gözlem yeni beklenen pencerede (13:05) zamanında yapıldıysa gözlem gerçekleşme ihlali üretilmemeli",
        )
        open_confs_day7_b = (
            self.db.query(Conflict)
            .filter(Conflict.study_id == s_obs.id, Conflict.step_id == day7.id, Conflict.is_resolved == False)  # noqa: E712
            .all()
        )
        self.assertTrue(
            any("Biyolojik Referans Saat Sapması" in (c.title or "") for c in open_confs_day7_b),
            "Kaynak adımın kendi referans sapması korunmalı",
        )

        # (c) Bağımlı gözlem adımı (Gün 9, +48s) COMPLETED yapılıp actual_reference_time girilmezse:
        #     actual_start kopyalanmamalı ve 'Eksik Biyolojik Gözlem Saati' uyarısı üretilmeli
        resp_obs_missing = self.client.patch(
            f"/api/v1/planning/steps/{day9.id}/status",
            headers=self.h_tfm,
            json={
                "status": "COMPLETED",
                "actual_start": "2026-12-16T12:50:00",
                "actual_end": "2026-12-16T13:20:00",
            },
        )
        self.assertEqual(resp_obs_missing.status_code, 200)
        self.db.expire_all()
        day9_after = self.db.query(StudyStep).filter(StudyStep.id == day9.id).first()
        self.assertIsNone(
            day9_after.actual_reference_time,
            "Bağımlı gözlem adımında actual_reference_time girilmediğinde actual_start kopyalanmamalı",
        )
        open_confs_day9 = (
            self.db.query(Conflict)
            .filter(Conflict.study_id == s_obs.id, Conflict.step_id == day9.id, Conflict.is_resolved == False)  # noqa: E712
            .all()
        )
        self.assertTrue(
            any("Eksik Biyolojik Gözlem Saati" in (c.title or "") for c in open_confs_day9),
            "Tamamlanan bağımlı gözlemde gerçek gözlem saati eksikse açıkça uyarı üretilmeli",
        )

    # ------------------------------------------------------------------
    # 9. Beklenen biyolojik pencerelerin çalışmalar arasında ve çalışma
    #    içinde sıra bağımsız tutarlı değerlendirilmesi
    # ------------------------------------------------------------------
    def test_9_cross_study_and_intra_study_expected_biological_window_consistency(self):
        sd = self.people["ezgi"]
        tech1 = self.people["invivo_1"]
        self.people["invivo_2"].is_active = False
        self.db.commit()

        # Çalışma B önce oluşturulsun (daha küçük Study.id!) -> 2026-12-15 13:00-13:45 arasında tech1 görevli
        s_b = Study(
            study_code="FIX9-STUDY-B",
            title="Study B Fixed 13:00",
            test_item_name="Item B",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
            extraction_polar=True,
            extraction_non_polar=False,
        )
        self.db.add(s_b)
        self.db.commit()
        step_b = StudyStep(
            study_id=s_b.id,
            step_order=1,
            study_day=1,
            step_name="Study B 13:00 Görevi",
            planned_start=datetime(2026, 12, 15, 13, 0),
            planned_end=datetime(2026, 12, 15, 13, 45),
            status=StepStatus.PENDING,
        )
        step_b.assignees = [tech1]
        self.db.add(step_b)
        self.db.commit()

        # Çalışma A sonra oluşturulsun (daha büyük Study.id) -> Gün 8 (2026-12-15) gözlemi planlanan 10:00,
        # ama Gün 7 uygulaması 13:00'te gerçekleştiği için beklenen gözlem penceresi 13:00-13:45'e kayıyor!
        s_a = Study(
            study_code="FIX9-STUDY-A",
            title="Study A Shifted to 13:00",
            test_item_name="Item A",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
            extraction_polar=True,
            extraction_non_polar=False,
        )
        self.db.add(s_a)
        self.db.commit()
        schedule_new_study(self.db, s_a.id, date(2026, 12, 7))
        s_a.status = StudyStatus.IN_PROGRESS
        self.db.commit()

        day7_a = (
            self.db.query(StudyStep)
            .filter(StudyStep.study_id == s_a.id, StudyStep.study_day == 7)
            .first()
        )
        self.client.patch(
            f"/api/v1/planning/steps/{day7_a.id}/status",
            headers=self.h_tfm,
            json={
                "status": "COMPLETED",
                "actual_start": "2026-12-14T12:50:00",
                "actual_reference_time": "2026-12-14T13:00:00",
                "actual_end": "2026-12-14T14:00:00",
            },
        )
        self.db.expire_all()

        # 1) Çalışma A doğrulandığında B ile 13:00'teki personel çakışmasını görmeli
        revalidate_study_conflicts(self.db, s_a)
        self.db.commit()
        confs_a = (
            self.db.query(Conflict)
            .filter(
                Conflict.study_id == s_a.id,
                Conflict.conflict_type == ConflictType.PERSONNEL_OVERLAP,
                Conflict.is_resolved == False,  # noqa: E712
            )
            .all()
        )
        self.assertGreaterEqual(len(confs_a), 1, "Çalışma A doğrulandığında B ile 13:00'teki beklenen pencere çakışması yakalanmalı")

        # 2) Çalışma B doğrulandığında da A'nın 13:00'e kaymış beklenen penceresiyle çakışma yakalanmalı!
        revalidate_study_conflicts(self.db, s_b)
        self.db.commit()
        confs_b = (
            self.db.query(Conflict)
            .filter(
                Conflict.study_id == s_b.id,
                Conflict.conflict_type == ConflictType.PERSONNEL_OVERLAP,
                Conflict.is_resolved == False,  # noqa: E712
            )
            .all()
        )
        self.assertGreaterEqual(
            len(confs_b),
            1,
            "Çalışma B doğrulandığında A'nın beklenen biyolojik penceresi (13:00) dikkate alınarak çakışma yakalanmalı",
        )

        # 3) Çalışma B için onay uç noktası (POST /approve) bu beklenen pencere çakışması yüzünden 409 dönmeli
        app_b = self.client.post(f"/api/v1/planning/studies/{s_b.id}/approve", headers=self.h_tfm)
        self.assertEqual(app_b.status_code, 409, "Beklenen biyolojik pencere çakışması olan Çalışma B onaylanamamalı (409)")

        # 4) recompute_all_conflicts çalışma ID sırasından bağımsız olarak her iki çalışmada da çakışmayı görmeli
        recompute_all_conflicts(self.db)
        open_all = (
            self.db.query(Conflict)
            .filter(
                Conflict.study_id.in_([s_a.id, s_b.id]),
                Conflict.conflict_type == ConflictType.PERSONNEL_OVERLAP,
                Conflict.is_resolved == False,  # noqa: E712
            )
            .all()
        )
        self.assertTrue(
            any(c.study_id == s_b.id for c in open_all) and any(c.study_id == s_a.id for c in open_all),
            "recompute_all_conflicts çalışma oluşturma sırasından bağımsız olarak her iki çalışmada da çakışmayı üretmeli",
        )

        # 5) Çalışma içi (intra-study) çakışma: Çalışma A içinde aynı gün 13:00-13:45'e ek bir adım konulursa
        #    kaymış beklenen gözlem penceresinin aynı çalışmadaki diğer adımla çakışması da yakalanmalı
        step_b.status = StepStatus.CANCELLED
        self.db.commit()
        intra_step = StudyStep(
            study_id=s_a.id,
            step_order=99,
            study_day=8,
            step_name="Aynı Çalışma İçi 13:00 Ek Görev",
            planned_start=datetime(2026, 12, 15, 13, 0),
            planned_end=datetime(2026, 12, 15, 13, 45),
            status=StepStatus.PENDING,
        )
        intra_step.assignees = [tech1]
        self.db.add(intra_step)
        self.db.commit()
        revalidate_study_conflicts(self.db, s_a)
        self.db.commit()
        intra_confs = (
            self.db.query(Conflict)
            .filter(
                Conflict.study_id == s_a.id,
                Conflict.conflict_type == ConflictType.PERSONNEL_OVERLAP,
                Conflict.is_resolved == False,  # noqa: E712
            )
            .all()
        )
        self.assertGreaterEqual(
            len(intra_confs),
            1,
            "Kaymış beklenen gözlem penceresinin aynı çalışma içindeki başka bir adımla personel çakışması da yakalanmalı",
        )

    # ------------------------------------------------------------------
    # 10. Zaman girdilerinin anlamı (timezone normalizasyonu) ve 422 doğrulaması
    # ------------------------------------------------------------------
    def test_10_datetime_timezone_normalization_and_validation_422(self):
        sd = self.people["ezgi"]
        s_dt = Study(
            study_code="FIX10-DT",
            title="Datetime Validation Study",
            test_item_name="DT Item",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
            extraction_polar=True,
            extraction_non_polar=False,
        )
        self.db.add(s_dt)
        self.db.commit()
        schedule_new_study(self.db, s_dt.id, date(2026, 12, 7))
        s_dt.status = StudyStatus.IN_PROGRESS
        self.db.commit()

        day7 = (
            self.db.query(StudyStep)
            .filter(StudyStep.study_id == s_dt.id, StudyStep.study_day == 7)
            .first()
        )
        # day7.planned_start = 2026-12-14 10:00:00 (Tesis yerel saati: Europe/Istanbul UTC+03:00)

        # 1) "2026-12-14T07:00:00Z", "2026-12-14T07:00:00+00:00", "2026-12-14T10:00:00+03:00" ve
        #    yerel "2026-12-14T10:00:00" girdilerinin hepsi yerel 10:00:00 anını temsil etmeli (sapma = 0 dk, 500 hatası yok!)
        for iso_val in (
            "2026-12-14T07:00:00Z",
            "2026-12-14T07:00:00+00:00",
            "2026-12-14T10:00:00+03:00",
            "2026-12-14T10:00:00",
        ):
            r = self.client.patch(
                f"/api/v1/planning/steps/{day7.id}/status",
                headers=self.h_tfm,
                json={
                    "status": "COMPLETED",
                    "actual_start": "2026-12-14T09:30:00+03:00",
                    "actual_reference_time": iso_val,
                    "actual_end": "2026-12-14T11:30:00+03:00",
                },
            )
            self.assertEqual(r.status_code, 200, f"Geçerli zaman girdisi ({iso_val}) 200 dönmeli (500 değil): {r.text}")
            data = r.json()
            self.assertEqual(
                data["actual_reference_time"],
                "2026-12-14T10:00:00",
                f"{iso_val} tesis yerel saatine (2026-12-14T10:00:00) normalize edilmeli",
            )
            self.assertEqual(data["deviation_minutes"], 0, f"{iso_val} için sapma 0 dk olmalı")

        # 2) Bozuk tarih formatı -> 422
        r_bad_fmt = self.client.patch(
            f"/api/v1/planning/steps/{day7.id}/status",
            headers=self.h_tfm,
            json={"actual_start": "gecersiz-tarih-formati"},
        )
        self.assertEqual(r_bad_fmt.status_code, 422, "Geçersiz tarih formatı 422 dönmeli")

        # 3) actual_end < actual_start -> 422
        r_end_before_start = self.client.patch(
            f"/api/v1/planning/steps/{day7.id}/status",
            headers=self.h_tfm,
            json={
                "status": "COMPLETED",
                "actual_start": "2026-12-14T11:00:00",
                "actual_end": "2026-12-14T10:00:00",
            },
        )
        self.assertEqual(r_end_before_start.status_code, 422, "actual_end < actual_start 422 dönmeli")

        # 4) actual_reference_time [actual_start, actual_end] aralığı dışında -> 422
        r_ref_outside = self.client.patch(
            f"/api/v1/planning/steps/{day7.id}/status",
            headers=self.h_tfm,
            json={
                "status": "COMPLETED",
                "actual_start": "2026-12-14T10:00:00",
                "actual_reference_time": "2026-12-14T12:30:00",
                "actual_end": "2026-12-14T11:30:00",
            },
        )
        self.assertEqual(
            r_ref_outside.status_code,
            422,
            "actual_reference_time [actual_start, actual_end] aralığı dışındaysa 422 dönmeli",
        )

        # 5) Durum ve zaman alanları arasında tutarsızlık (PENDING iken actual_end gönderilmesi) -> 422
        r_inconsistent_status = self.client.patch(
            f"/api/v1/planning/steps/{day7.id}/status",
            headers=self.h_tfm,
            json={
                "status": "PENDING",
                "actual_end": "2026-12-14T11:30:00",
            },
        )
        self.assertEqual(
            r_inconsistent_status.status_code,
            422,
            "PENDING durumundaki adıma actual_end girilmesi tutarsız olduğu için 422 dönmeli",
        )

    # ------------------------------------------------------------------
    # 11. Referans saati girişinin görev akışı API sözleşmesi
    # ------------------------------------------------------------------
    def test_11_reference_time_api_contract_for_task_workflow(self):
        sd = self.people["ezgi"]
        s_ui = Study(
            study_code="FIX11-UI",
            title="Task Workflow Reference Time Study",
            test_item_name="UI Item",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
            extraction_polar=True,
            extraction_non_polar=False,
        )
        self.db.add(s_ui)
        self.db.commit()
        schedule_new_study(self.db, s_ui.id, date(2026, 12, 7))
        s_ui.status = StudyStatus.IN_PROGRESS
        self.db.commit()

        steps_resp = self.client.get(
            f"/api/v1/planning/steps?study_id={s_ui.id}&include_all=true&active_only=false",
            headers=self.h_tfm,
        )
        self.assertEqual(steps_resp.status_code, 200)
        steps_list = steps_resp.json()
        d7 = next(s for s in steps_list if s["study_day"] == 7)
        d8 = next(s for s in steps_list if s["study_day"] == 8)
        d0 = next(s for s in steps_list if s["study_day"] == 0)

        self.assertTrue(d7.get("requires_reference_time"), "Kaynak biyolojik adım requires_reference_time=True dönmeli")
        self.assertEqual(d7.get("reference_time_role"), "SOURCE")
        self.assertTrue(d8.get("requires_reference_time"), "Bağımlı gözlem adımı requires_reference_time=True dönmeli")
        self.assertEqual(d8.get("reference_time_role"), "DEPENDENT_OBSERVATION")
        self.assertFalse(d0.get("requires_reference_time"), "Esnek idari adım requires_reference_time=False dönmeli")

    # ------------------------------------------------------------------
    # 12. Ekstraksiyon kaynak tanımının 9 kombinasyonun tamamında tutarlılığı
    # ------------------------------------------------------------------
    def test_12_unknown_extraction_info_not_assumed_polar(self):
        wb = self.db.query(Equipment).filter(Equipment.code == "EQ-WB-001").first()
        wb.polar_capacity = 1
        wb.non_polar_capacity = 1
        self.db.commit()

        sd = self.people["ezgi"]
        monday = date(2026, 11, 2)

        # (A) 9 kombinasyonun tamamı: {True, False, None} x {True, False, None}
        expected_matrix = [
            (True, True, True, True, True, False, [], "POLAR_AND_APOLAR"),
            (True, False, True, False, True, False, [], "POLAR_ONLY"),
            (False, True, False, True, True, False, [], "APOLAR_ONLY"),
            (False, False, False, False, False, False, [], "NONE"),
            (True, None, True, False, True, True, ["apolar"], "PARTIAL_MISSING"),
            (False, None, False, False, False, True, ["apolar"], "PARTIAL_MISSING"),
            (None, True, False, True, True, True, ["polar"], "PARTIAL_MISSING"),
            (None, False, False, False, False, True, ["polar"], "PARTIAL_MISSING"),
            (None, None, False, False, False, True, ["polar", "apolar"], "MISSING"),
        ]
        for idx, (pol, apo, exp_u_pol, exp_u_apo, exp_wb, exp_miss, exp_comp, exp_status) in enumerate(expected_matrix, start=1):
            st_cand = Study(
                study_code=f"FIX12-MAT-{idx}",
                title=f"Matrix {pol}/{apo}",
                test_item_name="Polymer",
                study_director_id=sd.id,
                status=StudyStatus.DRAFT,
                extraction_polar=pol,
                extraction_non_polar=apo,
            )
            self.db.add(st_cand)
            self.db.commit()
            usage = se.get_study_extraction_usage(st_cand)
            self.assertEqual(usage["uses_polar"], exp_u_pol, f"({pol}, {apo}) uses_polar uyumsuz")
            self.assertEqual(usage["uses_apolar"], exp_u_apo, f"({pol}, {apo}) uses_apolar uyumsuz")
            self.assertEqual(usage["uses_water_bath"], exp_wb, f"({pol}, {apo}) uses_water_bath uyumsuz")
            self.assertEqual(usage["polar_known"], pol is not None, f"({pol}, {apo}) polar_known uyumsuz")
            self.assertEqual(usage["apolar_known"], apo is not None, f"({pol}, {apo}) apolar_known uyumsuz")
            self.assertEqual(usage["missing_extraction_info"], exp_miss, f"({pol}, {apo}) missing_extraction_info uyumsuz")
            self.assertEqual(usage["missing_components"], exp_comp, f"({pol}, {apo}) missing_components uyumsuz")
            self.assertEqual(usage["status"], exp_status, f"({pol}, {apo}) status uyumsuz")

            # Planlama motorunda cihaz atamasının aynı kaynak tanımını kullandığını doğrula
            sched_date = monday + timedelta(days=idx * 14)
            res_m = schedule_new_study(self.db, st_cand.id, sched_date)
            ext_step_m = (
                self.db.query(StudyStep)
                .filter(StudyStep.study_id == st_cand.id, StudyStep.study_day == 4)
                .first()
            )
            self.assertEqual(
                ext_step_m.equipment_id,
                wb.id if exp_wb else None,
                f"({pol}, {apo}) için ekstraksiyon adımı equipment_id ataması uses_water_bath ile aynı olmalı",
            )
            self.assertEqual(res_m.get("missing_extraction_info"), exp_miss)
            self.assertEqual(res_m.get("extraction_info_status"), exp_status)

        # (B) Aynı tarihte (monday) çakışma, rezervasyon ve alternatif tarih önerisi tutarlılığı
        s_unknown = Study(
            study_code="FIX12-UNKNOWN",
            title="Unknown Extraction Study",
            test_item_name="Unknown Polymer",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
            extraction_polar=None,
            extraction_non_polar=None,
        )
        s_apolar = Study(
            study_code="FIX12-APOLAR",
            title="Apolar Only Study",
            test_item_name="Apolar Polymer",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
            extraction_polar=False,
            extraction_non_polar=True,
        )
        s_polar = Study(
            study_code="FIX12-POLAR",
            title="Polar Study",
            test_item_name="Polar Polymer",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
            extraction_polar=True,
            extraction_non_polar=False,
        )
        self.db.add_all([s_unknown, s_apolar, s_polar])
        self.db.commit()

        res_unk = schedule_new_study(self.db, s_unknown.id, monday)
        res_apo = schedule_new_study(self.db, s_apolar.id, monday)
        res_pol = schedule_new_study(self.db, s_polar.id, monday)

        unk_ext_step = (
            self.db.query(StudyStep)
            .filter(StudyStep.study_id == s_unknown.id, StudyStep.study_day == 4)
            .first()
        )
        apo_ext_step = (
            self.db.query(StudyStep)
            .filter(StudyStep.study_id == s_apolar.id, StudyStep.study_day == 4)
            .first()
        )
        pol_ext_step = (
            self.db.query(StudyStep)
            .filter(StudyStep.study_id == s_polar.id, StudyStep.study_day == 4)
            .first()
        )
        self.assertIsNone(unk_ext_step.equipment_id, "None/None çalışmaya Su Banyosu atanmamalı")
        self.assertEqual(apo_ext_step.equipment_id, wb.id, "Apolar (False/True) çalışmaya Su Banyosu (EQ-WB-001) atanmalı")
        self.assertEqual(pol_ext_step.equipment_id, wb.id, "Polar (True/False) çalışmaya Su Banyosu (EQ-WB-001) atanmalı")

        # Polar=1 ve Apolar=1 kapasitede: 1 Polar (s_polar) + 1 Apolar (s_apolar) + 1 Bilinmeyen (s_unknown)
        # hiçbirinde Su Banyosu kapasite aşımı üretmemeli
        pol_wb_confs = [
            c for c in res_pol["conflicts"]
            if c["type"] == "EQUIPMENT_OVERLAP" and "Su Banyosu" in (c["title"] or "")
        ]
        self.assertEqual(len(pol_wb_confs), 0, "None/None çalışma polar kapasiteyi tüketmemeli")

        # İkinci bir Apolar (None/True -> apolar=True, polar=bilinmeyen) eklendiğinde:
        # Apolar kapasite (Max: 1) aşımı yakalanmalı ve alternatif tarih önerisi aynı kaynağı kullanmalı
        s_apolar_partial = Study(
            study_code="FIX12-APOLAR-PARTIAL",
            title="Partial Unknown Apolar Study",
            test_item_name="Apolar Partial",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
            extraction_polar=None,
            extraction_non_polar=True,
        )
        self.db.add(s_apolar_partial)
        self.db.commit()
        res_apo2 = schedule_new_study(self.db, s_apolar_partial.id, monday)
        self.assertTrue(res_apo2.get("missing_extraction_info"), "polar=None olduğu için kısmi eksik bilgi korunmalı")
        self.assertEqual(res_apo2.get("extraction_info_status"), "PARTIAL_MISSING")
        apo2_confs = [
            c for c in res_apo2["conflicts"]
            if c["type"] == "EQUIPMENT_OVERLAP" and "Apolar Kapasite Aşımı" in (c["title"] or "")
        ]
        self.assertEqual(len(apo2_confs), 1, "Apolar=True olan ikinci çalışma Apolar Kapasite Aşımı üretmeli")
        self.assertTrue(
            any(r["action"] == "SHIFT_TO_NEXT_AVAILABLE_EQUIPMENT_DATE" for r in apo2_confs[0].get("resolutions", [])),
            "Alternatif cihaz tarihi önerisi Apolar çakışmasında da üretilmeli",
        )

        # Eksik bilgi sonradan tamamlandığında (s_unknown -> extraction_polar=True, extraction_non_polar=False)
        # yeniden doğrulama hem cihaz atamasını güncellemeli hem de Polar Su Banyosu çakışmasını yakalamalı
        s_unknown.extraction_polar = True
        s_unknown.extraction_non_polar = False
        self.db.commit()
        revalidate_study_conflicts(self.db, s_unknown)
        self.db.commit()
        self.db.refresh(unk_ext_step)
        self.assertEqual(unk_ext_step.equipment_id, wb.id)
        unk_wb_confs = (
            self.db.query(Conflict)
            .filter(
                Conflict.study_id == s_unknown.id,
                Conflict.conflict_type == ConflictType.EQUIPMENT_OVERLAP,
                Conflict.is_resolved == False,  # noqa: E712
            )
            .all()
        )
        self.assertTrue(any("Polar Kapasite Aşımı" in (c.title or "") for c in unk_wb_confs))

    # ------------------------------------------------------------------
    # 13. MyTasks ekranında gerçekleşen veri üretilmemesi ve aksiyonların ayrımı
    # ------------------------------------------------------------------
    def test_13_mytasks_no_fabricated_actuals_and_separate_action_semantics(self):
        sd = self.people["ezgi"]
        tech = self.people["invivo_1"]
        s_mt = Study(
            study_code="FIX13-MYTASKS",
            title="MyTasks Non-Fabrication Study",
            test_item_name="Gel Sample",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
            extraction_polar=True,
            extraction_non_polar=False,
        )
        self.db.add(s_mt)
        self.db.commit()
        schedule_new_study(self.db, s_mt.id, date(2026, 12, 7))
        s_mt.status = StudyStatus.IN_PROGRESS
        self.db.commit()

        steps = (
            self.db.query(StudyStep)
            .filter(StudyStep.study_id == s_mt.id)
            .order_by(StudyStep.step_order.asc())
            .all()
        )
        day7 = next(s for s in steps if s.study_day == 7)  # Plan: 2026-12-14 09:00 - 12:00, Ref: 10:00
        day8 = next(s for s in steps if s.study_day == 8)  # Plan: 2026-12-15 10:00 - 10:45, Ref: 10:00
        day7.assignees = [tech]
        day8.assignees = [tech]
        self.db.commit()

        h_tech = self.h_tech1

        # 1) Yalnızca 10:45 referansı kaydedildiğinde:
        #    - 09:00 / 12:00 plan saatleri actual_start / actual_end alanlarına YAZILMAMALI
        #    - Görev kendiliğinden COMPLETED olmamalı (PENDING kalmalı)
        r_save_ref = self.client.patch(
            f"/api/v1/planning/steps/{day7.id}/status",
            headers=h_tech,
            json={"actual_reference_time": "2026-12-14T10:45:00"},
        )
        self.assertEqual(r_save_ref.status_code, 200, r_save_ref.text)
        d7_after_ref = r_save_ref.json()
        self.assertEqual(d7_after_ref["status"], "PENDING", "Referans kaydetmek bekleyen görevi otomatik COMPLETED yapmamalı")
        self.assertEqual(d7_after_ref["actual_reference_time"], "2026-12-14T10:45:00")
        self.assertIsNone(d7_after_ref["actual_start"], "Planlanan 09:00 veya 10:45 actual_start alanına yazılmamalı")
        self.assertIsNone(d7_after_ref["actual_end"], "Planlanan 12:00 veya 10:45 actual_end alanına yazılmamalı")

        # 2) 'Başlat' henüz gerçekleşmemiş planlanan referansı kaydetmemeli
        r_start = self.client.patch(
            f"/api/v1/planning/steps/{day8.id}/status",
            headers=h_tech,
            json={"status": "IN_PROGRESS"},
        )
        self.assertEqual(r_start.status_code, 200, r_start.text)
        d8_after_start = r_start.json()
        self.assertEqual(d8_after_start["status"], "IN_PROGRESS")
        self.assertIsNotNone(d8_after_start["actual_start"])
        self.assertIsNone(d8_after_start["actual_end"])
        self.assertIsNone(
            d8_after_start["actual_reference_time"],
            "Başlat aksiyonu henüz girilmemiş/planlanan referans saatini actual_reference_time olarak kaydetmemeli",
        )

        # 3) Girilmiş gerçek başlangıç/bitiş bilgileri referansı değiştirmek için sessizce genişletilmemeli (422 dönmeli)
        day7.status = StepStatus.COMPLETED
        day7.actual_start = datetime(2026, 12, 14, 9, 0)
        day7.actual_end = datetime(2026, 12, 14, 12, 0)
        self.db.commit()
        r_out_of_bounds = self.client.patch(
            f"/api/v1/planning/steps/{day7.id}/status",
            headers=h_tech,
            json={"actual_reference_time": "2026-12-14T12:30:00"},
        )
        self.assertEqual(
            r_out_of_bounds.status_code,
            422,
            "Mevcut actual_start/actual_end aralığı dışındaki referans saati sessizce genişletilmeyip 422 ile reddedilmeli",
        )
        self.db.expire_all()
        d7_db = self.db.query(StudyStep).filter(StudyStep.id == day7.id).first()
        self.assertEqual(d7_db.actual_start, datetime(2026, 12, 14, 9, 0))
        self.assertEqual(d7_db.actual_end, datetime(2026, 12, 14, 12, 0))

        # 4) MyTasks.jsx kaynak kodunda buildCompatibleBounds kaldırılmış ve başlangıç referans girişi boş olmalı
        mytasks_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src", "pages", "MyTasks.jsx")
        )
        with open(mytasks_path, "r", encoding="utf-8") as f:
            mytasks_src = f.read()
        self.assertNotIn("buildCompatibleBounds", mytasks_src, "buildCompatibleBounds tamamen kaldırılmış olmalı")

    # ------------------------------------------------------------------
    # 14. Demo temizliğinde çalışma kodundan tahmin ederek silmenin kaldırılması
    # ------------------------------------------------------------------
    def test_14_excel_import_preserves_non_excel_records_without_code_guessing(self):
        from app.services.sample_service import import_study_status_workbook, sync_faz_9_3_sample_fields

        sd = self.people["ezgi"]
        tech = self.people["invivo_1"]
        tfm_user = self.people["emine"]

        # Excel dosyasında OLMAYAN gerçek kayıtlar: GLP2026-090, GLP2026-151, GLP2027-151 ve T-REAL-001
        preserved_codes = ["GLP2026-090", "GLP2026-151", "GLP2027-151", "T-REAL-001"]
        step_ids_by_code = {}
        for idx, code in enumerate(preserved_codes, start=1):
            sr = SampleRecord(
                study_code=code,
                glp_type="GLP",
                stored_status="ONGOING",
                test_item_name=f"Real Test Item {code}",
                sponsor_name="Real Sponsor",
                planned_start=date(2026, 11, 10 + idx),
            )
            st = Study(
                study_code=code,
                title=f"Real Study {code}",
                test_item_name=f"Real Test Item {code}",
                study_director_id=sd.id,
                status=StudyStatus.IN_PROGRESS,
                acclimatization_start_date=date(2026, 11, 10 + idx),
            )
            self.db.add_all([sr, st])
            self.db.flush()
            st_step = StudyStep(
                study_id=st.id,
                step_order=1,
                study_day=0,
                step_name=f"Gerçek Adım {code}",
                planned_start=datetime(2026, 11, 10 + idx, 9, 0),
                planned_end=datetime(2026, 11, 10 + idx, 11, 0),
                status=StepStatus.IN_PROGRESS,
                actual_start=datetime(2026, 11, 10 + idx, 9, 5),
            )
            st_step.assignees = [tech]
            self.db.add(st_step)
            self.db.flush()
            step_ids_by_code[code] = st_step.id

        # Açıkça demo olarak işaretlenmiş bir kayıt (yalnızca bu silinebilir)
        sr_demo = SampleRecord(
            study_code="DEMO-EXPLICIT-001",
            glp_type="GLP",
            stored_status="PLANNED",
            workflow={"is_historical_demo": True},
        )
        st_demo = Study(
            study_code="DEMO-EXPLICIT-001",
            title="Explicit Demo Study",
            test_item_name="Demo",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
            dossier_metadata={"is_historical_demo": True},
        )
        self.db.add_all([sr_demo, st_demo])
        self.db.commit()

        xlsx_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "Study Status last version (2).xlsx")
        )
        with open(xlsx_path, "rb") as xf:
            xlsx_bytes = xf.read()

        import_study_status_workbook(self.db, xlsx_bytes, tfm_user, auto_schedule=False, prune_non_excel=True)
        sync_faz_9_3_sample_fields(self.db)
        self.db.expire_all()

        for code in preserved_codes:
            sr_after = self.db.query(SampleRecord).filter(SampleRecord.study_code == code).first()
            st_after = self.db.query(Study).filter(Study.study_code == code).first()
            step_after = self.db.query(StudyStep).filter(StudyStep.id == step_ids_by_code[code]).first()
            self.assertIsNotNone(sr_after, f"Excel'de olmayan gerçek SampleRecord ({code}) silinmemeli")
            self.assertIsNotNone(st_after, f"Excel'de olmayan gerçek Study ({code}) silinmemeli")
            self.assertIsNotNone(step_after, f"Excel'de olmayan gerçek çalışmanın adımı ({code}) silinmemeli")
            self.assertEqual(step_after.status, StepStatus.IN_PROGRESS)
            self.assertEqual([u.id for u in step_after.assignees], [tech.id])

        self.assertIsNotNone(
            self.db.query(Study).filter(Study.study_code == "DEMO-EXPLICIT-001").first(),
            "Excel güncellemesi dosyada olmayan demo kayıtlarını da silmemeli",
        )

    # ------------------------------------------------------------------
    # 15. Otomatik operasyon saatlerinin tesis yerel saat standardını kullanması
    # ------------------------------------------------------------------
    def test_15_auto_operational_timestamps_use_facility_local_time_standard(self):
        sd = self.people["ezgi"]
        s_tz = Study(
            study_code="FIX15-TZ",
            title="Facility Local Time Study",
            test_item_name="TZ Item",
            study_director_id=sd.id,
            status=StudyStatus.IN_PROGRESS,
        )
        self.db.add(s_tz)
        self.db.commit()
        step_tz = StudyStep(
            study_id=s_tz.id,
            step_order=1,
            study_day=0,
            step_name="Saat Standardı Test Adımı",
            planned_start=datetime(2026, 12, 14, 9, 0),
            planned_end=datetime(2026, 12, 14, 15, 0),
            status=StepStatus.PENDING,
        )
        self.db.add(step_tz)
        self.db.commit()

        # Türkiye saati 12:00:00 (UTC 09:00:00) olarak sabitlendiğinde 'Başlat' actual_start=12:00 üretmeli
        frozen_local_noon = datetime(2026, 12, 14, 12, 0, 0)
        with patch("app.api.v1.planning._facility_now", return_value=frozen_local_noon):
            r_start = self.client.patch(
                f"/api/v1/planning/steps/{step_tz.id}/status",
                headers=self.h_tfm,
                json={"status": "IN_PROGRESS"},
            )
            self.assertEqual(r_start.status_code, 200, r_start.text)
            self.assertEqual(
                r_start.json()["actual_start"],
                "2026-12-14T12:00:00",
                "Türkiye saati 12:00'ye sabitlendiğinde Başlat aksiyonu actual_start alanını 12:00 üretmeli (UTC 09:00 değil)",
            )

        # Açık Z (09:00Z) ve +03:00 (12:00+03:00) girişleri aynı yerel sonucu (12:00:00) vermeli
        r_z = self.client.patch(
            f"/api/v1/planning/steps/{step_tz.id}/status",
            headers=self.h_tfm,
            json={"actual_start": "2026-12-14T09:00:00Z"},
        )
        r_plus3 = self.client.patch(
            f"/api/v1/planning/steps/{step_tz.id}/status",
            headers=self.h_tfm,
            json={"actual_start": "2026-12-14T12:00:00+03:00"},
        )
        self.assertEqual(r_z.status_code, 200)
        self.assertEqual(r_plus3.status_code, 200)
        self.assertEqual(r_z.json()["actual_start"], "2026-12-14T12:00:00")
        self.assertEqual(r_plus3.json()["actual_start"], "2026-12-14T12:00:00")
        self.assertEqual(r_z.json()["actual_start"], r_plus3.json()["actual_start"])

    # ------------------------------------------------------------------
    # 16. Tarihsel Excel aktarımında ONGOING -> COMPLETED geçişi
    # ------------------------------------------------------------------
    def test_16_historical_excel_import_ongoing_to_completed_transition(self):
        import io
        from openpyxl import Workbook
        from app.services.sample_service import import_study_status_workbook

        tfm_user = self.people["emine"]

        def _make_workbook_bytes(status_label: str) -> bytes:
            wb = Workbook()
            ws = wb.active
            ws.title = "GLP Medikal"
            for _ in range(7):
                ws.append([])
            row = [None] * 27
            row[0] = 1
            row[1] = "İntrakütanöz Reaktivite Testi (ISO 10993-23)"
            row[2] = "Geçiş Test Ürünü"
            row[3] = "Ezgi Nur AKIN"
            row[4] = "ACME Medikal"
            row[5] = "ACME Medikal"
            row[6] = "veli@acme.com"
            row[7] = "GLP2026-082"
            row[8] = "İlknur TOKLU"
            row[9] = "TKL-2026-082"
            row[10] = date(2026, 9, 1)
            row[11] = date(2026, 9, 2)
            row[12] = "TI-2026-0082"
            row[13] = "Edirne"
            row[14] = 10
            row[15] = "Mevcut"
            row[16] = date(2026, 9, 4)
            row[17] = date(2026, 9, 7)
            row[18] = date(2026, 9, 7)
            row[19] = None
            row[20] = date(2026, 9, 20)
            row[21] = "Ödendi"
            row[22] = date(2026, 9, 24)
            row[24] = status_label
            ws.append(row)
            buf = io.BytesIO()
            wb.save(buf)
            return buf.getvalue()

        wb_ongoing = _make_workbook_bytes("Devam eden/On going")
        wb_completed = _make_workbook_bytes("Biten/Finished")

        # 1) İlk aktarım: ONGOING -> çalışma IN_PROGRESS, adımlar PENDING (newly_completed_steps == 0)
        res1 = import_study_status_workbook(self.db, wb_ongoing, tfm_user, auto_schedule=True, prune_non_excel=False)
        self.db.expire_all()
        st1 = self.db.query(Study).filter(Study.study_code == "GLP2026-082").first()
        steps1 = self.db.query(StudyStep).filter(StudyStep.study_id == st1.id).all()
        self.assertEqual(st1.status, StudyStatus.IN_PROGRESS)
        self.assertEqual(len(steps1), 0, "Devam eden çalışmaya Excel görev üretmemeli")
        self.assertEqual(res1["auto_scheduled"], 0)
        self.assertEqual(res1["newly_completed_steps"], 0)

        # Operasyonel görev Excel dışında oluşturuldu; sonraki aktarım bunu korumalı.
        preserved = StudyStep(study_id=st1.id, step_order=1, step_name="Mevcut görev",
                              planned_start=datetime(2026,11,2,9), planned_end=datetime(2026,11,2,10),
                              status=StepStatus.PENDING)
        self.db.add(preserved)
        self.db.commit()
        preserved_id = preserved.id
        # 2) Tekrar ONGOING aktarımı -> 0 değişiklik
        res2 = import_study_status_workbook(self.db, wb_ongoing, tfm_user, auto_schedule=True, prune_non_excel=False)
        self.db.expire_all()
        steps2 = self.db.query(StudyStep).filter(StudyStep.study_id == st1.id).all()
        self.assertEqual(res2["newly_completed_steps"], 0)
        self.assertTrue(all(s.status == StepStatus.PENDING for s in steps2))

        # 3) Excel COMPLETED kaynağı operasyonel çalışmayı veya mevcut görevi tamamlamaz
        res3 = import_study_status_workbook(self.db, wb_completed, tfm_user, auto_schedule=True, prune_non_excel=False)
        self.db.expire_all()
        st3 = self.db.query(Study).filter(Study.study_code == "GLP2026-082").first()
        steps3 = self.db.query(StudyStep).filter(StudyStep.study_id == st3.id).all()
        self.assertEqual(st3.status, StudyStatus.IN_PROGRESS, "Excel tamamlandı işareti operasyonel gerçekleşme değildir")
        self.assertEqual(res3["newly_completed_steps"], 0)
        self.assertGreater(res3["review_required"], 0)
        self.assertEqual([s.id for s in steps3], [preserved_id])
        self.assertTrue(all(s.status == StepStatus.PENDING for s in steps3))
        self.assertTrue(all(s.actual_start is None and s.actual_end is None for s in steps3))

        # 4) Tekrar COMPLETED aktarımı -> 0 yeni değişiklik
        res4 = import_study_status_workbook(self.db, wb_completed, tfm_user, auto_schedule=True, prune_non_excel=False)
        self.assertEqual(res4["newly_completed_steps"], 0)

    # ------------------------------------------------------------------
    # 17. MyTasks gerçek tarayıcı (Headless Chrome) uçtan uca doğrulama testi
    # ------------------------------------------------------------------
    def test_17_mytasks_headless_browser_e2e_verification(self):
        import json as _json
        import socket
        import subprocess
        import threading
        import time as _time
        import uvicorn

        chrome_candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ]
        chrome_bin = next((p for p in chrome_candidates if os.path.exists(p)), None)
        if not chrome_bin:
            self.skipTest("Headless Chrome/Edge bulunamadı")

        sd = self.people["ezgi"]
        tech = self.people["invivo_1"]
        s_e2e = Study(
            study_code="FIX17-E2E",
            title="Browser E2E MyTasks Study",
            test_item_name="E2E Gel",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
            extraction_polar=True,
            extraction_non_polar=False,
        )
        self.db.add(s_e2e)
        self.db.commit()
        schedule_new_study(self.db, s_e2e.id, date(2026, 12, 7))
        s_e2e.status = StudyStatus.IN_PROGRESS
        self.db.commit()

        steps = (
            self.db.query(StudyStep)
            .filter(StudyStep.study_id == s_e2e.id)
            .order_by(StudyStep.step_order.asc())
            .all()
        )
        day7 = next(s for s in steps if s.study_day == 7)  # 2026-12-14 09:00-12:00, Plan Ref: 10:00
        day8 = next(s for s in steps if s.study_day == 8)  # 2026-12-15 10:00-10:45, Plan Ref: 10:00
        day9 = next(s for s in steps if s.study_day == 9)  # 2026-12-16 10:00-10:45, Plan Ref: 10:00
        day7.assignees = [tech]
        day8.assignees = [tech]
        day9.assignees = [tech]
        self.db.commit()

        token = self.client.post(
            "/api/v1/auth/login",
            json={"username": "invivo_1", "password": DEFAULT_PASSWORD},
        ).json()["access_token"]
        user_info = self.client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        ).json()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            for _ in range(50):
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    _time.sleep(0.1)

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s2:
                s2.bind(("127.0.0.1", 0))
                cdp_port = s2.getsockname()[1]

            user_data_dir = os.path.join(_TMP_DIR, "chrome_profile")
            proc = subprocess.Popen(
                [
                    chrome_bin,
                    "--headless=new",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-default-browser-check",
                    f"--user-data-dir={user_data_dir}",
                    f"--remote-debugging-port={cdp_port}",
                    f"http://127.0.0.1:{port}/login",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                import urllib.request
                import fitz  # noqa: F401
                ws_url = None
                for _ in range(50):
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list", timeout=0.5) as resp:
                            tabs = _json.loads(resp.read().decode("utf-8"))
                            page_tab = next((t for t in tabs if t.get("type") == "page"), None)
                            if page_tab and page_tab.get("webSocketDebuggerUrl"):
                                ws_url = page_tab["webSocketDebuggerUrl"]
                                break
                    except Exception:
                        _time.sleep(0.1)
                self.assertIsNotNone(ws_url, "Chrome CDP bağlantısı kurulamadı")

                # Basit standart kütüphane WebSocket istemcisi ile CDP Runtime.evaluate çalıştır
                import base64
                from urllib.parse import urlparse

                parsed_ws = urlparse(ws_url)
                sock = socket.create_connection((parsed_ws.hostname, parsed_ws.port), timeout=10)
                key = base64.b64encode(os.urandom(16)).decode("ascii")
                handshake = (
                    f"GET {parsed_ws.path} HTTP/1.1\r\n"
                    f"Host: {parsed_ws.hostname}:{parsed_ws.port}\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Key: {key}\r\n"
                    "Sec-WebSocket-Version: 13\r\n\r\n"
                )
                sock.sendall(handshake.encode("ascii"))
                resp_buf = b""
                while b"\r\n\r\n" not in resp_buf:
                    resp_buf += sock.recv(1024)

                msg_id = 0

                def cdp_eval(js_expr: str):
                    nonlocal msg_id
                    msg_id += 1
                    payload_bytes = _json.dumps(
                        {
                            "id": msg_id,
                            "method": "Runtime.evaluate",
                            "params": {"expression": js_expr, "awaitPromise": True, "returnByValue": True},
                        }
                    ).encode("utf-8")
                    mask_key = os.urandom(4)
                    header = bytearray([0x81])
                    length = len(payload_bytes)
                    if length < 126:
                        header.append(0x80 | length)
                    elif length < 65536:
                        header.append(0x80 | 126)
                        header.extend(length.to_bytes(2, "big"))
                    else:
                        header.append(0x80 | 127)
                        header.extend(length.to_bytes(8, "big"))
                    header.extend(mask_key)
                    masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload_bytes))
                    sock.sendall(bytes(header) + masked)

                    while True:
                        first2 = sock.recv(2)
                        plen = first2[1] & 0x7F
                        if plen == 126:
                            plen = int.from_bytes(sock.recv(2), "big")
                        elif plen == 127:
                            plen = int.from_bytes(sock.recv(8), "big")
                        frame = b""
                        while len(frame) < plen:
                            frame += sock.recv(plen - len(frame))
                        msg = _json.loads(frame.decode("utf-8"))
                        if msg.get("id") == msg_id:
                            return msg.get("result", {}).get("result", {}).get("value")

                # Token'ı localStorage'a yaz ve /my-tasks ekranına git
                cdp_eval(
                    f"""
                    localStorage.setItem('nanolab_glp_jwt', {_json.dumps(token)});
                    localStorage.setItem('nanolab_glp_user', {_json.dumps(_json.dumps(user_info))});
                    window.location.href = '/my-tasks';
                    'ok';
                    """
                )

                # 2026-12-14 tarih butonuna tıkla ve Gün 7 görev kartının yüklenmesini bekle
                for _ in range(40):
                    ready = cdp_eval(
                        f"""
                        (() => {{
                          const btns = Array.from(document.querySelectorAll('button'));
                          const dBtn = btns.find(b => b.textContent.trim() === '2026-12-14');
                          if (dBtn) dBtn.click();
                          const inp = document.querySelector('[data-testid="ref-time-input-{day7.id}"]');
                          return inp ? true : false;
                        }})()
                        """
                    )
                    if ready:
                        break
                    _time.sleep(0.2)

                # 1) Referans saati girişi başlangıçta boş ('') olmalı (planlanan 10:00 otomatik yazılmamalı)
                initial_state = cdp_eval(
                    f"""
                    (() => {{
                      const inp = document.querySelector('[data-testid="ref-time-input-{day7.id}"]');
                      const badge = document.querySelector('[data-testid="task-status-badge-{day7.id}"]');
                      return {{
                        inputValue: inp ? inp.value : null,
                        badgeText: badge ? badge.textContent.trim() : null
                      }};
                    }})()
                    """
                )
                self.assertEqual(initial_state["inputValue"], "", "Referans saati girişi başlangıçta boş olmalı")
                self.assertEqual(initial_state["badgeText"], "Bekliyor")

                # 2) Yalnızca 10:45 referans saatini gir ve 'Referans Saatini Kaydet' butonuna tıkla
                cdp_eval(
                    f"""
                    (() => {{
                      const inp = document.querySelector('[data-testid="ref-time-input-{day7.id}"]');
                      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                      setter.call(inp, '2026-12-14T10:45');
                      inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                      inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                      document.querySelector('[data-testid="save-ref-time-btn-{day7.id}"]').click();
                      return true;
                    }})()
                    """
                )

                for _ in range(30):
                    rec_badge = cdp_eval(
                        f"""
                        (() => {{
                          const el = document.querySelector('[data-testid="recorded-ref-time-{day7.id}"]');
                          return el ? el.textContent : null;
                        }})()
                        """
                    )
                    if rec_badge and "10:45" in rec_badge:
                        break
                    _time.sleep(0.2)

                after_ref_ui = cdp_eval(
                    f"""
                    (() => {{
                      const badge = document.querySelector('[data-testid="task-status-badge-{day7.id}"]');
                      const dev = document.querySelector('[data-testid="ref-deviation-badge-{day7.id}"]');
                      const actualWin = document.querySelector('[data-testid="task-actual-window-{day7.id}"]');
                      return {{
                        statusBadge: badge ? badge.textContent.trim() : null,
                        devBadge: dev ? dev.textContent.trim() : null,
                        hasActualWin: Boolean(actualWin)
                      }};
                    }})()
                    """
                )
                self.assertEqual(
                    after_ref_ui["statusBadge"],
                    "Bekliyor",
                    "Referans Saatini Kaydet bekleyen görevi otomatik Tamamlandı (COMPLETED) yapmamalı",
                )
                self.assertIn("+45 dk", after_ref_ui["devBadge"] or "")
                self.assertFalse(
                    after_ref_ui["hasActualWin"],
                    "Yalnızca 10:45 referansı kaydedildiğinde 09:00/12:00 plan saatleri gerçekleşen saatlere yazılmamalı",
                )

                # Veritabanında da durum ve gerçekleşen saatleri doğrula
                self.db.expire_all()
                d7_persisted = self.db.query(StudyStep).filter(StudyStep.id == day7.id).first()
                self.assertEqual(d7_persisted.status, StepStatus.PENDING)
                self.assertEqual(d7_persisted.actual_reference_time, datetime(2026, 12, 14, 10, 45))
                self.assertIsNone(d7_persisted.actual_start)
                self.assertIsNone(d7_persisted.actual_end)

                # 3) AYNI GÖREVDE (day7) tesis saati 12:00 iken doğrudan 'Başlat' tıklandığında:
                #    Otomatik 12:00 başlangıç saati (12:00 > 10:45) reddedilmeli, kayıt değişmemeli,
                #    ve kullanıcı çıkmazda kalmayıp geç kayıt alanlarına yönlendirilmeli!
                with patch("app.api.v1.planning._facility_now", return_value=datetime(2026, 12, 14, 12, 0, 0)):
                    cdp_eval(
                        f"""
                        document.querySelector('[data-testid="start-task-btn-{day7.id}"]').click();
                        true;
                        """
                    )
                    for _ in range(30):
                        guidance_txt = cdp_eval(
                            f"""
                            (() => {{
                              const g = document.querySelector('[data-testid="task-guidance-{day7.id}"]');
                              return g ? g.textContent.trim() : null;
                            }})()
                            """
                        )
                        if guidance_txt:
                            break
                        _time.sleep(0.2)

                    self.assertTrue(
                        bool(guidance_txt),
                        "Bilgi eksikse kullanıcı anlaşılır şekilde gerekli alanlara yönlendirilmeli",
                    )
                    self.db.expire_all()
                    d7_after_rejected_start = self.db.query(StudyStep).filter(StudyStep.id == day7.id).first()
                    self.assertEqual(d7_after_rejected_start.status, StepStatus.PENDING)
                    self.assertIsNone(
                        d7_after_rejected_start.actual_start,
                        "Reddedilen Başlat işlemi mevcut kayda 12:00 actual_start yazmamalı",
                    )

                    # 4) AYNI GÖREVDE (day7) gerçek başlangıç 09:30 girilip 'Başlat' ve ardından gerçek bitiş 11:30 girilip 'Tamamla'
                    cdp_eval(
                        f"""
                        (() => {{
                          const sInp = document.querySelector('[data-testid="actual-start-input-{day7.id}"]');
                          const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                          setter.call(sInp, '2026-12-14T09:30');
                          sInp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                          sInp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                          document.querySelector('[data-testid="start-task-btn-{day7.id}"]').click();
                          return true;
                        }})()
                        """
                    )
                    for _ in range(30):
                        st7_badge = cdp_eval(
                            f"""
                            (() => {{
                              const b = document.querySelector('[data-testid="task-status-badge-{day7.id}"]');
                              return b ? b.textContent.trim() : null;
                            }})()
                            """
                        )
                        if st7_badge == "Devam Ediyor":
                            break
                        _time.sleep(0.2)

                    self.assertEqual(st7_badge, "Devam Ediyor")
                    self.db.expire_all()
                    d7_in_prog = self.db.query(StudyStep).filter(StudyStep.id == day7.id).first()
                    self.assertEqual(d7_in_prog.status, StepStatus.IN_PROGRESS)
                    self.assertEqual(d7_in_prog.actual_start, datetime(2026, 12, 14, 9, 30))
                    self.assertEqual(d7_in_prog.actual_reference_time, datetime(2026, 12, 14, 10, 45))
                    self.assertIsNone(d7_in_prog.actual_end)

                    # Şimdi aynı görevde (day7) gerçek bitiş 11:30 girilip 'Tamamla'
                    cdp_eval(
                        f"""
                        (() => {{
                          const toggleBtn = document.querySelector('[data-testid="toggle-actual-times-btn-{day7.id}"]');
                          if (!document.querySelector('[data-testid="actual-end-input-{day7.id}"]') && toggleBtn) {{
                            toggleBtn.click();
                          }}
                          return true;
                        }})()
                        """
                    )
                    for _ in range(20):
                        has_end_inp = cdp_eval(
                            f"Boolean(document.querySelector('[data-testid=\"actual-end-input-{day7.id}\"]'))"
                        )
                        if has_end_inp:
                            break
                        _time.sleep(0.1)

                    cdp_eval(
                        f"""
                        (() => {{
                          const eInp = document.querySelector('[data-testid="actual-end-input-{day7.id}"]');
                          const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                          setter.call(eInp, '2026-12-14T11:30');
                          eInp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                          eInp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                          document.querySelector('[data-testid="complete-task-btn-{day7.id}"]').click();
                          return true;
                        }})()
                        """
                    )
                    for _ in range(30):
                        st7_done = cdp_eval(
                            f"""
                            (() => {{
                              const b = document.querySelector('[data-testid="task-status-badge-{day7.id}"]');
                              return b ? b.textContent.trim() : null;
                            }})()
                            """
                        )
                        if st7_done == "Tamamlandı":
                            break
                        _time.sleep(0.2)

                    self.assertEqual(st7_done, "Tamamlandı")
                    self.db.expire_all()
                    d7_completed = self.db.query(StudyStep).filter(StudyStep.id == day7.id).first()
                    self.assertEqual(d7_completed.status, StepStatus.COMPLETED)
                    self.assertEqual(d7_completed.actual_start, datetime(2026, 12, 14, 9, 30))
                    self.assertEqual(d7_completed.actual_reference_time, datetime(2026, 12, 14, 10, 45))
                    self.assertEqual(d7_completed.actual_end, datetime(2026, 12, 14, 11, 30))
                    self.assertEqual(d7_completed.planned_start, datetime(2026, 12, 14, 9, 0))
                    self.assertEqual(d7_completed.planned_end, datetime(2026, 12, 14, 12, 0))

                # 5) 2026-12-15 (Gün 8) görevine geç ve normal zamanında 'Başlat' butonuna tıkla:
                #    Planlanan/beklenen referans saati actual_reference_time olarak kaydedilmemeli!
                for _ in range(30):
                    d8_ready = cdp_eval(
                        f"""
                        (() => {{
                          const btns = Array.from(document.querySelectorAll('button'));
                          const dBtn = btns.find(b => b.textContent.trim() === '2026-12-15');
                          if (dBtn) dBtn.click();
                          const sBtn = document.querySelector('[data-testid="start-task-btn-{day8.id}"]');
                          return sBtn ? true : false;
                        }})()
                        """
                    )
                    if d8_ready:
                        break
                    _time.sleep(0.2)

                cdp_eval(
                    f"""
                    document.querySelector('[data-testid="start-task-btn-{day8.id}"]').click();
                    true;
                    """
                )
                for _ in range(30):
                    st8_badge = cdp_eval(
                        f"""
                        (() => {{
                          const b = document.querySelector('[data-testid="task-status-badge-{day8.id}"]');
                          return b ? b.textContent.trim() : null;
                        }})()
                        """
                    )
                    if st8_badge == "Devam Ediyor":
                        break
                    _time.sleep(0.2)

                self.db.expire_all()
                d8_persisted = self.db.query(StudyStep).filter(StudyStep.id == day8.id).first()
                self.assertEqual(d8_persisted.status, StepStatus.IN_PROGRESS)
                self.assertIsNotNone(d8_persisted.actual_start)
                self.assertIsNone(d8_persisted.actual_end)
                self.assertIsNone(
                    d8_persisted.actual_reference_time,
                    "Tarayıcıda 'Başlat' tıklandığında planlanan/beklenen referans saati actual_reference_time olarak kaydedilmemeli",
                )

                # 6) 2026-12-16 (Gün 9) görevinde: Referans kaydet (10:45) -> saat bilinmiyor seçeneğiyle doğrudan Tamamla
                with patch("app.api.v1.planning._facility_now", return_value=datetime(2026, 12, 16, 12, 0, 0)):
                    for _ in range(30):
                        d9_ready = cdp_eval(
                            f"""
                            (() => {{
                              const btns = Array.from(document.querySelectorAll('button'));
                              const dBtn = btns.find(b => b.textContent.trim() === '2026-12-16');
                              if (dBtn) dBtn.click();
                              const inp = document.querySelector('[data-testid="ref-time-input-{day9.id}"]');
                              return inp ? true : false;
                            }})()
                            """
                        )
                        if d9_ready:
                            break
                        _time.sleep(0.2)

                    cdp_eval(
                        f"""
                        (() => {{
                          const inp = document.querySelector('[data-testid="ref-time-input-{day9.id}"]');
                          const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                          setter.call(inp, '2026-12-16T10:45');
                          inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                          inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                          document.querySelector('[data-testid="save-ref-time-btn-{day9.id}"]').click();
                          return true;
                        }})()
                        """
                    )
                    for _ in range(30):
                        rec9 = cdp_eval(
                            f"""
                            (() => {{
                              const el = document.querySelector('[data-testid="recorded-ref-time-{day9.id}"]');
                              return el ? el.textContent : null;
                            }})()
                            """
                        )
                        if rec9 and "10:45" in rec9:
                            break
                        _time.sleep(0.2)

                    cdp_eval(
                        f"""
                        (() => {{
                          const chk = document.querySelector('[data-testid="preserve-missing-actuals-{day9.id}"]');
                          if (chk && !chk.checked) chk.click();
                          document.querySelector('[data-testid="complete-task-btn-{day9.id}"]').click();
                          return true;
                        }})()
                        """
                    )
                    for _ in range(30):
                        st9_badge = cdp_eval(
                            f"""
                            (() => {{
                              const b = document.querySelector('[data-testid="task-status-badge-{day9.id}"]');
                              return b ? b.textContent.trim() : null;
                            }})()
                            """
                        )
                        if st9_badge == "Tamamlandı":
                            break
                        _time.sleep(0.2)

                    self.assertEqual(st9_badge, "Tamamlandı")
                    self.db.expire_all()
                    d9_persisted = self.db.query(StudyStep).filter(StudyStep.id == day9.id).first()
                    self.assertEqual(d9_persisted.status, StepStatus.COMPLETED)
                    self.assertEqual(d9_persisted.actual_reference_time, datetime(2026, 12, 16, 10, 45))
                    self.assertIsNone(d9_persisted.actual_start, "Bilinmeyen actual_start uydurulmamalı")
                    self.assertIsNone(d9_persisted.actual_end, "Bilinmeyen actual_end uydurulmamalı")

                sock.close()
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
        finally:
            server.should_exit = True
            thread.join(timeout=5)

    # ------------------------------------------------------------------
    # 18. MyTasks durum geçişi, geç gerçekleşme kaydı ve zaman tutarlılığı kabul testleri
    # ------------------------------------------------------------------
    def test_18_mytasks_same_task_late_transition_and_consistency(self):
        sd = self.people["ezgi"]
        tech = self.people["invivo_1"]
        s_late = Study(
            study_code="FIX18-LATE",
            title="Same Task Late Transition Study",
            test_item_name="Late Gel",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
            extraction_polar=True,
            extraction_non_polar=False,
        )
        self.db.add(s_late)
        self.db.commit()
        schedule_new_study(self.db, s_late.id, date(2026, 12, 7))
        s_late.status = StudyStatus.IN_PROGRESS
        self.db.commit()

        steps = (
            self.db.query(StudyStep)
            .filter(StudyStep.study_id == s_late.id)
            .order_by(StudyStep.step_order.asc())
            .all()
        )
        day0 = next(s for s in steps if s.study_day == 0)   # 2026-12-07 09:00-17:00 (normal adım)
        day7 = next(s for s in steps if s.study_day == 7)   # 2026-12-14 09:00-12:00, Plan Ref: 10:00
        day8 = next(s for s in steps if s.study_day == 8)   # 2026-12-15 10:00-10:45, Plan Ref: 10:00
        day9 = next(s for s in steps if s.study_day == 9)   # 2026-12-16 10:00-10:45, Plan Ref: 10:00
        day10 = next(s for s in steps if s.study_day == 10) # 2026-12-17 10:00-10:45, Plan Ref: 10:00
        for st in (day0, day7, day8, day9, day10):
            st.assignees = [tech]
        self.db.commit()

        h_tech = self.h_tech1
        frozen_noon = datetime(2026, 12, 14, 12, 0, 0)

        with patch("app.api.v1.planning._facility_now", return_value=frozen_noon):
            # ------------------------------------------------------------------
            # A) Doğrulanacak hata senaryosu 1 & 2 ve kabul testi 1:
            #    Aynı görevde (day7): Referans kaydet (10:45) -> Başlat -> Tamamla
            # ------------------------------------------------------------------
            r_ref = self.client.patch(
                f"/api/v1/planning/steps/{day7.id}/status",
                headers=h_tech,
                json={"actual_reference_time": "2026-12-14T10:45:00"},
            )
            self.assertEqual(r_ref.status_code, 200, r_ref.text)
            self.assertEqual(r_ref.json()["status"], "PENDING")
            self.assertIsNone(r_ref.json()["actual_start"])
            self.assertIsNone(r_ref.json()["actual_end"])

            # Saat 12:00'de eksik bilgiyle 'Şimdi Başlat' ({"status": "IN_PROGRESS"}) denendiğinde:
            # Otomatik 12:00 > 10:45 olduğu için veritabanına yazılmadan önce 422 dönmeli ve kayıt değişmemeli!
            r_bad_start = self.client.patch(
                f"/api/v1/planning/steps/{day7.id}/status",
                headers=h_tech,
                json={"status": "IN_PROGRESS"},
            )
            self.assertEqual(
                r_bad_start.status_code,
                422,
                "10:45 referansı kayıtlıyken saat 12:00'de otomatik Başlat 12:00 atamayıp 422 ile reddedilmeli",
            )
            self.db.expire_all()
            d7_check = self.db.query(StudyStep).filter(StudyStep.id == day7.id).first()
            self.assertEqual(d7_check.status, StepStatus.PENDING, "Reddedilen işlem mevcut durumu değiştirmemeli")
            self.assertIsNone(d7_check.actual_start, "Reddedilen işlem actual_start=12:00 yazmamalı")
            self.assertEqual(d7_check.actual_reference_time, datetime(2026, 12, 14, 10, 45))

            # Doğrudan 'Tamamla' ({"status": "COMPLETED"}) da eksik başlangıç uydurmadan 422 ile reddedilmeli ve kayıt değişmemeli!
            r_bad_complete = self.client.patch(
                f"/api/v1/planning/steps/{day7.id}/status",
                headers=h_tech,
                json={"status": "COMPLETED"},
            )
            self.assertEqual(
                r_bad_complete.status_code,
                422,
                "Doğrudan Tamamla yolunda da otomatik saat uydurulmamalı ve tutarsız işlem 422 ile reddedilmeli",
            )
            self.db.expire_all()
            d7_check2 = self.db.query(StudyStep).filter(StudyStep.id == day7.id).first()
            self.assertEqual(d7_check2.status, StepStatus.PENDING)
            self.assertIsNone(d7_check2.actual_start)
            self.assertIsNone(d7_check2.actual_end)

            # Aynı görevde (day7) gerçek başlangıç 09:30 girilerek Başlat -> gerçek bitiş 11:30 girilerek Tamamla
            r_valid_start = self.client.patch(
                f"/api/v1/planning/steps/{day7.id}/status",
                headers=h_tech,
                json={"status": "IN_PROGRESS", "actual_start": "2026-12-14T09:30:00"},
            )
            self.assertEqual(r_valid_start.status_code, 200, r_valid_start.text)
            self.assertEqual(r_valid_start.json()["status"], "IN_PROGRESS")
            self.assertEqual(r_valid_start.json()["actual_start"], "2026-12-14T09:30:00")
            self.assertEqual(r_valid_start.json()["actual_reference_time"], "2026-12-14T10:45:00")
            self.assertIsNone(r_valid_start.json()["actual_end"])

            r_valid_complete = self.client.patch(
                f"/api/v1/planning/steps/{day7.id}/status",
                headers=h_tech,
                json={"status": "COMPLETED", "actual_end": "2026-12-14T11:30:00"},
            )
            self.assertEqual(r_valid_complete.status_code, 200, r_valid_complete.text)
            d7_done = r_valid_complete.json()
            self.assertEqual(d7_done["status"], "COMPLETED")
            self.assertEqual(d7_done["actual_start"], "2026-12-14T09:30:00")
            self.assertEqual(d7_done["actual_reference_time"], "2026-12-14T10:45:00")
            self.assertEqual(d7_done["actual_end"], "2026-12-14T11:30:00")
            self.assertEqual(d7_done["planned_start"], "2026-12-14T09:00:00", "Onaylı plan saatleri değişmemeli")
            self.assertEqual(d7_done["planned_end"], "2026-12-14T12:00:00", "Onaylı plan saatleri değişmemeli")

            # Gerçekleşen sınırların (09:30 - 11:30) dışındaki referans reddedilmeli ve kayıt değişmemeli
            for invalid_ref in ("2026-12-14T09:15:00", "2026-12-14T11:45:00"):
                r_out = self.client.patch(
                    f"/api/v1/planning/steps/{day7.id}/status",
                    headers=h_tech,
                    json={"actual_reference_time": invalid_ref},
                )
                self.assertEqual(r_out.status_code, 422)
                self.db.expire_all()
                d7_unchanged = self.db.query(StudyStep).filter(StudyStep.id == day7.id).first()
                self.assertEqual(d7_unchanged.actual_start, datetime(2026, 12, 14, 9, 30))
                self.assertEqual(d7_unchanged.actual_reference_time, datetime(2026, 12, 14, 10, 45))
                self.assertEqual(d7_unchanged.actual_end, datetime(2026, 12, 14, 11, 30))

        # ------------------------------------------------------------------
        # B) Saat gerçekten bilinmediğinde: Referans kaydet -> Başlat -> Tamamla (day8)
        #    Eksik saatler sessizce doldurulmamalı (actual_start=None, actual_end=None korunmalı)
        # ------------------------------------------------------------------
        with patch("app.api.v1.planning._facility_now", return_value=datetime(2026, 12, 15, 12, 0, 0)):
            self.client.patch(
                f"/api/v1/planning/steps/{day8.id}/status",
                headers=h_tech,
                json={"actual_reference_time": "2026-12-15T10:45:00"},
            )
            r_s8 = self.client.patch(
                f"/api/v1/planning/steps/{day8.id}/status",
                headers=h_tech,
                json={"status": "IN_PROGRESS", "preserve_missing_actuals": True},
            )
            self.assertEqual(r_s8.status_code, 200, r_s8.text)
            self.assertEqual(r_s8.json()["status"], "IN_PROGRESS")
            self.assertIsNone(r_s8.json()["actual_start"], "Eksik başlangıç saati sessizce doldurulmamalı")
            self.assertEqual(r_s8.json()["actual_reference_time"], "2026-12-15T10:45:00")

            r_c8 = self.client.patch(
                f"/api/v1/planning/steps/{day8.id}/status",
                headers=h_tech,
                json={"status": "COMPLETED", "preserve_missing_actuals": True},
            )
            self.assertEqual(r_c8.status_code, 200, r_c8.text)
            self.assertEqual(r_c8.json()["status"], "COMPLETED")
            self.assertIsNone(r_c8.json()["actual_start"], "Eksik başlangıç saati sessizce doldurulmamalı")
            self.assertIsNone(r_c8.json()["actual_end"], "Eksik bitiş saati sessizce doldurulmamalı")
            self.assertEqual(r_c8.json()["actual_reference_time"], "2026-12-15T10:45:00")

        # ------------------------------------------------------------------
        # C) Referans kaydet -> doğrudan Tamamla sırası (day9: bilinen saatlerle, day10: bilinmeyen saatlerle)
        # ------------------------------------------------------------------
        with patch("app.api.v1.planning._facility_now", return_value=datetime(2026, 12, 16, 12, 0, 0)):
            self.client.patch(
                f"/api/v1/planning/steps/{day9.id}/status",
                headers=h_tech,
                json={"actual_reference_time": "2026-12-16T10:45:00"},
            )
            r_direct_known = self.client.patch(
                f"/api/v1/planning/steps/{day9.id}/status",
                headers=h_tech,
                json={
                    "status": "COMPLETED",
                    "actual_start": "2026-12-16T09:30:00",
                    "actual_end": "2026-12-16T11:30:00",
                },
            )
            self.assertEqual(r_direct_known.status_code, 200, r_direct_known.text)
            self.assertEqual(r_direct_known.json()["status"], "COMPLETED")
            self.assertEqual(r_direct_known.json()["actual_start"], "2026-12-16T09:30:00")
            self.assertEqual(r_direct_known.json()["actual_reference_time"], "2026-12-16T10:45:00")
            self.assertEqual(r_direct_known.json()["actual_end"], "2026-12-16T11:30:00")

        with patch("app.api.v1.planning._facility_now", return_value=datetime(2026, 12, 17, 12, 0, 0)):
            self.client.patch(
                f"/api/v1/planning/steps/{day10.id}/status",
                headers=h_tech,
                json={"actual_reference_time": "2026-12-17T10:45:00"},
            )
            r_direct_unknown = self.client.patch(
                f"/api/v1/planning/steps/{day10.id}/status",
                headers=h_tech,
                json={"status": "COMPLETED", "preserve_missing_actuals": True},
            )
            self.assertEqual(r_direct_unknown.status_code, 200, r_direct_unknown.text)
            self.assertEqual(r_direct_unknown.json()["status"], "COMPLETED")
            self.assertIsNone(r_direct_unknown.json()["actual_start"])
            self.assertIsNone(r_direct_unknown.json()["actual_end"])
            self.assertEqual(r_direct_unknown.json()["actual_reference_time"], "2026-12-17T10:45:00")

        # ------------------------------------------------------------------
        # D) Normal, zamanında 'Başlat / Tamamla' akışı çalışmaya devam etmeli (day0)
        # ------------------------------------------------------------------
        with patch("app.api.v1.planning._facility_now", return_value=datetime(2026, 12, 7, 9, 0, 0)):
            r_norm_start = self.client.patch(
                f"/api/v1/planning/steps/{day0.id}/status",
                headers=h_tech,
                json={"status": "IN_PROGRESS"},
            )
            self.assertEqual(r_norm_start.status_code, 200, r_norm_start.text)
            self.assertEqual(r_norm_start.json()["status"], "IN_PROGRESS")
            self.assertEqual(r_norm_start.json()["actual_start"], "2026-12-07T09:00:00")
            self.assertIsNone(r_norm_start.json()["actual_end"])

        with patch("app.api.v1.planning._facility_now", return_value=datetime(2026, 12, 7, 12, 0, 0)):
            r_norm_end = self.client.patch(
                f"/api/v1/planning/steps/{day0.id}/status",
                headers=h_tech,
                json={"status": "COMPLETED"},
            )
            self.assertEqual(r_norm_end.status_code, 200, r_norm_end.text)
            self.assertEqual(r_norm_end.json()["status"], "COMPLETED")
            self.assertEqual(r_norm_end.json()["actual_start"], "2026-12-07T09:00:00")
            self.assertEqual(r_norm_end.json()["actual_end"], "2026-12-07T12:00:00")

    # ------------------------------------------------------------------
    # 19. SD Onaylı Biyolojik Plan Revizyonu (Kabul Testleri 1–8)
    # ------------------------------------------------------------------
    def test_19_biological_plan_revision_workflow_and_atomicity(self):
        from app.models.audit_log import AuditLog
        from app.utils.security import get_password_hash

        sd_ezgi = self.people["ezgi"]
        sd_onur = User(
            username="onur_sd",
            full_name="Onur Diğer SD",
            email="onur_sd@nanolab.com.tr",
            role=UserRole.STUDY_DIRECTOR,
            department="Biyouyumluluk",
            hashed_password=get_password_hash(DEFAULT_PASSWORD),
            is_active=True,
        )
        self.db.add(sd_onur)
        self.db.commit()

        tech1 = self.people["invivo_1"]
        tech2 = self.people["invivo_2"]
        qa_user = self.people["qa_user"]

        h_ezgi = _login_headers(self.client, "ezgi")
        h_onur = _login_headers(self.client, "onur_sd")
        h_tech1 = _login_headers(self.client, "invivo_1")
        h_qa = _login_headers(self.client, "qa_user")

        # Çalışma oluştur (Gün 0 = 2027-01-04 Pazartesi, Gün 7 Dozlama = 2027-01-11, Gün 8/9/10 = 12/13/14 Ocak)
        st = Study(
            study_code="FIX19-REV-001",
            title="SD Biyolojik Plan Revizyonu Çalışması",
            test_item_name="Revizyon Test Jel",
            study_director_id=sd_ezgi.id,
            status=StudyStatus.DRAFT,
            animal_species_strain="Tavşan (New Zealand White)",
            animal_count=3,
            extraction_polar=True,
            extraction_non_polar=False,
        )
        self.db.add(st)
        self.db.commit()
        schedule_new_study(self.db, st.id, date(2027, 1, 4))
        st.status = StudyStatus.IN_PROGRESS
        self.db.commit()

        steps = (
            self.db.query(StudyStep)
            .filter(StudyStep.study_id == st.id)
            .order_by(StudyStep.step_order.asc())
            .all()
        )
        day7 = next(s for s in steps if s.study_day == 7)   # order=3, 2027-01-11 09:00-12:00, Plan Ref: 10:00
        day8 = next(s for s in steps if s.study_day == 8)   # order=4, 2027-01-12 10:00-10:45 (24s)
        day9 = next(s for s in steps if s.study_day == 9)   # order=5, 2027-01-13 10:00-10:45 (48s)
        day10 = next(s for s in steps if s.study_day == 10)  # order=6, 2027-01-14 10:00-10:45 (72s)

        # Ek bir CANCELLED bağımlı adım (uygunluk testi için)
        cancelled_dep = StudyStep(
            study_id=st.id,
            step_order=6,
            study_day=10,
            step_name="İptal Edilmiş 72. Saat Gözlem Kopyası",
            step_type="Gözlem",
            planned_start=datetime(2027, 1, 14, 10, 0),
            planned_end=datetime(2027, 1, 14, 10, 45),
            is_biological_fixed_time=True,
            biological_tolerance_minutes=120,
            status=StepStatus.CANCELLED,
        )
        self.db.add(cancelled_dep)
        self.db.commit()

        # Kaynak adım (day7) gerçek referans saatini +180 dk gecikmeyle (13:00) kaydet ve tamamla
        r_ref = self.client.patch(
            f"/api/v1/planning/steps/{day7.id}/status",
            headers=h_tech1,
            json={
                "status": "COMPLETED",
                "actual_start": "2027-01-11T12:00:00",
                "actual_reference_time": "2027-01-11T13:00:00",
                "actual_end": "2027-01-11T14:00:00",
            },
        )
        self.assertEqual(r_ref.status_code, 200, r_ref.text)

        # ------------------------------------------------------------------
        # (1) Önizleme salt-okunur olmalı: planned_start / planned_end ve study.status değişmemeli
        # ------------------------------------------------------------------
        self.db.expire_all()
        before_times = {
            s.id: (s.planned_start, s.planned_end, s.study_day, s.status)
            for s in self.db.query(StudyStep).filter(StudyStep.study_id == st.id, StudyStep.status != StepStatus.CANCELLED).all()
        }
        r_prev = self.client.get(
            f"/api/v1/planning/studies/{st.id}/revision-preview",
            headers=h_ezgi,
        )
        self.assertEqual(r_prev.status_code, 200, r_prev.text)
        prev_data = r_prev.json()
        self.assertEqual(prev_data["source_reference"]["actual_reference_time"], "2027-01-11T13:00:00")
        self.assertEqual(prev_data["source_reference"]["deviation_minutes"], 180)
        self.assertEqual(len(prev_data["affected_steps"]), 3)

        self.db.expire_all()
        after_times = {
            s.id: (s.planned_start, s.planned_end, s.study_day, s.status)
            for s in self.db.query(StudyStep).filter(StudyStep.study_id == st.id, StudyStep.status != StepStatus.CANCELLED).all()
        }
        self.assertEqual(before_times, after_times, "Önizleme çağrısı hiçbir adımın planlanan saatini değiştirmemeli")

        # ------------------------------------------------------------------
        # (2) Adım uygunluğu: COMPLETED, CANCELLED, IN_PROGRESS veya actual_* verisi olan PENDING
        #     adımlar kaydırılmamalı; yalnızca uygun PENDING adımlar güncellenmeli
        # ------------------------------------------------------------------
        # day8'i COMPLETED yap ve gerçekleşen gözlem ihlali oluştur (beklenen 13:00 yerine 10:00'da gözlemlenmiş olsun)
        self.db.expire_all()
        d8_orm = self.db.query(StudyStep).filter(StudyStep.id == day8.id).first()
        d8_orm.status = StepStatus.COMPLETED
        d8_orm.actual_start = datetime(2027, 1, 12, 9, 50)
        d8_orm.actual_reference_time = datetime(2027, 1, 12, 10, 0)  # beklenen 13:00'a göre -180 dk (>120 dk ihlal!)
        d8_orm.actual_end = datetime(2027, 1, 12, 10, 30)
        self.db.commit()
        revalidate_study_conflicts(self.db, st)
        self.db.commit()

        # day9'u önce IN_PROGRESS olarak test et -> uygun olmamalı
        d9_orm = self.db.query(StudyStep).filter(StudyStep.id == day9.id).first()
        d9_orm.status = StepStatus.IN_PROGRESS
        d9_orm.actual_start = datetime(2027, 1, 13, 10, 0)
        self.db.commit()

        r_prev_elig1 = self.client.get(
            f"/api/v1/planning/studies/{st.id}/revision-preview",
            headers=h_ezgi,
        ).json()
        aff_orders_1 = [x["step_order"] for x in r_prev_elig1["affected_steps"]]
        inelig_by_order_1 = {x["step_order"]: x for x in r_prev_elig1["ineligible_steps"]}
        self.assertEqual(aff_orders_1, [day10.step_order], "Yalnızca PENDING ve actual verisi olmayan day10 uygun olmalı")
        self.assertIn(day8.step_order, inelig_by_order_1)
        self.assertIn("COMPLETED", inelig_by_order_1[day8.step_order]["ineligible_reason"])
        self.assertIn(day9.step_order, inelig_by_order_1)
        self.assertIn("IN_PROGRESS", inelig_by_order_1[day9.step_order]["ineligible_reason"])
        self.assertTrue(
            any(x["status"] == "CANCELLED" for x in r_prev_elig1["ineligible_steps"]),
            "CANCELLED adımlar da uygun olmayan adımlar arasında nedeni ile gösterilmeli",
        )

        # Şimdi day9'u status=PENDING ama actual_start dolu olarak test et -> yine uygun olmamalı!
        d9_orm = self.db.query(StudyStep).filter(StudyStep.id == day9.id).first()
        d9_orm.status = StepStatus.PENDING
        d9_orm.actual_start = datetime(2027, 1, 13, 10, 5)
        self.db.commit()

        r_prev_elig2 = self.client.get(
            f"/api/v1/planning/studies/{st.id}/revision-preview",
            headers=h_ezgi,
        ).json()
        aff_orders_2 = [x["step_order"] for x in r_prev_elig2["affected_steps"]]
        inelig_by_order_2 = {x["step_order"]: x for x in r_prev_elig2["ineligible_steps"]}
        self.assertEqual(aff_orders_2, [day10.step_order])
        self.assertIn(day9.step_order, inelig_by_order_2)
        self.assertIn("actual_start", inelig_by_order_2[day9.step_order]["ineligible_reason"])

        # Şimdi day9'un actual_start'ını temizle ki day9 ve day10 uygun PENDING olsun, day8 COMPLETED kalsın
        d9_orm = self.db.query(StudyStep).filter(StudyStep.id == day9.id).first()
        d9_orm.actual_start = None
        d9_orm.actual_end = None
        d9_orm.actual_reference_time = None
        self.db.commit()

        # ------------------------------------------------------------------
        # (4) Yetki ve gerekçe kontrolleri (403 ve 422)
        # ------------------------------------------------------------------
        # Farklı SD (onur) -> 403
        r_unauth_sd = self.client.post(
            f"/api/v1/planning/studies/{st.id}/approve-revision",
            headers=h_onur,
            json={"reason": "Farklı SD onay denemesi"},
        )
        self.assertEqual(r_unauth_sd.status_code, 403, r_unauth_sd.text)

        # Teknisyen -> 403
        r_unauth_tech = self.client.post(
            f"/api/v1/planning/studies/{st.id}/approve-revision",
            headers=h_tech1,
            json={"reason": "Teknisyen onay denemesi"},
        )
        self.assertEqual(r_unauth_tech.status_code, 403, r_unauth_tech.text)

        # QA (salt-okunur) -> 403
        r_unauth_qa = self.client.post(
            f"/api/v1/planning/studies/{st.id}/approve-revision",
            headers=h_qa,
            json={"reason": "QA onay denemesi"},
        )
        self.assertEqual(r_unauth_qa.status_code, 403, r_unauth_qa.text)

        # Boş gerekçe -> 422
        r_empty_reason = self.client.post(
            f"/api/v1/planning/studies/{st.id}/approve-revision",
            headers=h_ezgi,
            json={"reason": "   "},
        )
        self.assertEqual(r_empty_reason.status_code, 422, r_empty_reason.text)

        # ------------------------------------------------------------------
        # (5a) Bayat önizleme (Stale Preview): Önizleme alındıktan sonra kaynak referans değişirse eski onay 409 ile reddedilmeli
        # ------------------------------------------------------------------
        stale_prev = self.client.get(
            f"/api/v1/planning/studies/{st.id}/revision-preview",
            headers=h_ezgi,
        ).json()
        stale_token = stale_prev["preview_token"]

        # Kaynak referans saatini 13:00 -> 13:30 olarak değiştir
        self.client.patch(
            f"/api/v1/planning/steps/{day7.id}/status",
            headers=h_tech1,
            json={"actual_reference_time": "2027-01-11T13:30:00"},
        )

        # Eski preview_token ile (veya önbellekteki eski önizleme sonrasında) onay 409 dönmeli
        r_stale = self.client.post(
            f"/api/v1/planning/studies/{st.id}/approve-revision",
            headers=h_ezgi,
            json={"reason": "Bayat önizleme ile onay", "preview_token": stale_token},
        )
        self.assertEqual(r_stale.status_code, 409, r_stale.text)

        # Kaynak referansı tekrar 13:00 yap
        self.client.patch(
            f"/api/v1/planning/steps/{day7.id}/status",
            headers=h_tech1,
            json={"actual_reference_time": "2027-01-11T13:00:00"},
        )

        # ------------------------------------------------------------------
        # (6) Engel kontrolleri: Yeni saatlerde çakışma / kapasite / eksik rol / kapasite doğrulama hatası varsa 409 ve 0 değişiklik
        # ------------------------------------------------------------------
        # 6A) Başka bir çalışmada (other_st) 2027-01-13 13:00-13:45 saatinde aynı teknisyenin görevi varsa -> PERSONNEL_OVERLAP engeli
        other_st = Study(
            study_code="FIX19-BLOCKER",
            title="Blocker Study",
            test_item_name="Blocker Item",
            study_director_id=sd_ezgi.id,
            status=StudyStatus.APPROVED,
            acclimatization_start_date=date(2027, 1, 4),
            target_start_date=date(2027, 1, 4),
            target_end_date=date(2027, 1, 15),
        )
        self.db.add(other_st)
        self.db.flush()
        blocker_step = StudyStep(
            study_id=other_st.id,
            step_order=1,
            study_day=9,
            step_name="Çakışan Görev",
            step_type="Gözlem",
            planned_start=datetime(2027, 1, 13, 13, 0),
            planned_end=datetime(2027, 1, 13, 13, 45),
            is_biological_fixed_time=True,
            biological_tolerance_minutes=60,
            status=StepStatus.PENDING,
        )
        blocker_step.assignees = list(day9.assignees)
        self.db.add(blocker_step)
        self.db.commit()

        prev_with_blocker = self.client.get(
            f"/api/v1/planning/studies/{st.id}/revision-preview",
            headers=h_ezgi,
        ).json()
        self.assertTrue(prev_with_blocker["has_blocking_obstacles"])
        self.assertFalse(prev_with_blocker["can_approve_revision"])
        self.assertTrue(any(c["type"] == "PERSONNEL_OVERLAP" for c in prev_with_blocker["blocking_conflicts"]))

        r_blocked_overlap = self.client.post(
            f"/api/v1/planning/studies/{st.id}/approve-revision",
            headers=h_ezgi,
            json={"reason": "Çakışma varken onay denemesi", "preview_token": prev_with_blocker["preview_token"]},
        )
        self.assertEqual(r_blocked_overlap.status_code, 409, r_blocked_overlap.text)
        self.db.expire_all()
        self.assertEqual(
            self.db.query(StudyStep).filter(StudyStep.id == day9.id).first().planned_start,
            datetime(2027, 1, 13, 10, 0),
            "Engellenen revizyon adım saatini değiştirmemeli",
        )

        # 6B) 9 saat (540 dk) günlük iş yükü aşımı engeli (çakışmayan saatte 500 dk görev + 45 dk revize adım = 545 dk > 540 dk)
        blocker_step.planned_start = datetime(2027, 1, 13, 1, 0)
        blocker_step.planned_end = datetime(2027, 1, 13, 9, 20)  # 500 dk
        self.db.commit()

        prev_workload = self.client.get(
            f"/api/v1/planning/studies/{st.id}/revision-preview",
            headers=h_ezgi,
        ).json()
        self.assertTrue(prev_workload["has_blocking_obstacles"])
        self.assertTrue(any("9 Saat İş Yükü Aşımı" in c["title"] for c in prev_workload["blocking_conflicts"]))
        r_blocked_wl = self.client.post(
            f"/api/v1/planning/studies/{st.id}/approve-revision",
            headers=h_ezgi,
            json={"reason": "9 saat aşımı varken onay", "preview_token": prev_workload["preview_token"]},
        )
        self.assertEqual(r_blocked_wl.status_code, 409, r_blocked_wl.text)

        # Blocker step'i kaldır
        self.db.delete(blocker_step)
        self.db.delete(other_st)
        self.db.commit()

        # 6C) Eksik zorunlu rol ataması (QUALIFICATION_MISMATCH) engeli
        self.db.expire_all()
        d10_orm = self.db.query(StudyStep).filter(StudyStep.id == day10.id).first()
        saved_d10_assignees = list(d10_orm.assignees)
        d10_orm.assignees = []
        self.db.commit()

        prev_missing_role = self.client.get(
            f"/api/v1/planning/studies/{st.id}/revision-preview",
            headers=h_ezgi,
        ).json()
        self.assertTrue(prev_missing_role["has_blocking_obstacles"])
        self.assertTrue(any(c["type"] == "QUALIFICATION_MISMATCH" for c in prev_missing_role["blocking_conflicts"]))
        r_blocked_role = self.client.post(
            f"/api/v1/planning/studies/{st.id}/approve-revision",
            headers=h_ezgi,
            json={"reason": "Eksik rol varken onay", "preview_token": prev_missing_role["preview_token"]},
        )
        self.assertEqual(r_blocked_role.status_code, 409, r_blocked_role.text)

        d10_orm = self.db.query(StudyStep).filter(StudyStep.id == day10.id).first()
        d10_orm.assignees = saved_d10_assignees
        self.db.commit()

        # 6D) Kapasite doğrulama hatası (build_capacity_report exception) engeli
        with patch("app.services.scheduling_engine.build_capacity_report", side_effect=RuntimeError("Simüle Kapasite Servis Hatası")):
            prev_cap_err = self.client.get(
                f"/api/v1/planning/studies/{st.id}/revision-preview",
                headers=h_ezgi,
            ).json()
            self.assertFalse(prev_cap_err["capacity_verified"])
            self.assertTrue(prev_cap_err["has_blocking_obstacles"])
            r_blocked_cap_err = self.client.post(
                f"/api/v1/planning/studies/{st.id}/approve-revision",
                headers=h_ezgi,
                json={"reason": "Kapasite hatası varken onay", "preview_token": prev_cap_err["preview_token"]},
            )
            self.assertEqual(r_blocked_cap_err.status_code, 409, r_blocked_cap_err.text)

        # 6E) Oda/kafes kapasitesi aşımı (ROOM_CAPACITY_EXCEEDED) engeli
        from app.models.room_capacity import AnimalRoomCapacity, ensure_default_room_capacities

        ensure_default_room_capacities(self.db)
        self.db.expire_all()
        rabbit_room = self.db.query(AnimalRoomCapacity).filter(AnimalRoomCapacity.room_code == "RABBIT_ROOM").first()
        orig_phys_cages = rabbit_room.physical_cages
        orig_flex_pct = rabbit_room.flexibility_pct
        rabbit_room.physical_cages = 1
        rabbit_room.flexibility_pct = 0
        self.db.commit()

        prev_cage_exceed = self.client.get(
            f"/api/v1/planning/studies/{st.id}/revision-preview",
            headers=h_ezgi,
        ).json()
        self.assertTrue(prev_cage_exceed["has_blocking_obstacles"])
        self.assertTrue(any(c["type"] == "ROOM_CAPACITY_EXCEEDED" for c in prev_cage_exceed["blocking_conflicts"]))
        r_blocked_cage = self.client.post(
            f"/api/v1/planning/studies/{st.id}/approve-revision",
            headers=h_ezgi,
            json={"reason": "Kafes aşımı varken onay", "preview_token": prev_cage_exceed["preview_token"]},
        )
        self.assertEqual(r_blocked_cage.status_code, 409, r_blocked_cage.text)

        rabbit_room = self.db.query(AnimalRoomCapacity).filter(AnimalRoomCapacity.room_code == "RABBIT_ROOM").first()
        rabbit_room.physical_cages = orig_phys_cages
        rabbit_room.flexibility_pct = orig_flex_pct
        self.db.commit()

        # 6F) Cihaz kapasitesi / ekipman çakışması (EQUIPMENT_OVERLAP) engeli
        from app.services.scheduling_engine import seed_default_equipment

        wb_eq = seed_default_equipment(self.db)
        eq_other_st = Study(
            study_code="FIX19-EQ-BLOCKER",
            title="Equipment Blocker Study",
            test_item_name="Blocker Eq Item",
            study_director_id=sd_ezgi.id,
            status=StudyStatus.APPROVED,
            animal_species_strain="Tavşan",
            animal_count=3,
        )
        self.db.add(eq_other_st)
        self.db.flush()
        eq_other_step = StudyStep(
            study_id=eq_other_st.id,
            step_order=1,
            study_day=1,
            step_name="Cihaz Kullanan Adım",
            step_type="Gözlem",
            planned_start=datetime(2027, 1, 13, 13, 0),
            planned_end=datetime(2027, 1, 13, 14, 0),
            is_biological_fixed_time=True,
            biological_tolerance_minutes=60,
            equipment_id=wb_eq.id,
            status=StepStatus.PENDING,
        )
        self.db.add(eq_other_step)
        orig_wb_max_conc = wb_eq.max_concurrent_studies
        wb_eq.max_concurrent_studies = 1
        d9_orm_eq = self.db.query(StudyStep).filter(StudyStep.id == day9.id).first()
        d9_orm_eq.equipment_id = wb_eq.id
        self.db.commit()

        prev_eq_exceed = self.client.get(
            f"/api/v1/planning/studies/{st.id}/revision-preview",
            headers=h_ezgi,
        ).json()
        self.assertTrue(prev_eq_exceed["has_blocking_obstacles"])
        self.assertTrue(any(c["type"] == "EQUIPMENT_OVERLAP" for c in prev_eq_exceed["blocking_conflicts"]))
        r_blocked_eq = self.client.post(
            f"/api/v1/planning/studies/{st.id}/approve-revision",
            headers=h_ezgi,
            json={"reason": "Cihaz çakışması varken onay", "preview_token": prev_eq_exceed["preview_token"]},
        )
        self.assertEqual(r_blocked_eq.status_code, 409, r_blocked_eq.text)

        self.db.expire_all()
        wb_eq = self.db.query(Equipment).filter(Equipment.code == "EQ-WB-001").first()
        wb_eq.max_concurrent_studies = orig_wb_max_conc
        d9_orm_eq = self.db.query(StudyStep).filter(StudyStep.id == day9.id).first()
        d9_orm_eq.equipment_id = None
        self.db.delete(self.db.query(StudyStep).filter(StudyStep.id == eq_other_step.id).first())
        self.db.delete(self.db.query(Study).filter(Study.id == eq_other_st.id).first())
        self.db.commit()

        # ------------------------------------------------------------------
        # (8) Atomiklik: İşlem ortasında kontrollü hata oluştuğunda adım planları,
        #     çalışma meta verisi ve çakışma kayıtları birlikte geri alınmalı
        # ------------------------------------------------------------------
        from app.services.scheduling_engine import approve_biological_revision

        clean_prev = self.client.get(
            f"/api/v1/planning/studies/{st.id}/revision-preview",
            headers=h_ezgi,
        ).json()
        self.assertTrue(clean_prev["can_approve_revision"])

        with self.assertRaises(RuntimeError):
            approve_biological_revision(
                db=self.db,
                study_id=st.id,
                user=sd_ezgi,
                reason="Atomik rollback testi",
                preview_token=clean_prev["preview_token"],
                _fail_mid_transaction_for_test=True,
            )

        self.db.expire_all()
        st_after_fail = self.db.query(Study).filter(Study.id == st.id).first()
        d9_after_fail = self.db.query(StudyStep).filter(StudyStep.id == day9.id).first()
        d10_after_fail = self.db.query(StudyStep).filter(StudyStep.id == day10.id).first()
        open_src_conf = (
            self.db.query(Conflict)
            .filter(
                Conflict.study_id == st.id,
                Conflict.is_resolved == False,  # noqa: E712
                Conflict.title.like("%Biyolojik Referans Saat Sapması%"),
            )
            .first()
        )
        self.assertEqual(d9_after_fail.planned_start, datetime(2027, 1, 13, 10, 0), "Rollback sonrası day9 saati değişmemeli")
        self.assertEqual(d10_after_fail.planned_start, datetime(2027, 1, 14, 10, 0), "Rollback sonrası day10 saati değişmemeli")
        self.assertFalse(
            bool((st_after_fail.dossier_metadata or {}).get("biological_revisions")),
            "Rollback sonrası dossier_metadata içinde biological_revisions kalmamalı",
        )
        self.assertIsNotNone(open_src_conf, "Rollback sonrası kaynak sapma çakışması açık kalmalı")

        # ------------------------------------------------------------------
        # (3) Gün/gece yarısı geçişi ve (7) Başarılı onay, sapma/karar koruma ve yeniden hesaplama
        #     Kaynak referansı 22:00 yapalım (10:00 -> 22:00 = +720 dk):
        #     48. saat gözlem: 2027-01-13 22:00 - 22:45 (G9)
        #     72. saat gözlem: 2027-01-14 22:00 + 150 dk süre verirsek 2027-01-15 00:30'a taşar veya
        #     kaynak referansı 2027-01-12 01:00 (+15 saat = +900 dk) yaparsak:
        #       - 48s gözlem: 2027-01-13 10:00 (G9) -> 2027-01-14 01:00 (G10) [Gün değişimi G9 -> G10!]
        #       - 72s gözlem: 2027-01-14 10:00 (G10) -> 2027-01-15 01:00 (G11) [Gün değişimi G10 -> G11, target_end_date 14 Ocak -> 15 Ocak!]
        # ------------------------------------------------------------------
        self.client.patch(
            f"/api/v1/planning/steps/{day7.id}/status",
            headers=h_tech1,
            json={
                "status": "COMPLETED",
                "actual_start": "2027-01-11T22:00:00",
                "actual_reference_time": "2027-01-12T01:00:00",
                "actual_end": "2027-01-12T01:30:00",
            },
        )
        # Gece 01:00 mesai dışı uyarısı (WARNING) engellemez, önizlemede G9->G10 ve G10->G11 gün değişimini doğrula
        prev_midnight = self.client.get(
            f"/api/v1/planning/studies/{st.id}/revision-preview",
            headers=h_ezgi,
        ).json()
        self.assertTrue(prev_midnight["can_approve_revision"], prev_midnight)
        self.assertTrue(prev_midnight["any_day_changed"])
        self.assertTrue(prev_midnight["target_end_date_changed"])
        self.assertEqual(prev_midnight["current_target_end_date"], "2027-01-14")
        self.assertEqual(prev_midnight["proposed_target_end_date"], "2027-01-15")

        aff_by_order = {x["step_order"]: x for x in prev_midnight["affected_steps"]}
        self.assertEqual(aff_by_order[day9.step_order]["current_study_day"], 9)
        self.assertEqual(aff_by_order[day9.step_order]["proposed_study_day"], 10)
        self.assertTrue(aff_by_order[day9.step_order]["day_changed"])
        self.assertEqual(aff_by_order[day10.step_order]["current_study_day"], 10)
        self.assertEqual(aff_by_order[day10.step_order]["proposed_study_day"], 11)
        self.assertTrue(aff_by_order[day10.step_order]["day_changed"])

        # SD gerekçesiyle revizyonu onayla
        sd_reason = "Dozlama gece 01:00'de tamamlandığı için 48 ve 72. saat gözlemleri yeni güne revize edildi."
        r_approve = self.client.post(
            f"/api/v1/planning/studies/{st.id}/approve-revision",
            headers=h_ezgi,
            json={
                "reason": sd_reason,
                "preview_token": prev_midnight["preview_token"],
            },
        )
        self.assertEqual(r_approve.status_code, 200, r_approve.text)
        app_data = r_approve.json()
        self.assertEqual(app_data["target_end_date"], "2027-01-15")

        # (5b) Tokensız onay 422 ile reddedilmeli; aynı token veya onay sonrası yeni token ile mükerrer gönderim 409 ile reddedilmeli
        r_no_tok = self.client.post(
            f"/api/v1/planning/studies/{st.id}/approve-revision",
            headers=h_ezgi,
            json={"reason": sd_reason},
        )
        self.assertEqual(r_no_tok.status_code, 422, r_no_tok.text)

        r_dup = self.client.post(
            f"/api/v1/planning/studies/{st.id}/approve-revision",
            headers=h_ezgi,
            json={
                "reason": sd_reason,
                "preview_token": prev_midnight["preview_token"],
            },
        )
        self.assertEqual(r_dup.status_code, 409, r_dup.text)

        prev_after_app = self.client.get(
            f"/api/v1/planning/studies/{st.id}/revision-preview",
            headers=h_ezgi,
        ).json()
        r_dup_fresh = self.client.post(
            f"/api/v1/planning/studies/{st.id}/approve-revision",
            headers=h_ezgi,
            json={
                "reason": sd_reason,
                "preview_token": prev_after_app["preview_token"],
            },
        )
        self.assertEqual(r_dup_fresh.status_code, 409, r_dup_fresh.text)

        self.db.expire_all()
        st_db = self.db.query(Study).filter(Study.id == st.id).first()
        d7_db = self.db.query(StudyStep).filter(StudyStep.id == day7.id).first()
        d8_db = self.db.query(StudyStep).filter(StudyStep.id == day8.id).first()
        d9_db = self.db.query(StudyStep).filter(StudyStep.id == day9.id).first()
        d10_db = self.db.query(StudyStep).filter(StudyStep.id == day10.id).first()

        # Kaynak adımın orijinal planı ve gerçek referansı korunmalı
        self.assertEqual(d7_db.planned_start, datetime(2027, 1, 11, 9, 0))
        self.assertEqual(d7_db.planned_end, datetime(2027, 1, 11, 12, 0))
        self.assertEqual(d7_db.actual_reference_time, datetime(2027, 1, 12, 1, 0))

        # Uygun olmayan COMPLETED adım (day8) kaydırılmamalı
        self.assertEqual(d8_db.planned_start, datetime(2027, 1, 12, 10, 0))
        self.assertEqual(d8_db.study_day, 8)

        # Uygun PENDING adımlar (day9, day10) yeni saatlere ve yeni study_day değerlerine güncellenmeli
        self.assertEqual(d9_db.planned_start, datetime(2027, 1, 14, 1, 0))
        self.assertEqual(d9_db.planned_end, datetime(2027, 1, 14, 2, 0))
        self.assertEqual(d9_db.study_day, 10)
        self.assertEqual(d10_db.planned_start, datetime(2027, 1, 15, 1, 0))
        self.assertEqual(d10_db.planned_end, datetime(2027, 1, 15, 3, 0))
        self.assertEqual(d10_db.study_day, 11)
        self.assertEqual(st_db.target_end_date, date(2027, 1, 15))

        # Tek bir biological_revisions kaydı ve AuditLog kaydı oluşmalı
        revs_meta = (st_db.dossier_metadata or {}).get("biological_revisions") or []
        self.assertEqual(len(revs_meta), 1, "Mükerrer revizyon kaydı oluşmamalı")
        self.assertEqual(revs_meta[0]["reason"], sd_reason)
        self.assertEqual(revs_meta[0]["approved_by_id"], sd_ezgi.id)

        audit_row = (
            self.db.query(AuditLog)
            .filter(AuditLog.entity_name == "Study", AuditLog.entity_id == st.id, AuditLog.action == "APPROVE_BIOLOGICAL_REVISION")
            .first()
        )
        self.assertIsNotNone(audit_row)
        self.assertEqual(audit_row.reason, sd_reason)
        self.assertEqual(audit_row.old_values["target_end_date"], "2027-01-14")
        self.assertEqual(audit_row.new_values["target_end_date"], "2027-01-15")

        # (7) Çakışma durumu: ileriye dönük Bağımlı Biyolojik Adım Sapması (day9, day10) kalkmalı,
        #     kaynak sapması ve SD kararı korunmalı, daha önce gerçekleşmiş day8 gözlem ihlali ise AÇIK kalmalı!
        open_confs = (
            self.db.query(Conflict)
            .filter(Conflict.study_id == st.id, Conflict.is_resolved == False)  # noqa: E712
            .all()
        )
        open_titles = [c.title for c in open_confs]
        self.assertFalse(
            any("Biyolojik Referans Saat Sapması" in t for t in open_titles),
            f"SD onayından sonra kaynak referans sapma çakışması açık kalmamalı: {open_titles}",
        )
        self.assertFalse(
            any("Bağımlı Biyolojik Adım Sapması" in t and ("48. Saat" in t or "72. Saat" in t) for t in open_titles),
            f"Revize edilen 48 ve 72. saat adımlarında Bağımlı Biyolojik Adım Sapması kalkmalı: {open_titles}",
        )
        self.assertTrue(
            any("Gerçekleşen Gözlem Biyolojik Pencere İhlali" in t for t in open_titles),
            f"Daha önce gerçekleşmiş ve ihlal oluşturmuş 24. saat gözlem bulgusu korunmalı: {open_titles}",
        )

        # revalidate_study_conflicts ve recompute_all_conflicts sonrasında da bu durum bozulmamalı
        revalidate_study_conflicts(self.db, st_db)
        self.db.commit()
        recompute_all_conflicts(self.db, user=sd_ezgi)
        self.db.expire_all()

        open_after_recompute = (
            self.db.query(Conflict)
            .filter(Conflict.study_id == st.id, Conflict.is_resolved == False)  # noqa: E712
            .all()
        )
        titles_after_recompute = [c.title for c in open_after_recompute]
        self.assertFalse(
            any("Biyolojik Referans Saat Sapması" in t for t in titles_after_recompute),
            "recompute_all_conflicts sonrasında SD onaylı kaynak referans sapması tekrar açılmamalı",
        )
        self.assertTrue(
            any("Gerçekleşen Gözlem Biyolojik Pencere İhlali" in t for t in titles_after_recompute),
            "recompute_all_conflicts sonrasında gerçekleşmiş gözlem ihlali korunmalı",
        )

        # Kaynak referans saati tekrar değişirse (01:00 -> 04:00 = +180 dk > ±120 dk tolerans), yeni sapma yeniden değerlendirilmeli!
        r_new_ref = self.client.patch(
            f"/api/v1/planning/steps/{day7.id}/status",
            headers=h_tech1,
            json={
                "actual_reference_time": "2027-01-12T04:00:00",
                "actual_end": "2027-01-12T04:30:00",
            },
        )
        self.assertEqual(r_new_ref.status_code, 200, r_new_ref.text)
        self.assertEqual(len(r_new_ref.json()["revision_proposals"]), 2)
        self.db.expire_all()
        open_after_new_ref = (
            self.db.query(Conflict)
            .filter(Conflict.study_id == st.id, Conflict.is_resolved == False)  # noqa: E712
            .all()
        )
        titles_after_new_ref = [c.title for c in open_after_new_ref]
        self.assertTrue(
            any("Biyolojik Referans Saat Sapması" in t for t in titles_after_new_ref),
            "Kaynak referans saati tekrar değiştiğinde yeni sapma yeniden değerlendirilmeli",
        )
        self.assertTrue(
            any("Bağımlı Biyolojik Adım Sapması" in t for t in titles_after_new_ref),
            "Kaynak referans saati tekrar değiştiğinde bağımlı adımlar için yeni revizyon önerisi ve bulgu üretilmeli",
        )

    # ------------------------------------------------------------------
    # 20. Planlama ekranında SD Biyolojik Plan Revizyonu gerçek tarayıcı (Headless Chrome) testi
    # ------------------------------------------------------------------
    def test_20_biological_revision_headless_browser_e2e(self):
        import json as _json
        import socket
        import subprocess
        import threading
        import time as _time
        import uvicorn

        chrome_candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ]
        chrome_bin = next((p for p in chrome_candidates if os.path.exists(p)), None)
        if not chrome_bin:
            self.skipTest("Headless Chrome/Edge bulunamadı")

        sd = self.people["ezgi"]
        tech = self.people["invivo_1"]
        h_tech = _login_headers(self.client, "invivo_1")

        s_rev = Study(
            study_code="FIX20-BROWSER-REV",
            title="Browser E2E Biological Revision Study",
            test_item_name="Browser Rev Gel",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
            animal_species_strain="Tavşan (New Zealand White)",
            animal_count=3,
            extraction_polar=True,
            extraction_non_polar=False,
        )
        self.db.add(s_rev)
        self.db.commit()
        schedule_new_study(self.db, s_rev.id, date(2027, 2, 1))
        s_rev.status = StudyStatus.IN_PROGRESS
        self.db.commit()

        steps = (
            self.db.query(StudyStep)
            .filter(StudyStep.study_id == s_rev.id)
            .order_by(StudyStep.step_order.asc())
            .all()
        )
        day7 = next(s for s in steps if s.study_day == 7)  # 2027-02-08 09:00-12:00, Plan Ref: 10:00
        day8 = next(s for s in steps if s.study_day == 8)  # 2027-02-09 10:00-10:45

        # Kaynak adım (day7) gerçek referansını 13:00 (+180 dk) olarak kaydet
        r_ref = self.client.patch(
            f"/api/v1/planning/steps/{day7.id}/status",
            headers=h_tech,
            json={
                "status": "COMPLETED",
                "actual_start": "2027-02-08T12:00:00",
                "actual_reference_time": "2027-02-08T13:00:00",
                "actual_end": "2027-02-08T14:00:00",
            },
        )
        self.assertEqual(r_ref.status_code, 200, r_ref.text)

        sd_token = self.client.post(
            "/api/v1/auth/login",
            json={"username": "ezgi", "password": DEFAULT_PASSWORD},
        ).json()["access_token"]
        sd_user_info = self.client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {sd_token}"},
        ).json()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            for _ in range(50):
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    _time.sleep(0.1)

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s2:
                s2.bind(("127.0.0.1", 0))
                cdp_port = s2.getsockname()[1]

            user_data_dir = os.path.join(_TMP_DIR, "chrome_profile_rev")
            proc = subprocess.Popen(
                [
                    chrome_bin,
                    "--headless=new",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-default-browser-check",
                    f"--user-data-dir={user_data_dir}",
                    f"--remote-debugging-port={cdp_port}",
                    f"http://127.0.0.1:{port}/login",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                import base64
                import urllib.request
                from urllib.parse import urlparse

                ws_url = None
                for _ in range(50):
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list", timeout=0.5) as resp:
                            tabs = _json.loads(resp.read().decode("utf-8"))
                            page_tab = next((t for t in tabs if t.get("type") == "page"), None)
                            if page_tab and page_tab.get("webSocketDebuggerUrl"):
                                ws_url = page_tab["webSocketDebuggerUrl"]
                                break
                    except Exception:
                        _time.sleep(0.1)
                self.assertIsNotNone(ws_url, "Chrome CDP bağlantısı kurulamadı")

                parsed_ws = urlparse(ws_url)
                sock = socket.create_connection((parsed_ws.hostname, parsed_ws.port), timeout=10)
                key = base64.b64encode(os.urandom(16)).decode("ascii")
                handshake = (
                    f"GET {parsed_ws.path} HTTP/1.1\r\n"
                    f"Host: {parsed_ws.hostname}:{parsed_ws.port}\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Key: {key}\r\n"
                    "Sec-WebSocket-Version: 13\r\n\r\n"
                )
                sock.sendall(handshake.encode("ascii"))
                resp_buf = b""
                while b"\r\n\r\n" not in resp_buf:
                    resp_buf += sock.recv(1024)

                msg_id = 0

                def cdp_eval(js_expr: str):
                    nonlocal msg_id
                    msg_id += 1
                    payload_bytes = _json.dumps(
                        {
                            "id": msg_id,
                            "method": "Runtime.evaluate",
                            "params": {"expression": js_expr, "awaitPromise": True, "returnByValue": True},
                        }
                    ).encode("utf-8")
                    mask_key = os.urandom(4)
                    header = bytearray([0x81])
                    length = len(payload_bytes)
                    if length < 126:
                        header.append(0x80 | length)
                    elif length < 65536:
                        header.append(0x80 | 126)
                        header.extend(length.to_bytes(2, "big"))
                    else:
                        header.append(0x80 | 127)
                        header.extend(length.to_bytes(8, "big"))
                    header.extend(mask_key)
                    masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload_bytes))
                    sock.sendall(bytes(header) + masked)

                    while True:
                        first2 = sock.recv(2)
                        plen = first2[1] & 0x7F
                        if plen == 126:
                            plen = int.from_bytes(sock.recv(2), "big")
                        elif plen == 127:
                            plen = int.from_bytes(sock.recv(8), "big")
                        data = bytearray()
                        while len(data) < plen:
                            chunk = sock.recv(plen - len(data))
                            if not chunk:
                                break
                            data.extend(chunk)
                        msg = _json.loads(data.decode("utf-8"))
                        if msg.get("id") == msg_id:
                            return msg.get("result", {}).get("result", {}).get("value")

                # SD (ezgi) olarak oturum aç ve /planning?study_id=... ekranına git
                cdp_eval(
                    f"""
                    localStorage.setItem('nanolab_glp_jwt', {_json.dumps(sd_token)});
                    localStorage.setItem('nanolab_glp_user', {_json.dumps(_json.dumps(sd_user_info))});
                    window.location.href = 'http://127.0.0.1:{port}/planning?study_id={s_rev.id}';
                    true;
                    """
                )

                # FIX20-BROWSER-REV çalışmasının biyolojik revizyon kartının yüklenmesini bekle
                section_ready = False
                for _ in range(60):
                    has_sec = cdp_eval(
                        """
                        (() => {
                          return Boolean(document.querySelector('[data-testid="bio-revision-section"]'));
                        })()
                        """
                    )
                    if has_sec:
                        section_ready = True
                        break
                    _time.sleep(0.2)
                self.assertTrue(section_ready, "Planlama ekranında biyolojik revizyon bölümü yüklenmedi")

                # 1) "Revizyon Önizlemesi" butonuna tıkla ve önizleme panelinin açılmasını bekle
                cdp_eval(
                    """
                    document.querySelector('[data-testid="preview-bio-revision-btn"]').click();
                    true;
                    """
                )
                preview_ready = False
                for _ in range(40):
                    if cdp_eval("Boolean(document.querySelector('[data-testid=\"bio-revision-preview-panel\"]'))"):
                        preview_ready = True
                        break
                    _time.sleep(0.15)
                self.assertTrue(preview_ready, "Revizyon önizleme paneli açılmadı")

                preview_ui = cdp_eval(
                    f"""
                    (() => {{
                      const devBadge = document.querySelector('[data-testid="bio-source-deviation-badge"]')?.textContent || '';
                      const propRow = document.querySelector('[data-testid="bio-preview-proposed-{day8.step_order}"]')?.textContent || '';
                      const stepRowBefore = document.querySelector('[data-testid="schedule-step-planned-{day8.step_order}"]')?.textContent || '';
                      return {{ devBadge, propRow, stepRowBefore }};
                    }})()
                    """
                )
                self.assertIn("+180 dk", preview_ui["devBadge"])
                self.assertIn("13:00", preview_ui["propRow"])
                self.assertIn("10:00", preview_ui["stepRowBefore"], "Önizleme sırasında tablo saati henüz 10:00 olmalı")

                # 2) Gerekçe gir ve "Revizyonu Onayla ve Takvime İşle" butonuna tıkla
                e2e_reason = "Tarayıcı E2E SD Onayı: Dozlama 13:00'te gerçekleştiği için gözlem saatleri 13:00'e çekildi."
                cdp_eval(
                    f"""
                    (() => {{
                      const input = document.querySelector('[data-testid="bio-revision-reason-input"]');
                      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                      setter.call(input, {_json.dumps(e2e_reason)});
                      input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                      input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                      return true;
                    }})()
                    """
                )
                for _ in range(25):
                    btn_enabled = cdp_eval(
                        "Boolean(document.querySelector('[data-testid=\"approve-bio-revision-btn\"]') && !document.querySelector('[data-testid=\"approve-bio-revision-btn\"]').disabled)"
                    )
                    if btn_enabled:
                        break
                    _time.sleep(0.1)

                cdp_eval("document.querySelector('[data-testid=\"approve-bio-revision-btn\"]').click(); true;")

                approved_in_ui = False
                for _ in range(40):
                    if cdp_eval("Boolean(document.querySelector('[data-testid=\"bio-revision-history\"]'))"):
                        approved_in_ui = True
                        break
                    _time.sleep(0.15)
                self.assertTrue(approved_in_ui, "Onay sonrası revizyon geçmişi kartı görünmedi")

                # 3) Sayfayı yenile (reload) ve yeni saatler ile korunan kaynak sapmasını doğrula
                cdp_eval("window.location.reload(); true;")
                reloaded_ready = False
                for _ in range(60):
                    ok = cdp_eval(
                        """
                        (() => {
                          const cards = Array.from(document.querySelectorAll('button, div'));
                          const studyBtn = cards.find(el => (el.textContent || '').includes('FIX20-BROWSER-REV'));
                          if (studyBtn && !document.querySelector('[data-testid="bio-revision-history"]')) {
                            studyBtn.click();
                          }
                          return Boolean(document.querySelector('[data-testid="bio-revision-history"]'));
                        })()
                        """
                    )
                    if ok:
                        reloaded_ready = True
                        break
                    _time.sleep(0.2)
                self.assertTrue(reloaded_ready, "Sayfa yenilendikten sonra onaylı revizyon geçmişi yüklenmedi")

                after_reload = cdp_eval(
                    f"""
                    (() => {{
                      return {{
                        devBadge: document.querySelector('[data-testid="bio-source-deviation-badge"]')?.textContent || '',
                        approvedReason: document.querySelector('[data-testid="bio-approved-reason"]')?.textContent || '',
                        step8Planned: document.querySelector('[data-testid="schedule-step-planned-{day8.step_order}"]')?.textContent || '',
                        step7Planned: document.querySelector('[data-testid="schedule-step-planned-{day7.step_order}"]')?.textContent || '',
                      }};
                    }})()
                    """
                )
                self.assertIn("+180 dk", after_reload["devBadge"], "Kaynak sapması (+180 dk) sayfa yenileme sonrasında da korunmalı")
                self.assertIn(e2e_reason, after_reload["approvedReason"])
                self.assertIn("13:00", after_reload["step8Planned"], "24. saat gözlem adımı takvimde 13:00 olarak görünmeli")
                self.assertIn("09:00", after_reload["step7Planned"], "Kaynak adımın orijinal plan saati (09:00) korunmalı")

                sock.close()
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
        finally:
            server.should_exit = True
            thread.join(timeout=5)

    # ------------------------------------------------------------------
    # 21. SD Biyolojik Revizyon İnceleme Düzeltmeleri:
    #     - Önizlemenin kalıcı veri yazmaması (eksik oda ve cihaz tamamlama dalları dahil)
    #     - Zorunlu ve deterministik preview_token (_LATEST_PREVIEW_SNAPSHOTS bağımsız)
    #     - DELAYED + tüm actual_* boş adımın açıkça uygunsuz sayılması
    #     - İki ayrı Session ile simülasyon-uygulama arası eşzamanlı değişiklik koruması
    # ------------------------------------------------------------------
    def test_21_biological_revision_review_fixes_isolation_token_delayed_and_concurrency(self):
        from unittest.mock import patch
        from app.models.audit_log import AuditLog
        from app.models.calibration import SystemCalibration
        from app.models.room_capacity import AnimalRoomCapacity, ensure_default_room_capacities
        from app.seed import seed_default_equipment
        from app.services.templates import ensure_default_calibrations
        import app.services.scheduling_engine as se_mod
        from app.services.scheduling_engine import (
            _LATEST_PREVIEW_SNAPSHOTS,
            _build_biological_revision_snapshot,
            _evaluate_revision_candidate_obstacles,
            approve_biological_revision,
            preview_biological_revision,
        )

        sd_ezgi = self.people["ezgi"]
        tech1 = self.people["invivo_1"]
        h_ezgi = _login_headers(self.client, "ezgi")
        h_tech1 = _login_headers(self.client, "invivo_1")

        # Test çalışmasını ve ilişkili SampleRecord kaydını planla ve onayla
        st = Study(
            study_code="FIX21-REV-AUDIT",
            title="Fix 21 Revision Isolation & Concurrency Study",
            test_item_name="Audit Hydrogel",
            study_director_id=sd_ezgi.id,
            status=StudyStatus.DRAFT,
            animal_species_strain="Tavşan (New Zealand White)",
            animal_count=3,
            extraction_polar=True,
            extraction_non_polar=False,
        )
        sr = SampleRecord(
            study_code="FIX21-REV-AUDIT",
            test_item_name="Audit Hydrogel",
            planned_start=date(2027, 2, 4),
            planned_end=date(2027, 2, 14),
            stored_status="ONGOING",
        )
        self.db.add_all([st, sr])
        self.db.commit()

        r_sched = self.client.post(
            "/api/v1/planning/schedule-study",
            headers=h_ezgi,
            json={
                "study_code": "FIX21-REV-AUDIT",
                "template_code": "ISO_10993_23_IC",
                "acclimatization_start_date": "2027-02-04",
            },
        )
        self.assertEqual(r_sched.status_code, 200, r_sched.text)
        r_app = self.client.post(f"/api/v1/planning/studies/{st.id}/approve", headers=h_ezgi)
        self.assertEqual(r_app.status_code, 200, r_app.text)

        self.db.expire_all()
        steps = (
            self.db.query(StudyStep)
            .filter(StudyStep.study_id == st.id)
            .order_by(StudyStep.step_order.asc())
            .all()
        )
        day7 = next(s for s in steps if s.study_day == 7)   # G7: Uygulama (09:00-12:00, ref 10:00)
        day8 = next(s for s in steps if s.study_day == 8)   # G8: 24. Saat Gözlem (10:00-11:00)
        day9 = next(s for s in steps if s.study_day == 9)   # G9: 48. Saat Gözlem (10:00-11:00)
        day10 = next(s for s in steps if s.study_day == 10) # G10: 72. Saat Gözlem (10:00-12:00)

        # Kaynak adımı (G7 = 2027-02-11) gece 01:00 (+900 dk -> 2027-02-12 01:00) referansıyla tamamla:
        # -> G9 (2027-02-13) -> G10 (2027-02-14 01:00), G10 (2027-02-14) -> G11 (2027-02-15 01:00)
        # -> target_end_date 2027-02-14 -> 2027-02-15 önerisi oluşsun
        r_complete_d7 = self.client.patch(
            f"/api/v1/planning/steps/{day7.id}/status",
            headers=h_tech1,
            json={
                "status": "COMPLETED",
                "actual_start": "2027-02-11T22:00:00",
                "actual_reference_time": "2027-02-12T01:00:00",
                "actual_end": "2027-02-12T01:30:00",
            },
        )
        self.assertEqual(r_complete_d7.status_code, 200, r_complete_d7.text)

        # ==================================================================
        # BULGU 1 & BULGU 3 (Önizleme):
        # - Varsayılan kalibrasyon kaydını (ISO_10993_23_IC step_order=5),
        #   varsayılan oda kaydını (RABBIT_ROOM) sil ve cihaz varsayılan tamamlama
        #   dallarını (EQ-WB-001 kapasite alanları None + EQ-INC-001 eksik) tetikle.
        # - Ayrıca day8 adımını tüm actual_* alanları boş (None) olacak şekilde DELAYED yap.
        # - GET revision-preview sonrasında YENİ BİR Session ile kalibrasyon dahil
        #   hiçbir verinin kalıcılaşmadığını ve DELAYED adımın uygunsuz sayıldığını doğrula.
        # ==================================================================
        ensure_default_calibrations(self.db, commit=True)
        self.db.expire_all()
        day8_db = self.db.query(StudyStep).filter(StudyStep.id == day8.id).first()
        day8_db.status = StepStatus.DELAYED
        day8_db.actual_start = None
        day8_db.actual_end = None
        day8_db.actual_reference_time = None

        # Varsayılan SystemCalibration satırlarından birini sil
        self.db.query(SystemCalibration).filter(
            SystemCalibration.template_code == "ISO_10993_23_IC",
            SystemCalibration.step_order == 5,
        ).delete()

        # Varsayılan oda kaydını sil
        self.db.query(AnimalRoomCapacity).filter(AnimalRoomCapacity.room_code == "RABBIT_ROOM").delete()

        # Cihaz varsayılanlarını tamamlama dalını tetiklemek için:
        # 1) EQ-WB-001'in polar/nonpolar/max_concurrent_studies alanlarını None yap
        wb_eq = self.db.query(Equipment).filter(Equipment.code == "EQ-WB-001").first()
        if wb_eq:
            wb_eq.polar_capacity = None
            wb_eq.nonpolar_capacity = None
            wb_eq.max_concurrent_studies = None
        # 2) EQ-INC-001 cihazını başka adımlarda referans varsa temizleyip sil
        inc_eq = self.db.query(Equipment).filter(Equipment.code == "EQ-INC-001").first()
        if inc_eq:
            self.db.query(StudyStep).filter(StudyStep.equipment_id == inc_eq.id).update({"equipment_id": None})
            self.db.delete(inc_eq)
        self.db.commit()

        # Önizleme öncesi veritabanı durumunu yeni bir Session ile kaydet
        snap_before_s = SessionLocal()
        try:
            st_before = snap_before_s.query(Study).filter(Study.id == st.id).first()
            sr_before = snap_before_s.query(SampleRecord).filter(SampleRecord.study_code == st.study_code).first()
            steps_before = {
                s.id: (s.planned_start, s.planned_end, s.study_day, s.status)
                for s in snap_before_s.query(StudyStep).filter(StudyStep.study_id == st.id).all()
            }
            target_end_before = st_before.target_end_date
            sr_end_before = sr_before.planned_end
            status_before = st_before.status
            meta_before = dict(st_before.dossier_metadata or {})
            confs_before = [
                (c.id, c.conflict_type, c.title, c.is_resolved)
                for c in snap_before_s.query(Conflict)
                .filter(Conflict.study_id == st.id)
                .order_by(Conflict.id.asc())
                .all()
            ]
            audits_before = [
                a.id
                for a in snap_before_s.query(AuditLog).order_by(AuditLog.id.asc()).all()
            ]
            cals_before = [
                (c.id, c.template_code, c.step_order)
                for c in snap_before_s.query(SystemCalibration).order_by(SystemCalibration.id.asc()).all()
            ]
            self.assertIsNone(
                snap_before_s.query(SystemCalibration)
                .filter(
                    SystemCalibration.template_code == "ISO_10993_23_IC",
                    SystemCalibration.step_order == 5,
                )
                .first()
            )
            self.assertIsNone(
                snap_before_s.query(AnimalRoomCapacity).filter(AnimalRoomCapacity.room_code == "RABBIT_ROOM").first()
            )
            self.assertIsNone(
                snap_before_s.query(Equipment).filter(Equipment.code == "EQ-INC-001").first()
            )
        finally:
            snap_before_s.close()

        # GET /revision-preview çağrısı yap
        r_prev = self.client.get(
            f"/api/v1/planning/studies/{st.id}/revision-preview",
            headers=h_ezgi,
        )
        self.assertEqual(r_prev.status_code, 200, r_prev.text)
        prev_json = r_prev.json()
        self.assertTrue(prev_json["can_approve_revision"], prev_json)
        self.assertTrue(prev_json["target_end_date_changed"])
        self.assertEqual(prev_json["current_target_end_date"], "2027-02-14")
        self.assertEqual(prev_json["proposed_target_end_date"], "2027-02-15")

        # BULGU 3 kontrolü (Önizleme): DELAYED + tüm actual_* boş olan day8 uygunsuz olmalı!
        aff_orders = [x["step_order"] for x in prev_json["affected_steps"]]
        inelig_by_order = {x["step_order"]: x for x in prev_json["ineligible_steps"]}
        self.assertNotIn(day8.step_order, aff_orders, "DELAYED adım affected_steps içinde yer almamalı")
        self.assertIn(day8.step_order, inelig_by_order, "DELAYED adım ineligible_steps içinde yer almalı")
        self.assertFalse(inelig_by_order[day8.step_order]["eligible"])
        self.assertIn("DELAYED", inelig_by_order[day8.step_order]["ineligible_reason"])

        # BULGU 1 kontrolü: YENİ BİR Session ile önizlemenin kalibrasyon dahil hiçbir kalıcı veri yazmadığını doğrula!
        snap_after_s = SessionLocal()
        try:
            st_after = snap_after_s.query(Study).filter(Study.id == st.id).first()
            sr_after = snap_after_s.query(SampleRecord).filter(SampleRecord.study_code == st.study_code).first()
            steps_after = {
                s.id: (s.planned_start, s.planned_end, s.study_day, s.status)
                for s in snap_after_s.query(StudyStep).filter(StudyStep.study_id == st.id).all()
            }
            confs_after = [
                (c.id, c.conflict_type, c.title, c.is_resolved)
                for c in snap_after_s.query(Conflict)
                .filter(Conflict.study_id == st.id)
                .order_by(Conflict.id.asc())
                .all()
            ]
            audits_after = [
                a.id
                for a in snap_after_s.query(AuditLog).order_by(AuditLog.id.asc()).all()
            ]
            cals_after = [
                (c.id, c.template_code, c.step_order)
                for c in snap_after_s.query(SystemCalibration).order_by(SystemCalibration.id.asc()).all()
            ]

            self.assertEqual(steps_after, steps_before, "GET revision-preview adım saatlerini veya günlerini değiştirmemeli")
            self.assertEqual(st_after.target_end_date, target_end_before, "GET revision-preview target_end_date alanını değiştirmemeli")
            self.assertEqual(sr_after.planned_end, sr_end_before, "GET revision-preview SampleRecord.planned_end alanını değiştirmemeli")
            self.assertEqual(st_after.status, status_before, "GET revision-preview çalışma durumunu değiştirmemeli")
            self.assertEqual(dict(st_after.dossier_metadata or {}), meta_before, "GET revision-preview dossier_metadata alanını değiştirmemeli")
            self.assertNotIn("__PREVIEW_SIMULATION__", st_after.dossier_metadata or {})
            self.assertEqual(confs_after, confs_before, "GET revision-preview Conflict kayıtlarını değiştirmemeli")
            self.assertEqual(audits_after, audits_before, "GET revision-preview AuditLog kaydı üretmemeli")
            self.assertEqual(cals_after, cals_before, "GET revision-preview SystemCalibration kayıtlarını değiştirmemeli")
            self.assertIsNone(
                snap_after_s.query(SystemCalibration)
                .filter(
                    SystemCalibration.template_code == "ISO_10993_23_IC",
                    SystemCalibration.step_order == 5,
                )
                .first(),
                "GET revision-preview eksik SystemCalibration satırını veritabanına commit etmemeli",
            )
            self.assertIsNone(
                snap_after_s.query(AnimalRoomCapacity).filter(AnimalRoomCapacity.room_code == "RABBIT_ROOM").first(),
                "GET revision-preview eksik oda varsayılanını veritabanına commit etmemeli",
            )
            self.assertIsNone(
                snap_after_s.query(Equipment).filter(Equipment.code == "EQ-INC-001").first(),
                "GET revision-preview eksik cihaz varsayılanını veritabanına commit etmemeli",
            )
            wb_after = snap_after_s.query(Equipment).filter(Equipment.code == "EQ-WB-001").first()
            self.assertIsNone(wb_after.polar_capacity, "GET revision-preview cihaz alanlarını veritabanına commit etmemeli")
        finally:
            snap_after_s.close()

        # BULGU 1 ek kontrolü: preview_biological_revision çağıranın bekleyen işlemlerini (hem flush edilmiş hem flush edilmemiş)
        # kaydetmemeli (commit etmemeli) veya geri almamalı (rollback etmemeli)!
        s_caller_pending = SessionLocal()
        try:
            flushed_marker = AuditLog(
                user_id=sd_ezgi.id,
                action="CALLER_PENDING_FLUSHED",
                entity_name="Study",
                entity_id=st.id,
                reason="Önizleme çağıranın flush edilmiş işlemini commit veya rollback etmemeli",
            )
            s_caller_pending.add(flushed_marker)
            s_caller_pending.flush()
            flushed_marker_id = flushed_marker.id

            unflushed_marker = AuditLog(
                user_id=sd_ezgi.id,
                action="CALLER_PENDING_UNFLUSHED",
                entity_name="Study",
                entity_id=st.id,
                reason="Önizleme çağıranın henüz flush edilmemiş işlemini flush/commit/rollback etmemeli",
            )
            s_caller_pending.add(unflushed_marker)

            # Kalibrasyon satırı hala eksikken doğrudan preview_biological_revision çağır
            prev_direct = preview_biological_revision(s_caller_pending, st.id)
            self.assertEqual(prev_direct["preview_token"], prev_json["preview_token"])

            # 1) Başka bir Session'dan bakıldığında çağıranın bekleyen işlemleri commit edilmemiş olmalı!
            s_ext_check = SessionLocal()
            try:
                self.assertIsNone(
                    s_ext_check.query(AuditLog).filter(AuditLog.id == flushed_marker_id).first(),
                    "preview_biological_revision çağıranın bekleyen işlemini commit etmemeli!",
                )
                self.assertEqual(
                    s_ext_check.query(AuditLog).filter(AuditLog.action == "CALLER_PENDING_UNFLUSHED").count(),
                    0,
                    "preview_biological_revision çağıranın bekleyen işlemini flush/commit etmemeli!",
                )
            finally:
                s_ext_check.close()

            # 2) Çağıran Session içinde ise hem flush edilmiş işlem hem de s.new içindeki nesne korunmuş olmalı (rollback edilmemiş olmalı)
            #    ve s.dirty içine simülasyondan hiçbir kirli nesne kalmamış olmalı!
            self.assertIn(unflushed_marker, s_caller_pending.new)
            self.assertEqual(set(s_caller_pending.dirty), set(), "Önizleme sonrasında Session.dirty içinde kirli nesne kalmamalı")
            self.assertIsNotNone(
                s_caller_pending.query(AuditLog).filter(AuditLog.id == flushed_marker_id).first(),
                "preview_biological_revision çağıranın bekleyen işlemini rollback ile geri almamalı!",
            )
            s_caller_pending.rollback()
        finally:
            s_caller_pending.close()

        # Sonraki test adımları için varsayılan kalibrasyon, oda ve cihaz kayıtlarını geri yükle
        ensure_default_calibrations(self.db, commit=True)
        ensure_default_room_capacities(self.db, commit=True)
        seed_default_equipment(self.db, commit=True)

        # ==================================================================
        # BULGU 2:
        # - Onay isteğinde geçerli preview_token zorunlu olsun.
        # - Bellek içi _LATEST_PREVIEW_SNAPSHOTS temizlendiğinde ve ayrı Session
        #   kullanıldığında da deterministik çalışsın:
        #   1) Tokensız / boş token istekleri 422 ile veri değiştirmeden reddedilsin.
        #   2) Kaynak referans değişince eski token 409 dönsün.
        #   3) Güncel token (_LATEST_PREVIEW_SNAPSHOTS boşken bile) kabul edilsin.
        # ==================================================================
        token_0100 = prev_json["preview_token"]
        self.assertTrue(token_0100)

        # Bellek içi önbelleği tamamen temizle
        _LATEST_PREVIEW_SNAPSHOTS.clear()

        # 2a) Tokensız ve boş tokenlı onay istekleri reddedilmeli (422)
        for bad_payload in [
            {"reason": "Tokensız onay denemesi"},
            {"reason": "Null token denemesi", "preview_token": None},
            {"reason": "Boş string token denemesi", "preview_token": ""},
            {"reason": "Boşluk token denemesi", "preview_token": "   "},
        ]:
            r_bad_tok = self.client.post(
                f"/api/v1/planning/studies/{st.id}/approve-revision",
                headers=h_ezgi,
                json=bad_payload,
            )
            self.assertEqual(r_bad_tok.status_code, 422, f"Payload reddedilmeliydi: {bad_payload} -> {r_bad_tok.text}")

        # Ayrı bir Session ile doğrudan servis katmanında da boş tokenın ValueError fırlattığını doğrula
        s_tok_check = SessionLocal()
        try:
            with self.assertRaises(ValueError):
                approve_biological_revision(
                    s_tok_check,
                    st.id,
                    reason="Serviste tokensız çağrı",
                    user=sd_ezgi,
                    preview_token=None,
                )
            d9_check = s_tok_check.query(StudyStep).filter(StudyStep.id == day9.id).first()
            self.assertEqual(d9_check.planned_start, datetime(2027, 2, 13, 10, 0))
        finally:
            s_tok_check.close()

        # 2b) Kaynak referans saati (01:00 -> 02:00) değiştiğinde eski token (token_0100) 409 ile reddedilmeli!
        r_shift_0200 = self.client.patch(
            f"/api/v1/planning/steps/{day7.id}/status",
            headers=h_tech1,
            json={
                "actual_reference_time": "2027-02-12T02:00:00",
                "actual_end": "2027-02-12T02:30:00",
            },
        )
        self.assertEqual(r_shift_0200.status_code, 200, r_shift_0200.text)

        _LATEST_PREVIEW_SNAPSHOTS.clear()
        r_stale_tok = self.client.post(
            f"/api/v1/planning/studies/{st.id}/approve-revision",
            headers=h_ezgi,
            json={
                "reason": "Eski 01:00 önizleme tokenı ile onay denemesi",
                "preview_token": token_0100,
            },
        )
        self.assertEqual(r_stale_tok.status_code, 409, r_stale_tok.text)

        # Eski token reddedildiğinde hiçbir adımın değişmediğini ayrı Session ile doğrula
        s_verify_stale = SessionLocal()
        try:
            d9_stale = s_verify_stale.query(StudyStep).filter(StudyStep.id == day9.id).first()
            st_stale = s_verify_stale.query(Study).filter(Study.id == st.id).first()
            self.assertEqual(d9_stale.planned_start, datetime(2027, 2, 13, 10, 0))
            self.assertEqual(st_stale.target_end_date, date(2027, 2, 14))
            self.assertEqual(len((st_stale.dossier_metadata or {}).get("biological_revisions") or []), 0)
        finally:
            s_verify_stale.close()

        # ==================================================================
        # BULGU 4:
        # - Simülasyon yardımcısının çağıranın transaction'ını kapatmadığını doğrula.
        # - İki ayrı Session kullanan kontrollü eşzamanlılık testleri:
        #   4a) Simülasyondan hemen sonra kaynak referans saati değişirse eski öneri uygulanmamalı (409).
        #   4b) Simülasyondan hemen sonra önerilen pencereye personel engeli eklenirse revizyon kaydedilmemeli (409).
        #   4c) Simülasyondan hemen sonra önerilen pencereye cihaz engeli eklenirse revizyon kaydedilmemeli (409).
        #   Reddedilen işlemlerde adım planları, revizyon geçmişi ve AuditLog kısmi oluşmamalı.
        # ==================================================================
        # Önce güncel 02:00 durumu için geçerli preview_token al ve önbelleği temizle
        prev_0200 = self.client.get(
            f"/api/v1/planning/studies/{st.id}/revision-preview",
            headers=h_ezgi,
        ).json()
        token_0200 = prev_0200["preview_token"]
        _LATEST_PREVIEW_SNAPSHOTS.clear()

        # 4.0) _evaluate_revision_candidate_obstacles çağıranın transaction'ını rollback ile kapatmamalı
        s_tx_check = SessionLocal()
        try:
            st_tx = s_tx_check.query(Study).filter(Study.id == st.id).first()
            steps_tx = (
                s_tx_check.query(StudyStep)
                .filter(StudyStep.study_id == st.id)
                .order_by(StudyStep.step_order.asc())
                .all()
            )
            # Çağıran session içinde flush edilmiş geçici bir AuditLog oluştur
            marker_log = AuditLog(
                user_id=sd_ezgi.id,
                action="CALLER_TX_MARKER",
                entity_name="Study",
                entity_id=st.id,
                reason="Transaction korunuyor mu kontrolü",
            )
            s_tx_check.add(marker_log)
            s_tx_check.flush()
            marker_id = marker_log.id
            self.assertIsNotNone(marker_id)

            _evaluate_revision_candidate_obstacles(
                s_tx_check,
                st_tx,
                steps_tx,
                [
                    {
                        "step_id": day9.id,
                        "expected_start": "2027-02-14T02:00:00",
                        "expected_end": "2027-02-14T03:00:00",
                        "proposed_study_day": 10,
                    }
                ],
                [
                    {
                        "source_step_id": day7.id,
                        "actual_reference_time": "2027-02-12T02:00:00",
                    }
                ],
                date(2027, 2, 15),
            )
            # Çağıranın flush ettiği marker_log hala aynı transaction içinde durmalı (rollback edilmemiş olmalı!)
            still_in_tx = s_tx_check.query(AuditLog).filter(AuditLog.id == marker_id).first()
            self.assertIsNotNone(
                still_in_tx,
                "_evaluate_revision_candidate_obstacles çağıranın transaction'ını rollback ile kapatmamalı!",
            )
            s_tx_check.rollback()
        finally:
            s_tx_check.close()

        # 4a) Simülasyondan hemen sonra ikinci bir Session ile kaynak referans saati (02:00 -> 03:00) değiştirilirse:
        orig_eval = _evaluate_revision_candidate_obstacles

        def eval_then_concurrent_ref_change(*args, **kwargs):
            res = orig_eval(*args, **kwargs)
            s_concurrent = SessionLocal()
            try:
                d7_c = s_concurrent.query(StudyStep).filter(StudyStep.id == day7.id).first()
                d7_c.actual_reference_time = datetime(2027, 2, 12, 3, 0)
                d7_c.actual_end = datetime(2027, 2, 12, 3, 30)
                s_concurrent.commit()
            finally:
                s_concurrent.close()
            return res

        with patch.object(se_mod, "_evaluate_revision_candidate_obstacles", side_effect=eval_then_concurrent_ref_change):
            r_race_ref = self.client.post(
                f"/api/v1/planning/studies/{st.id}/approve-revision",
                headers=h_ezgi,
                json={
                    "reason": "Simülasyon sonrası eşzamanlı referans değişimi testi",
                    "preview_token": token_0200,
                },
            )
        self.assertEqual(r_race_ref.status_code, 409, r_race_ref.text)

        # Reddedilen işlemde kısmi veri (adım planı, dossier_metadata, AuditLog) oluşmadığını yeni Session ile doğrula
        s_ver_4a = SessionLocal()
        try:
            st_4a = s_ver_4a.query(Study).filter(Study.id == st.id).first()
            d9_4a = s_ver_4a.query(StudyStep).filter(StudyStep.id == day9.id).first()
            d10_4a = s_ver_4a.query(StudyStep).filter(StudyStep.id == day10.id).first()
            self.assertEqual(d9_4a.planned_start, datetime(2027, 2, 13, 10, 0), "Eski öneri uygulanmamalı")
            self.assertEqual(d10_4a.planned_start, datetime(2027, 2, 14, 10, 0), "Eski öneri uygulanmamalı")
            self.assertEqual(st_4a.target_end_date, date(2027, 2, 14))
            self.assertEqual(len((st_4a.dossier_metadata or {}).get("biological_revisions") or []), 0)
            self.assertEqual(
                s_ver_4a.query(AuditLog)
                .filter(AuditLog.entity_name == "Study", AuditLog.entity_id == st.id, AuditLog.action == "APPROVE_BIOLOGICAL_REVISION")
                .count(),
                0,
            )
        finally:
            s_ver_4a.close()

        # 4b) Simülasyondan hemen sonra ikinci bir Session ile önerilen pencereye (2027-02-14 03:00-04:00)
        #     PERSONEL ENGELİ (aynı teknisyene başka aktif çalışmada adım) eklenirse revizyon kaydedilmemeli (409)!
        prev_0300 = self.client.get(
            f"/api/v1/planning/studies/{st.id}/revision-preview",
            headers=h_ezgi,
        ).json()
        self.assertTrue(prev_0300["can_approve_revision"], prev_0300)
        token_0300 = prev_0300["preview_token"]
        _LATEST_PREVIEW_SNAPSHOTS.clear()

        # Rakip çalışma oluştur ve day9'un atanmış teknisyenini bul
        s_setup_other = SessionLocal()
        try:
            d9_for_tech = s_setup_other.query(StudyStep).filter(StudyStep.id == day9.id).first()
            target_tech_id = d9_for_tech.assignees[0].id if d9_for_tech.assignees else tech1.id
            other_study = Study(
                study_code="FIX21-RIVAL-STUDY",
                title="Rival Concurrent Study",
                test_item_name="Rival Item",
                study_director_id=sd_ezgi.id,
                status=StudyStatus.APPROVED,
                acclimatization_start_date=date(2027, 2, 4),
                target_end_date=date(2027, 2, 20),
            )
            s_setup_other.add(other_study)
            s_setup_other.commit()
            other_study_id = other_study.id
        finally:
            s_setup_other.close()

        rival_step_id_holder = []

        def eval_then_concurrent_personnel_obstacle(*args, **kwargs):
            res = orig_eval(*args, **kwargs)
            s_concurrent = SessionLocal()
            try:
                # İkinci Session bir SystemCalibration satırını silsin VE önerilen pencereye personel engeli eklesin!
                s_concurrent.query(SystemCalibration).filter(
                    SystemCalibration.template_code == "ISO_10993_23_IC",
                    SystemCalibration.step_order == 6,
                ).delete()
                tech_c = s_concurrent.query(User).filter(User.id == target_tech_id).first()
                rival_step = StudyStep(
                    study_id=other_study_id,
                    step_name="Eşzamanlı Eklenen Rakip Gözlem",
                    step_order=99,
                    study_day=10,
                    planned_start=datetime(2027, 2, 14, 3, 0),
                    planned_end=datetime(2027, 2, 14, 4, 0),
                    status=StepStatus.PENDING,
                )
                rival_step.assignees.append(tech_c)
                s_concurrent.add(rival_step)
                s_concurrent.commit()
                rival_step_id_holder.append(rival_step.id)
            finally:
                s_concurrent.close()
            return res

        with patch.object(se_mod, "_evaluate_revision_candidate_obstacles", side_effect=eval_then_concurrent_personnel_obstacle):
            r_race_pers = self.client.post(
                f"/api/v1/planning/studies/{st.id}/approve-revision",
                headers=h_ezgi,
                json={
                    "reason": "Simülasyon sonrası eşzamanlı kalibrasyon silme + personel çakışması testi",
                    "preview_token": token_0300,
                },
            )
        self.assertEqual(r_race_pers.status_code, 409, r_race_pers.text)

        # Reddedilen işlemde yeni Session ile adım saatlerinin, target_end_date, SampleRecord.planned_end,
        # biological_revisions ve onay AuditLog kayıtlarının değişmediğini; ikinci Session'ın kendi yaptığı
        # değişikliklerin (silinen SystemCalibration satırı ve eklenen rival_step) ise korunduğunu doğrula!
        s_ver_4b = SessionLocal()
        try:
            st_4b = s_ver_4b.query(Study).filter(Study.id == st.id).first()
            sr_4b = s_ver_4b.query(SampleRecord).filter(SampleRecord.study_code == st.study_code).first()
            d9_4b = s_ver_4b.query(StudyStep).filter(StudyStep.id == day9.id).first()
            d10_4b = s_ver_4b.query(StudyStep).filter(StudyStep.id == day10.id).first()
            self.assertEqual(d9_4b.planned_start, datetime(2027, 2, 13, 10, 0), "Personel engeli varken adım kaydırılmamalı")
            self.assertEqual(d9_4b.planned_end, datetime(2027, 2, 13, 11, 0))
            self.assertEqual(d9_4b.study_day, 9)
            self.assertEqual(d10_4b.planned_start, datetime(2027, 2, 14, 10, 0), "Personel engeli varken adım kaydırılmamalı")
            self.assertEqual(d10_4b.planned_end, datetime(2027, 2, 14, 12, 0))
            self.assertEqual(d10_4b.study_day, 10)
            self.assertEqual(st_4b.target_end_date, date(2027, 2, 14), "target_end_date değişmemeli")
            self.assertEqual(sr_4b.planned_end, date(2027, 2, 14), "SampleRecord.planned_end değişmemeli")
            self.assertEqual(len((st_4b.dossier_metadata or {}).get("biological_revisions") or []), 0)
            self.assertEqual(
                s_ver_4b.query(AuditLog)
                .filter(AuditLog.entity_name == "Study", AuditLog.entity_id == st.id, AuditLog.action == "APPROVE_BIOLOGICAL_REVISION")
                .count(),
                0,
            )
            # İkinci Session'ın kendi yaptığı değişiklikler korunmalı!
            self.assertEqual(len(rival_step_id_holder), 1)
            self.assertIsNotNone(
                s_ver_4b.query(StudyStep).filter(StudyStep.id == rival_step_id_holder[0]).first(),
                "İkinci Session'ın eklediği rival_step korunmalı",
            )
            self.assertIsNone(
                s_ver_4b.query(SystemCalibration)
                .filter(
                    SystemCalibration.template_code == "ISO_10993_23_IC",
                    SystemCalibration.step_order == 6,
                )
                .first(),
                "İkinci Session'ın sildiği SystemCalibration satırı get_template tarafından yeniden commit edilmemeli!",
            )
            # Rakip adımı temizle ve kalibrasyonu geri yükle
            for rsid in rival_step_id_holder:
                rs_obj = s_ver_4b.query(StudyStep).filter(StudyStep.id == rsid).first()
                if rs_obj:
                    rs_obj.assignees.clear()
                    s_ver_4b.delete(rs_obj)
            s_ver_4b.commit()
            ensure_default_calibrations(s_ver_4b, commit=True)
        finally:
            s_ver_4b.close()

        # 4c) Simülasyondan hemen sonra ikinci bir Session ile önerilen pencereye (2027-02-14 03:00-04:00)
        #     CİHAZ ENGELİ (aynı cihazı kullanan başka adım) eklenirse revizyon kaydedilmemeli (409)!
        s_eq_setup = SessionLocal()
        try:
            eq_inc = s_eq_setup.query(Equipment).filter(Equipment.code == "EQ-INC-001").first()
            orig_inc_max_conc = eq_inc.max_concurrent_studies
            eq_inc.max_concurrent_studies = 1
            d9_eq = s_eq_setup.query(StudyStep).filter(StudyStep.id == day9.id).first()
            d9_eq.equipment_id = eq_inc.id
            s_eq_setup.commit()
            eq_inc_id = eq_inc.id
        finally:
            s_eq_setup.close()

        prev_0300_eq = self.client.get(
            f"/api/v1/planning/studies/{st.id}/revision-preview",
            headers=h_ezgi,
        ).json()
        self.assertTrue(prev_0300_eq["can_approve_revision"], prev_0300_eq)
        token_0300_eq = prev_0300_eq["preview_token"]
        _LATEST_PREVIEW_SNAPSHOTS.clear()

        rival_eq_step_holder = []

        def eval_then_concurrent_equipment_obstacle(*args, **kwargs):
            res = orig_eval(*args, **kwargs)
            s_concurrent = SessionLocal()
            try:
                rival_eq_step = StudyStep(
                    study_id=other_study_id,
                    step_name="Eşzamanlı Eklenen Cihaz İşgali",
                    step_order=100,
                    study_day=10,
                    planned_start=datetime(2027, 2, 14, 3, 0),
                    planned_end=datetime(2027, 2, 14, 4, 0),
                    status=StepStatus.PENDING,
                    equipment_id=eq_inc_id,
                )
                s_concurrent.add(rival_eq_step)
                s_concurrent.commit()
                rival_eq_step_holder.append(rival_eq_step.id)
            finally:
                s_concurrent.close()
            return res

        with patch.object(se_mod, "_evaluate_revision_candidate_obstacles", side_effect=eval_then_concurrent_equipment_obstacle):
            r_race_eq = self.client.post(
                f"/api/v1/planning/studies/{st.id}/approve-revision",
                headers=h_ezgi,
                json={
                    "reason": "Simülasyon sonrası eşzamanlı cihaz çakışması testi",
                    "preview_token": token_0300_eq,
                },
            )
        self.assertEqual(r_race_eq.status_code, 409, r_race_eq.text)

        s_ver_4c = SessionLocal()
        try:
            st_4c = s_ver_4c.query(Study).filter(Study.id == st.id).first()
            d9_4c = s_ver_4c.query(StudyStep).filter(StudyStep.id == day9.id).first()
            self.assertEqual(d9_4c.planned_start, datetime(2027, 2, 13, 10, 0), "Cihaz engeli varken adım kaydırılmamalı")
            self.assertEqual(st_4c.target_end_date, date(2027, 2, 14))
            self.assertEqual(len((st_4c.dossier_metadata or {}).get("biological_revisions") or []), 0)
            self.assertEqual(
                s_ver_4c.query(AuditLog)
                .filter(AuditLog.entity_name == "Study", AuditLog.entity_id == st.id, AuditLog.action == "APPROVE_BIOLOGICAL_REVISION")
                .count(),
                0,
            )
            for rsid in rival_eq_step_holder:
                s_ver_4c.query(StudyStep).filter(StudyStep.id == rsid).delete()
            eq_inc_restore = s_ver_4c.query(Equipment).filter(Equipment.code == "EQ-INC-001").first()
            if eq_inc_restore is not None:
                eq_inc_restore.max_concurrent_studies = orig_inc_max_conc
            s_ver_4c.commit()
        finally:
            s_ver_4c.close()

        # ==================================================================
        # BULGU 2 EK DOĞRULAMA:
        # - preview_token öneriyi belirleyen bağlamı (Gün 0, template_code) ve
        #   hesaplanan önerilerin kararlı temsilini (hedef adım kimliği, önerilen
        #   başlangıç/bitiş, önerilen study_day ve önerilen çalışma bitişi) içermeli;
        #   aynı veri aynı token'ı üretmeli.
        # - Önizleme sonrasında YALNIZCA Gün 0 (acclimatization_start_date) değiştiğinde
        #   önerilen çalışma günlerinin değiştiğini ve eski token'ın hiçbir veri
        #   yazılmadan 409 ile reddedildiğini, güncel önizlemeyle ise normal onayın
        #   çalıştığını doğrula.
        # ==================================================================
        prev_g0_a = self.client.get(
            f"/api/v1/planning/studies/{st.id}/revision-preview",
            headers=h_ezgi,
        ).json()
        prev_g0_b = self.client.get(
            f"/api/v1/planning/studies/{st.id}/revision-preview",
            headers=h_ezgi,
        ).json()
        self.assertEqual(prev_g0_a["preview_token"], prev_g0_b["preview_token"], "Aynı veri aynı preview_token üretmeli")
        token_before_g0_change = prev_g0_a["preview_token"]
        aff_before_g0 = {x["step_order"]: x for x in prev_g0_a["affected_steps"]}
        self.assertEqual(aff_before_g0[day9.step_order]["proposed_study_day"], 10)
        self.assertEqual(aff_before_g0[day10.step_order]["proposed_study_day"], 11)

        # Yalnızca Gün 0'ı (acclimatization_start_date: 2027-02-04 -> 2027-02-03) değiştir
        s_change_g0 = SessionLocal()
        try:
            st_g0 = s_change_g0.query(Study).filter(Study.id == st.id).first()
            snap_check = _build_biological_revision_snapshot(
                st_g0,
                s_change_g0.query(StudyStep)
                .filter(StudyStep.study_id == st.id, StudyStep.status != StepStatus.CANCELLED)
                .order_by(StudyStep.step_order.asc())
                .all(),
            )
            self.assertEqual(snap_check["template_code"], "ISO_10993_23_IC")
            self.assertEqual(snap_check["acclimatization_start_date"], "2027-02-04")
            self.assertEqual(snap_check["proposed_target_end_date"], "2027-02-15")
            self.assertEqual(len(snap_check["proposals"]), 2)

            st_g0.acclimatization_start_date = date(2027, 2, 3)
            s_change_g0.commit()
        finally:
            s_change_g0.close()

        # Yeni önizlemede önerilen çalışma günleri (10->11 ve 11->12) ve preview_token değişmiş olmalı!
        prev_after_g0 = self.client.get(
            f"/api/v1/planning/studies/{st.id}/revision-preview",
            headers=h_ezgi,
        ).json()
        aff_after_g0 = {x["step_order"]: x for x in prev_after_g0["affected_steps"]}
        self.assertEqual(aff_after_g0[day9.step_order]["proposed_study_day"], 11)
        self.assertEqual(aff_after_g0[day10.step_order]["proposed_study_day"], 12)
        self.assertNotEqual(
            prev_after_g0["preview_token"],
            token_before_g0_change,
            "Gün 0 ve önerilen study_day değiştiğinde preview_token değişmeli",
        )

        # Eski token (token_before_g0_change) hiçbir veri yazılmadan 409 ile reddedilmeli!
        _LATEST_PREVIEW_SNAPSHOTS.clear()
        r_old_g0_tok = self.client.post(
            f"/api/v1/planning/studies/{st.id}/approve-revision",
            headers=h_ezgi,
            json={
                "reason": "Gün 0 değişimi öncesi eski token ile onay denemesi",
                "preview_token": token_before_g0_change,
            },
        )
        self.assertEqual(r_old_g0_tok.status_code, 409, r_old_g0_tok.text)

        s_ver_g0 = SessionLocal()
        try:
            d9_g0 = s_ver_g0.query(StudyStep).filter(StudyStep.id == day9.id).first()
            st_g0_ver = s_ver_g0.query(Study).filter(Study.id == st.id).first()
            sr_g0_ver = s_ver_g0.query(SampleRecord).filter(SampleRecord.study_code == st.study_code).first()
            self.assertEqual(d9_g0.planned_start, datetime(2027, 2, 13, 10, 0), "Eski token reddedildiğinde adım saati değişmemeli")
            self.assertEqual(d9_g0.study_day, 9, "Eski token reddedildiğinde study_day değişmemeli")
            self.assertEqual(st_g0_ver.target_end_date, date(2027, 2, 14))
            self.assertEqual(sr_g0_ver.planned_end, date(2027, 2, 14))
            self.assertEqual(len((st_g0_ver.dossier_metadata or {}).get("biological_revisions") or []), 0)
            self.assertEqual(
                s_ver_g0.query(AuditLog)
                .filter(AuditLog.entity_name == "Study", AuditLog.entity_id == st.id, AuditLog.action == "APPROVE_BIOLOGICAL_REVISION")
                .count(),
                0,
            )
        finally:
            s_ver_g0.close()

        # ==================================================================
        # SON DOĞRULAMA (Güncel Önizlemeyle Normal Onay + BULGU 3 Onay):
        # - _LATEST_PREVIEW_SNAPSHOTS boşken ve ayrı Session üzerinde güncel
        #   prev_after_g0["preview_token"] ile onay başarılı olmalı!
        # - Onay sonrasında DELAYED + tüm actual_* boş olan day8 kesinlikle
        #   değişmemeli; yalnızca PENDING olan day9 ve day10 yeni saatlere ve
        #   yeni Gün 0'a göre hesaplanan study_day (11 ve 12) değerlerine güncellenmeli!
        # ==================================================================
        _LATEST_PREVIEW_SNAPSHOTS.clear()
        s_approve_separate = SessionLocal()
        try:
            sd_in_sep = s_approve_separate.query(User).filter(User.id == sd_ezgi.id).first()
            approved_res = approve_biological_revision(
                s_approve_separate,
                st.id,
                reason="Ayrı Session ve temiz önbellek ile güncel önizleme tokenı onayı",
                user=sd_in_sep,
                preview_token=prev_after_g0["preview_token"],
            )
            self.assertEqual(approved_res["target_end_date"], "2027-02-15")
        finally:
            s_approve_separate.close()

        s_final = SessionLocal()
        try:
            d8_final = s_final.query(StudyStep).filter(StudyStep.id == day8.id).first()
            d9_final = s_final.query(StudyStep).filter(StudyStep.id == day9.id).first()
            d10_final = s_final.query(StudyStep).filter(StudyStep.id == day10.id).first()
            st_final = s_final.query(Study).filter(Study.id == st.id).first()
            sr_final = s_final.query(SampleRecord).filter(SampleRecord.study_code == st.study_code).first()

            # DELAYED + tüm actual_* boş olan day8 korunmuş olmalı
            self.assertEqual(d8_final.status, StepStatus.DELAYED)
            self.assertIsNone(d8_final.actual_start)
            self.assertIsNone(d8_final.actual_end)
            self.assertIsNone(d8_final.actual_reference_time)
            self.assertEqual(d8_final.planned_start, datetime(2027, 2, 12, 10, 0), "DELAYED adımın plan saati değişmemeli")
            self.assertEqual(d8_final.planned_end, datetime(2027, 2, 12, 11, 0), "DELAYED adımın plan bitişi değişmemeli")
            self.assertEqual(d8_final.study_day, 8, "DELAYED adımın çalışma günü değişmemeli")

            # PENDING olan day9 ve day10 ise 03:00 referansı ve güncel Gün 0 (2027-02-03) ile güncellenmiş olmalı
            self.assertEqual(d9_final.planned_start, datetime(2027, 2, 14, 3, 0))
            self.assertEqual(d9_final.planned_end, datetime(2027, 2, 14, 4, 0))
            self.assertEqual(d9_final.study_day, 11)
            self.assertEqual(d10_final.planned_start, datetime(2027, 2, 15, 3, 0))
            self.assertEqual(d10_final.planned_end, datetime(2027, 2, 15, 5, 0))
            self.assertEqual(d10_final.study_day, 12)
            self.assertEqual(st_final.target_end_date, date(2027, 2, 15))
            self.assertEqual(sr_final.planned_end, date(2027, 2, 15))
            self.assertEqual(len((st_final.dossier_metadata or {}).get("biological_revisions") or []), 1)
            self.assertEqual(
                s_final.query(AuditLog)
                .filter(AuditLog.entity_name == "Study", AuditLog.entity_id == st.id, AuditLog.action == "APPROVE_BIOLOGICAL_REVISION")
                .count(),
                1,
            )
        finally:
            s_final.close()

    def test_22_equipment_peak_concurrent_usage_and_half_open_boundary(self):
        """
        CİHAZ KAPASİTESİNDE GERÇEK EŞZAMANLI TEPE KULLANIM (PEAK CONCURRENT USAGE), YARI-AÇIK ARALIK [start, end),
        KURULUM / REZERVASYON SÜRESİ AYRIMI VE TANIMLI 1/2/4 KAPASİTE TUTARLILIĞI TESTİ:
          - Kurulum görevleri 24/72 saatlik insan görevlerine dönüştürülmez (90 dk insan kurulum görevi korunur);
            tamamı 72 saat olan protokol cihaz rezervasyonlarıyla:
              * Çalışma A: Gün 3 08:00 – Gün 6 08:00 (72 saat rezervasyon, kurulum Gün 3 08:00–09:30)
              * Çalışma B: Gün 1 08:00 – Gün 4 08:00 (72 saat rezervasyon, kurulum Gün 1 08:00–09:30)
              * Çalışma C: Gün 4 08:00 – Gün 7 08:00 (72 saat rezervasyon, kurulum Gün 4 08:00–09:30;
                B tam Gün 4 08:00'da biterken C Gün 4 08:00'da başlar, çakışmaz)
          - A hem B hem C ile kesişmesine rağmen hiçbir anda 2 kapasiteyi aşmaz (peak = 2);
            yanlış EQUIPMENT_OVERLAP / Uzun Süreli Cihaz Kapasite Aşımı üretilmez ve her üçü de onaylanabilir.
          - Gerçek 3. eşzamanlı rezervasyon (Çalışma D: Gün 2 08:00 – Gün 5 08:00, 72 saat) eklendiğinde
            Gün 3–4 arasında A + B + D (peak = 3 > 2) kapasite aşımı yakalanır ve onay engellenir.
          - 72 saatlik ekstraksiyonda kurulum süresinin 90 dakikadan 4 saate (08:00–12:00) değişmesinin
            72 saatlik cihaz rezervasyonunu kısaltmadığı ve tamamlanan (COMPLETED) kurulumun rezervasyonu
            koruduğu doğrulanır.
          - Tanımlı 1 / 2 / 4 cihaz kapasitelerinin (max_concurrent_studies) sessizce değiştirilmeden
            tutarlı biçimde uygulandığı doğrulanır.
        """
        from dataclasses import replace as dc_replace
        from app.services.capacity_service import (
            build_capacity_report,
            compute_peak_concurrent_details,
            evaluate_capacity_conflicts,
            peak_concurrent_usage,
        )
        from app.services.scheduling_engine import (
            _find_next_available_water_bath_offset,
            revalidate_study_conflicts,
            seed_default_equipment,
        )
        from app.services.templates import ISO_10993_5_CYTO

        h_ezgi = _login_headers(self.client, "ezgi")
        sd_ezgi = self.db.query(User).filter(User.username == "ezgi").first()
        tech1 = self.db.query(User).filter(User.username == "invivo_1").first()
        tech2 = self.db.query(User).filter(User.username == "invivo_2").first()
        wb = seed_default_equipment(self.db, commit=True)

        day1_0800 = datetime(2027, 4, 5, 8, 0)   # Gün 1 08:00 (Pazartesi)
        day2_0800 = datetime(2027, 4, 6, 8, 0)   # Gün 2 08:00 (Salı)
        day3_0800 = datetime(2027, 4, 7, 8, 0)   # Gün 3 08:00 (Çarşamba)
        day4_0800 = datetime(2027, 4, 8, 8, 0)   # Gün 4 08:00 (Perşembe)
        day5_0800 = datetime(2027, 4, 9, 8, 0)   # Gün 5 08:00 (Cuma)
        day6_0800 = datetime(2027, 4, 10, 8, 0)  # Gün 6 08:00 (Cumartesi)
        day7_0800 = datetime(2027, 4, 11, 8, 0)  # Gün 7 08:00 (Pazar)

        # 0) Doğrudan birim fonksiyon doğrulaması (tamamı 72 saatlik A: Gün 3–6, B: Gün 1–4, C: Gün 4–7)
        direct_details_abc = compute_peak_concurrent_details(
            day3_0800,
            day6_0800,
            [
                (day1_0800, day4_0800, "B", "B"),
                (day4_0800, day7_0800, "C", "C"),
            ],
        )
        self.assertEqual(
            direct_details_abc["peak_other"],
            1,
            "B [Gün 1..Gün 4) ve C [Gün 4..Gün 7) yarı-açık [start, end) kuralına göre aynı anda aktif değildir",
        )
        self.assertEqual(direct_details_abc["peak_total"], 2, "A (Gün 3–6) + max(B, C) tepe eşzamanlı kullanım 2 olmalı")
        self.assertEqual(len(direct_details_abc["overlapping_items"]), 2)
        self.assertEqual(
            peak_concurrent_usage(
                [
                    (day3_0800, day6_0800),  # A: Gün 3–6 (72s)
                    (day1_0800, day4_0800),  # B: Gün 1–4 (72s)
                    (day4_0800, day7_0800),  # C: Gün 4–7 (72s)
                ]
            ),
            2,
        )
        self.assertEqual(
            peak_concurrent_usage(
                [
                    (day3_0800, day6_0800),  # A: Gün 3–6 (72s)
                    (day1_0800, day4_0800),  # B: Gün 1–4 (72s)
                    (day4_0800, day7_0800),  # C: Gün 4–7 (72s)
                    (day2_0800, day5_0800),  # D: Gün 2–5 (72s) -> Gün 3–4 arasında A, B, D eşzamanlı (3)
                ]
            ),
            3,
        )

        # ==================================================================
        # BÖLÜM 1: EQ-WB-001 (Polar Kapasite = 2) üzerinde tamamı 72 saatlik
        # rezervasyonlar (A: Gün 3–6, B: Gün 1–4, C: Gün 4–7) ve 90 dk kurulum görevleri
        # ==================================================================
        wb.polar_capacity = 2
        wb.non_polar_capacity = 1
        self.db.commit()

        def _create_wb_study(code: str, ex_start_dt: datetime, setup_minutes: int = 90, tech_user=tech1):
            g0_dt = ex_start_dt.date() - timedelta(days=4)
            st_obj = Study(
                study_code=code,
                title=f"Peak WB Test {code}",
                test_item_name="Peak Test Polymer",
                study_director_id=sd_ezgi.id,
                status=StudyStatus.DRAFT,
                template_code="ISO_10993_23_IC",
                acclimatization_start_date=g0_dt,
                target_start_date=g0_dt,
                target_end_date=(ex_start_dt + timedelta(hours=72)).date(),
                extraction_polar=True,
                extraction_non_polar=False,
            )
            self.db.add(st_obj)
            self.db.flush()
            step_obj = StudyStep(
                study_id=st_obj.id,
                step_order=2,
                study_day=4,
                step_name="72 Saatlik Ekstraksiyon Kurulumu",
                step_type="Ekstraksiyon",
                planned_start=ex_start_dt,
                planned_end=ex_start_dt + timedelta(minutes=setup_minutes),
                is_biological_fixed_time=True,
                biological_tolerance_minutes=120,
                equipment_id=wb.id,
                status=StepStatus.PENDING,
            )
            step_obj.assignees = [tech_user]
            self.db.add(step_obj)
            self.db.commit()
            return st_obj, step_obj

        wb_a, step_wb_a = _create_wb_study("FIX22-WB-A", day3_0800, setup_minutes=90, tech_user=tech1)  # Rezervasyon: Gün 3–6 (72s)
        wb_b, step_wb_b = _create_wb_study("FIX22-WB-B", day1_0800, setup_minutes=90, tech_user=tech1)  # Rezervasyon: Gün 1–4 (72s)
        wb_c, step_wb_c = _create_wb_study("FIX22-WB-C", day4_0800, setup_minutes=90, tech_user=tech1)  # Rezervasyon: Gün 4–7 (72s)

        for st_item in (wb_a, wb_b, wb_c):
            findings_item = revalidate_study_conflicts(self.db, st_item)
            self.db.commit()
            eq_conflicts = [
                c for c, _ in findings_item
                if c.conflict_type == ConflictType.EQUIPMENT_OVERLAP
            ]
            self.assertEqual(
                eq_conflicts,
                [],
                f"{st_item.study_code} için peak=2 <= 2 iken yanlış EQUIPMENT_OVERLAP üretilmemeli: {[c.title for c in eq_conflicts]}",
            )
            r_app = self.client.post(f"/api/v1/planning/studies/{st_item.id}/approve", headers=h_ezgi)
            self.assertEqual(r_app.status_code, 200, f"{st_item.study_code} onaylanabilmeli: {r_app.text}")

        # Şimdi Gün 2 08:00 – Gün 5 08:00 (72s) arasına gerçekten 3. eşzamanlı Çalışma D eklendiğinde
        # Gün 3–4 arasında A + B + D aynı anda cihazdadır (peak = 3 > 2)
        wb_d, _ = _create_wb_study("FIX22-WB-D", day2_0800, setup_minutes=90, tech_user=tech2)
        findings_d = revalidate_study_conflicts(self.db, wb_d)
        self.db.commit()
        eq_conflicts_d = [
            c for c, _ in findings_d
            if c.conflict_type == ConflictType.EQUIPMENT_OVERLAP
        ]
        self.assertEqual(len(eq_conflicts_d), 1, "Peak=3 > 2 olduğunda Polar kapasite aşımı yakalanmalı")
        self.assertIn("Polar Kapasite Aşımı (Max: 2)", eq_conflicts_d[0].title)
        self.assertIn("eşzamanlı 3 Polar çalışma", eq_conflicts_d[0].description)

        r_app_d = self.client.post(f"/api/v1/planning/studies/{wb_d.id}/approve", headers=h_ezgi)
        self.assertIn(r_app_d.status_code, (400, 409), "Peak=3 > 2 iken Çalışma D onayı engellenmeli")

        # En erken uygun tarih önerisi (_find_next_available_water_bath_offset):
        # A (Gün 3–6) ve B (Gün 1–4) varken B'nin Gün 0'ından başlanarak arandığında,
        # Gün 2 (+1) ve Gün 3 (+2) ofsetlerinde peak=3 > 2 olur; Gün 4 (+3) ofsetinde B bittiği için peak=2 <= 2 ile uygundur!
        existing_ab_steps = (
            self.db.query(StudyStep)
            .filter(StudyStep.study_id.in_([wb_a.id, wb_b.id]))
            .all()
        )
        next_off, next_dt = _find_next_available_water_bath_offset(
            self.db,
            wb_d,
            wb_b.acclimatization_start_date,
            0,
            existing_ab_steps,
            wb,
        )
        self.assertEqual(next_off, 3, "B (Gün 1–4) bittiğinde Gün 4 (+3 gün ofset) peak=2 <= 2 ile ilk uygun gün olmalı")
        self.assertEqual(next_dt, day4_0800.date())

        # ==================================================================
        # BÖLÜM 2: Kurulum süresinin 90 dakikadan 4 saate (08:00–12:00) değişmesinin
        # 72 saatlik cihaz rezervasyonunu kısaltmadığı ve COMPLETED kurulumun
        # devam eden 72 saatlik rezervasyonu koruduğu doğrulaması
        # ==================================================================
        # 2a) Çalışma B'nin kurulum süresi 90 dakikadan 4 saate (08:00–12:00) çıkarılır:
        step_wb_b_db = self.db.query(StudyStep).filter(StudyStep.id == step_wb_b.id).first()
        step_wb_b_db.planned_end = day1_0800 + timedelta(hours=4)  # 4 saatlik kurulum (08:00–12:00)
        self.db.commit()

        findings_d_4h = revalidate_study_conflicts(self.db, wb_d)
        self.db.commit()
        eq_conflicts_d_4h = [
            c for c, _ in findings_d_4h
            if c.conflict_type == ConflictType.EQUIPMENT_OVERLAP
        ]
        self.assertEqual(
            len(eq_conflicts_d_4h),
            1,
            "Kurulum süresinin 90 dk'dan 4 saate çıkması 72 saatlik rezervasyonu 4 saate düşürmemeli (peak=3 > 2 korunmalı)",
        )

        # 2b) Çalışma B'nin kurulum görevi COMPLETED yapılır; devam eden 72 saatlik cihaz rezervasyonu korunmalı:
        step_wb_b_db.status = StepStatus.COMPLETED
        step_wb_b_db.actual_start = day1_0800
        step_wb_b_db.actual_end = day1_0800 + timedelta(hours=4)
        self.db.commit()

        findings_d_completed = revalidate_study_conflicts(self.db, wb_d)
        self.db.commit()
        eq_conflicts_d_completed = [
            c for c, _ in findings_d_completed
            if c.conflict_type == ConflictType.EQUIPMENT_OVERLAP
        ]
        self.assertEqual(
            len(eq_conflicts_d_completed),
            1,
            "Tamamlanan (COMPLETED) kurulum görevi devam eden 72 saatlik cihaz rezervasyonunu kaldırmamalı",
        )
        r_app_d_after_comp = self.client.post(f"/api/v1/planning/studies/{wb_d.id}/approve", headers=h_ezgi)
        self.assertIn(r_app_d_after_comp.status_code, (400, 409))

        # Bölüm 1-2 çalışmalarını temizle
        for st_prev in (wb_a, wb_b, wb_c, wb_d):
            self.db.query(Conflict).filter(Conflict.study_id == st_prev.id).delete()
            self.db.query(StudyStep).filter(StudyStep.study_id == st_prev.id).delete()
            self.db.delete(st_prev)
        wb.polar_capacity = 3
        self.db.commit()

        # ==================================================================
        # BÖLÜM 3: capacity_service (build_capacity_report, evaluate_capacity_conflicts,
        # find_first_free_g0) üzerinde 72 saatlik şablon cihaz rezervasyonlarıyla
        # A (Gün 3–6), B (Gün 1–4), C (Gün 4–7) ve D (Gün 2–5) doğrulaması
        # ==================================================================
        eq_inc = self.db.query(Equipment).filter(Equipment.code == "EQ-INC-001").first()
        self.assertIsNotNone(eq_inc)
        eq_inc.max_concurrent_studies = 2
        self.db.commit()

        tpl_72h_inc = dc_replace(
            ISO_10993_5_CYTO,
            equipment_windows=(("EQ-INC-001", 0, "08:00", 72),),
        )

        def _create_cap_study(code: str, g0_dt: date, tech_user=tech1):
            st_obj = Study(
                study_code=code,
                title=f"Peak Cap Test {code}",
                test_item_name="Peak Cyto Item",
                study_director_id=sd_ezgi.id,
                status=StudyStatus.DRAFT,
                template_code="ISO_10993_5_CYTO",
                acclimatization_start_date=g0_dt,
                target_start_date=g0_dt,
                target_end_date=g0_dt + timedelta(days=3),
                extraction_polar=False,
                extraction_non_polar=False,
            )
            self.db.add(st_obj)
            self.db.flush()
            step_obj = StudyStep(
                study_id=st_obj.id,
                step_order=1,
                study_day=0,
                step_name="L929 Hücre Kültürü Pasajlama ve 96 Kuyucuklu Plak Ekimi",
                step_type="Hazırlık",
                planned_start=datetime.combine(g0_dt, time(8, 0)),
                planned_end=datetime.combine(g0_dt, time(9, 30)),  # 90 dk insan kurulum görevi
                is_biological_fixed_time=False,
                biological_tolerance_minutes=0,
                status=StepStatus.PENDING,
            )
            step_obj.assignees = [tech_user]
            self.db.add(step_obj)
            self.db.commit()
            return st_obj, step_obj

        cap_a, step_cap_a = _create_cap_study("FIX22-CAP-A", day3_0800.date(), tech_user=tech1)  # Gün 3–6 (72s)
        cap_b, step_cap_b = _create_cap_study("FIX22-CAP-B", day1_0800.date(), tech_user=tech1)  # Gün 1–4 (72s)
        cap_c, step_cap_c = _create_cap_study("FIX22-CAP-C", day4_0800.date(), tech_user=tech1)  # Gün 4–7 (72s)

        for st_cap, s_cap in ((cap_a, step_cap_a), (cap_b, step_cap_b), (cap_c, step_cap_c)):
            rep = build_capacity_report(self.db, st_cap, template=tpl_72h_inc)
            inc_entry = next(e for e in rep["equipment"] if e["equipment_code"] == "EQ-INC-001")
            self.assertEqual(inc_entry["used"], 2, f"{st_cap.study_code} için tepe eşzamanlı kullanım 2 olmalı: {inc_entry}")
            self.assertEqual(inc_entry["level"], "OK", f"{st_cap.study_code} için kapasite (2) aşılmamalı")
            confs = evaluate_capacity_conflicts(self.db, st_cap, [s_cap], template=tpl_72h_inc)
            self.assertEqual(confs, [], f"{st_cap.study_code} için yanlış Uzun Süreli Cihaz Kapasite Aşımı üretilmemeli")

        # 3. eşzamanlı çalışma D (Gün 2–5, 72s) eklendiğinde peak = 3 > 2 yakalanmalı:
        cap_d, step_cap_d = _create_cap_study("FIX22-CAP-D", day2_0800.date(), tech_user=tech2)
        rep_d = build_capacity_report(self.db, cap_d, template=tpl_72h_inc)
        inc_entry_d = next(e for e in rep_d["equipment"] if e["equipment_code"] == "EQ-INC-001")
        self.assertEqual(inc_entry_d["used"], 3, "Çalışma D eklendiğinde tepe eşzamanlı kullanım 3 olmalı")
        self.assertEqual(inc_entry_d["level"], "EXCEEDED", "Peak=3 > 2 olduğunda EXCEEDED dönmeli")
        self.assertIsNotNone(rep_d["first_free_g0"])
        confs_d = evaluate_capacity_conflicts(self.db, cap_d, [step_cap_d], template=tpl_72h_inc)
        self.assertEqual(len(confs_d), 1, "Peak=3 > 2 olduğunda Uzun Süreli Cihaz Kapasite Aşımı üretilmeli")

        for st_prev in (cap_a, cap_b, cap_c, cap_d):
            self.db.query(Conflict).filter(Conflict.study_id == st_prev.id).delete()
            self.db.query(StudyStep).filter(StudyStep.study_id == st_prev.id).delete()
            self.db.delete(st_prev)
        self.db.commit()

        # ==================================================================
        # BÖLÜM 4: Tanımlı 1 / 2 / 4 cihaz kapasitelerinin (max_concurrent_studies)
        # kısa/normal görevlerde dahi sessizce değiştirilmeden tutarlı uygulanması
        # ==================================================================
        slot_start = datetime(2027, 5, 3, 10, 0)
        slot_end = datetime(2027, 5, 3, 11, 0)  # 1 saatlik kısa görev

        for defined_cap in (1, 2, 4):
            eq_inc.max_concurrent_studies = defined_cap
            self.db.commit()

            created_cap_studies = []
            for idx in range(1, defined_cap + 2):
                st_k = Study(
                    study_code=f"FIX22-CAP{defined_cap}-{idx}",
                    title=f"Defined Cap {defined_cap} #{idx}",
                    test_item_name="Cap Item",
                    study_director_id=sd_ezgi.id,
                    status=StudyStatus.APPROVED if idx <= defined_cap else StudyStatus.DRAFT,
                    template_code="ISO_10993_23_IC",
                    acclimatization_start_date=slot_start.date() - timedelta(days=8),
                    target_start_date=slot_start.date() - timedelta(days=8),
                    target_end_date=slot_start.date() + timedelta(days=2),
                    extraction_polar=False,
                    extraction_non_polar=False,
                )
                self.db.add(st_k)
                self.db.flush()
                step_k = StudyStep(
                    study_id=st_k.id,
                    step_order=4,
                    study_day=8,
                    step_name="24. Saat Gözlemi ve Skorlama",
                    step_type="Gözlem",
                    planned_start=slot_start,
                    planned_end=slot_end,
                    is_biological_fixed_time=True,
                    biological_tolerance_minutes=120,
                    equipment_id=eq_inc.id,
                    status=StepStatus.PENDING,
                )
                self.db.add(step_k)
                self.db.commit()
                created_cap_studies.append((st_k, step_k))

                findings_k = revalidate_study_conflicts(self.db, st_k)
                self.db.commit()
                eq_overlaps_k = [
                    c for c, _ in findings_k
                    if c.conflict_type == ConflictType.EQUIPMENT_OVERLAP
                ]
                if idx <= defined_cap:
                    self.assertEqual(
                        eq_overlaps_k,
                        [],
                        f"Tanımlı kapasite {defined_cap} iken {idx}. eşzamanlı kısa görevde çakışma üretilmemeli",
                    )
                else:
                    self.assertEqual(
                        len(eq_overlaps_k),
                        1,
                        f"Tanımlı kapasite {defined_cap} iken {idx}. eşzamanlı görevde (peak={idx} > {defined_cap}) EQUIPMENT_OVERLAP üretilmeli",
                    )

            for st_k, _ in created_cap_studies:
                self.db.query(Conflict).filter(Conflict.study_id == st_k.id).delete()
                self.db.query(StudyStep).filter(StudyStep.study_id == st_k.id).delete()
                self.db.delete(st_k)
            self.db.commit()

        eq_inc.max_concurrent_studies = 4
        self.db.commit()


if __name__ == "__main__":
    unittest.main(verbosity=2)
