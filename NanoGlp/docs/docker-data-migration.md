# Docker SQLite verisi ve yüklenen belgeler

## Yollar

Compose'u `NanoGlp` dizininden kullanırken:

| Veri | Host | Container |
| --- | --- | --- |
| SQLite ve WAL/SHM | `./backend/data/` | `/app/backend/data/` |
| Veritabanı | `./backend/data/nanolab_glp.db` | `/app/backend/data/nanolab_glp.db` |
| Yüklenen belgeler | `./backend/uploads/` | `/app/backend/uploads/` |

Dockerfile iki dizini oluşturur; Dockerfile ve Compose `DATABASE_URL=sqlite:////app/backend/data/nanolab_glp.db` ve `UPLOAD_DIR=/app/backend/uploads` kullanır. Veritabanı dizini bütünüyle bağlanır: `.db`, `-wal` ve `-shm` aynı kalıcı disktedir. Container yeniden oluşturulurken bu iki host dizinini koruyun. Yalnız `.db` dosyasını bağlamayın.

`.dockerignore`, eski/yeni veritabanını ve yüklemeleri image'dan dışlar. **Yeni `backend/data` dizini eski verileri kendiliğinden içermez.** Geçiş yapılmadan boş dizinle başlatılan uygulama eski kurulumun devamı değildir. Yerel Docker dışı varsayılan `backend/nanolab_glp.db` ve `.env` davranışı değişmez; bu dosya taşınmaz veya silinmez.

## Mevcut kurulumdan geçiş (operatör yönergesi; otomatik çalışmaz)

1. Önce çalışan kurulumun gerçekten kullandığı `DATABASE_URL` ve mount'ları doğrulayın. Eski Compose'ta adres ile mount farklı olduğundan, repodaki `backend/nanolab_glp.db` güncel veri kaynağı olmayabilir. Doğru kaynak dosyayı ve yüklenen belgeleri belirlemeden devam etmeyin.
2. Bakım aralığında uygulamayı ve aynı SQLite dosyasına yazan diğer süreçleri durdurun. Eski container'ı henüz silmeyin/yeniden oluşturmayın. Veriler container katmanındaysa, durmuş container'daki gerçek veri dizinini (`.db` ve varsa `-wal`/`-shm` dahil) ve uploads dizinini `docker cp` ile ayrı bir yedek dizinine çıkarın. Container silinmeden bu kopyanın varlığını doğrulayın.
3. Aşağıdaki örnekte kaynakları doğruladığınız **host yollarına** ayarlayın. Kaynak dosyalar yalnız okunup kopyalanır. WAL'daki son commit'leri kaybetmemek için yalnız `.db` kopyasıyla yetinmeyin. Uygulama bu işlem boyunca kapalı kalmalıdır.

```sh
# Yer tutucuları kendi doğrulanmış yollarınızla değiştirin.
set -eu
source_db=/absolute/verified/source/nanolab_glp.db
source_uploads=/absolute/verified/source/uploads
backup_dir=$(mktemp -d /absolute/backup/location/nanolab.XXXXXX)
mkdir "$backup_dir/sqlite"
cp -p "$source_db" "$backup_dir/sqlite/nanolab_glp.db"
for suffix in -wal -shm; do
  if [ -f "${source_db}${suffix}" ]; then
    cp -p "${source_db}${suffix}" "$backup_dir/sqlite/nanolab_glp.db${suffix}"
  fi
done
cp -a "$source_uploads" "$backup_dir/uploads"
```

4. Yedeği saklayın. WAL birleştirmesi ve SQLite backup işlemi için yedeğin ayrıca bir çalışma kopyasını hazırlayın. Böylece orijinal veritabanı **ve ham yedek** değişmez. Aşağıdaki Python yalnız standart `sqlite3` kullanır. `NanoGlp` dizininden çalıştırın; hedefte mevcut `.db` veya yan dosya varsa durur, üzerine yazmaz.

```sh
python3 - "$backup_dir" <<'PY'
import shutil
import sqlite3
import sys
from pathlib import Path

backup = Path(sys.argv[1]).resolve()
target = Path('backend/data/nanolab_glp.db')
if any(Path(str(target) + suffix).exists() for suffix in ('', '-wal', '-shm')):
    raise SystemExit('Hedefte veri var; üzerine yazılmadı. Kaynak/hedefi inceleyin.')
work = backup / 'sqlite-working-copy'
shutil.copytree(backup / 'sqlite', work)  # exists -> fail, never overwrite
# SQLite opens only the disposable copy and recovers its committed WAL data.
src = sqlite3.connect(work / 'nanolab_glp.db')
dst_path = backup / 'migrated.db'
if dst_path.exists():
    raise SystemExit('Hazırlanmış kopya zaten var; üzerine yazılmadı.')
dst = sqlite3.connect(dst_path)
try:
    src.backup(dst)
    if dst.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise SystemExit('Bütünlük kontrolü başarısız; hedefe kopyalanmadı.')
finally:
    dst.close()
    src.close()
target.parent.mkdir(parents=True, exist_ok=True)
with dst_path.open('rb') as source, target.open('xb') as destination:
    shutil.copyfileobj(source, destination)
print('Yeni veritabanı hazır; orijinal ve ham yedek korundu.')
PY
```

5. `backend/uploads` zaten doğrulanmış mevcut host diziniyse yerinde bırakın. Belgeler container katmanından/başka bir konumdan kurtarıldıysa yedekteki uploads dizinini **boş/yeni** `backend/uploads` hedefine kopyalayın; mevcut farklı belgelerin üzerine yazmayın. DB içindeki belge yollarını kontrol edin: container'da `/app/backend/uploads` yolu korunur, başka ortamlara ait mutlak yolların kendiliğinden değişmesi beklenmez. Her iki host dizini container kullanıcısınca yazılabilir olmalıdır.
6. Dosya bütünlüğünü, beklenen kayıt sayılarını ve belge örneklerini kontrol ettikten sonra yeni Compose ile başlatın. Kayıtları ve belgeleri uygulamadan doğrulayın. Sorun varsa yazmaları durdurun, ham yedeği koruyun ve doğrulanmış eski kurulum/veri kaynağına dönün. Yeni düzende yazılmış kayıtlar varsa eski kopyaya körlemesine dönmeyin. Yedekleri doğrulama tamamlanmadan silmeyin.

Bu PR geçişi, canlı container yeniden oluşturmasını veya yayınlamayı çalıştırmaz.
