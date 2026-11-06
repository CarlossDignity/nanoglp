# Personel iletişimi, hayvan takibi ve erişim kayıtları

## Personel iletişimi

Yeni personel modeli yoktur: `User.email` kullanılır, `User.phone` nullable olarak eklenir.
`PATCH /api/v1/personnel/{id}/contact` mevcut personel düzenleme yetkisini kullanır;
yalnız `email` ve `phone` kabul eder. Gönderilmeyen alanlar korunur, null/boş metin
alanı temizler. E-posta biçimi ve büyük/küçük harften bağımsız benzersizlik denetlenir.
Bu yol rol/parola/hesap güncellemesi kabul etmez; `/users` yetkileri değişmez.
Günlük/haftalık iş yükü yanıtları ve personel ekranı iki alanı da taşır.

DOCX Bölüm 22'de yönetici atanmış User'dan; diğer personel mevcut seçim kuralıyla
iptal edilmemiş adımlara atanmış, yönetici dışındaki tekil User'lardan alınır.
Telefon/e-posta için dolu değerler virgülle birleştirilir; bilinmeyen değer `TBD` olur.
Mevcut modelde açık personele özel bir iletişim override alanı bulunmadığından yeni
bir override eklenmedi. Sponsor iletişimi bu alana taşınmaz. Bölüm 1'in polar/non-polar
metni, şablon yer tutucu koruması ve görseller değiştirilmez.

## İş akışı 03: sipariş ve kabul

Mevcut `/samples/{id}/workflow/3` işlemi `order`, `receive`, `undo` eylemlerini alır.
Veri yalnız `workflow["3"]` içindedir; 11 adım ve diğer adımların numaraları korunur.
Sipariş tesisin güncel tarihi ve 15 takvim günüyle varsayılan gelir. Sunucu geliş
tarihini hesaplar, oturumdaki kişinin kimliğini/adını kaydeder. Kabul tarihi
siparişten önce veya tesisin bugününden sonra olamaz; sipariş de gelecekte olamaz.
Sipariş kabul edilene kadar adım tamamlanmaz. Aynı istek yeniden gönderildiğinde
ilk kişi/tarih korunur; farklı bilgi için önce geri alma gerekir. Yeni kayıtta eski
`complete` eylemi kabulü atlayamaz. Geri alma önce kabulü, sonra siparişi kaldırır;
kaldırılan alanlar ve geri alan kişi aynı adımın `history` alanında saklanır.

Eski tamamlanmış Excel/tek-tık kayıtları tarih/kişi uydurulmadan korunur. Uygulama
kaydı kaynak işaretinden ayrılır; tekrar Excel aktarımı sipariş/kabulü ezmez.
Bu işlem planı, Gün 0'ı, karantinayı, hayvan/sarf alanlarını veya DOCX'i değiştirmez.

## Erişim kayıtları

`user_access_logs` LOGIN, LOGIN_FAILED ve kimliği doğrulanmış açık LOGOUT eylemini
saklar. Kullanıcı bilgileri olay anındaki kopyadır; kullanıcı silinirse user_id
NULL olur, kimlik kopyası korunur. Bilinmeyen kimlik sadece attempted_identifier'dır.
Parola/JWT/istek gövdesi kaydedilmez. Mevcut AuditLog ve 401/429 limit akışı korunur;
başarısız girişin kaydı hata yanıtından önce commit edilir.

`GET /api/v1/access-logs`: user_id, user (kimlik/ad/e-posta araması), event_type,
date_from, date_to, page ve page_size (1–100). Gün filtreleri Europe/Istanbul'a
göre başlangıç dahil, bitiş gününün sonuna kadar uygulanır. DB UTC standardındadır;
API `+00:00` saat dilimini döndürür, ekran Europe/Istanbul gösterir. API, menü ve
rota yalnız SYSADMIN/ADMIN rollerine açıktır; users menüsü veya kullanıcı adı yetki vermez.

Çıkış Yap önce `/auth/logout` çağırır, sonra (istek başarısız olsa da) yerel oturumu
temizler. 401/süre dolması yalnız yerel temizleme yapar. Tarayıcı kapanışı kaydedilmez.
LOGOUT kullanıcının çıkış talebidir, JWT iptali değildir; mevcut token süresi dolana
kadar sunucuda geçerli olabilir. Yeni token iptal/oturum mimarisi eklenmedi.

### Proxy/IP yapılandırması

Varsayılan `TRUSTED_PROXY_CIDRS` boştur: başlıklara güvenilmez. Uvicorn gerçek bağlantı
adresini korumalıdır: `--no-proxy-headers`. Docker CMD bunu içerir; Docker dışındaki
başlatma komutlarında da bu seçenek kullanılmalıdır. Uvicorn'un önceden dönüştürdüğü
istemci adresinden güvenilir proxy sınırı çıkarılamaz.

Yalnız gerçekten yönettiğiniz, istemci başlıklarını temizleyip yeniden yazan proxy
adreslerini tanımlayın (ör. sadece ilgili proxy için `10.20.30.40/32`, IPv6 için `/128`).
Tüm kaynaklara veya tüm özel ağlara körlemesine güvenmeyin. CF-Connecting-IP ve
X-Real-IP başlıkları proxy tarafından temizlenmeli/üzerine yazılmalıdır; Cloudflare
kullanılıyorsa gerçek Cloudflare bağlantısı proxy katmanında doğrulanmalıdır.

Güvenilir bağlantıda geçerli CF-Connecting-IP, ardından X-Real-IP, ardından temiz
X-Forwarded-For zinciri kullanılır. Zincir sağdan ilk güvenilmeyen adrese kadar
incelenir. Hatalı zincir veya kullanılamayan başlıklar bağlantı adresine döner.
Güvenilmeyen bağlantıdaki başlıklar IP veya hız sınırlama kimliğini değiştirmez.
Yapılandırma yapılmadan reverse proxy arkasında tüm kullanıcılar proxy IP'sini ve
mevcut IP tabanlı hız sınırını paylaşır; gerçek altyapı CIDR'leri bu PR'da varsayılmadı.

## Şema ve doğrulama

Mevcut başlangıç mekanizması `Base.metadata.create_all` ile yeni log tablosunu,
`_ensure_sqlite_columns` ile nullable phone sütununu ekler. Tekrar çalışması ve eski
verilerin korunması yalnız geçici eski/yeni şema SQLite testlerinde doğrulandı.
Bu değişiklik hazırlanırken gerçek DB üzerinde başlangıç/migrasyon çalıştırılmadı.
Uygulama daha sonra işletmeci tarafından başlatıldığında bu mevcut mekanizma çalışır;
öncesinde normal veritabanı yedeği alınmalıdır.

Backend testleri `python -m unittest discover -s tests -v` ile ve ayrıca her modül
ayrı `python -m unittest discover -s tests -p test_<modül>.py -v` sürecinde çalıştırılır.
Modüller DATABASE_URL'i import öncesinde geçici dizine ayarlar; yeni testler SQLite
engine bağlantılarını süreç kapanışında kapatır (Windows dosya kilidi uyumu).
DOCX testleri gerçek paragraf/tablo/XML ve görselleri inceler; hayvan işlemlerinde
ZIP zaman damgası yerine belge parçalarının XML içeriği karşılaştırılır.
03.11.2026 tarihsel sınırı ve planlama kuralları değiştirilmemiştir.
