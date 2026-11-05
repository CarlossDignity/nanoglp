# Study Status Excel güncellemesi

Aktarım yalnız normalize edilmiş çalışma koduyla eşleştirir. TI/numune kodu eşleştirme anahtarı değildir. GLP ve Non-GLP sekmelerinde yinelenen çalışma kodu dosyanın tamamını reddeder; sonuçta hata ve atlanan satır sayıları döner. Dosyada olmayan kayıtlar (demo işaretli olanlar dahil) korunur. `prune_non_excel` eski çağrılarla uyumluluk için kabul edilir, silme yapmaz.

## Alan sahipliği

- Firma, numune, lot, SKT, üretim ve saklama bilgisi SampleRecord'a yazılır. Study karşılıkları sırasıyla `sponsor_name`, `test_item_name`, `test_item_batch`, `expiry_date`, `manufacture_date`, `test_item_storage_condition` olarak eşitlenir. Analiz adı `Study.test_type`, kişiler `Study.sponsor_contact` ile eşitlenir.
- Geliş, teklif, miktar, ödeme, rapor/termin ve Excel deney tarihleri SampleRecord kaynak alanlarıdır; StudyStep gerçekleşme saatlerine dönüşmez.
- Taslak plan başlangıcı/bitişi Study hedef tarihleriyle eşitlenir. Onaylı/başlamış, imzalı veya gerçekleşmesi bulunan planın takvim ve yönetici ataması korunur. Excel'in farklı değeri `workflow._excel_source` içinde saklanır ve inceleme farkı döner.
- Mevcut operasyonel durum Excel'den geriye veya ileri taşınmaz. Kaynağın durumu ayrıca saklanır; uyumsuzluk raporlanır. Yeni kaydın ilk kaynak durumu alınabilir, ancak devam eden/tamamlanan kaynak satırlarına görev veya gerçekleşme üretilmez.
- Uygulama workflow girdileri ve imzaları korunur. Excel `+` işaretleri kaynak bilgisi olarak saklanır; `done_by`, `done_at` veya imza oluşturmaz. Arayüz imza durumunu yalnız gerçek `approvals` kaydından okur.

Resmî şablonun başlıkları adlarıyla eşlenir; sütun silinmesi sonraki alanları kaydırmaz. Eski başlıksız sabit yerleşim de desteklenir. `Lot No` / `lot_no` ve `Termin` / `Termin Tarihi` ek başlıkları desteklenir (termin, `final_report_date`). Boş, eksik veya `-` değer dolu alanı silmez; inceleme farkı döner. Silme anlamı taşıyan bir boş hücre protokolü eklenmemiştir.

Son Excel kaynak değerleri, otomatik planlama tarafından hesaplanan tarihlerden ayrı tutulur. Böylece aynı dosya tekrar yüklendiğinde değişen sayısı sıfırdır. Otomatik planlama yalnız yeni veya planlama girdileri değişen, yürütülmemiş uygun taslaklar için çalışır. Sonuç `scheduling` listesinde sebep döner.

Aktarım, eski yardımcıların `commit()` çağrılarını yalnız `flush()` yapan bir iç oturumda çalıştırır. Dış oturum tek kez commit eder; planlamanın sonundaki hata dahil tüm yazmalar rollback olur. Başarısız yardımcılar için kısmi başarı uygulanmaz.

`created`, `updated`, `unchanged`, `failed`, `review_required` kayıt sayılarını; `changes` ve `reviews` çalışma kodu, alan, eski değer, Excel değeri ve hedef kaydı taşır. İnceleme sayısı diğer gruplarla örtüşebilir. Mevcut aktarım sonucunda açılan detay tablosu kullanılır.

## Test beklentilerindeki bilinçli değişiklikler

- Excel'de bulunmayan demo kayıtları artık silinmez.
- ONGOING satırına otomatik takvim üretilmez; sonraki COMPLETED kaynak işareti mevcut görevi tamamlamaz.
- 93 kaynak satırı önceki kayıtların üzerine eklenir/güncellenir; liste toplamı önceden var olan ek kayıtları da içerir. Kaynak durum dağılımı ile operasyonel durum dağılımı ayrı doğrulanır.
- Geniş motor testinin tarihsel görevleri artık açık fixture verileriyle oluşturulur. 03.11.2026 sınırının iki tarafındaki görevler, sahte saat üretmeme ve geçmiş görevi doğrulanmış tamamlanma saymama kontrolleri korunur. Üretim kodundaki tarihsel sınır ve hesaplama değiştirilmemiştir.

Testler: `backend/venv/bin/python backend/tests/test_excel_updates.py`, `backend/venv/bin/python backend/tests/test_scheduling_engine_fixes.py`, `backend/venv/bin/python backend/tests/verify_engine.py`, `backend/venv/bin/python deploy_check.py`. Her betik kendi geçici SQLite veritabanını kullanır. Frontend: `npm run build -- --outDir /workspace/nanoglp-runtime/frontend-dist --emptyOutDir` (`frontend/` dizininden); depodaki izlenen `dist` dosyalarını değiştirmez.
