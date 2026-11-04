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
    # 12. Bilinmeyen ekstraksiyon bilgisinin polar olarak varsayılmaması
    # ------------------------------------------------------------------
    def test_12_unknown_extraction_info_not_assumed_polar(self):
        wb = self.db.query(Equipment).filter(Equipment.code == "EQ-WB-001").first()
        wb.polar_capacity = 1
        wb.non_polar_capacity = 1
        self.db.commit()

        sd = self.people["ezgi"]
        monday = date(2026, 11, 2)

        # Çalışma 1: Ekstraksiyon bilgisi bilinmiyor (None / None)
        s_unknown = Study(
            study_code="FIX12-UNKNOWN",
            title="Unknown Extraction Study",
            test_item_name="Unknown Polymer",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
            extraction_polar=None,
            extraction_non_polar=None,
        )
        # Çalışma 2: Yalnızca apolar (False / True)
        s_apolar = Study(
            study_code="FIX12-APOLAR",
            title="Apolar Only Study",
            test_item_name="Apolar Polymer",
            study_director_id=sd.id,
            status=StudyStatus.DRAFT,
            extraction_polar=False,
            extraction_non_polar=True,
        )
        # Çalışma 3: Polar (True / False)
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

        # 1) Bilinmeyen (None/None) çalışmaya Su Banyosu (EQ-WB-001) atanmamalı ve eksik bilgi durumu açıkça görünmeli
        unk_ext_step = (
            self.db.query(StudyStep)
            .filter(StudyStep.study_id == s_unknown.id, StudyStep.study_day == 4)
            .first()
        )
        self.assertIsNone(
            unk_ext_step.equipment_id,
            "extraction_polar=None iken ekstraksiyon adımına Su Banyosu (equipment_id) varsayılan olarak atanmamalı",
        )
        self.assertTrue(
            res_unk.get("missing_extraction_info"),
            "extraction_polar=None ve extraction_non_polar=None olduğunda missing_extraction_info=True dönmeli",
        )
        self.assertEqual(res_unk.get("extraction_info_status"), "MISSING")

        # 2) Yalnızca apolar (False/True) çalışmaya Su Banyosu atanmamalı
        apo_ext_step = (
            self.db.query(StudyStep)
            .filter(StudyStep.study_id == s_apolar.id, StudyStep.study_day == 4)
            .first()
        )
        self.assertIsNone(apo_ext_step.equipment_id, "Yalnızca apolar çalışmaya Su Banyosu atanmamalı")
        self.assertFalse(res_apo.get("missing_extraction_info"))
        self.assertEqual(res_apo.get("extraction_info_status"), "APOLAR_ONLY")

        # 3) Polar (True/False) çalışmaya Su Banyosu atanmalı, ancak s_unknown (None/None) yüzünden kesinleşmiş
        #    Su Banyosu kapasite aşımı üretilmemeli (kapasite=1 ve yalnızca s_polar kesin polar kullanıyor)
        pol_ext_step = (
            self.db.query(StudyStep)
            .filter(StudyStep.study_id == s_polar.id, StudyStep.study_day == 4)
            .first()
        )
        self.assertEqual(pol_ext_step.equipment_id, wb.id, "Polar çalışmaya Su Banyosu atanmalı")
        pol_wb_confs = [
            c for c in res_pol["conflicts"]
            if c["type"] == "EQUIPMENT_OVERLAP" and "Su Banyosu" in (c["title"] or "")
        ]
        self.assertEqual(
            len(pol_wb_confs),
            0,
            "Bilinmeyen (None) ekstraksiyonlu çalışma su banyosunu kesin kullanıyor sayılıp s_polar'da sahte cihaz çakışması üretmemeli",
        )

        # 4) Eksik bilgi sonradan tamamlandığında (s_unknown -> extraction_polar=True) yeniden doğrulama
        #    hem cihaz atamasını güncellemeli hem de gerçek Su Banyosu çakışmasını yakalamalı!
        s_unknown.extraction_polar = True
        s_unknown.extraction_non_polar = False
        self.db.commit()
        revalidate_study_conflicts(self.db, s_unknown)
        self.db.commit()
        self.db.refresh(unk_ext_step)
        self.assertEqual(
            unk_ext_step.equipment_id,
            wb.id,
            "Eksik ekstraksiyon bilgisi polar=True olarak tamamlandığında Su Banyosu atanmalı",
        )
        unk_wb_confs = (
            self.db.query(Conflict)
            .filter(
                Conflict.study_id == s_unknown.id,
                Conflict.conflict_type == ConflictType.EQUIPMENT_OVERLAP,
                Conflict.is_resolved == False,  # noqa: E712
            )
            .all()
        )
        self.assertTrue(
            any("Su Banyosu" in (c.title or "") for c in unk_wb_confs),
            "Eksik ekstraksiyon bilgisi polar=True olarak tamamlandığında Su Banyosu çakışması tespit edilmeli",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
