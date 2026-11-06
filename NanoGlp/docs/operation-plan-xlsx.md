# Günlük ve haftalık operasyon planı XLSX

Planning'in günlük/haftalık görünümündeki **Excel İndir (.xlsx)**, seçili tarih ve ortak çalışma filtresini `GET /api/v1/planning/export-excel` uç noktasına gönderir. Parametreler: `view=daily|weekly`, zorunlu `target_date=YYYY-MM-DD`, isteğe bağlı tam `study_code`. Haftalık tarih Pazartesi'ye normalize edilir ve Pazar dahil yedi günü kapsar. `study_code` verilmezse tüm çalışmalar alınır. Günlük görünümde de mevcut ortak filtre görünürdür.

Repoda incelenen tek XLSX `Study Status last version (2).xlsx`: GLP Medikal, IN VIVO TEST SÜRELERİ, TEKRAR KULLANIM, SPONSOR SÖZLŞ.-SPONSOR AGREEM., Fiziksel Kimyasal non-GLP ve NUMUNE İŞ AKIŞI sayfaları bulunur. Günlük/haftalık kurumsal operasyon şablonu bulunmadı; çıktı mevcut openpyxl ile hazırlanmış sade bir listedir, resmi şablon iddiası yoktur.

## Veri ve süre kapsamı

- Kaynak kayıtlı `StudyStep` planları ve bağlı `Study`/personeldir. Takvim API'si gibi iptal edilmiş çalışmalar ve görevler dışlanır; DRAFT, APPROVED, IN_PROGRESS, REPORTING ve COMPLETED kapsamda kalır. Yeni tarihsel görünürlük kuralı eklenmez; 03.11.2026 sınırına dokunulmaz.
- Dosyanın üstünde tarih aralığı, çalışma filtresi ve tesis saat standardı (Europe/Istanbul / UTC+03:00) yazılıdır. Günlük XLSX, ekrandaki saat dilimlerinden bağımsız olarak günün tamamını kapsar; bu açıklama günlük görünümde de bulunur.
- Her görev/gün için bir satır: çalışma kodu, görev adı, çalışma günü, özgün planlanan başlangıç/bitiş, o güne düşen başlangıç/bitiş/dakika, tüm atanmış personeller ve ayrı çalışma/görev durumları. Atanmamış görevler kaybolmaz. Birden fazla personel görevi çoğaltmaz; süre kişi sayısıyla çarpılmaz.
- Süre, salt okunur iş yükü hesabıyla aynı günlük kesişim yaklaşımını kullanır. Aralıklar `[başlangıç, bitiş)` olarak ele alınır: örneğin Pazar 23:00–Pazartesi 01:00 görevinin ilgili haftaya yalnız 60 dakikası girer. Özgün plan tarihleri ayrı sütunlarda korunur. Dakikalar mevcut iş yükü servisi gibi tam dakikaya aşağı yuvarlanır.
- Gerçekleşen saatler dahil edilmez, planlanan saatlerin yerine geçirilmez. Ekstraksiyonun 72 saatlik cihaz rezervasyonu personelin kurulum süresine eklenmez. Kaynak metinler Excel formülü olarak yorumlanmaz.
- Boş dönem veya eşleşmeyen filtre, kapsam bilgisi ve “görev bulunmuyor” açıklaması içeren geçerli XLSX üretir.

Uç nokta takvimle aynı `require_management_read` yetkisini kullanır; QA gibi salt okunur kullanıcılar indirebilir. Yeniden planlama, onay, otomatik tamamlama, actual veya çakışma üretimi çağrılmaz. Mevcut Çalışma Takip Listesi Excel ve Study Plan DOCX dışa aktarımları değiştirilmez.

## Doğrulama

`backend/venv/bin/python backend/tests/test_operation_plan_xlsx.py` (NanoGlp dizininden) gerçek HTTP yanıtındaki XLSX'i openpyxl ile açar. Gün/hafta, filtre, durumlar, atamalar, boş dönem, gece/hafta sınırları, cihaz/personel süresi ayrımı, önceki tarihlerin takvim kapsamı, okuma yetkisi ve hücre biçimleri doğrulanır. Her indirmeden önce/sonra yeni Session ile tüm tablolar karşılaştırılır. Test yalnız geçici SQLite kullanır.

Frontend: `npm run test:planning-export`. Gerçek Planning bileşeni ve API indirme yardımcısı çalıştırılır; HTTP sınırı Axios adapter ile taklit edilir. Tarih/filtre, haftanın Pazartesi'ye dönüşümü, QA indirmesi, dosya adı, blob temizliği, işlem sırasında düğmenin kilitlenmesi ve hata gösterimi kontrol edilir. Mevcut takvim/detay okumaları dışında yalnız GET export isteğine izin verilir.

Mevcut test beklentileri değiştirilmedi. Test komutları ve bu PR'ın gerçek sonuçları PR açıklamasında listelenir.
