"""
FAZ 4, FAZ 5 & FAZ 5.1 MOTOR, JWT AUTH, RBAC VE KULLANICI YÖNETİMİ TESTLERİ — İZOLE GEÇİCİ VERİTABANI

Gerçek veritabanına ASLA dokunmaz: DATABASE_URL, uygulama import edilmeden önce geçici bir
SQLite dosyasına yönlendirilir ve test sonunda silinir.

Kullanım (proje kökünden):
    backend\\venv\\Scripts\\python.exe backend\\tests\\verify_engine.py
"""
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, time, timedelta

_TMP_DIR = tempfile.mkdtemp(prefix="nanoglp_test_")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_TMP_DIR, "test.db")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Conflict, Study, StudyStatus, StudyStep, User, UserRole  # noqa: E402
from app.seed import DEFAULT_PASSWORD, reset_schema, seed_personnel  # noqa: E402
from app.services.scheduling_engine import schedule_new_study  # noqa: E402
from app.utils.security import verify_password  # noqa: E402

assert "nanoglp_test_" in settings.DATABASE_URL, "Güvenlik: test gerçek veritabanını hedefliyor!"

MONDAY = date(2026, 11, 2)      # Gün 0 Pazartesi → tüm kilitli günler hafta içi
WEDNESDAY = date(2026, 11, 4)   # Gün 0 Çarşamba → Gün 4 Pazar, Gün 10 Cumartesi
PASSED = []


def check(cond, msg):
    assert cond, "BAŞARISIZ: " + msg
    PASSED.append(msg)
    print("  ✓", msg)


def make_draft(db, code):
    sd = db.query(User).filter(User.role == UserRole.STUDY_DIRECTOR).first()
    s = Study(study_code=code, title=code, test_item_name="TEST", study_director_id=sd.id, status=StudyStatus.DRAFT)
    db.add(s)
    db.commit()
    return s


def types(result):
    return [c["type"] for c in result["conflicts"]]


def auth_headers(client: TestClient, username: str, password: str = DEFAULT_PASSWORD) -> dict:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"Login failed for {username}: {r.text}"
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def main():
    reset_schema()
    db = SessionLocal()
    try:
        people = {u.username: u for u in seed_personnel(db)}
        sysadmin = people["admin"]
        tfm, sd = people["emine"], people["ezgi"]
        t1, t2 = people["invivo_1"], people["invivo_2"]
        qa = people["qa_user"]
        check(
            len(people) == 7 and all(u.max_daily_hours == 9 for u in people.values()),
            "7 kurumsal kullanıcı (admin, emine, ezgi, koray, invivo_1, invivo_2, qa_user) seed edildi",
        )
        check(sysadmin.role == UserRole.SYSADMIN, "admin rolü SYSADMIN")
        check(
            all(u.hashed_password and verify_password(DEFAULT_PASSWORD, u.hashed_password) for u in people.values()),
            f"Tüm personelin parolası '{DEFAULT_PASSWORD}' olarak bcrypt ile şifrelendi",
        )
        check(people["koray"].role == UserRole.PLANNING_COORDINATOR, "koray rolü PLANNING_COORDINATOR")

        print("\n[1] ISO 10993-23 şablonu — Gün 0 Pazartesi, boş takvim")
        a = make_draft(db, "T-A")
        ra = schedule_new_study(db, a.id, MONDAY)
        days = [s["study_day"] for s in ra["steps"]]
        check(days == [0, 4, 7, 8, 9, 10], f"Gün dizilimi {days}")
        check([s["is_biological_fixed_time"] for s in ra["steps"]] == [False, True, True, True, True, True],
              "Gün 0 esnek, Gün 4/7/8/9/10 biyolojik kilitli")
        check(all(datetime.fromisoformat(s["planned_start"]).date() == MONDAY + timedelta(days=s["study_day"])
                  for s in ra["steps"]), "Her adım tarihi = Gün 0 + ofset")
        roles = {s["study_day"]: sorted(p["role"] for p in s["assignees"]) for s in ra["steps"]}
        check(roles[0] == ["TFM"] and roles[7] == ["STUDY_DIRECTOR", "TECHNICIAN"] and roles[4] == ["TECHNICIAN"],
              "Roller: Gün 0 TFM, Gün 7 SD+Teknisyen, diğerleri Teknisyen")
        techs_a = {p["full_name"] for s in ra["steps"] for p in s["assignees"] if p["role"] == "TECHNICIAN"}
        check(techs_a == {t1.full_name}, "Çalışma boyunca tek teknisyen (skorlama tutarlılığı)")
        obs = [datetime.fromisoformat(s["planned_start"]) for s in ra["steps"] if s["study_day"] in (8, 9, 10)]
        check([o - obs[0] for o in obs] == [timedelta(0), timedelta(hours=24), timedelta(hours=48)],
              "24/48/72. saat gözlemleri aynı referans saate kilitli")
        check(ra["status"] == "SCHEDULED_CLEAN", "Boş takvimde çakışma yok")

        print("\n[2] Taslak ↔ taslak — aynı Gün 0 ile ikinci taslak")
        b = make_draft(db, "T-B")
        rb = schedule_new_study(db, b.id, MONDAY)
        check("T-A" in rb["compared_draft_studies"], "Diğer DRAFT çalışma kıyas kümesinde")
        techs_b = {p["full_name"] for s in rb["steps"] for p in s["assignees"] if p["role"] == "TECHNICIAN"}
        check(techs_b == {t2.full_name}, "Boştaki 2. teknisyen seçildi (saat kaydırılmadan)")
        check("BIOLOGICAL_TIME_VIOLATION" in types(rb), "Gün 7'de SD iki taslakta → BIOLOGICAL_TIME_VIOLATION")
        check("PERSONNEL_OVERLAP" in types(rb), "Gün 0'da TFM iki taslakta → PERSONNEL_OVERLAP")
        check(all(c["related_study_id"] == a.id for c in rb["conflicts"]), "Çakışmalar karşı taslağı (T-A) işaret ediyor")
        check(all(c["severity"] == "CRITICAL" for c in rb["conflicts"]), "Tümü CRITICAL")
        a_times = [(s.planned_start, s.planned_end) for s in db.query(StudyStep).filter_by(study_id=a.id)]
        check([(datetime.fromisoformat(s["planned_start"]), datetime.fromisoformat(s["planned_end"]))
               for s in ra["steps"]] == sorted(a_times), "T-A saatleri değişmedi")

        print("\n[3] Hafta sonu — Gün 0 Çarşamba")
        c = make_draft(db, "T-C")
        rc = schedule_new_study(db, c.id, WEDNESDAY)
        weekend = [x for x in rc["conflicts"] if "Mesai Dışında" in x["title"]]
        check(any("Gün 4" in x["title"] for x in weekend) and any("Gün 10" in x["title"] for x in weekend),
              "Gün 4 (Pazar) ve Gün 10 (Cumartesi) → BIOLOGICAL_TIME_VIOLATION, saat kaydırılmadı")
        d4 = next(s for s in rc["steps"] if s["study_day"] == 4)
        check(datetime.fromisoformat(d4["planned_start"]).weekday() == 6, "Gün 4 Pazar'da kaldı (öteleme yok)")

        print("\n[4] 9 saat kuralı — iki teknisyen de Gün 8'de 510 dk dolu")
        busy = Study(study_code="T-BUSY", title="x", test_item_name="x", study_director_id=sd.id,
                     status=StudyStatus.APPROVED)
        db.add(busy)
        db.commit()
        d8 = date(2026, 11, 24)  # Gün 0 = 16.11 (Pzt) → Gün 8 = 24.11
        for t in (t1, t2):
            st = StudyStep(study_id=busy.id, step_order=1, study_day=0, step_name="Uzun görev",
                           planned_start=datetime.combine(d8, time(11, 0)),
                           planned_end=datetime.combine(d8, time(19, 30)))
            st.assignees = [t]
            db.add(st)
        db.commit()
        busy_times = [(s.planned_start, s.planned_end) for s in db.query(StudyStep).filter_by(study_id=busy.id)]
        d = make_draft(db, "T-D")
        rd = schedule_new_study(db, d.id, date(2026, 11, 16))
        wl = [x for x in rd["conflicts"] if x["title"].startswith("9 Saat")]
        check(len(wl) == 1 and wl[0]["type"] == "PERSONNEL_OVERLAP" and wl[0]["severity"] == "CRITICAL",
              "570 dk (>540) → CRITICAL PERSONNEL_OVERLAP")
        check(wl[0]["step_ids"], "9 saat çakışması ilgili adıma bağlı (Gantt vurgusu için)")
        check("T-BUSY" in rd["untouched_approved_studies"], "APPROVED çalışma dokunulmayanlar listesinde")
        check(sorted(busy_times) == sorted((s.planned_start, s.planned_end)
                                           for s in db.query(StudyStep).filter_by(study_id=busy.id)),
              "APPROVED çalışmanın saatleri değişmedi")

        print("\n[5] Non-destructive — onaylı çalışma yeniden planlanamaz")
        try:
            schedule_new_study(db, busy.id, MONDAY)
            check(False, "APPROVED çalışma planlandı!")
        except PermissionError:
            check(True, "APPROVED çalışma → PermissionError")

        print("\n[6] Taslak yeniden planlama — eski kayıtlar SUPERSEDED")
        rb2 = schedule_new_study(db, b.id, date(2026, 12, 7))
        check(rb2["superseded_conflicts"] >= 1, f"{rb2['superseded_conflicts']} eski çakışma SUPERSEDED olarak kapatıldı")
        check(db.query(StudyStep).filter_by(study_id=b.id).count() == 6, "Adımlar yenilendi (tekrar 6, birikme yok)")
        open_b = db.query(Conflict).filter(Conflict.is_resolved == False, Conflict.study_id == b.id).count()  # noqa: E712
        check(open_b == rb2["total_conflicts"], "T-B için yalnızca güncel analiz açık")
        hist = db.query(Conflict).filter(Conflict.resolution_notes.like("SUPERSEDED%")).count()
        check(hist >= 1, "Eski kayıtlar silinmedi, denetim izi için saklandı")

        print("\n[7] FAZ 5 & 5.1: JWT Auth, RBAC ve /api/v1/users Kullanıcı Yönetimi")
        client = TestClient(app)

        # 7a) Token olmadan korunan uç noktalar 401 dönmeli
        check(client.get("/api/v1/planning/summary").status_code == 401, "Token olmadan GET /summary → 401")
        check(client.get("/api/v1/users").status_code == 401, "Token olmadan GET /users → 401")
        check(client.post("/api/v1/auth/login",
                          json={"username": "emine", "password": "YanlisSifre"}).status_code == 401,
              "Hatalı şifre → 401")

        # 7b) SYSADMIN / TFM / SD / PK yetkileri
        h_admin = auth_headers(client, "admin")
        h_tfm = auth_headers(client, "emine")
        h_sd = auth_headers(client, "ezgi")
        h_pk = auth_headers(client, "koray")
        check(client.get("/api/v1/auth/me", headers=h_admin).json()["role"] == "SYSADMIN", "GET /auth/me (SYSADMIN)")
        check(client.get("/api/v1/auth/me", headers=h_tfm).json()["username"] == "emine", "GET /auth/me (emine/TFM)")
        tpl = client.get("/api/v1/planning/templates", headers=h_pk).json()
        check(tpl["default"] == "ISO_10993_23_IC" and len(tpl["templates"][0]["steps"]) == 6, "GET /templates (PK)")
        r = client.post("/api/v1/planning/schedule-study", headers=h_sd,
                        json={"study_code": "T-API", "acclimatization_start_date": "2027-01-04"})
        check(r.status_code == 200 and r.json()["total_new_steps"] == 6, "POST /schedule-study (SD yetkili)")
        check(client.post("/api/v1/planning/schedule-study", headers=h_tfm,
                          json={"study_code": "T-BUSY", "acclimatization_start_date": "2027-01-04"}).status_code == 409,
              "Onaylı çalışma kodu → 409")

        # 7c) /api/v1/users CRUD — Sadece SYSADMIN ve TFM erişebilir
        check(client.get("/api/v1/users", headers=h_admin).status_code == 200, "SYSADMIN GET /users → 200")
        check(client.get("/api/v1/users", headers=h_tfm).status_code == 200, "TFM GET /users → 200")
        check(client.get("/api/v1/users", headers=h_sd).status_code == 403, "SD GET /users → 403")
        check(client.get("/api/v1/users", headers=h_pk).status_code == 403, "PK GET /users → 403")

        # Geçersiz username (boşluk içeren) reddedilmeli
        bad_u = client.post("/api/v1/users", headers=h_admin,
                            json={"username": "bosluklu isim", "full_name": "Test", "role": "TECHNICIAN", "password": "Nanolab2026!"})
        check(bad_u.status_code == 422, "Boşluklu username → 422 Validation Error")

        # Yeni kullanıcı oluşturma, düzenleme ve silme
        new_u = client.post("/api/v1/users", headers=h_admin,
                            json={"username": "invivo_3", "full_name": "In Vivo Teknisyeni 3", "role": "TECHNICIAN", "password": "YeniSifre123!"})
        check(new_u.status_code == 201 and new_u.json()["username"] == "invivo_3", "POST /users yeni kullanıcı oluşturdu")
        new_uid = new_u.json()["id"]
        h_new = auth_headers(client, "invivo_3", "YeniSifre123!")
        check(client.get("/api/v1/auth/me", headers=h_new).json()["full_name"] == "In Vivo Teknisyeni 3",
              "Yeni oluşturulan kullanıcı kendi şifresiyle giriş yapabildi")

        upd_u = client.put(f"/api/v1/users/{new_uid}", headers=h_tfm,
                           json={"full_name": "Kıdemli Teknisyen 3", "role": "ANALYST"})
        check(upd_u.status_code == 200 and upd_u.json()["role"] == "ANALYST", "PUT /users/{id} TFM tarafından güncellendi")

        del_u = client.delete(f"/api/v1/users/{new_uid}", headers=h_admin)
        check(del_u.status_code == 200, "DELETE /users/{id} SYSADMIN tarafından silindi")

        # 7d) QA (Kalite Güvence): Sadece Okuma (Read-Only)
        h_qa = auth_headers(client, "qa_user")
        check(client.get("/api/v1/planning/summary", headers=h_qa).status_code == 200, "QA GET /summary → 200 (Read-Only)")
        check(client.get("/api/v1/users", headers=h_qa).status_code == 403, "QA GET /users → 403")
        check(client.post("/api/v1/planning/schedule-study", headers=h_qa,
                          json={"study_code": "T-QA-FAIL", "acclimatization_start_date": "2027-02-01"}).status_code == 403,
              "QA POST /schedule-study → 403 (Yazma engellendi)")

        # 7e) TECHNICIAN (Teknisyen): Sadece kendi görevleri (/my-tasks), yönetim ekranları 403
        h_tech1 = auth_headers(client, "invivo_1")
        check(client.get("/api/v1/planning/summary", headers=h_tech1).status_code == 403,
              "Teknisyen GET /summary → 403 (Yönetim ekranı engellendi)")
        check(client.get("/api/v1/users", headers=h_tech1).status_code == 403,
              "Teknisyen GET /users → 403")
        my_tasks = client.get("/api/v1/planning/my-tasks", params={"target_date": "2026-11-06"}, headers=h_tech1)
        check(my_tasks.status_code == 200 and len(my_tasks.json()["todays_tasks"]) >= 1,
              "Teknisyen GET /my-tasks kendi görevlerini döndürüyor")
        step_id = my_tasks.json()["todays_tasks"][0]["id"]
        upd = client.patch(f"/api/v1/planning/steps/{step_id}/status", headers=h_tech1,
                           json={"status": "IN_PROGRESS"})
        check(upd.status_code == 200 and upd.json()["status"] == "IN_PROGRESS",
              "Teknisyen kendisine atanmış görevin durumunu güncelleyebiliyor")
        check(client.patch(f"/api/v1/planning/steps/{step_id}/status", headers=h_qa,
                           json={"status": "COMPLETED"}).status_code == 403,
              "QA görev durumu güncelleyemez → 403")

        print("\n[8] FAZ 6: Belge yükleme ve AI ayrıştırma (OpenAI çağrısı mock — ücretsiz, deterministik)")
        from app.services import document_parser as dp
        from app.models.document import Document
        from app.models.audit_log import AuditLog

        settings.UPLOAD_DIR = os.path.join(_TMP_DIR, "uploads")
        doc_text = ("FM.083 CALISMA TALEP FORMU\nCalisma Kodu: GLP-2026-EDR-014\n"
                    "Talep Edilen Test: ISO 10993-23 Intrakutanoz Reaktivite\n"
                    "Talep Edilen Calisma Baslangic Tarihi: 16.11.2026\nRapor Teslim: 15.12.2026\n")
        captured = {}

        def fake_llm(messages):
            captured["messages"] = messages
            return {
                "study_code": "GLP-2026-EDR-014",
                "test_type": "ISO 10993-23 Intrakutanöz Reaktivite",
                "requested_start_date": "2026-11-16",
                "evidence": {"study_code": "Calisma Kodu: GLP-2026-EDR-014",
                             "test_type": "ISO 10993-23 Intrakutanoz Reaktivite",
                             "requested_start_date": "Talep Edilen Calisma Baslangic Tarihi: 16.11.2026"},
                "warnings": [],
            }

        original_llm = dp._llm_call
        dp._llm_call = fake_llm
        try:
            up = client.post("/api/v1/documents/upload", headers=h_tfm,
                             files={"file": ("FM083.txt", doc_text.encode("utf-8"), "text/plain")})
            check(up.status_code == 200, f"POST /documents/upload → 200 ({up.status_code})")
            body = up.json()
            data = body["extracted_data"]
            check(data["study_code"] == "GLP-2026-EDR-014" and data["requested_start_date"] == "2026-11-16",
                  "JSON: study_code + requested_start_date (YYYY-MM-DD) döndü")
            check(data["suggested_template_code"] == "ISO_10993_23_IC", "Test türü → ISO_10993_23_IC şablon önerisi")
            check(body["status"] == "PARSED" and not data["needs_review"], "Alıntılar belgede doğrulandı → PARSED")
            check("<belge>" in captured["messages"][1]["content"], "Belge metni modele veri sınırlayıcı içinde gönderildi")
            doc_row = db.query(Document).filter(Document.id == body["id"]).first()
            check(doc_row is not None and len(doc_row.sha256) == 64 and
                  os.path.exists(os.path.join(settings.UPLOAD_DIR, doc_row.stored_filename)),
                  "Orijinal dosya SHA-256 ile saklandı")
            check(db.query(AuditLog).filter(AuditLog.action == "DOCUMENT_UPLOAD_AI_PARSE",
                                            AuditLog.entity_id == body["id"]).count() == 1,
                  "Yükleme + AI sonucu denetim izine yazıldı")

            # Halüsinasyon koruması: belgede olmayan kod → NEEDS_REVIEW
            def hallucinating_llm(messages):
                r = fake_llm(messages)
                r["study_code"] = "GLP-2099-XXX-999"
                return r
            dp._llm_call = hallucinating_llm
            up2 = client.post("/api/v1/documents/upload", headers=h_tfm,
                              files={"file": ("FM083_b.txt", doc_text.encode("utf-8"), "text/plain")})
            check(up2.status_code == 200 and up2.json()["status"] == "NEEDS_REVIEW",
                  "Belgede geçmeyen çalışma kodu → NEEDS_REVIEW (uydurma veri işaretlendi)")

            # Geçersiz tarih → boş + uyarı
            def bad_date_llm(messages):
                r = fake_llm(messages)
                r["requested_start_date"] = "2026-13-45"
                return r
            dp._llm_call = bad_date_llm
            up3 = client.post("/api/v1/documents/upload", headers=h_tfm,
                              files={"file": ("FM083_c.txt", doc_text.encode("utf-8"), "text/plain")})
            check(up3.json()["extracted_data"]["requested_start_date"] is None,
                  "Geçersiz tarih (2026-13-45) reddedildi, alan boş bırakıldı")

            check(client.post("/api/v1/documents/upload", headers=h_tfm,
                              files={"file": ("virus.exe", b"MZ", "application/octet-stream")}).status_code == 415,
                  "Desteklenmeyen tür (.exe) → 415")
            check(client.post("/api/v1/documents/upload", headers=h_qa,
                              files={"file": ("FM083.txt", doc_text.encode(), "text/plain")}).status_code == 403,
                  "QA belge yükleyemez → 403")
            check(client.post("/api/v1/documents/upload", headers=h_tech1,
                              files={"file": ("FM083.txt", doc_text.encode(), "text/plain")}).status_code == 403,
                  "Teknisyen belge yükleyemez → 403")
            check(client.get("/api/v1/documents", headers=h_qa).status_code == 200, "QA belge listesini görebilir")

            # Anahtar yoksa net hata (503) ve FAILED kaydı
            dp._llm_call = original_llm
            saved_key = settings.OPENAI_API_KEY
            settings.OPENAI_API_KEY = None
            try:
                nk = client.post("/api/v1/documents/upload", headers=h_tfm,
                                 files={"file": ("FM083_d.txt", doc_text.encode(), "text/plain")})
            finally:
                settings.OPENAI_API_KEY = saved_key
            check(nk.status_code == 503 and "OPENAI_API_KEY" in nk.json()["detail"]["message"],
                  "API anahtarı yoksa → 503 + açıklayıcı mesaj (FAILED kaydı tutuldu)")

            # Belgeden planlama: kaynak belge denetim izine bağlanır
            pl = client.post("/api/v1/planning/schedule-study", headers=h_tfm, json={
                "study_code": data["study_code"], "acclimatization_start_date": data["requested_start_date"],
                "template_code": data["suggested_template_code"], "source_document_id": body["id"]})
            check(pl.status_code == 200 and pl.json()["source_document_id"] == body["id"],
                  "Belgeden gelen verilerle plan oluşturuldu (source_document_id)")
            check(db.query(AuditLog).filter(AuditLog.action == "PLAN_FROM_AI_DOCUMENT").count() == 1,
                  "PLAN_FROM_AI_DOCUMENT denetim kaydı oluştu")

            # FAZ 6.1 — PyMuPDF Vision OCR + Çoklu Belge Dosya Birleştirme (Dossier Aggregation)
            import fitz
            pdf_doc = fitz.open()
            page = pdf_doc.new_page()
            page.insert_text((72, 72), "TIIS TEST MADDESI FORMU - Lot: LOT-2026-99 - [X] Polar [X] Non-Polar")
            pdf_bytes = pdf_doc.tobytes()
            pdf_doc.close()

            vision_captured = {}
            def fake_tiis_vision_llm(messages):
                vision_captured["messages"] = messages
                return {
                    "doc_category": "TIIS_FORM",
                    "doc_summary": "Test Maddesi Bilgi Formu (TIIS)",
                    "study_codes": [],
                    "primary_study_code": None,
                    "study_code_mappings": [],
                    "test_type": "Intracutaneous Reactivity Test",
                    "guideline": "ISO 10993-23",
                    "sponsor_name": "MedTech Tibbi Cihaz A.S.",
                    "sponsor_contact": None,
                    "test_item_name": "Steril Kateter",
                    "lot_batch_no": "LOT-2026-99",
                    "manufacture_date": "2026-01-10",
                    "expiry_date": "2029-01-10",
                    "storage_conditions": "Oda Sicakligi (15-25 C)",
                    "physical_state": "Kati polimer",
                    "sterility": "Steril (EO)",
                    "extraction_polar": True,
                    "extraction_polar_solvent": "%0.9 NaCl (Salin)",
                    "extraction_non_polar": True,
                    "extraction_non_polar_solvent": "Susam Yagi",
                    "extraction_ratio": "3 cm2/mL",
                    "extraction_conditions": "37 C, 72 saat",
                    "animal_species_strain": None,
                    "animal_count": None,
                    "animal_birth_date": None,
                    "acclimatization_start_date": None,
                    "requested_start_period": None,
                    "study_director": None,
                    "warnings": [],
                }

            dp._llm_call = fake_tiis_vision_llm
            up_tiis = client.post("/api/v1/documents/upload", headers=h_tfm,
                                  files={"file": ("IMG_20261027_0007.pdf", pdf_bytes, "application/pdf")})
            check(up_tiis.status_code == 200, "PyMuPDF Vision PDF yükleme → 200")
            tiis_body = up_tiis.json()
            check("vision" in tiis_body["extraction_method"].lower(),
                  f"PyMuPDF Vision kullanıldı ({tiis_body['extraction_method']})")
            check(tiis_body["doc_category"] == "TIIS_FORM" and tiis_body["status"] == "PARSED",
                  "TIIS belgesinde study_code olmasa bile kendi alanları doluysa PARSED (sahte hata yok)")
            user_content = vision_captured["messages"][1]["content"]
            check(isinstance(user_content, list) and any(part.get("type") == "image_url" for part in user_content),
                  "GPT-4o Vision'a base64 PNG görüntü (image_url) gönderildi")

            # Hayvan Menşei Sertifikası + FM.083 Aklimatizasyon Çapraz Doğrulama (Dual-Source Check)
            def fake_animal_cert_llm(messages):
                return {
                    "doc_category": "ANIMAL_ORIGIN_CERT",
                    "doc_summary": "Hayvan Mensei ve Saglik Sertifikasi",
                    "study_codes": [],
                    "primary_study_code": None,
                    "study_code_mappings": [],
                    "test_type": None, "guideline": None, "sponsor_name": None, "sponsor_contact": None,
                    "test_item_name": None, "lot_batch_no": None, "manufacture_date": None, "expiry_date": None,
                    "storage_conditions": None, "physical_state": None, "sterility": None,
                    "extraction_polar": None, "extraction_polar_solvent": None,
                    "extraction_non_polar": None, "extraction_non_polar_solvent": None,
                    "extraction_ratio": None, "extraction_conditions": None,
                    "animal_species_strain": "Tavsan / New Zealand White",
                    "animal_count": "3 disi",
                    "animal_birth_date": "10.07.2026",
                    "acclimatization_start_date": None, "requested_start_period": None, "study_director": None,
                    "warnings": [],
                }
            dp._llm_call = fake_animal_cert_llm
            client.post("/api/v1/documents/upload", headers=h_tfm,
                        files={"file": ("IMG_20261027_0012.pdf", pdf_bytes, "application/pdf")})

            def fake_fm083_llm(messages):
                return {
                    "doc_category": "FM083_ACCLIMATIZATION",
                    "doc_summary": "FM.083 Aklimatizasyon Formu",
                    "study_codes": ["26/0221-T02-2"],
                    "primary_study_code": "26/0221-T02-2",
                    "study_code_mappings": [{"code": "26/0221-T02-2", "test_type": "ISO 10993-23 Intrakutanoz"}],
                    "test_type": "ISO 10993-23 Intrakutanoz", "guideline": "ISO 10993-23",
                    "sponsor_name": None, "sponsor_contact": None,
                    "test_item_name": None, "lot_batch_no": None, "manufacture_date": None, "expiry_date": None,
                    "storage_conditions": None, "physical_state": None, "sterility": None,
                    "extraction_polar": None, "extraction_polar_solvent": None,
                    "extraction_non_polar": None, "extraction_non_polar_solvent": None,
                    "extraction_ratio": None, "extraction_conditions": None,
                    "animal_species_strain": "Tavsan / New Zealand White",
                    "animal_count": "3",
                    "animal_birth_date": "10.07.2026",
                    "acclimatization_start_date": "2026-10-20",
                    "requested_start_period": None, "study_director": "Ezgi",
                    "warnings": [],
                }
            dp._llm_call = fake_fm083_llm
            client.post("/api/v1/documents/upload", headers=h_tfm,
                        files={"file": ("IMG_20261027_0015.pdf", pdf_bytes, "application/pdf")})

            dossier_res = client.get("/api/v1/documents/dossier", headers=h_tfm)
            check(dossier_res.status_code == 200, "GET /api/v1/documents/dossier → 200")
            dossier = dossier_res.json()
            mf = dossier["merged_fields"]
            check(mf["lot_batch_no"]["value"] == "LOT-2026-99" and mf["lot_batch_no"]["source_filename"] == "IMG_20261027_0007.pdf",
                  "Dossier birleştirme: Lot No TIIS belgesinden kaynak rozetiyle alındı")
            check(mf["acclimatization_start_date"]["value"] == "2026-10-20" and mf["acclimatization_start_date"]["source_filename"] == "IMG_20261027_0015.pdf",
                  "Dossier birleştirme: Aklimatizasyon tarihi FM.083 belgesinden kaynak rozetiyle alındı")
            check(any(cc["check"] == "ANIMAL_BIRTH_DATE" and cc["status"] == "MATCH" for cc in dossier["cross_checks"]),
                  "Dual-Source Check: Menşei Sertifikası ve FM.083 doğum tarihi eşleşti (MATCH)")

            # Birleştirilmiş Dossier verileriyle çalışma ve plan oluşturma
            pl_dossier = client.post("/api/v1/planning/schedule-study", headers=h_tfm, json={
                "study_code": "26/0221-T02-2",
                "acclimatization_start_date": "2026-10-20",
                "template_code": "ISO_10993_23_IC",
                "sponsor_name": mf["sponsor_name"]["value"],
                "test_item_name": mf["test_item_name"]["value"],
                "test_item_batch": mf["lot_batch_no"]["value"],
                "extraction_polar": mf["extraction_polar"]["value"],
                "extraction_polar_solvent": mf["extraction_polar_solvent"]["value"],
                "extraction_non_polar": mf["extraction_non_polar"]["value"],
                "extraction_non_polar_solvent": mf["extraction_non_polar_solvent"]["value"],
                "animal_species_strain": mf["animal_species_strain"]["value"],
                "source_document_ids": [tiis_body["id"]],
            })
            check(pl_dossier.status_code == 200, "Birleştirilmiş Dossier ile planlama → 200")
            created_study = db.query(Study).filter(Study.study_code == "26/0221-T02-2").first()
            check(
                created_study is not None
                and created_study.sponsor_name == "MedTech Tibbi Cihaz A.S."
                and created_study.test_item_batch == "LOT-2026-99"
                and created_study.extraction_polar is True
                and created_study.extraction_non_polar is True,
                "Birleştirilmiş Dossier verileri (Sponsor, Lot, Polar/Apolar) Study tablosuna kaydedildi",
            )

            print("\n[9] FAZ 6.2: SD Devir, Hafta Sonu Çözüm Motoru, Su Banyosu Kilidi, Dossier İzolasyonu ve .docx Üretici")
            # 9a) SD Eşleştirme ve Devir Mantığı: Yiğit BABAOĞLU (eski çalışan) -> Ezgi Nur AKIN önerisi
            def fake_former_sd_llm(messages):
                return {
                    "doc_category": "SD_ASSIGNMENT",
                    "doc_summary": "SD Atama Formu",
                    "study_codes": ["GLP2026-026"],
                    "primary_study_code": "GLP2026-026",
                    "study_code_mappings": [],
                    "test_type": "ISO 10993-23", "guideline": "ISO 10993-23",
                    "sponsor_name": "ELISA TIBBI GERECLER SAN A.S.",
                    "sponsor_contact": "Phone: +90 541 630 36 36",
                    "test_item_name": "Hyaluronik Asit HA 30 mg/ml",
                    "lot_batch_no": "EDC-NO-230586",
                    "manufacture_date": "11.2025", "expiry_date": "11.2027",
                    "storage_conditions": "Serin ve kuru yerde saklayiniz.",
                    "physical_state": None, "sterility": None,
                    "extraction_polar": True, "extraction_polar_solvent": "%0.9 NaCl",
                    "extraction_non_polar": True, "extraction_non_polar_solvent": "Cottonseed oil",
                    "extraction_ratio": "3.0 g/10 ml", "extraction_conditions": "37 C, 72h",
                    "animal_species_strain": "Oryctolagus cuniculus / New Zealand White",
                    "animal_count": 6, "animal_birth_date": "12-16 hafta",
                    "acclimatization_start_date": "2026-07-30",
                    "requested_start_period": "July / August",
                    "study_director": "Yiğit BABAOĞLU",
                    "warnings": [],
                }
            dp._llm_call = fake_former_sd_llm
            client.post(
                "/api/v1/documents/upload?dossier_key=DOSSIER-ELISA-TEST&dossier_label=ELISA+TEST+PAKETI",
                headers=h_tfm,
                files={"file": ("IMG_20261027_0002.pdf", pdf_bytes, "application/pdf")},
            )
            dos_elisa = client.get("/api/v1/documents/dossier", params={"dossier_key": "DOSSIER-ELISA-TEST"}, headers=h_tfm).json()
            sd_res = dos_elisa["sd_resolution"]
            check(
                sd_res["requires_handover"] is True
                and sd_res["document_sd_name"] == "Yiğit BABAOĞLU"
                and sd_res["suggested_sd_id"] == sd.id
                and "Yiğit BABAOĞLU" in sd_res["message"],
                "Belgedeki eski SD 'Yiğit BABAOĞLU' aktif SD listesinde yok → devir uyarısı + aktif SD önerisi",
            )
            check(
                db.query(User).filter(User.full_name.like("%BABAOĞLU%")).count() == 0,
                "Eski çalışan 'Yiğit BABAOĞLU' veritabanına aktif kullanıcı olarak EKLENMEDİ",
            )

            # 9b) Dossier İzolasyonu: DOSSIER-ELISA-TEST ile varsayılan DOSSIER-ELISA-2026 birbirine karışmaz
            dossiers_list = client.get("/api/v1/documents/dossiers", headers=h_tfm).json()
            pkg_keys = [p["dossier_key"] for p in dossiers_list["dossiers"]]
            check("DOSSIER-ELISA-TEST" in pkg_keys and "DOSSIER-ELISA-2026" in pkg_keys,
                  "Çalışma paketleri (dossier_key) izole olarak listelendi")
            check(dos_elisa["total_documents"] == 1 and dos_elisa["study_codes"] == ["GLP2026-026"],
                  "Dossier izolasyonu: farklı paketlerin belgeleri birbirine karışmadı")

            # 9c) Hafta Sonu Mantığı (WARNING) & Çözüm 1 (Nöbetçi Personel Onayı) + Çözüm 2 (Ekstraksiyonu Cuma'ya Hizala)
            pl_026 = client.post("/api/v1/planning/schedule-study", headers=h_tfm, json={
                "study_code": "GLP2026-026",
                "acclimatization_start_date": "2026-07-30",
                "study_director_id": sd.id,
                "former_study_director_name": "Yiğit BABAOĞLU",
                "sponsor_name": "ELISA TIBBI GEREÇLER SAN A.Ş.",
                "sponsor_contact": "Phone: +90 541 630 36 36, Email: elisatibbi@gmail.com.tr",
                "test_item_name": "Hyaluronik Asit HA 30 mg/ml",
                "test_item_batch": "EDC-NO-230586",
                "manufacture_date": "11.2025",
                "expiry_date": "11.2027",
                "extraction_polar": True,
                "extraction_polar_solvent": "%0.9 NaCl",
                "extraction_non_polar": True,
                "extraction_non_polar_solvent": "Cottonseed oil",
                "extraction_ratio": "3.0 g/10 ml",
                "extraction_conditions": "37 ± 1 °C for (72 ± 2) h",
                "animal_species_strain": "Oryctolagus cuniculus / New Zealand White",
                "animal_count": 6,
            }).json()
            wk_conflicts = [c for c in pl_026["conflicts"] if "Hafta Sonu" in c["title"] or "Mesai Dışında" in c["title"]]
            check(
                len(wk_conflicts) == 2 and all(c["severity"] == "WARNING" for c in wk_conflicts),
                "08.08.2026 (Cmt G9) ve 09.08.2026 (Paz G10) gözlemleri WARNING seviyesinde üretildi",
            )
            res_actions = [r["action"] for r in wk_conflicts[0]["resolutions"]]
            check(
                "APPROVE_WEEKEND_DUTY" in res_actions and "ALIGN_EXTRACTION_TO_FRIDAY" in res_actions,
                "Hafta sonu uyarısında her iki Tek Tık Çözüm Butonu mevcut",
            )

            # Çözüm 1: Hafta Sonu Nöbetçi Personeli Onayla
            res1 = client.post(
                f"/api/v1/planning/conflicts/{wk_conflicts[0]['id']}/apply-resolution",
                headers=h_tfm,
                json={"action": "APPROVE_WEEKEND_DUTY"},
            )
            check(
                res1.status_code == 200 and res1.json()["total_conflicts"] == 0 and res1.json()["can_approve"] is True,
                "Çözüm 1 ('Hafta Sonu Nöbetçi Personeli Onayla') tüm hafta sonu uyarılarını RESOLVED yaptı",
            )

            # Yeniden planla ve Çözüm 2'yi test et: Ekstraksiyonu Cuma'ya Hizala (Gözlemler Hafta İçi Olsun)
            pl_026_b = client.post("/api/v1/planning/schedule-study", headers=h_tfm, json={
                "study_code": "GLP2026-026",
                "acclimatization_start_date": "2026-07-30",
            }).json()
            wk_id_2 = pl_026_b["conflicts"][0]["id"]
            res2 = client.post(
                f"/api/v1/planning/conflicts/{wk_id_2}/apply-resolution",
                headers=h_tfm,
                json={"action": "ALIGN_EXTRACTION_TO_FRIDAY"},
            )
            check(res2.status_code == 200 and res2.json()["total_conflicts"] == 0,
                  "Çözüm 2 ('Ekstraksiyonu Cuma'ya Hizala') ile 0 hafta sonu insan görevi oluştu")
            steps_aligned = {s["step_order"]: datetime.fromisoformat(s["planned_start"]) for s in res2.json()["steps"]}
            check(
                steps_aligned[1].date() == date(2026, 7, 30)
                and steps_aligned[2].weekday() == 4  # Cuma ekstraksiyon
                and steps_aligned[3].weekday() == 0  # Pazartesi enjeksiyon
                and [steps_aligned[4].weekday(), steps_aligned[5].weekday(), steps_aligned[6].weekday()] == [1, 2, 3],
                "G0 sabit (30.07), Ekstraksiyon Cuma (07.08), Enjeksiyon Pazartesi (10.08), Gözlemler Salı-Çarşamba-Perşembe",
            )

            # 9d) Polar / Apolar Su Banyosu (EQ-WB-001) Cihaz Kapasite Kilidi & Çözümü
            from app.models.equipment import Equipment
            wb = db.query(Equipment).filter(Equipment.code == "EQ-WB-001").first()
            check(
                wb is not None and wb.polar_capacity == 3 and wb.non_polar_capacity == 1,
                "Çalkalamalı Su Banyosu 1 (EQ-WB-001, Polar Max: 3, Apolar Max: 1) veritabanında tanımlı",
            )
            # GLP2026-024 çalışmasını GLP2026-026 ile aynı ekstraksiyon penceresine (07.08.2026 Cuma = G0 03.08.2026 Pzt) koyalım
            pl_024 = client.post("/api/v1/planning/schedule-study", headers=h_tfm, json={
                "study_code": "GLP2026-024",
                "acclimatization_start_date": "2026-08-03",
                "extraction_polar": True,
                "extraction_non_polar": True,
                "extraction_non_polar_solvent": "Cottonseed oil",
            }).json()
            eq_conflicts = [c for c in pl_024["conflicts"] if c["type"] == "EQUIPMENT_OVERLAP"]
            check(
                len(eq_conflicts) == 1
                and eq_conflicts[0]["severity"] == "CRITICAL"
                and "Çalkalamalı Su Banyosu Apolar Kapasite Aşımı (Max: 1)" in eq_conflicts[0]["title"],
                "Aynı 72s pencerede 2. Apolar çalışma → CRITICAL EQUIPMENT_OVERLAP ('Çalkalamalı Su Banyosu Apolar Kapasite Aşımı (Max: 1)')",
            )
            eq_res = client.post(
                f"/api/v1/planning/conflicts/{eq_conflicts[0]['id']}/apply-resolution",
                headers=h_tfm,
                json={"action": "SHIFT_TO_NEXT_AVAILABLE_EQUIPMENT_DATE"},
            )
            check(
                eq_res.status_code == 200
                and not any(c["type"] == "EQUIPMENT_OVERLAP" for c in eq_res.json()["conflicts"]),
                "Cihaz Çözüm Butonu ('Cihazın Boşaldığı İlk Güne Kaydır') ekstraksiyonu boş güne kaydırdı ve cihaz çakışmasını çözdü",
            )

            # 9e) Otomatik Study Plan (.docx) Word Belgesi Üretici
            study_026 = db.query(Study).filter(Study.study_code == "GLP2026-026").first()
            docx_resp = client.get(f"/api/v1/studies/{study_026.id}/export-study-plan", headers=h_tfm)
            check(
                docx_resp.status_code == 200
                and "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in docx_resp.headers["content-type"],
                "GET /api/v1/studies/{id}/export-study-plan → 200 (.docx Word belgesi döndü)",
            )
            import io
            from docx import Document as DocxReader
            parsed_docx = DocxReader(io.BytesIO(docx_resp.content))
            full_docx_text = "\n".join(
                [p.text for p in parsed_docx.paragraphs]
                + [cell.text for tbl in parsed_docx.tables for row in tbl.rows for cell in row.cells]
            )
            check(
                "GLP2026-026" in full_docx_text
                and "ELISA TIBBI GEREÇLER SAN A.Ş." in full_docx_text
                and "Hyaluronik Asit HA 30 mg/ml" in full_docx_text
                and "EDC-NO-230586" in full_docx_text
                and "%0.9 NaCl" in full_docx_text
                and "Cottonseed oil" in full_docx_text
                and "Ezgi Nur AKIN" in full_docx_text
                and "Emine ARMUTOĞLU" in full_docx_text,
                "Üretilen .docx içinde Çalışma Kodu, Sponsor, Test Maddesi, Lot, Polar/Apolar Çözücüler, Aktif SD 'Ezgi Nur AKIN', TFM 'Emine ARMUTOĞLU' ve Takvim yer alıyor",
            )

            print("\n[10] FAZ 6.3: Kalıcı Master Takvim (/calendar), Haftalık İş Yükü (/workload-weekly) ve Taslak Onayı (/approve)")
            cal_resp = client.get("/api/v1/planning/calendar", headers=h_tfm)
            check(cal_resp.status_code == 200, "GET /api/v1/planning/calendar → 200")
            cal_json = cal_resp.json()
            cal_codes = [s["study_code"] for s in cal_json["studies"]]
            check(
                "GLP2026-026" in cal_codes
                and len(cal_json["all_steps"]) > 0
                and "2026-07-30" in cal_json["active_dates"]
                and len(cal_json["active_weeks"]) > 0,
                "Master Takvim (/calendar) tüm çalışmaları, adımları ve görev olan aktif tarih/haftaları döndürüyor",
            )

            # Taslak (DRAFT) çalışmayı Onaylı (APPROVED) statüsüne geçir
            summary_before = client.get("/api/v1/planning/summary", headers=h_tfm).json()
            app_resp = client.post(f"/api/v1/planning/studies/{study_026.id}/approve", headers=h_sd)
            check(
                app_resp.status_code == 200 and app_resp.json()["study_status"] == "APPROVED",
                "POST /api/v1/planning/studies/{id}/approve → DRAFT çalışmayı APPROVED statüsüne geçirdi",
            )
            summary_after = client.get("/api/v1/planning/summary", headers=h_tfm).json()
            check(
                summary_after["active_studies"] == summary_before["active_studies"] + 1
                and summary_after["draft_studies"] == summary_before["draft_studies"] - 1,
                "Onay sonrası Dashboard 'Aktif Çalışmalar' sayacı +1 arttı, 'Taslak Çalışma' sayacı -1 azaldı",
            )

            # Haftalık İş Yükü Matrisi
            wk_wl = client.get("/api/v1/planning/workload-weekly", params={"target_date": "2026-07-30"}, headers=h_tfm)
            check(
                wk_wl.status_code == 200
                and len(wk_wl.json()["days"]) == 7
                and any(p["weekly_total_minutes"] > 0 for p in wk_wl.json()["personnel"]),
                "GET /api/v1/planning/workload-weekly → 7 günlük (Pzt-Paz) personel iş yükü matrisi döndü",
            )

            # Tüm planlı adımlar (include_all=true)
            all_bio = client.get(
                "/api/v1/planning/steps",
                params={"biological_only": True, "include_all": True},
                headers=h_tfm,
            )
            check(
                all_bio.status_code == 200 and any(s["study_code"] == "GLP2026-026" for s in all_bio.json()),
                "GET /api/v1/planning/steps?include_all=true → geçmiş/taslak dahil tüm biyolojik kilometre taşlarını döndürdü",
            )
        finally:
            dp._llm_call = original_llm
    finally:
        db.close()
        engine.dispose()
        shutil.rmtree(_TMP_DIR, ignore_errors=True)

    print(f"\nTÜM TESTLER GEÇTİ ({len(PASSED)} kontrol) — gerçek veritabanına dokunulmadı.")


if __name__ == "__main__":
    main()
