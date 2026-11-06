# Görev yürütmede plan onayı

Taban: önceki altı PR'ı içeren main `aaf04fb888fd0abc9ead1c26b18eb7b9e8ca4b9f`.

`PATCH /api/v1/planning/steps/{step_id}/status`, mevcut rol ve atama kontrollerinden sonra bağlı Study'nin `APPROVED` veya `IN_PROGRESS` olmasını gerektirir. Diğer durumlar açıklayıcı HTTP 409 döndürür. Kontrol zaman ayrıştırma, durum/not/actual değişikliği, çakışma doğrulama ve audit yazımından önce yapılır. Status içermeyen referans saati, not, geç kayıt ve eksik saat seçenekleri de aynı kontrolden geçer.

MyTasks'ın bugünkü kartları ve tüm görevler tablosu aynı izin kuralını kullanır. Uygun olmayan çalışmalarda yürütme düğmeleri ve gerçekleşme/not girişleri kapalıdır; gönderim işleyicileri de kontrol eder. Taslaklar “Plan onayı bekleniyor” açıklamasıyla önizlemede kalır. Planlama takvimi, kapasite, iş yükü, tarihsel 03.11.2026 sınırı ve canlı tarih hesapları değiştirilmedi.

## Tekrar üretim ve fixture gerekçeleri

Düzeltme öncesi yeni API paketindeki iki test metodu toplam 32 alt senaryoda beklenen 409'u alamadı; örneğin DRAFT görevine yalnız `IN_PROGRESS` gönderilmesi 200 dönüp actual_start üretti. Diğer üç test metodu (izinli yürütme ve yetkiler) geçti. İlk test hazırlığında QA kullanıcı adı düzeltildi (`qa_user`); bu fixture hatası ürün hatası olarak sayılmadı.

İlk frontend paketinde 5 kapalı/bilinmeyen durum testi başarısız, izinli akışları kontrol eden 5 test başarılıydı. Son paket, her kapalı durum için hem PENDING hem IN_PROGRESS görevi kapsar: 15 test. Gerçek MyTasks bileşeni React test renderer ile yüklenir; yalnız API ve kimlik sınırları taklit edilir. Her iki görünümün düğmeleri, girişleri ve gönderdiği gövdeler doğrulanır. Bu testler tarayıcı E2E testi değildir.

Mevcut regresyonun ilk çalıştırmasında `test_3_biological_reference_delay...` içindeki eksik referans senaryosu ve `verify_engine.py` teknisyen güncelleme kontrolü DRAFT fixture nedeniyle 409 aldı. Bu iki yürütme fixture'ı APPROVED olarak hazırlandı. Mevcut başarı, zaman doğrulaması, eksik gerçekleşme ve koruma assertion'ları gevşetilmedi. Üretim kodu çalışma durumunu otomatik onaylamaz.

Atlanan mevcut tarayıcı testlerinin (`test_17_mytasks_headless_browser_e2e_verification`, `test_20_biological_revision_headless_browser_e2e`) fixture'ları incelendi: planlama sonrası zaten IN_PROGRESS yapıyorlar; değişiklik gerekmedi. Windows Chrome/Edge yollarını aradıkları ve bu Linux ortamında bulamadıkları için çalıştırılmadılar.

## Son doğrulama

Backend testleri ayrı süreçlerde ve geçici SQLite veritabanlarında çalıştırılır. Yeni API testi her ret sonrası yeni Session ile bütün tabloları karşılaştırır; mevcut actual'lar, tamamlayan kişi, not, atama, çakışma, plan tarihleri ve audit kayıtları korunur. İzinli normal/geç kayıtlar ve 422 zaman doğrulamaları da sınanır.

| Komut | Geçen | Başarısız | Atlanan |
| --- | ---: | ---: | ---: |
| `venv/bin/python tests/test_task_execution_approval.py` | 5 | 0 | 0 |
| `venv/bin/python tests/test_scheduling_engine_fixes.py` | 20 | 0 | 2 |
| `venv/bin/python tests/verify_engine.py` | 262 kontrol | 0 | 0 |
| `venv/bin/python tests/test_excel_updates.py` | 18 | 0 | 0 |
| `venv/bin/python tests/test_docx_isolation.py` | 11 | 0 | 0 |
| `venv/bin/python tests/test_replan_execution_guard.py` | 7 | 0 | 0 |
| `venv/bin/python tests/test_sample_study_sync.py` | 10 | 0 | 0 |
| `venv/bin/python tests/test_dashboard_water_bath.py` | 4 | 0 | 0 |
| `venv/bin/python tests/test_live_facility_date.py` | 6 | 0 | 0 |
| `venv/bin/python ../deploy_check.py` | 68 kontrol | 0 | 0 |
| `node --test tests/mytasks-approval.test.mjs tests/dashboard-water-bath.test.mjs` (frontend) | 23 | 0 | 0 |
| `npm run build` (frontend) | Başarılı | 0 | 0 |

Production build'in mevcut 500 kB chunk boyutu uyarısı devam ediyor. Build çıktıları commit edilmez; mevcut Docker build'i kaynakları derler. `deploy_check.py` izole güvenlik/regresyon kontrolüdür; yayınlama işlemi değildir.

Canlı veritabanı kullanılmadı. İzlenen `nanolab_glp.db` önce/sonra blob hash'i: `8ed4b65160353ff5c047f8597f0219e66c29eb43`. Merge veya deploy yapılmadı.
