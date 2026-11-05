# Study Plan DOCX alan kaynakları

Bu değişiklik PR #1'in `b99782c8c3ba43da4c4f0e90d0860a8a98bcbf7e` sürümündeki Excel düzeltmelerini temel alır. Excel aktarımı ve 03.11.2026 tarihsel sınırı değişmez.

- **Belge ilişkilendirmesi:** `Document.dossier_key == Study.study_code`, `primary_study_code == Study.study_code` veya `study_codes` listesindeki tam çalışma kodu eşleşmesi gerekir. Sponsor, TI, dosya adı, dossier etiketi ve çıkarılmış metindeki benzerlik ilişki kurmaz. Başka çalışmanın veya genel demo klasörünün belgeleri yedek kaynak değildir. `FAILED` belgeler kullanılmaz.
- **Firma/ürün/lot/üretim/SKT/saklama/iletişim:** Dolu Study alanı → aynı çalışma kodundaki SampleRecord alanı → açıkça bağlı belgenin çıkarılmış alanı → `TBD`. Belgeler arasında mevcut alan/kategori önceliği kullanılır; aynı öncelikte en yeni yükleme, sonra en büyük belge ID'si seçilir. Örnek ürün/lot lehine özel puanlama uygulanmaz.
- **Takvim:** Çalışmanın kayıtlı başlangıç/bitiş hedefleri, yoksa mevcut adımların en erken başlangıç/en geç bitiş tarihleri kullanılır. Adım saatleri aynen alınır. Belge tarihinden operasyonel takvim üretilmez. Ayrı bir kayıtlı çalışma tamamlanma tarihi bulunmadığı için bu hücre `TBD` olur; bitişe 14 gün eklenmez. Mevcut Study'nin numune ekranından indirilmesi de eksik takvim yüzünden yeniden planlama başlatmaz.
- **Kişiler:** SD ve QA, Study'nin gerçek kullanıcı ilişkilerinden; diğer personel mevcut adımların atamalarından gelir. E-posta ilgili User kaydından gelir. Modelde bulunmayan kişi telefonu `TBD` kalır. Yönetim imza adında yalnız açık görev ataması bulunan tek TFM/EXECUTIVE kullanılır; aksi halde `TBD`. İmza veya gerçekleşme saati oluşturulmaz.
- **Eksik bilgi:** Boş/eksik, `N/A`, `UNKNOWN`, `TBD`, `BELİRTİLMEDİ`, `BİLİNMİYOR` veya `-` çalışmaya özgü değerler yerine `TBD` kullanılır. Pozitif kontrol çalışmasının örnek numarası, hayvan tedarikçisi, yem markası ve bilinmeyen sponsor temsilcisi de uydurulmaz.

Tesis adı/adresi, standart referansları, güvenlik ifadeleri, şablonun standart deney yöntemi ve şablona özgü protokol metinleri korunur. Bunlar sponsor/ürün/lot/personel veya gerçekleşme kaynağı değildir. Master şablonun referans şekli ve özgün ISO kaynak açıklaması korunur; farklı protokol uyarlamalarındaki bölüm metinleri kendi standartlarını kullanır. XML metin düğümleri yerinde değiştirilir; run biçimleri, çizimler, logo, medya dosyaları, sayfa alanları ve ilişkiler korunur. Annex için oda bilgisi yalnız okunur; dışa aktarım sırasında varsayılan kapasite kaydı oluşturulmaz.

## Yer tutucular ve gerçek metin

Şablon yüklenince, henüz kayıt veya belge değeri eklenmeden önce yer tutucu alanları o üretime özgü işaretlerle ayrılır. Doldurma ve TBD tamamlama yalnız bu işaretleri işler. Çok alanlı paragraflarda eşleşmeler baştan alınır ve sondan değiştirilir; eklenen değerler yeniden taranmaz. Böylece `LOT-XX123`, `EXXON`, `XXL`, hatta gerçek alan değeri olan `XX` veya `GLP20XX-XXX` aynen kalır. Şablondaki QA ve yönetim örnek isimleri yalnız onay bölümündeki ilgili rolün `Name:` alanında işlenir; başka rol veya içerikte aynı isim değişmez. Görsel ilişkileri ve metin biçimleri korunur.

## Test beklentisi değişiklikleri

Önceki geniş test şablonda sabit `Selin BOLCAN` ve `Dr. Shivadasan ANOOP` isimlerini bekliyordu. Artık gerçek atama yoksa bu isimlerin bulunmaması ve `TBD` kullanılması beklenir. Diğer protokoller için eski şekil silme davranışına dayanan kontrol de daraltıldı: yalnız korunan referans şeklinin özgün kaynak açıklamasında ISO 10993-23 kalabilir; protokol metninin hedef standarda uyarlanması hâlâ kontrol edilir.

“Belgede hiç XX kalmasın” beklentisi kaldırılmıştır: XX gerçek lot, ürün, sponsor veya kişi bilgisinin parçası olabilir. Testler artık belirli alanların birebir kayıt değerini ve eksik alanların TBD olduğunu kontrol eder; paragraf içindeki çoklu alanlar, rol bağlamı, üst/altbilgi, run biçimi ve aynı run içindeki görseller ayrıca doğrulanır.

`backend/tests/test_docx_isolation.py` her çalıştırmada geçici SQLite oluşturur; üretilen gerçek DOCX'in Word XML parçalarını, hücre değerlerini ve gömülü medyayı okur. Dışa aktarım öncesi/sonrası veritabanı tabloları karşılaştırılır. İzlenen `backend/nanolab_glp.db` kullanılmaz.
