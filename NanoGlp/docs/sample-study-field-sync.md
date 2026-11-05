# Numune PUT → Study ortak alan eşitlemesi

Taban: PR #1–3 düzeltmelerini içeren main `61ab957d8700cbeea2a61fb6456065bcd2cf1c39`.

`PUT /api/v1/samples/{sample_id}` ve aynı yolu kullanan “Belgedeki farkı uygula” işlemi, gönderilen ortak bilgileri SampleRecord ile bağlı Study arasında eşitler. Eşleme, Excel yenilemesinin `SHARED` alan haritasını kullanır:

| SampleRecord | Study |
| --- | --- |
| sponsor_name | sponsor_name |
| test_item_name | test_item_name |
| lot_no | test_item_batch |
| manufacture_date | manufacture_date |
| expiry_date | expiry_date |
| storage_condition | test_item_storage_condition |
| requested_analysis | test_type |
| contacts | sponsor_contact (`Ad <eposta>; Ad <eposta>`; mevcut Excel biçimi) |

Yalnız istekteki alanlar ele alınır; her hedefte değer farklıysa yazılır. Numune zaten gönderilen değeri içeriyor fakat Study eski kalmışsa, aynı alan Study üzerinde düzeltilir. Gönderilmeyen diğer farklar kendiliğinden eşitlenmez. Tekrar aynı değeri kaydetmek ek güncelleme veya planlama üretmez.

Çalışma kodu mevcut `_clean_code` kuralıyla (boşlukları kaldırma/büyük harf) eşleştirilir. TI kodu Study ilişkilendirmesinde kullanılmaz. Study yoksa yalnız numune değişir; çalışma/takvim oluşturulmaz. Birden fazla normalize Study eşleşmesi varsa belirsiz işlem 422 ile reddedilir.

Manuel istekteki açık null/boş metin, mevcut numune alan kurallarıyla nullable alanları boşaltır; boş contacts listesi sponsor_contact'u boşaltır. Bu, Excel'deki anlamı belirsiz boş hücreleri koruma kuralından farklı bir kullanıcı eylemidir. Bağlı Study'nin zorunlu test_item_name alanını boşaltma isteği açıklayıcı 422 üretir; isteğin diğer değişiklikleri de geri alınır. Study bulunmayan numunede mevcut nullable ürün adı davranışı sürer.

`apply_to_related=false` yalnız seçilen numune/Study çiftini günceller. True olduğunda mevcut aynı-TI numune sorgusu ve mevcut TRM alan kapsamı korunur: kabul alanları (lot, üretim/SKT, saklama vb.) ilgili her numuneye ve kendi Study karşılığına uygulanır. Sponsor, ürün adı, analiz ve kişiler mevcut satış alanları olarak diğer numunelere yayılmaz. İlgili Study yoksa oluşturulmaz. Mevcut rol izinleri korunur.

Bütün numune/Study/ilgili kayıtlar ve audit tek transaction'da tamamlanır. Yanıt hazırlama dahil hata olursa rollback yapılır. PUT yanıtı hazırlanırken numunenin gönderilmeyen plan tarihleri eşitlenmez; mevcut geliş tarihi nedeniyle ilgisiz bir bilgi düzenlemesinde durum geçişi yapılmaz. Geliş tarihi gerçekten değiştirildiğinde mevcut kabul davranışı devam eder.

Şablon, SD ataması, ekstraksiyon ve kaynak planlaması Study'ye yayılmaz. Onaylı/başlamış çalışmalarda durum, plan saatleri, görev kimlikleri/atamaları, gerçekleşmeler, imzalar ve biyolojik revizyonlar korunur. DOCX kaynak önceliği değişmez; güncellenen Study alanları mevcut öncelikle çıktıya yansır. `requested_analysis` yalnız test_type bilgisini düzeltir; Word'ün şablona özgü protokolünü değiştirmez.

## Doğrulama

`backend/tests/test_sample_study_sync.py` gerçek PUT ve DOCX indirme isteklerini izole geçici SQLite üzerinde çalıştırır. Gerçek Word XML/hücre içeriği okunur. Serialization hatası ve ilişkili Study yazımı sırasında enjekte edilen veritabanı hatasından sonra tüm tablolar yeni Session ile karşılaştırılır. Mevcut test beklentileri değiştirilmedi.

Backend dizininde çalıştırılan son paketler:

| Komut | Geçen | Başarısız | Atlanan |
| --- | ---: | ---: | ---: |
| `venv/bin/python tests/test_sample_study_sync.py` | 10 | 0 | 0 |
| `venv/bin/python tests/test_excel_updates.py` | 18 | 0 | 0 |
| `venv/bin/python tests/test_docx_isolation.py` | 11 | 0 | 0 |
| `venv/bin/python tests/test_replan_execution_guard.py` | 7 | 0 | 0 |
| `venv/bin/python tests/test_scheduling_engine_fixes.py` | 20 | 0 | 2 |
| `venv/bin/python tests/verify_engine.py` | 262 kontrol | 0 | 0 |
| `venv/bin/python ../deploy_check.py` | 68 kontrol | 0 | 0 |

Atlanan iki mevcut test Chrome/Edge tarayıcısı gerektirir. İzlenen `nanolab_glp.db` dosyasının önce/sonra Git blob hash'i aynıdır: `8ed4b65160353ff5c047f8597f0219e66c29eb43`. 03.11.2026 sınırı değiştirilmedi.
