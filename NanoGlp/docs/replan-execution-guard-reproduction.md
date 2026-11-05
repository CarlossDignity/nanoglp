# Tam yeniden planlamada gerçekleşme kaybı — tekrar üretim

Değişiklik, PR #1 ve #2'yi içeren main `b4c48db5b33a832412e61972de5d50bce153ad68` tabanındadır.

## Koruma

`scheduling_engine.ensure_no_execution_for_full_replan` mevcut adımlarda `actual_start`, `actual_end`, `actual_reference_time` veya IN_PROGRESS/COMPLETED durumunu kontrol eder. Bu kanıtlardan biri varsa açıklayıcı PermissionError verir; API bunu HTTP 409 olarak döndürür. Hata mesajı çalışma kodunu ve engelleyen adımı belirtir.

Kontrol doğrudan `schedule_new_study` içinde şablon/kapasite yazımları ve adım silme işleminden önce, planlama API'sinin ID/kod çözümlemesinde dosya alanlarını değiştiren erken commit'ten önce, `plan_sample` içinde alan güncellemesi ve DRAFT durumuna çevirme işleminden önce çağrılır. `allow_non_draft` kontrolü atlamaz. Ret yolu veri yazmaz. Henüz yürütülmemiş taslakların tam planlaması devam eder. SD biyolojik revizyon akışı değiştirilmez; bu koruma tam yeniden planlama içindir.

## Test sözleşmesi

`backend/tests/test_replan_execution_guard.py`, her çalıştırmada ayrı bir geçici SQLite veritabanı oluşturur. Korunması gereken alanlar için başarılı davranış bekler. Düzeltme öncesinde başarısız olan kontroller, düzeltme sonrasında aynı beklentilerle geçer; `expectedFailure` veya skip kullanılmaz.

- PENDING adımda tek başına `actual_start`, `actual_end` veya `actual_reference_time`.
- Saatleri boş IN_PROGRESS ve COMPLETED adımlar.
- Doğrudan `schedule_new_study`, `plan_sample`, çalışma ID'si/kodu ile planlama API'si ve numune planlama API'si.
- `plan_sample(allow_non_draft=True)` ve mevcut APPROVED çalışmanın korunması.
- Planlama API'sinde veya plan_sample'da motor reddi taklit edilerek erken commit'lerin ayrıca kontrolü. Bu iki test, yalnız motor içine eklenen geç bir kontrolün yeterli olmadığını gösterir.
- Henüz yürütülmemiş taslağın motor, plan_sample ve API üzerinden yeniden planlanmaya devam etmesi.

Her denemeden önce ve sonra **yeni bir Session** ile bütün tabloların değerleri karşılaştırılır. Buna adımlar, kişi atama ilişkileri, plan/gerçekleşme tarihleri, çalışma alanları, mevcut ve karşı taraftan ilişkili çakışmalar, imzalar ve revizyon geçmişi dahildir. Servis çağrısında ret yakalandıktan sonra ayrıca commit denenerek bekleyen alan değişiklikleri de yakalanır.

## Düzeltme öncesi tekrar üretim sonucu (b4c48db)

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

## Düzeltme sonrası doğrulama

| Komut (backend dizininde) | Geçen | Başarısız | Atlanan |
| --- | ---: | ---: | ---: |
| `venv/bin/python tests/test_replan_execution_guard.py` | 7 (32 ret + 3 normal planlama senaryosu) | 0 | 0 |
| `venv/bin/python tests/test_docx_isolation.py` | 11 | 0 | 0 |
| `venv/bin/python tests/test_excel_updates.py` | 18 | 0 | 0 |
| `venv/bin/python tests/test_scheduling_engine_fixes.py` | 20 | 0 | 2 |
| `venv/bin/python tests/verify_engine.py` | 262 kontrol | 0 | 0 |
| `venv/bin/python ../deploy_check.py` | 68 kontrol | 0 | 0 |

İki atlama mevcut Chrome/Edge tarayıcı testleridir. SD biyolojik revizyonunun API/servis regresyonları dahil diğer planlama testleri geçti. Mevcut test beklentileri değiştirilmedi.
