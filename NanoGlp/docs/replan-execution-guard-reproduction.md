# Tam yeniden planlamada gerçekleşme kaybı — tekrar üretim

Bu aşamada **üretim koduna düzeltme uygulanmadı**. Kullanıcının talimatıyla PR #1 ve #2 birleşene kadar yeni PR bekletiliyor. GitHub kontrolünde main `3c9a2f5d1a0375abaa307f0b4b3ae2a3ef7bcac3`, iki PR da açıktı. Testler, bu iki PR'ın düzeltmelerini içeren `e09fb0a9eac8f19b325cf6c584463366a0d28d70` üzerinde yerel hazırlık dalında çalıştırıldı. Birleşmelerden sonra çalışmalar güncel main tabanına taşınmalı.

## Test sözleşmesi

`backend/tests/test_replan_execution_guard.py`, her çalıştırmada ayrı bir geçici SQLite veritabanı oluşturur. Korunması gereken alanlar için başarılı davranış bekler; mevcut hata nedeniyle koruma testleri bilerek başarısızdır. `expectedFailure` veya skip ile gizlenmezler.

- PENDING adımda tek başına `actual_start`, `actual_end` veya `actual_reference_time`.
- Saatleri boş IN_PROGRESS ve COMPLETED adımlar.
- Doğrudan `schedule_new_study`, `plan_sample`, çalışma ID'si/kodu ile planlama API'si ve numune planlama API'si.
- `plan_sample(allow_non_draft=True)` ve mevcut APPROVED çalışmanın korunması.
- Planlama API'sinde veya plan_sample'da motor reddi taklit edilerek erken commit'lerin ayrıca kontrolü. Bu iki test, yalnız motor içine eklenen geç bir kontrolün yeterli olmadığını gösterir.
- Henüz yürütülmemiş taslağın motor, plan_sample ve API üzerinden yeniden planlanmaya devam etmesi.

Her denemeden önce ve sonra **yeni bir Session** ile bütün tabloların değerleri karşılaştırılır. Buna adımlar, kişi atama ilişkileri, plan/gerçekleşme tarihleri, çalışma alanları, mevcut ve karşı taraftan ilişkili çakışmalar, imzalar ve revizyon geçmişi dahildir. Servis çağrısında ret yakalandıktan sonra ayrıca commit denenerek bekleyen alan değişiklikleri de yakalanır.

## Tekrar üretim sonucu

Backend dizininde:

```sh
venv/bin/python tests/test_replan_execution_guard.py
```

- 7 test metodu çalıştırıldı: 1 geçti, 6 başarısız; atlanan yok.
- Başarısız metotlarda toplam 32 başarısız kontrol/alt senaryo var: motor 5, plan_sample 10, planlama API'si 10, numune API'si 5, geç motor reddi 2.
- Geçen metot, yürütülmemiş taslağın üç yoldan da yeniden planlanabildiğini doğruladı.
- Gerçek API çağrıları beklenen 409 yerine 200 döndü. Adımlar, atamalar, çakışmalar ve çalışma alanları değişti.
- Geç motor reddi testinde planlama API'si 409 dönmesine rağmen `studies` tablosu değişti; plan_sample da PermissionError sonrasında Study değişikliklerini korudu. Böylece ret öncesindeki erken commit sorunu ayrı olarak doğrulandı.

Canlı `backend/nanolab_glp.db` kullanılmadı. İzlenen dosyanın Git blob hash'i önce/sonra `8ed4b65160353ff5c047f8597f0219e66c29eb43` olarak aynı kaldı. Excel/DOCX, tarihsel aktarım sınırı ve SD biyolojik revizyon kodu değiştirilmedi.

## Mevcut regresyonların taban sonucu

| Komut (backend dizininde) | Geçen | Başarısız | Atlanan |
| --- | ---: | ---: | ---: |
| `venv/bin/python tests/test_docx_isolation.py` | 11 | 0 | 0 |
| `venv/bin/python tests/test_excel_updates.py` | 18 | 0 | 0 |
| `venv/bin/python tests/test_scheduling_engine_fixes.py` | 20 | 0 | 2 |
| `venv/bin/python tests/verify_engine.py` | 262 kontrol | 0 | 0 |

İki atlama mevcut Chrome/Edge tarayıcı testleridir. SD biyolojik revizyonunun API/servis regresyonları dahil diğer planlama testleri geçti. Mevcut test beklentileri değiştirilmedi.
