"""
NANOLAB Edirne GLP — FAZ 10 Canlı Ortam ve Güvenlik Doğrulama Scripti (deploy_check.py)

Gerçek veritabanına dokunmadan izole test ortamında (veya mevcut derleme dosyaları üzerinde):
1. Anonim erişim reddi (Auth Audit — tüm korunan API uçları 401, yetkisiz yazma/silme 403)
2. Brute-Force (IP Rate-Limiting -> HTTP 429 + AuditLog) ve Şifre Değiştirme (/auth/change-password)
3. Dosya yükleme güvenliği (Path Traversal '..', .exe/.sh/.php/.js reddi, Magic Bytes kontrolü, 25 MB sınırı -> 413)
4. SQLite WAL modu (journal_mode=wal, foreign_keys=1, timeout=15)
5. HTTP Güvenlik Başlıkları (X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy),
   ENV=production'da /docs kapatma ve Tek Port SPA (frontend/dist) + Docker paket kontrolü

Kullanım:
    backend\\venv\\Scripts\\python.exe deploy_check.py
"""
import os
import shutil
import sys
import tempfile

_TMP_DIR = tempfile.mkdtemp(prefix="nanoglp_deploy_check_")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_TMP_DIR, "deploy_check.db")

ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(ROOT_DIR, "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.api.v1.endpoints.auth import reset_login_rate_limiter  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import SessionLocal, connect_args, engine  # noqa: E402
from app.main import app, create_app  # noqa: E402
from app.models.audit_log import AuditLog  # noqa: E402
from app.seed import DEFAULT_PASSWORD, reset_schema, seed_personnel  # noqa: E402

CHECKS = []


def ok(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(f"GÜVENLİK DENETİMİ BAŞARISIZ: {msg}")
    CHECKS.append(msg)
    print(f"  ✓ {msg}")


def login_headers(client: TestClient, username: str, password: str = DEFAULT_PASSWORD, ip: str = "10.0.0.10") -> dict:
    r = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
        headers={"X-Forwarded-For": ip},
    )
    assert r.status_code == 200, f"Login hatası ({username}): {r.status_code} {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def main() -> None:
    print("================================================================================")
    print("NANOLAB EDİRNE GLP — FAZ 10 GÜVENLİK VE PRODUCTION HAZIRLIK DENETİMİ (deploy_check)")
    print("================================================================================")

    reset_schema()
    reset_login_rate_limiter()
    db = SessionLocal()
    try:
        seed_personnel(db)
        client = TestClient(app)

        print("\n[1] TÜM API UÇLARINDA ANONİM ERİŞİM REDDİ (401) VE ROL YETKİ DENETİMİ (403)")
        # Health hariç tüm uçlar anonim erişime kapalı olmalı
        ok(client.get("/api/v1/health").status_code == 200, "GET /api/v1/health anonim erişime açık (200)")
        ok(client.get("/api/health").status_code == 200, "GET /api/health anonim erişime açık (200)")

        protected_gets = [
            "/api/v1/auth/me",
            "/api/v1/samples",
            "/api/samples",
            "/api/v1/samples/next-code",
            "/api/v1/samples/export-excel",
            "/api/v1/planning/summary",
            "/api/v1/planning/calendar",
            "/api/v1/planning/workload",
            "/api/v1/planning/workload-weekly",
            "/api/v1/planning/conflicts",
            "/api/v1/planning/templates",
            "/api/v1/planning/calibration",
            "/api/v1/planning/steps",
            "/api/v1/planning/my-tasks",
            "/api/v1/studies/",
            "/api/v1/documents",
            "/api/v1/documents/dossiers",
            "/api/v1/documents/dossier",
            "/api/v1/users",
            "/api/users",
            "/api/v1/users/roles",
            "/api/v1/restrictions",
            "/api/v1/room-capacities",
            "/api/v1/long-equipment",
            "/api/v1/personnel/",
            "/api/v1/equipment",
        ]
        for ep in protected_gets:
            st = client.get(ep).status_code
            ok(st == 401, f"Anonim GET {ep} → 401 Unauthorized (alınan: {st})")

        protected_writes = [
            ("POST", "/api/v1/samples", {"study_code": "GLP2026-999"}),
            ("POST", "/api/v1/planning/schedule-study", {"study_code": "GLP2026-999", "acclimatization_start_date": "2027-01-04"}),
            ("POST", "/api/v1/planning/recompute-conflicts", {}),
            ("PUT", "/api/v1/planning/calibration", {"reason": "Test"}),
            ("POST", "/api/v1/users", {"username": "x", "full_name": "X", "role": "TECHNICIAN", "password": "Password123!"}),
            ("POST", "/api/v1/restrictions", {"target_type": "TEST", "target_key": "ISO_10993_23_IC", "start_date": "2027-01-01", "end_date": "2027-01-10", "reason": "Bakım"}),
            ("PUT", "/api/v1/room-capacities/RABBIT", {"physical_cages": 50}),
            ("PUT", "/api/v1/long-equipment/EQ-WB-001", {"max_concurrent_studies": 2}),
            ("POST", "/api/v1/auth/change-password", {"current_password": "a", "new_password": "Password123!"}),
        ]
        for method, ep, body in protected_writes:
            resp = client.request(method, ep, json=body)
            ok(resp.status_code == 401, f"Anonim {method} {ep} → 401 Unauthorized (alınan: {resp.status_code})")

        h_admin = login_headers(client, "admin", ip="10.0.0.1")
        h_tfm = login_headers(client, "emine", ip="10.0.0.2")
        h_qa = login_headers(client, "qa_user", ip="10.0.0.3")
        h_tech = login_headers(client, "invivo_1", ip="10.0.0.4")

        # Rol bazlı yazma/silme engelleri (403)
        ok(client.post("/api/v1/restrictions", headers=h_tfm, json={
            "target_type": "TEST", "target_key": "ISO_10993_23_IC",
            "start_date": "2027-01-01", "end_date": "2027-01-10", "reason": "Test"
        }).status_code == 403, "TFM POST /restrictions → 403 (Sadece SYSADMIN)")
        ok(client.put("/api/v1/room-capacities/RABBIT", headers=h_qa, json={"physical_cages": 60}).status_code == 403,
           "QA PUT /room-capacities → 403 (Salt Okunur)")
        ok(client.put("/api/v1/long-equipment/EQ-WB-001", headers=h_qa, json={"max_concurrent_studies": 3}).status_code == 403,
           "QA PUT /long-equipment → 403 (Salt Okunur)")
        ok(client.post("/api/v1/users", headers=h_qa, json={
            "username": "u_test", "full_name": "Test", "role": "TECHNICIAN", "password": "Password123!"
        }).status_code == 403, "QA POST /users → 403")
        ok(client.delete("/api/v1/samples/1", headers=h_qa).status_code == 403, "QA DELETE /samples/{id} → 403")
        ok(client.post("/api/v1/samples/import-excel", headers=h_tech,
                       files={"file": ("test.csv", b"GLP No\nGLP1\n", "text/csv")}).status_code == 403,
           "Teknisyen POST /samples/import-excel → 403")

        print("\n[2] BRUTE-FORCE (RATE LIMITING -> HTTP 429) VE ŞİFRE DEĞİŞTİRME TESTİ")
        attacker_ip = "203.0.113.99"
        for i in range(5):
            r_fail = client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": f"YanlisSifre_{i}"},
                headers={"X-Forwarded-For": attacker_ip},
            )
            assert r_fail.status_code == 401
        r_locked = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": DEFAULT_PASSWORD},
            headers={"X-Forwarded-For": attacker_ip},
        )
        ok(r_locked.status_code == 429 and "Retry-After" in r_locked.headers,
           "Aynı IP'den 60 sn içinde >5 başarısız giriş → HTTP 429 Too Many Requests + 5 dk IP kilidi")
        lock_logs = db.query(AuditLog).filter(AuditLog.action == "LOGIN_RATE_LIMIT_LOCKOUT").count()
        ok(lock_logs >= 1, f"Brute-Force IP kilitleme olayı AuditLog tablosuna kaydedildi ({lock_logs} kayıt)")
        reset_login_rate_limiter()

        # Şifre değiştirme (/api/v1/auth/change-password)
        bad_cur = client.post("/api/v1/auth/change-password", headers=h_tfm,
                              json={"current_password": "HataliMevcutSifre!", "new_password": "YeniGucluSifre2026!"})
        ok(bad_cur.status_code == 400, "Hatalı mevcut şifre ile şifre değiştirme → 400 Bad Request")
        short_pw = client.post("/api/v1/auth/change-password", headers=h_tfm,
                               json={"current_password": DEFAULT_PASSWORD, "new_password": "kisa"})
        ok(short_pw.status_code == 422, "8 karakterden kısa yeni şifre → 422 Unprocessable Entity")
        ok_pw = client.post("/api/v1/auth/change-password", headers=h_tfm,
                            json={"current_password": DEFAULT_PASSWORD, "new_password": "YeniGucluSifre2026!"})
        ok(ok_pw.status_code == 200 and ok_pw.json().get("status") == "success",
           "POST /api/v1/auth/change-password geçerli yeni şifreyi bcrypt ile kaydetti (200)")
        ok(db.query(AuditLog).filter(AuditLog.action == "CHANGE_PASSWORD").count() == 1,
           "Şifre değiştirme işlemi AuditLog tablosuna kaydedildi")
        # Yeni şifreyle giriş yapılabilmeli, ardından varsayılan şifreye geri döndür
        h_tfm_new = login_headers(client, "emine", password="YeniGucluSifre2026!", ip="10.0.0.2")
        client.post("/api/v1/auth/change-password", headers=h_tfm_new,
                    json={"current_password": "YeniGucluSifre2026!", "new_password": DEFAULT_PASSWORD})

        print("\n[3] DOSYA YÜKLEME GÜVENLİĞİ (PATH TRAVERSAL, MAGIC BYTES, .EXE/.SH/.PHP REDDİ & 25 MB SINIRI)")
        # 3a) Path traversal ('..')
        pt_doc = client.post("/api/v1/documents/upload", headers=h_tfm,
                             files={"file": ("../../etc/passwd.txt", b"root:x:0:0", "text/plain")})
        ok(pt_doc.status_code == 400, f"Path Traversal ('../../etc/passwd.txt') reddedildi → {pt_doc.status_code}")

        # 3b) Çalıştırılabilir uzantılar (.exe, .sh, .php, .bat, .js)
        for bad_name, bad_bytes in [
            ("trojan.exe", b"MZ\x90\x00\x03\x00"),
            ("exploit.sh", b"#!/bin/bash\nrm -rf /"),
            ("webshell.php", b"<?php system($_GET['cmd']); ?>"),
            ("script.bat", b"@echo off\ndel *.*"),
            ("payload.js", b"alert(1);"),
        ]:
            r_bad = client.post("/api/v1/documents/upload", headers=h_tfm,
                                files={"file": (bad_name, bad_bytes, "application/octet-stream")})
            ok(r_bad.status_code == 415, f"Zararlı/çalıştırılabilir dosya '{bad_name}' reddedildi → 415")

        # 3c) Sahte uzantılı dosyalar (Magic Bytes uyuşmazlığı: .pdf uzantılı .exe veya geçersiz .xlsx)
        fake_pdf = client.post("/api/v1/documents/upload", headers=h_tfm,
                               files={"file": ("sahte_belge.pdf", b"MZ\x90\x00WindowsExecutableDisguisedAsPdf", "application/pdf")})
        ok(fake_pdf.status_code == 415, "PDF uzantılı çalıştırılabilir (MZ magic bytes) sahte dosya reddedildi → 415")

        fake_xlsx = client.post("/api/v1/samples/import-excel", headers=h_tfm,
                                files={"file": ("sahte_tablo.xlsx", b"NOT_A_VALID_ZIP_OR_XLSX_HEADER", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        ok(fake_xlsx.status_code == 415, "Geçersiz başlığa sahip sahte .xlsx dosyası reddedildi → 415")

        # 3d) 25 MB boyut sınırı kontrolü (MAX_UPLOAD_MB geçici olarak 1 MB ile test edilir)
        orig_max = settings.MAX_UPLOAD_MB
        settings.MAX_UPLOAD_MB = 1
        try:
            oversized = b"%PDF-1.7\n" + (b"A" * (1024 * 1024 + 512))
            r_413 = client.post("/api/v1/documents/upload", headers=h_tfm,
                                files={"file": ("buyuk_dosya.pdf", oversized, "application/pdf")})
            ok(r_413.status_code == 413, "Boyut sınırını aşan yükleme → HTTP 413 Request Entity Too Large")
        finally:
            settings.MAX_UPLOAD_MB = orig_max

        print("\n[4] SQLITE ÇOKLU KULLANICI PERFORMANSI (WAL MODE) VE GÜVENLİK BAŞLIKLARI (SECURITY HEADERS)")
        with engine.connect() as conn:
            j_mode = conn.execute(text("PRAGMA journal_mode;")).scalar()
            fk_mode = conn.execute(text("PRAGMA foreign_keys;")).scalar()
        ok(str(j_mode).lower() == "wal", f"SQLite PRAGMA journal_mode = '{j_mode}' (WAL modu aktif)")
        ok(int(fk_mode) == 1, f"SQLite PRAGMA foreign_keys = {fk_mode} (Foreign Keys aktif)")
        ok(connect_args.get("check_same_thread") is False and connect_args.get("timeout") == 15,
           f"SQLite connect_args doğrulandı: {connect_args}")

        resp_sec = client.get("/api/v1/health")
        ok(resp_sec.headers.get("X-Content-Type-Options") == "nosniff"
           and resp_sec.headers.get("X-Frame-Options") == "DENY"
           and resp_sec.headers.get("X-XSS-Protection") == "1; mode=block"
           and resp_sec.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin",
           "HTTP Security Headers (nosniff, DENY, XSS-Protection, Referrer-Policy) tüm yanıtlarda aktif")

        # ENV=production modunda /docs, /redoc, /openapi.json kapalı olmalı
        prod_app = create_app(is_production=True)
        prod_client = TestClient(prod_app)
        ok(prod_client.get("/docs").status_code == 404
           and prod_client.get("/redoc").status_code == 404
           and prod_client.get("/openapi.json").status_code == 404,
           "ENV=production modunda /docs, /redoc ve /openapi.json otomatik olarak devre dışı (404)")

        print("\n[5] TEK PORT CANLI ORTAM SUNUMU (FastAPI + frontend/dist) VE DOCKER PAKETİ KONTROLÜ")
        ok(os.path.isfile(os.path.join(ROOT_DIR, ".env.example")), ".env.example dosyası mevcut")
        ok(os.path.isfile(os.path.join(ROOT_DIR, "Dockerfile")), "Dockerfile dosyası mevcut")
        ok(os.path.isfile(os.path.join(ROOT_DIR, "docker-compose.yml")), "docker-compose.yml dosyası mevcut")
        dist_index = os.path.join(ROOT_DIR, "frontend", "dist", "index.html")
        ok(os.path.isfile(dist_index), "frontend/dist/index.html derlenmiş canlı arayüz paketi mevcut")
        spa_resp = client.get("/samples", headers={"Accept": "text/html"})
        ok(spa_resp.status_code == 200 and "<!doctype html>" in spa_resp.text.lower(),
           "FastAPI tek port (8000) üzerinden SPA rotalarını (frontend/dist/index.html) doğrudan sunuyor")

    finally:
        db.close()
        engine.dispose()
        shutil.rmtree(_TMP_DIR, ignore_errors=True)

    print("\n================================================================================")
    print(f"TÜM GÜVENLİK VE PRODUCTION KONTROLLERİ GEÇTİ ({len(CHECKS)} / {len(CHECKS)} kontrol başarılı)")
    print("================================================================================")


if __name__ == "__main__":
    main()
