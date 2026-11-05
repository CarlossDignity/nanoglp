# Dashboard su banyosu doluluğu

Taban: önceki dört PR'ı içeren main `1f31c04d9d712315601c99ba685989c60b747e10`.

Dashboard artık personelin ekstraksiyon kurulum adımının tamamlanmasını rezervasyonun bitmesi olarak yorumlamaz. `/api/v1/planning/calendar` yanıtındaki çalışma başına `water_bath_reservations` alanını kullanır. Alan yalnız mevcut planlama motorunun EQ-WB-001 rezervasyonlarının aktarımıdır; planlama/rezervasyon kuralları değiştirilmez.

Her rezervasyon cihaz kodu, adım ID'si, pencere başlangıç/bitişi ve doğrulanmış polar/apolar kullanım bayraklarını taşır. Motorun mevcut kuralı olan planlanan ekstraksiyon başlangıcından itibaren 72 saat kullanılır; 90 dakikalık kurulum süresi veya kurulumun COMPLETED olması bu pencereyi kısaltmaz. Gerçekleşme saatlerinden yeni rezervasyon türetilmez.

Kapsam mevcut motorla aynıdır: DRAFT, APPROVED ve IN_PROGRESS çalışmalar; iptal edilmemiş ekstraksiyon adımları. COMPLETED/CANCELLED çalışmalar ve CANCELLED adımlar dışarıda kalır. `is_historical_unverified_step` aynı 03.11.2026 kuralıyla uygulanır. Polar/apolar ihtiyacı `get_study_extraction_usage` ile alınır; None kesin kullanım sayılmaz, kısmen bilinen bilgide yalnız True bileşen sayılır. Başka adımlardaki cihaz atamasından kullanım çıkarılmaz.

Frontend [start, end) pencerelerinde zirve eşzamanlı çalışma sayısını hesaplar. Biri bittiği anda başlayan rezervasyon onunla çakışmaz. Aynı çalışmanın birden fazla ekstraksiyon penceresi varsa aynı anda bir çalışma olarak sayılır. Kartta gösterilen çalışma sayısı da benzersiz çalışma sayısıdır. API'de rezervasyon yoksa personel görevinin saatlerinden yedek rezervasyon uydurulmaz.

Kapasite mevcut `/equipment` kaydından alınır; kart düzeni, renk eşikleri ve mevcut kapasite varsayılanları değiştirilmez. Gösterge tüm takvimdeki zirve kullanım anlamını korur; anlık kullanım göstergesine dönüştürülmez.

## Doğrulama

- `frontend/tests/dashboard-water-bath.test.mjs`: Gerçek Dashboard modülü esbuild ile test için yüklenir. Tamamlanmış kurulum, 72 saat, yetkili API penceresinin kullanımı, yarı açık sınır, gerçek aşım, polar/apolar/eksik bilgi, iptal kapsamı, çoklu pencere ve geçersiz tarih test edilir. Gerçek EquipmentCapacityCard React ile render edilerek 2/7, 2/1, benzersiz çalışma sayısı ve aşım rengi kontrol edilir; yeni test bağımlılığı eklenmedi.
- `backend/tests/test_dashboard_water_bath.py`: Gerçek takvim/cihaz API istekleri geçici SQLite ile çalışır. 90 dakikalık kurulumun 72 saatlik penceresi, yalnız durum değiştiğinde rezervasyonun aynı kalması, tüm polar/apolar kombinasyonları, kayıtlı 7/2 kapasitesi, iptal/tamamlanmış/tarihsel kapsam ve motorun gerçek kapasite bulgularıyla sınır/aşım uyumu doğrulanır. API okumasından sonra yeni Session ile tabloların değişmediği kontrol edilir.
- Düzeltme öncesi frontend paketinde 2 test geçti, 6 başarısız oldu. Backend'deki 4 test eksik rezervasyon alanını gösterdi. Mevcut test beklentileri değiştirilmedi.

| Komut | Geçen | Başarısız | Atlanan |
| --- | ---: | ---: | ---: |
| frontend: `npm run test:dashboard` | 8 | 0 | 0 |
| backend: `venv/bin/python tests/test_dashboard_water_bath.py` | 4 | 0 | 0 |
| backend: `venv/bin/python tests/test_scheduling_engine_fixes.py` | 20 | 0 | 2 |
| backend: `venv/bin/python tests/verify_engine.py` | 262 kontrol | 0 | 0 |
| frontend: `npm run build` | Başarılı | 0 | 0 |

İki mevcut tarayıcı testi bu Linux ortamında Chrome/Edge bulamadığı için atlandı. Build yalnız 500 kB üzeri chunk boyutu uyarısı verdi. Build doğrulandı; üretilmiş dist değişiklikleri PR'a eklenmedi (Docker build mevcut derleme adımını çalıştırır). Merge/deploy yapılmadı.

İzlenen `nanolab_glp.db` önce/sonra hash'i aynı: `8ed4b65160353ff5c047f8597f0219e66c29eb43`. Canlı veritabanı kullanılmadı.
