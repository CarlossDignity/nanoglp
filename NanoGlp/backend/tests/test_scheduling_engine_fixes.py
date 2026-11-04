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
        reset_schema()
        self.db = SessionLocal()
        self.people = {u.username: u for u in seed_personnel(self.db)}
        self.client = TestClient(app)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
