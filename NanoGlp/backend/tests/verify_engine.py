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
from unittest.mock import patch
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
from app.models.document import Document  # noqa: E402
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


@patch("app.utils.facility_time.facility_now", return_value=datetime(2026, 11, 5, 12))
def main(_facility_clock):
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

        print("\n[2] Taslak ↔ taslak — aynı Gün 0 ile ikinci taslak (FAZ 6.4: Esnek G0 boş saate yerleşir, Kilitli G7 PERSONNEL_OVERLAP)")
        b = make_draft(db, "T-B")
        rb = schedule_new_study(db, b.id, MONDAY)
        check("T-A" in rb["compared_draft_studies"], "Diğer DRAFT çalışma kıyas kümesinde")
        techs_b = {p["full_name"] for s in rb["steps"] for p in s["assignees"] if p["role"] == "TECHNICIAN"}
        check(techs_b == {t2.full_name}, "Boştaki 2. teknisyen seçildi (saat kaydırılmadan)")
        g0_b = next(s for s in rb["steps"] if s["study_day"] == 0)
        check(
            datetime.fromisoformat(g0_b["planned_start"]).time() == time(11, 0)
            and datetime.fromisoformat(g0_b["planned_end"]).time() == time(13, 0),
            "Esnek Gün 0 (TFM) 09:00-11:00 dolu olduğu için otomatik 11:00-13:00 boş dilimine yerleştirildi",
        )
        check("PERSONNEL_OVERLAP" in types(rb), "Gün 7'de SD iki taslakta (başka aktif SD yok) → PERSONNEL_OVERLAP")
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
            import re as _re
            import zipfile as _zipfile
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
                and "0.9% NaCl" in full_docx_text
                and "Cottonseed oil" in full_docx_text
                and "Ezgi Nur AKIN" in full_docx_text
                and "Emine ARMUTOĞLU" in full_docx_text
                and "Selin BOLCAN" not in full_docx_text
                and "Dr. Shivadasan ANOOP" not in full_docx_text
                and "TBD" in full_docx_text,
                "Üretilen .docx içinde Çalışma Kodu, Sponsor, Test Maddesi, Lot, Polar/Apolar Çözücüler, Aktif SD 'Ezgi Nur AKIN', TFM 'Emine ARMUTOĞLU', gerçek görev atamaları ve Takvim yer alıyor; atanmamış şablon kişileri yerine TBD kullanılıyor",
            )
            # Assert field outcomes, not absence of XX (valid in lots/names).
            docx_fields = {row.cells[0].text.strip(): row.cells[2].text.strip()
                           for table in parsed_docx.tables for row in table.rows if len(row.cells) == 3}
            check(
                docx_fields["LOT Number"] == "EDC-NO-230586"
                and docx_fields["Name of the test item"] == "Hyaluronik Asit HA 30 mg/ml"
                and docx_fields["Study Completion Date"] == "TBD",
                "FAZ 6.5: DOCX alanları kayıt değerlerini koruyor; eksik tamamlanma tarihi TBD",
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

            print("\n[11] FAZ 6.4: 4 Şablon, Kanonik Sözleşme Eşleştirmesi, Canlı Kalibrasyon DB (/calibration) ve Çözüm Sonrası Re-Validation")
            tpls_64 = client.get("/api/v1/planning/templates", headers=h_tfm).json()
            tpl_codes_64 = [t["code"] for t in tpls_64["templates"]]
            check(
                all(c in tpl_codes_64 for c in ("ISO_10993_23_IC", "ISO_10993_5_CYTO", "ISO_10993_10_SENS", "ISO_10993_11_ACUTE")),
                "4 GLP test şablonu (ISO 10993-23, 10993-5, 10993-10, 10993-11) aktif",
            )
            cal_get = client.get("/api/v1/planning/calibration", headers=h_tfm)
            check(
                cal_get.status_code == 200 and len(cal_get.json()["steps"]) >= 16 and len(cal_get.json()["equipment"]) >= 1,
                "GET /api/v1/planning/calibration → şablon görev süreleri ve EQ-WB-001 kapasiteleri veritabanından okundu",
            )
            cal_put = client.put(
                "/api/v1/planning/calibration",
                headers=h_tfm,
                json={
                    "reason": "FAZ 6.4 kalibrasyon testi: G0 süresi 150 dk yapıldı",
                    "template_code": "ISO_10993_23_IC",
                    "step_order": 1,
                    "duration_minutes": 150,
                    "equipment_code": "EQ-WB-001",
                    "polar_capacity": 4,
                },
            )
            check(
                cal_put.status_code == 200
                and any(s["template_code"] == "ISO_10993_23_IC" and s["step_order"] == 1 and s["duration_minutes"] == 150 for s in cal_put.json()["steps"])
                and cal_put.json()["equipment"][0]["polar_capacity"] == 4
                and len(cal_put.json()["audit_logs"]) >= 1,
                "PUT /api/v1/planning/calibration → veritabanını güncelledi ve AuditLog kaydı üretti",
            )

            print("\n[12] FAZ 7.2: EXECUTIVE (Üst Yönetim) Rolü, Dinamik Rol & Ekran Yetki Matrisi (/users/roles) ve Salt Okunur Koruması")
            roles_res = client.get("/api/v1/users/roles", headers=h_admin)
            check(roles_res.status_code == 200, "GET /api/v1/users/roles → 200")
            exec_role = next((r for r in roles_res.json() if r["role_code"] == "EXECUTIVE"), None)
            check(
                exec_role is not None
                and exec_role["is_read_only"] is True
                and sorted(exec_role["allowed_menus"]) == sorted(["dashboard", "samples", "planning", "personnel", "studies", "conflicts"]),
                "EXECUTIVE rolü varsayılan olarak Salt Okunur ve sadece izleme ekranları (dashboard, samples, planning, personnel, studies, conflicts) açık",
            )
            exec_u = client.post(
                "/api/v1/users",
                headers=h_admin,
                json={
                    "username": "ozkan.bey",
                    "full_name": "Özkan Bey (Üst Yönetim — GM / GMY)",
                    "role": "EXECUTIVE",
                    "password": DEFAULT_PASSWORD,
                },
            )
            check(exec_u.status_code == 201 and exec_u.json()["is_read_only"] is True, "EXECUTIVE kullanıcısı (ozkan.bey) oluşturuldu")
            h_exec = auth_headers(client, "ozkan.bey", DEFAULT_PASSWORD)
            check(client.get("/api/v1/planning/summary", headers=h_exec).status_code == 200, "EXECUTIVE GET /summary (İzleme) → 200")
            check(client.get("/api/v1/planning/calendar", headers=h_exec).status_code == 200, "EXECUTIVE GET /calendar (İzleme) → 200")
            check(
                client.post(
                    "/api/v1/planning/schedule-study",
                    headers=h_exec,
                    json={"study_code": "T-EXEC-FAIL", "acclimatization_start_date": "2027-02-01"},
                ).status_code == 403,
                "EXECUTIVE POST /schedule-study → 403 (Salt Okunur İzleme Modu yazmayı engelledi)",
            )
            check(client.get("/api/v1/users", headers=h_exec).status_code == 403, "EXECUTIVE GET /users → 403")
            new_role_res = client.post(
                "/api/v1/users/roles",
                headers=h_admin,
                json={
                    "role_code": "GMY_IZLEME",
                    "role_label": "Genel Müdür Yardımcısı (İzleme)",
                    "allowed_menus": ["dashboard", "studies"],
                    "is_read_only": True,
                },
            )
            check(new_role_res.status_code == 201 and new_role_res.json()["role_code"] == "GMY_IZLEME", "SYSADMIN POST /users/roles ile yeni özel rol oluşturdu")
            upd_role_res = client.put(
                "/api/v1/users/roles/GMY_IZLEME",
                headers=h_admin,
                json={"allowed_menus": ["dashboard", "planning", "studies"], "is_read_only": True},
            )
            check(upd_role_res.status_code == 200 and "planning" in upd_role_res.json()["allowed_menus"], "SYSADMIN PUT /users/roles/{code} ile ekran yetkilerini güncelledi")
            check(client.put("/api/v1/users/roles/GMY_IZLEME", headers=h_tfm, json={"is_read_only": False}).status_code == 403, "TFM rol matrisini değiştiremez (Sadece SYSADMIN) → 403"
            )


            print("\n[13] FAZ 8.1: Test Kısıtlama Takvimi, Kafes + Dr. Anoop Esneklik %, 24-72s Cihaz Motoru, 5 Şablon, Numune & Çalışma Takip")
            import io as _io
            from docx import Document as _DocxReader

            def sched(code, start, tpl="ISO_10993_23_IC", headers=None):
                r = client.post("/api/v1/planning/schedule-study", headers=headers or h_tfm,
                                json={"study_code": code, "acclimatization_start_date": start, "template_code": tpl})
                assert r.status_code == 200, f"{code}: {r.status_code} {r.text}"
                return r.json()

            # 13a) Test kısıtlama takvimi ---------------------------------------------------------
            rs_forbidden = client.post("/api/v1/restrictions", headers=h_qa, json={
                "template_code": "ISO_10993_23_IC", "test_name": "X", "restricted_from": "2026-12-01",
                "restricted_until": "2026-12-17", "reason": "test"})
            check(rs_forbidden.status_code == 403, "QA (salt okunur) test kısıtlaması ekleyemez → 403")
            rs_tfm_forbidden = client.post("/api/v1/restrictions", headers=h_tfm, json={
                "template_code": "ISO_10993_23_IC", "test_name": "X", "restricted_from": "2026-12-01",
                "restricted_until": "2026-12-17", "reason": "test"})
            check(rs_tfm_forbidden.status_code == 403, "TFM test kısıtlaması ekleyemez (Sadece SYSADMIN) → 403")
            bad_rng = client.post("/api/v1/restrictions", headers=h_admin, json={
                "template_code": "ISO_10993_23_IC", "test_name": "X", "restricted_from": "2026-12-17",
                "restricted_until": "2026-12-01", "reason": "test"})
            check(bad_rng.status_code == 422, "Bitiş tarihi başlangıçtan önce olan kısıtlama → 422")
            rs = client.post("/api/v1/restrictions", headers=h_admin, json={
                "template_code": "ISO_10993_23_IC", "test_name": "İntrakütanöz Reaktivite Testi (ISO 10993-23)",
                "restricted_from": "2026-12-01", "restricted_until": "2026-12-17",
                "reason": "Tavşan tedarikçisi sevkiyat aksaklığı"})
            check(rs.status_code == 201 and rs.json()["is_active"] is True, "POST /restrictions (SYSADMIN) → kısıtlama kaydı oluşturuldu")
            rs_id = rs.json()["id"]
            check(client.get("/api/v1/restrictions", headers=h_exec).status_code == 200, "EXECUTIVE kısıtlamaları görüntüleyebilir (GET → 200)")
            shifted = sched("T-BLK-1", "2026-12-07")
            exp_notice = ("OTOMATİK TARİH PLANLAMASI: İntrakütanöz Reaktivite Testi (ISO 10993-23), 'Tavşan tedarikçisi sevkiyat aksaklığı' "
                          "nedeniyle 17.12.2026 tarihine kadar kısıtlı olduğu için başlangıç tarihi otomatik olarak 18.12.2026 tarihine planlanmıştır.")
            check(shifted["acclimatization_start_date"] == "2026-12-18", "Gün 0 (07.12) kısıtlı aralıkta → restricted_until + 1 = 18.12.2026'ya ötelendi")
            check((shifted["auto_schedule_notice"] or {}).get("text") == exp_notice, "Otomatik tarih planlaması bilgisi tam metinle kaydedildi")
            check(datetime.fromisoformat(shifted["steps"][0]["planned_start"]).date() == date(2026, 12, 18), "Takvimin G0 adımı yeni Gün 0'a taşındı")
            blk_study = db.query(Study).filter(Study.study_code == "T-BLK-1").first()
            db.refresh(blk_study)
            check(exp_notice in (blk_study.description or ""), "Bilgi çalışma kaydına (description) yazıldı")
            sat_case = client.post("/api/v1/restrictions", headers=h_admin, json={
                "template_code": "ALL", "test_name": "Tüm Testler", "restricted_from": "2027-02-01",
                "restricted_until": "2027-02-05", "reason": "Tesis bakımı"})
            sat_json = client.post("/api/v1/restrictions/preview-shift", headers=h_tfm,
                                   json={"template_code": "ISO_10993_5_CYT", "start_date": "2027-02-03"}).json()
            check(sat_json["shifted"] and sat_json["new_start_date"] == "2027-02-08",
                  "ALL kısıtlaması + takma ad (ISO_10993_5_CYT): Cuma biten kısıtlama → hafta sonu atlanıp Pazartesi'ye öteleme")
            client.delete(f"/api/v1/restrictions/{sat_case.json()['id']}", headers=h_admin)
            other_tpl = sched("T-BLK-CYT", "2026-12-07", tpl="ISO_10993_5_CYT")
            check(other_tpl["acclimatization_start_date"] == "2026-12-07" and other_tpl["auto_schedule_notice"] is None,
                  "Kısıtlama yalnızca ilgili test şablonunu etkiler (sitotoksisite ötelenmedi)")
            check(other_tpl["template"]["code"] == "ISO_10993_5_CYTO", "ISO_10993_5_CYT takma adı kanonik şablona çözüldü")
            check(client.delete(f"/api/v1/restrictions/{rs_id}", headers=h_admin).status_code == 200, "DELETE /restrictions/{id} (SYSADMIN) → kısıtlama silindi")
            again = sched("T-BLK-1", "2026-12-07")
            check(again["acclimatization_start_date"] == "2026-12-07" and again["auto_schedule_notice"] is None,
                  "Kısıtlama silinince aynı çalışma talep edilen tarihe planlandı ve otomatik tarih notu temizlendi")

            # 13b) Kafes kapasitesi (Fiziksel + Dr. Anoop esneklik %) -----------------------------
            rooms = client.get("/api/v1/room-capacities", headers=h_tfm).json()["rooms"]
            caps = {r["room_code"]: (r["physical_cages"], r["flexibility_pct"], r["planning_capacity"]) for r in rooms}
            check(caps == {"RABBIT_ROOM": (100, 100.0, 200), "RAT_ROOM": (100, 40.0, 140),
                           "GUINEA_PIG_ROOM": (100, 50.0, 150), "MOUSE_ROOM": (120, 50.0, 180)},
                  "Oda kafes tablosu: Tavşan 100/%100→200, Rat 100/%40→140, Kobay 100/%50→150, Fare 120/%50→180")
            upd_room = client.put("/api/v1/room-capacities/RAT_ROOM", headers=h_tfm, json={"physical_cages": 120, "flexibility_pct": 50})
            check(upd_room.status_code == 200 and next(r for r in upd_room.json()["rooms"] if r["room_code"] == "RAT_ROOM")["planning_capacity"] == 180,
                  "PUT /room-capacities: 120 × (1 + %50) = 180 Kafes")
            client.put("/api/v1/room-capacities/RAT_ROOM", headers=h_tfm, json={"physical_cages": 100, "flexibility_pct": 40})
            check(client.put("/api/v1/room-capacities/RABBIT_ROOM", headers=h_qa, json={"physical_cages": 5}).status_code == 403,
                  "QA kafes kapasitesini değiştiremez → 403")
            client.put("/api/v1/room-capacities/RABBIT_ROOM", headers=h_tfm, json={"physical_cages": 3, "flexibility_pct": 100})
            c1 = sched("T-CAGE-1", "2028-03-06")
            check(c1["capacity_info"]["cage"]["level"] == "OK" and c1["capacity_info"]["cage"]["required"] == 3,
                  "Doluluk ≤ Fiziksel Kafes → OK (3 kafes)")
            c2 = sched("T-CAGE-2", "2028-03-06")
            check(c2["capacity_info"]["cage"]["level"] == "FLEX" and "Dr. Anoop" in c2["capacity_info"]["cage"]["message"]
                  and not any(c["type"] == "ROOM_CAPACITY_EXCEEDED" for c in c2["conflicts"]),
                  "Fiziksel < Doluluk ≤ Planlama Kapasitesi → yalnızca bilgi etiketi (çalışma engellenmedi)")
            c3 = sched("T-CAGE-3", "2028-03-06")
            cap_conf = next((c for c in c3["conflicts"] if c["type"] == "ROOM_CAPACITY_EXCEEDED"), None)
            check(c3["capacity_info"]["cage"]["level"] == "EXCEEDED" and cap_conf is not None and cap_conf["severity"] == "CRITICAL",
                  "Doluluk > Sistem Planlama Kapasitesi → kapasite uyarısı (ROOM_CAPACITY_EXCEEDED)")
            res_actions = [r["action"] for r in cap_conf["resolutions"]]
            check("SHIFT_TO_NEXT_AVAILABLE_CAPACITY_DATE" in res_actions, "Uyarıda 'İlk Boşalan Tarihe Kaydır' çözüm butonu var")
            fixed = client.post(f"/api/v1/planning/conflicts/{cap_conf['id']}/apply-resolution", headers=h_tfm,
                                json={"action": "SHIFT_TO_NEXT_AVAILABLE_CAPACITY_DATE"})
            check(fixed.status_code == 200 and fixed.json()["acclimatization_start_date"] > "2028-03-06"
                  and not any(c["type"] == "ROOM_CAPACITY_EXCEEDED" for c in fixed.json()["conflicts"]),
                  "Çözüm uygulandı: Gün 0 ilk boşalan tarihe kaydırıldı ve kapasite uyarısı kalktı")
            client.put("/api/v1/room-capacities/RABBIT_ROOM", headers=h_tfm, json={"physical_cages": 100, "flexibility_pct": 100})

            # 13c) 24-72 saatlik uzun süreli cihazlar (CO2 inkübatör / etüv) --------------------
            leq = {e["code"]: e["max_concurrent_studies"] for e in client.get("/api/v1/long-equipment", headers=h_tfm).json()}
            check({"EQ-WB-001", "EQ-INC-001", "EQ-OVN-001"} <= set(leq), "Yalnızca 24-72s darboğaz cihazlar tanımlı: EQ-WB-001, EQ-INC-001, EQ-OVN-001")
            client.put("/api/v1/long-equipment/EQ-INC-001", headers=h_tfm, json={"max_concurrent_studies": 1})
            y1 = sched("T-CYT-1", "2028-06-05", tpl="ISO_10993_5_CYT")
            check(y1["capacity_info"]["cage"] is None and all(e["level"] == "OK" for e in y1["capacity_info"]["equipment"]),
                  "Sitotoksisite: 0 kafes, ilk çalışma CO2 inkübatör / etüv kapasitesinde")
            y2 = sched("T-CYT-2", "2028-06-05", tpl="ISO_10993_5_CYT")
            check(any("Uzun Süreli Cihaz Kapasite Aşımı" in c["title"] and "EQ-INC-001" in c["title"] for c in y2["conflicts"]),
                  "2. sitotoksisite aynı 24s pencerede → EQ-INC-001 CO2 İnkübatör kapasite aşımı")
            client.put("/api/v1/long-equipment/EQ-INC-001", headers=h_tfm, json={"max_concurrent_studies": 4})

            # 13d) Yeni şablon: ISO 10993-6 İmplantasyon + .docx -----------------------------------
            tpls = {t["code"]: t for t in client.get("/api/v1/planning/templates", headers=h_tfm).json()["templates"]}
            check("ISO_10993_6_IMP" in tpls and len(tpls["ISO_10993_6_IMP"]["steps"]) == 10 and tpls["ISO_10993_6_IMP"]["cage_count"] == 3,
                  "ISO_10993_6_IMP: 10 biyolojik adım, 3 tavşan kafesi")
            check(tpls["ISO_10993_10_SENS"]["cage_count"] == 3 and tpls["ISO_10993_11_ACUTE"]["cage_count"] == 2
                  and tpls["ISO_10993_5_CYTO"]["cage_count"] == 0 and tpls["ISO_10993_23_IC"]["cage_count"] == 3,
                  "Kafes gereksinimleri: IC 3, IMP 3, SENS 3 (kobay), SYS 2 (kemirgen), CYT 0")
            imp = sched("T-IMP-1", "2028-09-04", tpl="ISO_10993_6_IMP")
            check([s["study_day"] for s in imp["steps"]] == [0, 4, 7, 8, 9, 10, 14, 21, 28, 35], "İmplantasyon takvimi G0,G4,G7,G8,G9,G10,G14,G21,G28,G35")
            imp_doc = client.get(f"/api/v1/studies/{imp['study_id']}/export-study-plan", headers=h_tfm)
            doc_txt = ""
            if imp_doc.status_code == 200:
                rd = _DocxReader(_io.BytesIO(imp_doc.content))
                doc_txt = "\n".join(p.text for p in rd.paragraphs) + "\n".join(c.text for t in rd.tables for row in t.rows for c in row.cells)
            check(imp_doc.status_code == 200 and "Subcutaneous Implantation Test" in doc_txt and "ANNEX A" in doc_txt and "ISO 10993-6" in doc_txt,
                  "ISO 10993-6 için .docx Study Plan üretildi (başlık, standart ve Annex A uyarlandı)")

            # 13e) Numune & Çalışma Takip ----------------------------------------------------------
            from app.services.sample_service import seed_sample_tracking
            seeded = seed_sample_tracking(db)
            check(seeded["samples"] == 6 and seeded["users"] == 4, "Örnek veri tohumlandı: 6 numune/çalışma kaydı, 4 kullanıcı (Ayşe Özgür, Burcu DİGER KULAK, İlknur Toklu, TRM Kabul)")
            check(seed_sample_tracking(db) == {"users": 0, "samples": 0}, "Tohumlama idempotent (ikinci çalıştırmada kayıt eklenmedi)")
            h_sales = auth_headers(client, "ilknur.toklu", "NanoLab2026!")
            h_trm = auth_headers(client, "trm_kabul", "NanoLab2026!")
            lst = client.get("/api/v1/samples", headers=h_tfm)
            check(lst.status_code == 200 and lst.json()["summary"]["total"] == 6, "GET /samples → 6 kayıt + özet şeridi")
            summ = lst.json()["summary"]
            check(all(k in summ for k in ("expected", "planned", "ongoing", "overdue", "by_study_director")), "Özet: Beklenen / Planlanan / Devam eden / Gecikmiş + ÇY bazında açık çalışmalar")
            check([x["name"] for x in summ["by_study_director"][:4]] == ["Ezgi Nur AKIN", "Ayşe Özgür", "Burcu DİGER KULAK", "Atanmamış"],
                  "Çalışma Yöneticisi bazında: Ezgi Nur AKIN, Ayşe Özgür, Burcu DİGER KULAK, Atanmamış")
            check(client.get("/api/samples", headers=h_tfm).status_code == 200, "/api/samples kısa yolu da çalışıyor")
            by_code = {i["study_code"]: i for i in lst.json()["items"]}
            sid = {k: v["id"] for k, v in by_code.items()}
            check(by_code["GLP2026-078"]["status"] == "EXPECTED" and by_code["GLP2026-072"]["status"] == "PLANNED"
                  and by_code["GLP2026-031"]["status"] == "ONGOING", "Durumlar: 078 Beklenen, 072 Planlanan, 031 Devam eden")
            check(by_code["GLP2026-026"]["is_overdue"] is True, "GLP2026-026: final rapor süresi geçti → Gecikmiş iş")
            check(client.get("/api/v1/samples", headers=auth_headers(client, "invivo_1")).status_code == 403, "Teknisyen Numune Takip ekranına giremez → 403")
            # Rol bazlı düzenleme
            check(client.put(f"/api/v1/samples/{sid['GLP2026-072']}", headers=h_sales, json={"quote_no": "TKL-2026-114"}).status_code == 200,
                  "Satış rolü satış bilgilerini (Teklif No) düzenleyebilir")
            check(client.put(f"/api/v1/samples/{sid['GLP2026-072']}", headers=h_sales, json={"lot_no": "L-1"}).status_code == 403,
                  "Satış rolü numune kabul (TRM) alanlarını düzenleyemez → 403")
            check(client.put(f"/api/v1/samples/{sid['GLP2026-072']}", headers=h_trm, json={"quote_no": "X"}).status_code == 403,
                  "TRM Kabul rolü satış alanlarını düzenleyemez → 403")
            shared = client.put(f"/api/v1/samples/{sid['GLP2026-072']}", headers=h_trm,
                                json={"lot_no": "LOT-PLLA-001", "storage_condition": "Oda sıcaklığı", "apply_to_related": True})
            check(shared.status_code == 200 and sorted(shared.json()["propagated_to"]) == ["GLP2026-073", "GLP2026-076"],
                  "TRM Kabul: 'Aynı numuneyi kullanan diğer çalışmalar' (076, 073) ortak güncellendi")
            rel = client.get(f"/api/v1/samples/{sid['GLP2026-076']}", headers=h_tfm).json()
            check(rel["lot_no"] == "LOT-PLLA-001" and {r["study_code"] for r in rel["related"]} == {"GLP2026-072", "GLP2026-073"},
                  "Bağlantılı çalışmalar listesi (TI-2026-0016) ve ortak Lot doğrulandı")
            check(client.put(f"/api/v1/samples/{sid['GLP2026-072']}", headers=h_exec, json={"quote_no": "Y"}).status_code == 403,
                  "EXECUTIVE (GM/GMY) numune kaydını düzenleyemez → 403")
            check(client.post(f"/api/v1/samples/{sid['GLP2026-072']}/plan", headers=h_exec, json={}).status_code == 403,
                  "EXECUTIVE otomatik takvim oluşturamaz → 403")
            check(client.get(f"/api/v1/samples/{sid['GLP2026-072']}", headers=h_exec).status_code == 200, "EXECUTIVE numune detayını görüntüleyebilir")
            check(client.get("/api/v1/planning/summary", headers=h_sales).status_code == 200
                  and client.post("/api/v1/planning/schedule-study", headers=h_sales, json={}).status_code == 403,
                  "Satış rolü Dashboard özetini görebilir ancak çalışma takvimi oluşturamaz (403)")
            # Otomatik takvim + tarihler
            plan = client.post(f"/api/v1/samples/{sid['GLP2026-072']}/plan", headers=h_sd, json={})
            check(plan.status_code == 200 and plan.json()["plan"]["study_id"] and plan.json()["sample"]["scheduled"] is True,
                  "İş Akışı & Takvimi Planla: 072 için otomatik taslak çalışma + takvim oluştu")
            s72 = plan.json()["sample"]
            end72 = date.fromisoformat(s72["dates"]["end"])
            check(s72["dates"]["draft_report"] == (end72 + timedelta(days=3)).isoformat()
                  and s72["dates"]["final_report"] == (end72 + timedelta(days=7)).isoformat(),
                  "Taslak rapor = bitiş + 3 gün, Final rapor = bitiş + 7 gün")
            wf72 = {s["no"]: s for s in s72["workflow"]}
            check(len(s72["workflow"]) == 11 and wf72[4]["done"] and wf72[5]["done"] and wf72[1]["done"],
                  "11 adımlı iş akışı: sözleşme, numune kabulü ve taslak plan otomatik tamamlandı")
            study72 = db.query(Study).filter(Study.study_code == "GLP2026-072").first()
            db.refresh(study72)
            check(study72.template_code == "ISO_10993_6_IMP" and study72.test_item_name == "MERKEN PLLA+HA", "Çalışma kaydı numune verileriyle oluştu (ISO_10993_6_IMP)")
            dl = client.get(f"/api/v1/samples/{sid['GLP2026-072']}/study-plan-docx", headers=h_exec)
            check(dl.status_code == 200 and dl.content[:2] == b"PK", "Satırdan Study Plan (.docx) indirildi (GM/GMY salt okunur dahil)")
            dl_none = client.get(f"/api/v1/samples/{sid['GLP2026-078']}/study-plan-docx", headers=h_exec)
            check(dl_none.status_code == 409, "Takvimi olmayan satırda salt okunur rol için açıklayıcı 409 döner")
            # Onay imzaları
            check(client.post(f"/api/v1/samples/{sid['GLP2026-072']}/workflow/6", headers=h_sd, json={"action": "sign", "approver": "KG"}).status_code == 403,
                  "ÇY, KG onayını veremez → 403")
            ap1 = client.post(f"/api/v1/samples/{sid['GLP2026-072']}/workflow/6", headers=h_sd, json={"action": "sign", "approver": "CY"})
            ap2 = client.post(f"/api/v1/samples/{sid['GLP2026-072']}/workflow/6", headers=h_qa, json={"action": "sign", "approver": "KG"})
            ap3 = client.post(f"/api/v1/samples/{sid['GLP2026-072']}/workflow/6", headers=h_tfm, json={"action": "sign", "approver": "TBY"})
            st6 = next(s for s in ap3.json()["workflow"] if s["no"] == 6)
            check(ap1.status_code == 200 and ap2.status_code == 200 and st6["done"] and all(a["signed"] and a["by"] and a["at"] for a in st6["approvals"]),
                  "Plan onayı: ÇY · KG · TBY imzaları kişi adı ve tarihiyle kaydedildi → adım 6 tamamlandı")
            check(client.post(f"/api/v1/samples/{sid['GLP2026-072']}/workflow/2", headers=h_sales, json={"action": "complete"}).status_code == 403,
                  "Satış, Çalışma Yöneticisi adımını (Etik kurul) tamamlayamaz → 403")
            check(client.post(f"/api/v1/samples/{sid['GLP2026-072']}/workflow/10", headers=h_sales, json={"action": "complete"}).status_code == 200,
                  "Satış, 'Ödemenin tamamlanması' adımını tamamlayabilir")
            # Tümünü otomatik takvimle
            allp = client.post("/api/v1/samples/auto-schedule-all", headers=h_tfm)
            ok_codes = sorted(r["study_code"] for r in allp.json()["results"] if r["ok"])
            check(allp.status_code == 200 and ok_codes == ["GLP2026-073", "GLP2026-076"],
                  "Tüm Planlananları Otomatik Takvimle: 076 (Sitotoksisite) ve 073 (Sensitizasyon) takvimlendi")
            s76 = client.get(f"/api/v1/samples/{sid['GLP2026-076']}", headers=h_tfm).json()
            check(s76["scheduled"] and s76["study_director_name"] == "Ayşe Özgür", "076 çalışması Ayşe Özgür'e atandı ve takvimlendi")
            # Excel / CSV içe aktarma
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.append(["Rapor: Numune Listesi"])
            ws.append(["GLP No", "Talep Edilen Analiz", "Test Maddesinin Adı", "Sponsor", "Teklif No", "Beklenen Geliş Tarihi", "Çalışma Yöneticisi"])
            ws.append(["GLP2026-090", "Sitotoksisite Testi", "Örnek Test Ürünü", "ACME Medikal", "TKL-2026-200", "15.11.2026", "Burcu DİGER KULAK"])
            ws.append(["GLP2026-091", "Sensitizasyon Testi", "Örnek Test Ürünü 2", "ACME Medikal", "TKL-2026-201", datetime(2026, 11, 20), None])
            buf = _io.BytesIO()
            wb.save(buf)
            imp_x = client.post("/api/v1/samples/import-excel", headers=h_sales,
                                files={"file": ("numuneler.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
            check(imp_x.status_code == 200 and imp_x.json()["created"] == 2, "Excel (.xlsx) içe aktarma: başlık satırı otomatik bulundu, 2 kayıt oluştu")
            csv_txt = "GLP No;Teklif No;Lot No\nGLP2026-090;TKL-2026-999;LOT-77\n"
            imp_c = client.post("/api/v1/samples/import-excel", headers=h_tfm, files={"file": ("guncelle.csv", csv_txt.encode("utf-8"), "text/csv")})
            check(imp_c.status_code == 200 and imp_c.json()["updated"] == 1, "CSV (;) içe aktarma: mevcut kayıt güncellendi")
            s90 = client.get("/api/v1/samples", headers=h_tfm).json()
            row90 = next(i for i in s90["items"] if i["study_code"] == "GLP2026-090")
            check(row90["template_code"] == "ISO_10993_5_CYTO" and row90["quote_no"] == "TKL-2026-999" and row90["expected_arrival_date"] == "2026-11-15",
                  "İçe aktarma: analiz adından şablon (sitotoksisite) çıkarıldı, tarih ve alanlar eşlendi")
            check(client.post("/api/v1/samples/import-excel", headers=h_exec, files={"file": ("x.csv", b"GLP No\nGLP1", "text/csv")}).status_code == 403,
                  "EXECUTIVE Excel içe aktaramaz → 403")
            print("\n[14] FAZ 8.2: Şablona Özgü Study Plan (.docx) Bölüm 6–10 Metinleri ve Çekmeceden TIIS / CoA / FM.083 PDF Yükleme + Otomatik Doldurma")
            import re as _re

            def docx_text(study_id, include_document=False):
                r = client.get(f"/api/v1/studies/{study_id}/export-study-plan", headers=h_tfm)
                assert r.status_code == 200, f"docx {study_id}: {r.status_code}"
                rd = _DocxReader(_io.BytesIO(r.content))
                parts = [p.text for p in rd.paragraphs]
                for t in rd.tables:
                    for row in t.rows:
                        seen = set()
                        for c in row.cells:
                            if id(c._tc) in seen:
                                continue
                            seen.add(id(c._tc))
                            parts.append(c.text)
                return ("\n".join(parts), rd) if include_document else "\n".join(parts)

            doc_cases = [
                ("T-DOC-IMP", "2029-02-05", "ISO_10993_6_IMP", "ISO 10993-6",
                 ["Subcutaneous Implantation Test", "histopatholog", "implant sites", "Tests for Local Effects after Implantation"], ["New Zealand White Rabbits"][:0]),
                ("T-DOC-CYT", "2029-03-05", "ISO_10993_5_CYT", "ISO 10993-5",
                 ["L929", "CO2", "MTT", "Not Applicable for Live Animals", "In Vitro Cytotoxicity"], ["New Zealand", "Rabbit"]),
                ("T-DOC-SENS", "2029-04-02", "ISO_10993_10_SENS", "ISO 10993-10",
                 ["Magnusson & Kligman", "Induction", "Challenge", "Guinea Pig Room", "Albino"], ["New Zealand", "Rabbit"]),
                ("T-DOC-SYS", "2029-05-07", "ISO_10993_11_SYS", "ISO 10993-11",
                 ["intravenous", "intraperitoneal", "4, 24, 48 and 72", "Mouse / Rat Room", "Systemic Toxicity"], ["New Zealand", "Rabbit"]),
            ]
            for code, start, tpl_code, std, must, must_not in doc_cases:
                rsp = sched(code, start, tpl=tpl_code)
                txt, rendered = docx_text(rsp["study_id"], include_document=True)
                low = txt.lower()
                miss = [m for m in must if m.lower() not in low]
                bad = [m for m in must_not if m.lower() in low]
                check(not miss and not bad, f"{std} .docx: bölüm metinleri şablona göre dinamik (eksik={miss}, kalan={bad})")
                # Preserve the master-template figure and its truthful source caption.
                # Only that reference illustration may retain the original ISO number.
                protocol_txt = txt.replace("Figure-1: Arrangement of Injection Sites (Source: ISO 10993-23)", "")
                check("intracutaneous" not in low and "ISO 10993-23" not in protocol_txt and std in txt,
                      f"{std} .docx: protokol metni hedef standarda uyarlandı; referans şeklin özgün kaynak açıklaması korundu")
                fields = {r.cells[0].text.strip(): r.cells[2].text.strip()
                          for t in rendered.tables for r in t.rows if len(r.cells) == 3}
                check(fields["LOT Number"] == "TBD" and fields["Study Completion Date"] == "TBD",
                      f"{std} .docx: eksik lot ve tamamlanma tarihi alanları TBD")

            # --- Çekmeceden belge yükleme + otomatik doldurma (OpenAI çağrısı mock) ---
            import fitz as _fitz

            def make_pdf(text):
                pdf = _fitz.open()
                pdf.new_page().insert_text((72, 72), text)
                data = pdf.tobytes()
                pdf.close()
                return data

            calls = {"n": 0}

            def fake_drawer_llm(messages):
                calls["n"] += 1
                coa = calls["n"] % 2 == 0
                return {
                    "doc_category": "COA_CERTIFICATE" if coa else "TIIS_FORM",
                    "doc_summary": "Analiz Sertifikası (CoA)" if coa else "Test Maddesi Bilgi Formu (TIIS)",
                    "study_codes": [], "primary_study_code": None, "study_code_mappings": [],
                    "test_type": None, "guideline": None,
                    "sponsor_name": "MERKEN", "sponsor_contact": None,
                    "test_item_name": "MERKEN PLLA+HA",
                    "lot_batch_no": "LOT-2026-77",
                    "manufacture_date": "2026-05-02",
                    "expiry_date": "2029-05-01",
                    "storage_conditions": "Oda Sicakligi (15-25 C)",
                    "physical_state": None, "sterility": None,
                    "extraction_polar": True if not coa else None,
                    "extraction_polar_solvent": "%0.9 NaCl (Salin)" if not coa else None,
                    "extraction_non_polar": True if not coa else None,
                    "extraction_non_polar_solvent": "Susam Yagi" if not coa else None,
                    "extraction_ratio": None, "extraction_conditions": None,
                    "animal_species_strain": None, "animal_count": None, "animal_birth_date": None,
                    "acclimatization_start_date": None, "requested_start_period": None, "study_director": None,
                    "warnings": [],
                }

            dp._llm_call = fake_drawer_llm
            pdfs = [("TIIS_MERKEN.pdf", make_pdf("TIIS Lot LOT-2026-77 Polar Non-Polar"), "application/pdf"),
                    ("CoA_MERKEN.pdf", make_pdf("Certificate of Analysis Lot LOT-2026-77 Expiry 2029-05-01"), "application/pdf")]
            check(client.post(f"/api/v1/samples/{sid['GLP2026-078']}/documents", headers=h_exec,
                              files=[("files", p) for p in pdfs]).status_code == 403,
                  "EXECUTIVE (salt okunur) çekmeceden belge yükleyemez → 403")
            check(client.post(f"/api/v1/samples/{sid['GLP2026-078']}/documents", headers=auth_headers(client, "invivo_1"),
                              files=[("files", pdfs[0])]).status_code == 403, "Teknisyen belge yükleyemez → 403")
            up78 = client.post(f"/api/v1/samples/{sid['GLP2026-078']}/documents", headers=h_trm, files=[("files", p) for p in pdfs])
            j78 = up78.json()
            check(up78.status_code == 200 and j78["ok_count"] == 2 and j78["failed_count"] == 0,
                  "TRM Kabul çekmeceden 2 PDF (TIIS + CoA) yükledi → Vision OCR ile okundu")
            s78 = j78["sample"]
            check(s78["lot_no"] == "LOT-2026-77" and s78["expiry_date"] == "2029-05-01" and s78["manufacture_date"] == "2026-05-02"
                  and s78["storage_condition"] == "Oda Sicakligi (15-25 C)",
                  "Lot / SKT / Üretim Tarihi / Saklama Koşulu PDF'ten SampleRecord'a yazıldı")
            check(s78["extraction_polar_solvent"] == "%0.9 NaCl (Salin)" and s78["extraction_non_polar_solvent"] == "Susam Yagi"
                  and s78["extraction_polar"] is True and s78["extraction_non_polar"] is True,
                  "Polar / Apolar ekstraksiyon çözücüleri PDF'ten okunup kaydedildi")
            check(s78["sponsor_name"] == "MERKEN" and s78["test_item_name"] == "MERKEN PLLA+HA",
                  "Sponsor ve Test Maddesi Adı doldu ('(Numune bekleniyor)' yer tutucusu değiştirildi)")
            check(db.query(Document).filter(Document.dossier_key == "GLP2026-078").count() == 2,
                  "Belgeler çalışmanın klasörüne (dossier_key = study_code) kaydedildi")
            check(len(client.get(f"/api/v1/samples/{sid['GLP2026-078']}/documents", headers=h_tfm).json()["documents"]) == 2,
                  "GET /samples/{id}/documents klasördeki belgeleri listeledi")
            bad_up = client.post(f"/api/v1/samples/{sid['GLP2026-078']}/documents", headers=h_trm,
                                 files=[("files", ("virus.exe", b"MZ", "application/octet-stream"))])
            check(bad_up.status_code == 200 and bad_up.json()["failed_count"] == 1, "Desteklenmeyen dosya türü satır bazında hata döner (diğer dosyalar etkilenmez)")

            # Planlama: belgelerden dolan alanlar yeni çalışma kaydına aktarılır
            pl78 = client.post(f"/api/v1/samples/{sid['GLP2026-078']}/plan", headers=h_tfm, json={})
            study78 = db.query(Study).filter(Study.study_code == "GLP2026-078").first()
            db.refresh(study78)
            check(pl78.status_code == 200 and study78.test_item_batch == "LOT-2026-77" and study78.extraction_polar is True
                  and study78.extraction_non_polar_solvent == "Susam Yagi",
                  "Belgelerden dolan Lot ve çözücü bilgileri planlamada Study kaydına aktarıldı")

            # Study zaten varken: farklı alanlar bildirilir, boşlar dolar, Study.dossier_metadata güncellenir, ortak numuneye yayılır
            up72 = client.post(f"/api/v1/samples/{sid['GLP2026-072']}/documents", headers=h_trm, files=[("files", p) for p in pdfs])
            j72 = up72.json()
            check(up72.status_code == 200 and any(d["field"] == "lot_no" and d["current"] == "LOT-PLLA-001" for d in j72["differences"]),
                  "Kayıtta dolu olan Lot, belgedekinden farklıysa ezilmeden 'fark' olarak bildirildi")
            check(j72["sample"]["lot_no"] == "LOT-PLLA-001" and j72["sample"]["expiry_date"] == "2029-05-01",
                  "Dolu alan korundu, boş SKT belgeden dolduruldu")
            study72 = db.query(Study).filter(Study.study_code == "GLP2026-072").first()
            db.refresh(study72)
            check(study72.expiry_date == "2029-05-01" and study72.extraction_polar is True
                  and (study72.dossier_metadata or {}).get("document_autofill", {}).get("fields", {}).get("expiry_date"),
                  "Bağlı Study kaydı (alanlar + dossier_metadata.document_autofill) güncellendi")
            check(sorted(j72["propagated_to"]) == ["GLP2026-073", "GLP2026-076"],
                  "Aynı TI kodunu paylaşan 076 ve 073 çalışmalarının boş alanlarına yayıldı")
            ow72 = client.post(f"/api/v1/samples/{sid['GLP2026-072']}/documents?overwrite=true", headers=h_trm, files=[("files", pdfs[0])])
            check(ow72.status_code == 200 and ow72.json()["sample"]["lot_no"] == "LOT-2026-77", "overwrite=true ile Lot belgedeki değerle güncellendi")
            db.refresh(study72)
            check(study72.test_item_batch == "LOT-2026-77", "Study.test_item_batch de eşitlendi")
            check("LOT-2026-77" in docx_text(study72.id), "Study Plan .docx belgesi yüklenen belgedeki Lot ile dolduruldu")

            print("\n[15] FAZ 8.3: Study Status last version (2).xlsx Tam İçe Aktarım (88 GLP + 5 Non-GLP + 47 İş Akışı), 12 Şablon TAT/Hayvan Akıbeti ve Otomatik Takvimleme")
            from app.services.templates import TEMPLATES as _TPLS
            check(len(_TPLS) >= 12 and {"ISO_10993_11_PYRO", "ISO_10993_4_HEMO", "ISO_10993_11_SUBACUTE", "ISO_10993_11_SUBCHRONIC",
                                        "ISO_10993_6_IMP_13W", "ISO_10993_6_IMP_26W", "PHYS_CHEM_MONO"}.issubset(set(_TPLS.keys())),
                  "IN VIVO TEST SÜRELERİ & TEKRAR KULLANIM: 12 şablon eksiksiz tanımlı")
            check(_TPLS["ISO_10993_23_IC"].tat_without_quarantine_days == 26 and _TPLS["ISO_10993_23_IC"].tat_with_quarantine_days == 33
                  and _TPLS["ISO_10993_10_SENS"].max_animals == 30 and _TPLS["ISO_10993_6_IMP_26W"].tat_with_quarantine_days == 202,
                  "TAT (karantinalı/karantinasız) ve maksimum hayvan sayıları Excel ile birebir uyumlu")
            rc_res = client.get("/api/v1/room-capacities", headers=h_tfm).json()
            check(rc_res.get("available_animals") == {"Guinea pig": 152, "Rabbit": 98, "Mouse": 20, "Rat": 19},
                  "Tesiste mevcut hayvan stok bilgisi (Guinea pig: 152, Rabbit: 98, Mouse: 20, Rat: 19) doğrulandı")
            # [1]..[14] bölümlerinde oluşturulan geçici test kayıtlarını açıkça is_historical_demo=True olarak işaretle
            from app.models.sample import SampleRecord as _SR83
            for _sr_tmp in db.query(_SR83).filter(_SR83.study_code.in_(["GLP2026-090", "GLP2026-091"])).all():
                _wf_tmp = dict(_sr_tmp.workflow or {})
                _wf_tmp["is_historical_demo"] = True
                _sr_tmp.workflow = _wf_tmp
            for _st_tmp in db.query(Study).all():
                if (_st_tmp.study_code or "").startswith(("T-", "26/", "GLP-2026-EDR-")) or _st_tmp.study_code in ("GLP2026-090", "GLP2026-091"):
                    _md_tmp = dict(_st_tmp.dossier_metadata or {})
                    _md_tmp["is_historical_demo"] = True
                    _st_tmp.dossier_metadata = _md_tmp
            db.commit()
            xlsx_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Study Status last version (2).xlsx"))
            with open(xlsx_path, "rb") as _xf:
                xlsx_bytes = _xf.read()
            before_codes = {x.study_code for x in db.query(_SR83).all()}
            before_030 = [x.id for x in db.query(StudyStep).join(Study).filter(Study.study_code == "GLP2026-030").all()]
            imp83 = client.post("/api/v1/samples/import-excel", headers=h_tfm,
                                files={"file": ("Study Status last version (2).xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
            j83 = imp83.json()
            check(imp83.status_code == 200 and j83["glp_count"] == 88 and j83["non_glp_count"] == 5 and j83["total_rows"] == 93 and j83["workflow_matched"] == 47,
                  "Study Status last version (2).xlsx: 88 GLP + 5 Non-GLP = 93 çalışma ve 47 numune iş akışı içe aktarıldı")
            s_all = client.get("/api/v1/samples", headers=h_tfm).json()
            check(before_codes.issubset({x["study_code"] for x in s_all["items"]}) and len(s_all["items"]) == 93 + len(before_codes - {x.study_code for x in db.query(_SR83).all() if (x.workflow or {}).get("_excel_source")}), "Excel satırları aktarıldı; dosyada olmayan kayıtlar korundu")
            glp_items = [i for i in s_all["items"] if i.get("glp_type") == "GLP"]
            nglp_items = [i for i in s_all["items"] if i.get("glp_type") == "NON-GLP"]
            from collections import Counter as _Cnt
            glp_cnt = _Cnt((i.workflow or {}).get("_excel_source", {}).get("stored_status") for i in db.query(_SR83).all() if i.glp_type == "GLP" and (i.workflow or {}).get("_excel_source"))
            nglp_cnt = _Cnt((i.workflow or {}).get("_excel_source", {}).get("stored_status") for i in db.query(_SR83).all() if i.glp_type == "NON-GLP" and (i.workflow or {}).get("_excel_source"))
            check(glp_cnt["EXPECTED"] == 3 and glp_cnt["PLANNED"] == 14 and glp_cnt["ONGOING"] == 30 and glp_cnt["COMPLETED"] == 41,
                  f"88 GLP durum dağılımı birebir: 3 Beklenen, 14 Planlanan, 30 Devam Eden, 41 Biten ({dict(glp_cnt)})")
            check(nglp_cnt["PLANNED"] == 2 and nglp_cnt["ONGOING"] == 3,
                  f"5 Non-GLP durum dağılımı birebir: 2 Planlanan, 3 Devam Eden ({dict(nglp_cnt)})")
            yb = db.query(User).filter(User.username == "yigit.babaoglu").first()
            yk = db.query(User).filter(User.username.in_(["yigit", "admin"])).first()
            check(yb is not None and yb.is_active is False and yk is not None and yk.is_active is True,
                  "Eski ÇY Yiğit Babaoğlu pasif (is_active=False) olarak korundu, aktif SYSADMIN hesabına dokunulmadı")
            s030 = next(i for i in glp_items if i["study_code"] == "GLP2026-030")
            s059 = next(i for i in glp_items if i["study_code"] == "GLP2026-059")
            check(before_030 == [x.id for x in db.query(StudyStep).join(Study).filter(Study.study_code == "GLP2026-030").all()] and s059["scheduled"] and s059["status"] == "EXPECTED",
                  "Devam eden 030 görevleri korundu; yeni Beklenen 059 taslağı takvimlendi")
            dl059 = client.get(f"/api/v1/samples/{s059['id']}/study-plan-docx", headers=h_exec)
            check(dl059.status_code == 200 and dl059.content[:2] == b"PK",
                  "Beklenen/Planlanan/Devam Eden tüm satırlarda Study Plan İndir (.docx) sorunsuz çalışıyor")

            print("\n[16] FAZ 8.4: yigit SYSADMIN Koruması, Test Kısıtlama SYSADMIN Yetkisi, Personel/ÇY Rol Filtresi, Dashboard Erişim Matrisi ve Hızlı Takvim Motoru")
            me_admin = client.get("/api/v1/auth/me", headers=h_admin).json()
            check(me_admin["role"] == "SYSADMIN" and me_admin["is_active"] is True and "dashboard" in me_admin["allowed_menus"],
                  "/api/v1/auth/me → SYSADMIN rolü, aktif durumu ve allowed_menus senkronize")
            self_demote = client.put(f"/api/v1/users/{me_admin['id']}", headers=h_admin, json={"role": "STUDY_DIRECTOR"})
            check(self_demote.status_code == 400, "PUT /api/v1/users/{id}: aktif SYSADMIN kendi rolünü düşüremez → 400")
            self_deact = client.put(f"/api/users/{me_admin['id']}", headers=h_admin, json={"is_active": False})
            check(self_deact.status_code == 400, "PUT /api/users/{id}: aktif SYSADMIN kendi hesabını pasife alamaz → 400")
            # Personel ve İş Yükü rol filtreleri
            pers_list = client.get("/api/v1/personnel", headers=h_tfm).json()
            forbidden_roles = {"SYSADMIN", "ADMIN", "EXECUTIVE", "SALES", "TRM_KABUL", "TRM_ACCEPTANCE"}
            check(all(u["role"] not in forbidden_roles and u["username"] != "yigit" for u in pers_list),
                  "GET /api/v1/personnel: SYSADMIN, EXECUTIVE, SALES ve TRM_KABUL hariç tutuldu")
            wl_list = client.get("/api/v1/planning/workload?target_date=2026-10-12", headers=h_tfm).json()["personnel"]
            wl_alias = client.get("/api/v1/planning/personnel-workload?target_date=2026-10-12", headers=h_tfm).json()["personnel"]
            check(all(p["role"] not in forbidden_roles and p["personnel_id"] != me_admin["id"] for p in wl_list) and len(wl_list) == len(wl_alias),
                  "GET /workload & /personnel-workload: yalnızca gerçek laboratuvar personeli listeleniyor")
            # SYSADMIN / EXECUTIVE / SALES ÇY olarak atanamaz
            bad_sd = client.post("/api/v1/planning/schedule-study", headers=h_tfm,
                                 json={"study_code": "T-BAD-SD", "acclimatization_start_date": "2027-04-05", "study_director_id": me_admin["id"]})
            check(bad_sd.status_code == 400, "SYSADMIN (yigit) Çalışma Yöneticisi (SD) olarak atanamaz → 400")
            # Dashboard erişim matrisi: sadece SYSADMIN, EXECUTIVE ve TFM varsayılan olarak dashboard'a sahip
            roles_84 = {r["role_code"]: r["allowed_menus"] for r in client.get("/api/v1/users/roles", headers=h_admin).json()}
            check(all("dashboard" in roles_84[c] for c in ("SYSADMIN", "EXECUTIVE", "TFM"))
                  and all("dashboard" not in roles_84[c] for c in ("STUDY_DIRECTOR", "PLANNING_COORDINATOR", "QA", "SALES", "TRM_KABUL", "TECHNICIAN")),
                  "Varsayılan rol matrisi: 'dashboard' sadece SYSADMIN, EXECUTIVE ve TFM rollerinde açık")
            # Master takvim performans ve yetim çalışma temizliği
            import time as _t84
            t0 = _t84.perf_counter()
            cal84 = client.get("/api/v1/planning/calendar", headers=h_tfm)
            dt_ms = (_t84.perf_counter() - t0) * 1000
            cal_codes = {s["study_code"] for s in cal84.json()["studies"]}
            check(cal84.status_code == 200 and dt_ms < 2500 and not any(c.startswith("NDMA") or c.startswith("GADOBUTROL") for c in cal_codes),
                  f"GET /api/v1/planning/calendar {len(cal_codes)} çalışmayı {dt_ms:.0f} ms'de döndürdü ve bozuk Non-GLP kodları temizlendi")

            print("\n[17] FAZ 9.2: Geçmiş Görevlerin Kapatılması (Referans: 03.11.2026), Çakışma Kategorizasyonu (CONFIRMED vs MISSING_INFO) ve Recompute Motoru")
            from app.models.study_step import StepStatus
            from app.models.sample import SampleRecord
            # Historical boundary coverage uses explicit pre-existing tasks.
            # Refresh no longer synthesizes tasks for an ongoing Excel row.
            st_hist = db.query(Study).filter(Study.study_code == "GLP2026-030").one()
            if not before_030:
                for offset, day in enumerate((date(2026,10,30), date(2026,11,2), date(2026,11,3), date(2026,11,4))):
                    db.add(StudyStep(study_id=st_hist.id, step_order=offset+1, study_day=offset,
                                     step_name="Historical boundary fixture", status=StepStatus.PENDING,
                                     planned_start=datetime.combine(day, datetime.min.time()),
                                     planned_end=datetime.combine(day, datetime.min.time())+timedelta(hours=1)))
                db.commit()
            completed_fixture = Study(study_code="TEST-HIST-COMPLETED", title="Historical completion fixture",
                                      test_item_name="Fixture", study_director_id=st_hist.study_director_id,
                                      status=StudyStatus.COMPLETED)
            db.add(completed_fixture)
            db.flush()
            for offset in range(6):
                db.add(StudyStep(study_id=completed_fixture.id, step_order=offset+1,
                                 step_name="Explicit historical completion", status=StepStatus.PENDING,
                                 planned_start=datetime(2026,10,1,9)+timedelta(days=offset),
                                 planned_end=datetime(2026,10,1,10)+timedelta(days=offset)))
            db.commit()
            expected_completed = db.query(Study).filter(Study.status == StudyStatus.COMPLETED).count()
            rec92 = client.post("/api/v1/planning/recompute-conflicts", headers=h_tfm)
            db.expire_all()
            check(rec92.status_code == 200 and rec92.json().get("status") == "success",
                  "POST /api/v1/planning/recompute-conflicts başarıyla çalıştı")
            j92 = rec92.json()
            check(j92["reference_date"] == "2026-11-03" and j92["completed_studies_count"] == expected_completed
                  and j92["total_completed_steps"] >= 6 and j92.get("historical_excluded_steps", 0) >= 2,
                  f"Referans tarih 2026-11-03 baz alınarak biten çalışmalar ({j92['completed_studies_count']}) kapatıldı ve devam eden çalışmaların geçmiş adımları ({j92.get('historical_excluded_steps', 0)}) COMPLETED yapılmadan aktif çakışmadan hariç tutuldu")
            # Açıkça COMPLETED (Biten) olan çalışmaların adımları COMPLETED (actual_start/end=None) olmalı;
            # GLP2026-005 ve GLP2026-030 (Devam Eden) içindeki < 03.11.2026 geçmiş adımlar otomatik COMPLETED yapılmadan
            # PENDING kalmalı ve aktif çakışmadan hariç tutulmalı
            steps_comp = (
                db.query(StudyStep)
                .join(StudyStep.study)
                .filter(Study.status == StudyStatus.COMPLETED)
                .order_by(StudyStep.id)
                .all()
            )
            st005 = db.query(Study).filter(Study.study_code == "GLP2026-005").first()
            steps005 = db.query(StudyStep).filter(StudyStep.study_id == st005.id).order_by(StudyStep.step_order).all()
            st030 = db.query(Study).filter(Study.study_code == "GLP2026-030").first()
            steps030 = db.query(StudyStep).filter(StudyStep.study_id == st030.id).order_by(StudyStep.step_order).all()
            past030 = [s for s in steps030 if s.planned_start.date() < date(2026, 11, 3)]
            fut030 = [s for s in steps030 if s.planned_start.date() >= date(2026, 11, 3)]
            past030_confs = db.query(Conflict).filter(
                Conflict.study_id == st030.id,
                Conflict.step_id.in_([s.id for s in past030]),
                Conflict.is_resolved == False,  # noqa: E712
            ).count()
            check(len(steps_comp) >= 1 and all(s.status == StepStatus.COMPLETED and s.actual_start is None for s in steps_comp)
                  and all(s.status == StepStatus.PENDING for s in steps005)
                  and len(past030) >= 2 and all(s.status == StepStatus.PENDING for s in past030) and past030_confs == 0
                  and len(fut030) >= 2 and all(s.status != StepStatus.COMPLETED for s in fut030),
                  "Biten çalışmaların adımları COMPLETED (uydurma saat yok); GLP2026-005 ve GLP2026-030 (Devam Eden): < 03.11.2026 geçmiş adımlar COMPLETED yapılmadan aktif çakışmadan hariç tutuldu, >= 03.11.2026 gelecekteki adımlar PENDING korundu")
            # Aktif görevler filtresi (active_only=true) yalnızca tamamlanmamış ve >= 2026-11-03 adımları döndürmeli
            act_steps = client.get("/api/v1/planning/steps?biological_only=true&active_only=true", headers=h_tfm).json()
            all_steps = client.get("/api/v1/planning/steps?biological_only=true&include_all=true&active_only=false", headers=h_tfm).json()
            check(len(act_steps) > 0 and len(all_steps) > len(act_steps)
                  and all(s["status"] != "COMPLETED" and s["planned_start"][:10] >= "2026-11-03" for s in act_steps),
                  f"GET /api/v1/planning/steps?active_only=true yalnızca aktif/bekleyen (>= 03.11.2026) görevleri döndürdü ({len(act_steps)} aktif / {len(all_steps)} toplam)")
            # Çakışma kategorizasyonu: CONFIRMED_CONFLICT vs MISSING_INFO
            conf_all = client.get("/api/v1/planning/conflicts?unresolved_only=true", headers=h_tfm).json()
            conf_real = client.get("/api/v1/planning/conflicts?unresolved_only=true&category=CONFIRMED_CONFLICT", headers=h_tfm).json()
            conf_miss = client.get("/api/v1/planning/conflicts?unresolved_only=true&category=MISSING_INFO", headers=h_tfm).json()
            check(len(conf_real) > 0 and len(conf_miss) > 0 and len(conf_real) + len(conf_miss) == len(conf_all),
                  f"Açık çakışmalar 2 kategoriye ayrıldı: {len(conf_real)} Gerçek Çakışma + {len(conf_miss)} Eksik Bilgi Kaynaklı = {len(conf_all)} Toplam")
            check(all(c["conflict_category"] == "CONFIRMED_CONFLICT" and len(c.get("missing_info_codes", [])) == 0 for c in conf_real),
                  "Gerçek Çakışmalar (CONFIRMED_CONFLICT) eksiksiz tarih/atama içeren gerçek darboğazlardan oluşuyor")
            check(all(c["conflict_category"] == "MISSING_INFO" and len(c.get("missing_info_badges", [])) >= 1 and len(c.get("missing_info_tags", [])) >= 1 for c in conf_miss),
                  "Eksik Bilgi Sebebiyle Çakışmalar (MISSING_INFO) rozet (missing_info_badges) ve açıklama etiketleri içeriyor")
            sum92 = client.get("/api/v1/planning/summary", headers=h_tfm).json()
            check(sum92["confirmed_conflicts"] == len(conf_real) and sum92["missing_info_conflicts"] == len(conf_miss)
                  and sum92.get("historical_excluded_tasks", 0) == j92["historical_excluded_steps"] and sum92.get("historical_completed_tasks", 0) >= 6,
                  "GET /api/v1/planning/summary: confirmed_conflicts, missing_info_conflicts ve doğrulanmamış geçmiş görev ayrımları (historical_excluded_tasks / historical_completed_tasks) birebir uyumlu")
            # Eksik başlangıç tarihi olan bir çalışmaya (GLP2026-031) tarih girildiğinde 'Başlangıç Tarihi Eksik' rozetinin kalktığını doğrula
            sr031 = db.query(SampleRecord).filter(SampleRecord.study_code == "GLP2026-031").first()
            plan031 = client.post(f"/api/v1/samples/{sr031.id}/plan", headers=h_tfm, json={"start_date": "2026-12-08"})
            check(plan031.status_code == 200, "POST /api/v1/samples/{id}/plan ile GLP2026-031 başlangıç tarihi teyit edildi")
            client.post("/api/v1/planning/recompute-conflicts", headers=h_tfm)
            conf_after_031 = client.get("/api/v1/planning/conflicts?unresolved_only=true", headers=h_tfm).json()
            c031_list = [c for c in conf_after_031 if c.get("study_code") == "GLP2026-031" and not c.get("related_study_code")]
            check(all("MISSING_START_DATE" not in c.get("missing_info_codes", []) for c in c031_list),
                  "Başlangıç tarihi girilip Recompute çalıştırıldığında GLP2026-031 için 'MISSING_START_DATE' eksik bilgi rozeti kalktı")

            print("\n[18] FAZ 9.3: Otomatik GLP Sayacı (GLP2026-083), Devam Eden (11 Sahada / 22 Rapor-QA), Hayvan/Sarf & Sözleşme ve Excel Dışa Aktarım")
            nxt93 = client.get("/api/v1/samples/next-code", headers=h_tfm)
            dos93 = client.get("/api/v1/documents/dossier", headers=h_tfm)
            check(nxt93.status_code == 200 and nxt93.json()["next_glp_code"] == "GLP2026-092"
                  and nxt93.json()["next_non_glp_code"] == "NGLP-2026-012"
                  and dos93.json().get("next_glp_code") == "GLP2026-092",
                  "Otomatik sıradaki çalışma kodu sayacı: korunan 090/091 sonrası GLP2026-092 (GLP) ve NGLP-2026-012 (Non-GLP)")
            samp93 = client.get("/api/v1/samples", headers=h_tfm).json()
            s93_sum = samp93["summary"]
            s93_items = {it["study_code"]: it for it in samp93["items"]}
            ongoing_rows = [it for it in samp93["items"] if it["status"] == "ONGOING"]
            check(s93_sum["ongoing"] == len(ongoing_rows)
                  and s93_sum["ongoing_in_experiment"] == sum(it["ongoing_phase"] == "IN_EXPERIMENT" for it in ongoing_rows)
                  and s93_sum["ongoing_in_reporting"] == sum(it["ongoing_phase"] == "IN_REPORTING_QA" for it in ongoing_rows)
                  and s93_sum["ongoing_overdue_draft"] == sum(bool(it.get("is_draft_report_overdue")) for it in samp93["items"]),
                  "Korunan operasyonel durumlar dahil numune özeti listedeki kayıtlarla uyumlu")
            psum93 = client.get("/api/v1/planning/summary", headers=h_tfm).json()
            check(all(psum93[key] == s93_sum[key] for key in ("ongoing_in_experiment", "ongoing_in_reporting", "ongoing_overdue_draft")),
                  "Planlama özeti korunan numune operasyon durumlarıyla uyumlu")
            check(s93_sum["consumables_pending"] == 3 and s93_sum["quarantine_count"] == 10 and s93_sum["animal_reuse_count"] == 6,
                  "Excel 16. Sütun dağılımı: 3 Sarf Malzeme Bekleniyor, 10 Karantina (+7g), 6 Tekrar Kullanım (Vet/HADYEK)")
            check(all(s93_items[c]["animal_status_code"] == "CONSUMABLES_PENDING" and s93_items[c]["animal_status_badge"] == "⚠️ Sarf Malzeme Bekleniyor" for c in ("GLP2026-077", "GLP2026-078", "GLP2026-079")),
                  "GLP2026-077, 078, 079 (DiSERA): '⚠️ Sarf Malzeme Bekleniyor' uyarı rozeti doğrulandı")
            check(s93_items["GLP2026-072"]["requires_quarantine"] is True and s93_items["GLP2026-072"]["quarantine_days"] == 7
                  and s93_items["GLP2026-072"]["animal_status_badge"] == "Karantina (+7g)",
                  "GLP2026-072 (Mevcut Karantina): 'Karantina (+7g)' rozeti ve +7 gün TAT farkı doğrulandı")
            check(s93_items["GLP2026-038"]["contract_commitment_date"] == "2026-11-10"
                  and s93_items["GLP2026-029"]["contract_commitment_date"] == "2026-09-30"
                  and s93_items["GLP2026-072"]["contract_commitment_date"] == "2026-12-26",
                  "SPONSOR SÖZLŞ.-SPONSOR AGREEM. sekmesinden sözleşme/taahhüt tarihleri ve 'Sözleşme Termini Aşılıyor' uyarısı doğrulandı")
            # A signed plan is no longer silently moved by import. Exercise the
            # deadline warning with an explicit late report date instead.
            overdue_sample = db.query(SampleRecord).filter(SampleRecord.study_code == "GLP2026-072").one()
            overdue_sample.final_report_date = date(2027, 1, 1)
            db.commit()
            overdue_rows = client.get("/api/v1/samples", headers=h_tfm).json()["items"]
            check(next(it for it in overdue_rows if it["study_code"] == "GLP2026-072")["is_contract_deadline_exceeded"] is True,
                  "Açık geç rapor tarihi sözleşme termini uyarısı üretiyor")
            exp_xl = client.get("/api/v1/samples/export-excel", headers=h_tfm)
            check(exp_xl.status_code == 200
                  and "spreadsheetml.sheet" in exp_xl.headers.get("content-type", "")
                  and len(exp_xl.content) > 10000,
                  f"GET /api/v1/samples/export-excel başarıyla çalıştı ({len(exp_xl.content)} byte .xlsx)")
            from openpyxl import load_workbook as _lwb93
            wb93 = _lwb93(io.BytesIO(exp_xl.content), read_only=True)
            ws93 = wb93.active
            rows93 = list(ws93.iter_rows(values_only=True))
            wb93.close()
            check(len(rows93) == 1 + len(samp93["items"]) and len(rows93[0]) == 23 and rows93[0][0] == "Sıra No" and rows93[0][22] == "11 Adımlı İş Akışı Özeti",
                  f"İndirilen Excel (.xlsx) dosyası 1 başlık + tüm korunan çalışma satırları ve 23 kurumsal sütun içeriyor")

            print("\n[19] FAZ 10: Güvenlik Denetimi (Auth Audit, Brute-Force 429, Şifre Değiştirme, Dosya Güvenliği, WAL Modu & Security Headers)")
            from sqlalchemy import text as _sql_text
            from app.api.v1.endpoints.auth import reset_login_rate_limiter
            from app.main import create_app

            # 19a) Anonim erişim reddi
            for anon_ep in ("/api/v1/samples", "/api/v1/planning/calendar", "/api/v1/studies/", "/api/v1/documents",
                            "/api/v1/restrictions", "/api/v1/room-capacities", "/api/v1/long-equipment", "/api/v1/personnel/"):
                check(client.get(anon_ep).status_code == 401, f"Token olmadan GET {anon_ep} → 401")

            # 19b) Brute-Force Rate Limiting (5 başarısız deneme sonrası 6. denemede 429 + AuditLog)
            reset_login_rate_limiter()
            bf_ip = "198.51.100.77"
            for _i in range(5):
                client.post("/api/v1/auth/login", json={"username": "admin", "password": "BadPassword!"}, headers={"X-Forwarded-For": bf_ip})
            bf_resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": DEFAULT_PASSWORD}, headers={"X-Forwarded-For": bf_ip})
            check(bf_resp.status_code == 429 and db.query(AuditLog).filter(AuditLog.action == "LOGIN_RATE_LIMIT_LOCKOUT").count() >= 1,
                  "Brute-Force Koruması: 60 sn içinde >5 başarısız giriş → HTTP 429 Too Many Requests + AuditLog")
            reset_login_rate_limiter()

            # 19c) Şifre değiştirme (/api/v1/auth/change-password)
            check(client.post("/api/v1/auth/change-password", headers=h_sd,
                              json={"current_password": "Wrong", "new_password": "NewPassword2026!"}).status_code == 400,
                  "POST /auth/change-password: hatalı mevcut şifre → 400")
            check(client.post("/api/v1/auth/change-password", headers=h_sd,
                              json={"current_password": DEFAULT_PASSWORD, "new_password": "short"}).status_code == 422,
                  "POST /auth/change-password: <8 karakter şifre → 422")
            cp_ok = client.post("/api/v1/auth/change-password", headers=h_sd,
                                json={"current_password": DEFAULT_PASSWORD, "new_password": "EzgiSecure2026!"})
            check(cp_ok.status_code == 200 and db.query(AuditLog).filter(AuditLog.action == "CHANGE_PASSWORD").count() >= 1,
                  "POST /auth/change-password: şifre bcrypt ile güncellendi ve AuditLog'a yazıldı")
            h_sd_new = auth_headers(client, "ezgi", "EzgiSecure2026!")
            client.post("/api/v1/auth/change-password", headers=h_sd_new,
                        json={"current_password": "EzgiSecure2026!", "new_password": DEFAULT_PASSWORD})

            # 19d) Dosya yükleme güvenliği (Path Traversal, Magic Bytes, .sh/.php/.js reddi)
            check(client.post("/api/v1/documents/upload", headers=h_tfm,
                              files={"file": ("../../etc/passwd.txt", b"test", "text/plain")}).status_code == 400,
                  "Path Traversal ('../../etc/passwd.txt') reddedildi → 400")
            check(client.post("/api/v1/documents/upload", headers=h_tfm,
                              files={"file": ("fake.pdf", b"MZ\x90\x00ExecutableDisguisedAsPdf", "application/pdf")}).status_code == 415,
                  "Magic Bytes kontrolü: PDF uzantılı çalıştırılabilir (MZ) sahte dosya reddedildi → 415")
            check(client.post("/api/v1/samples/import-excel", headers=h_tfm,
                              files={"file": ("shell.php", b"<?php echo 1; ?>", "application/x-php")}).status_code == 415,
                  "import-excel: çalıştırılabilir (.php) dosya reddedildi → 415")

            # 19e) SQLite WAL Modu & HTTP Security Headers & Production Docs Kapatma
            with engine.connect() as _conn:
                wal_mode = str(_conn.execute(_sql_text("PRAGMA journal_mode;")).scalar()).lower()
                fk_on = int(_conn.execute(_sql_text("PRAGMA foreign_keys;")).scalar())
            check(wal_mode == "wal" and fk_on == 1, f"SQLite WAL modu ('{wal_mode}') ve foreign_keys ({fk_on}) aktif")
            sec_h = client.get("/api/v1/health").headers
            check(sec_h.get("X-Content-Type-Options") == "nosniff" and sec_h.get("X-Frame-Options") == "DENY"
                  and sec_h.get("X-XSS-Protection") == "1; mode=block"
                  and sec_h.get("Referrer-Policy") == "strict-origin-when-cross-origin",
                  "HTTP Security Headers (nosniff, DENY, XSS-Protection, Referrer-Policy) doğrulandı")
            prod_c = TestClient(create_app(is_production=True))
            check(prod_c.get("/docs").status_code == 404 and prod_c.get("/redoc").status_code == 404
                  and prod_c.get("/openapi.json").status_code == 404,
                  "ENV=production modunda /docs, /redoc ve /openapi.json devre dışı (404)")
        finally:
            dp._llm_call = original_llm
    finally:
        db.close()
        engine.dispose()
        shutil.rmtree(_TMP_DIR, ignore_errors=True)

    print(f"\nTÜM TESTLER GEÇTİ ({len(PASSED)} kontrol) — gerçek veritabanına dokunulmadı.")


if __name__ == "__main__":
    main()
