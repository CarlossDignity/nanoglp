"""
VERİTABANI SIFIRLAMA + GERÇEK PERSONEL SEED

Kullanım (proje kökünden):
    backend\\venv\\Scripts\\python.exe backend\\scripts\\reset_and_seed.py --yes

⚠ TÜM verileri (çalışmalar, görevler, çakışmalar, denetim kayıtları, oda/cihaz) kalıcı olarak siler.
Çalıştırmadan önce API sunucusunu durdurun.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.seed import log_reset, reset_schema, seed_personnel  # noqa: E402


def main() -> int:
    if "--yes" not in sys.argv:
        print(f"Bu işlem şu veritabanındaki TÜM verileri siler:\n  {settings.DATABASE_URL}\n"
              f"Onaylamak için --yes parametresiyle çalıştırın.")
        return 1

    print(f"Hedef veritabanı: {settings.DATABASE_URL}")
    reset_schema()
    print("Tüm tablolar silindi ve güncel şemayla yeniden oluşturuldu.")

    db = SessionLocal()
    try:
        created = seed_personnel(db)
        log_reset(db, len(created))
        for u in created:
            print(f"  + #{u.id} {u.username:<12} | {u.full_name:<22} | {u.role.value:<22} | max {u.max_daily_hours} sa/gün")
    finally:
        db.close()
    print(f"Tamamlandı: {len(created)} personel eklendi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
