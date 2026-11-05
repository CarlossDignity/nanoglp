# Canlı göstergelerde tesis tarihi

Taban: önceki beş PR'ı içeren main `40bc3070d93812b830878ca0ff89c09f7471533e`.

`app.utils.facility_time`, uygulamanın mevcut Europe/Istanbul / UTC+03:00 tesis saati standardını ortak yardımcıya taşır. `facility_today()` çağrı anında güncel yerel günü döndürür; uygulama başlangıcında tarih saklanmaz. Planlama API'sindeki mevcut `_facility_now` aynı yerel-naive saat davranışını koruyarak bu yardımcıya delegasyon yapar. UTC audit saatleri ve kayıtlı gerçekleşmeler dönüştürülmez.

## Amaçlarına göre tarih kullanımları

| Kullanım | Tarih dayanağı |
| --- | --- |
| Numune canlı evresi, geciken taslak rapor, müşteri taahhüdü | İstek anındaki tesis günü |
| Numune workflow tarih göstergeleri, hesaplanan görünüm durumu, gecikme nedenleri | Aynı tesis günü |
| Dashboard özeti: bugünkü görevler, devam eden çalışma kırılımı, geciken taslak rapor | Aynı ortak yardımcıdan alınan tesis günü |
| Numune listesi ve Excel dışa aktarımı | Bir istek içinde bir kez okunup tüm satırlara iletilen tesis günü |
| `scheduling_engine.REFERENCE_DATE`, `is_historical_unverified_step` | Sabit 03.11.2026 |
| `sync_historical_completion_and_conflicts`, `recompute_all_conflicts` tarihsel kapsamı | Sabit 03.11.2026 |
| Planlama API'sinin `active_only` tarih filtresi ve tarihsel-belirsiz sayaçları | Sabit 03.11.2026 |
| `sample_service.REFERENCE_DATE` | Uyumluluk için sabit bırakıldı; canlı hesapta kullanılmaz |

Planlama başlangıç varsayılanları, takvim odak/seçim kuralları ve eski çalışmaların gösterilme kararları korunur. Sabitler topluca bugüne çevrilmez; tarih ilerlediği için 3 Kasım sonrasındaki görevler tarihsel-belirsiz sınıfına girmez.

## Alan anlamları

Tarih bazlı gecikme yalnız `termin < tesis_günü` olduğunda oluşur: dün gecikmiş, bugün ve gelecek gecikmemiştir. Mevcut ek kontrol korunur: planlanan taslak/final rapor tarihi müşteri taahhüdünden sonraysa, taahhüt henüz gelmemiş olsa bile sözleşme aşımı gösterilir.

Mevcut durum/evre koşulları, GLP taslak rapor kapsamı, eksik tarih davranışları ve tamamlanmış/iptal kayıt istisnaları korunur. Numune evresinin deney bitişi alanı ve dashboard'un deney bitişi yoksa planlanan bitişi kullanma davranışı değiştirilmez; her ikisinin tarih karşılaştırması tesis günüyle yapılır. Bu değişiklik kalıcı durum geçişi, görev tamamlama, actual_* üretimi veya plan kaydırma yapmaz.

## Testler

Yeni `tests/test_live_facility_date.py`, yalnız tesis saatini sabitler; gerçek API isteklerini geçici SQLite ile çalıştırır. UTC 4 Kasım 22:30 → tesis 5 Kasım, dün/bugün/yarın terminleri, yeniden başlatmadan gün değişimi, liste içinde tek gün kullanımı, eksik tarih, biten/iptal kayıtlar, gelecekteki plan/taahhüt çelişkisi ve tarihsel sınır doğrulanır. Yeni Session ile bütün tabloların karşılaştırılması kayıtlı durumların, görevlerin, atamaların, plan/actual saatlerinin, onay/revizyon ve audit kayıtlarının değişmediğini gösterir.

Excel güncelleme, manuel numune eşitleme, planlama ve ana regresyon paketlerinde canlı tesis saati 05.11.2026 12:00 olarak sabitlendi. Böylece bu göstergelerin beklentileri testin çalıştığı güne bağlı değildir. Mevcut assertion'lar ve tarihsel beklentiler değiştirilmedi; önceki actual saat testlerinin özel `_facility_now` patch'leri çalışmaya devam eder.

Düzeltme öncesi 5 hedefli testten 3'ü sabit tarih/gün değişimi sorununu gösterdi. Son hedefli pakette 6 testin tamamı geçti.

| Komut (backend dizininde) | Geçen | Başarısız | Atlanan |
| --- | ---: | ---: | ---: |
| `venv/bin/python tests/test_live_facility_date.py` | 6 | 0 | 0 |
| `venv/bin/python tests/test_excel_updates.py` | 18 | 0 | 0 |
| `venv/bin/python tests/test_sample_study_sync.py` | 10 | 0 | 0 |
| `venv/bin/python tests/test_scheduling_engine_fixes.py` | 20 | 0 | 2 |
| `venv/bin/python tests/verify_engine.py` | 262 kontrol | 0 | 0 |
| `venv/bin/python tests/test_docx_isolation.py` | 11 | 0 | 0 |
| `venv/bin/python tests/test_replan_execution_guard.py` | 7 | 0 | 0 |
| `venv/bin/python tests/test_dashboard_water_bath.py` | 4 | 0 | 0 |

Atlanan iki mevcut test Linux ortamında Chrome/Edge bulamadı. Canlı veritabanı kullanılmadı; izlenen `nanolab_glp.db` önce/sonra blob hash'i aynı: `8ed4b65160353ff5c047f8597f0219e66c29eb43`.
