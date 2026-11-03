/**
 * FAZ 9 & 9.1 — Kurumsal Türkçe / İngilizce (TR | EN) Çeviri Sözlüğü ve Dinamik Metin Çevirici
 */

export const STATUS_BADGE_MAP = {
  PENDING: { tr: 'BEKLİYOR', en: 'PENDING' },
  COMPLETED: { tr: 'TAMAMLANDI', en: 'COMPLETED' },
  IN_PROGRESS: { tr: 'DEVAM EDİYOR', en: 'ONGOING' },
  APPROVED: { tr: 'ONAYLI', en: 'APPROVED' },
  DRAFT: { tr: 'TASLAK', en: 'DRAFT' },
  ACTIVE: { tr: 'AKTİF', en: 'ACTIVE' },
  PLANNED: { tr: 'PLANLANDI', en: 'PLANNED' },
  EXPECTED: { tr: 'BEKLENEN', en: 'EXPECTED' },
  ONGOING: { tr: 'DEVAM EDİYOR', en: 'ONGOING' },
  CANCELLED: { tr: 'İPTAL', en: 'CANCELLED' },
};

export function formatStatusBadge(status, lang = 'tr') {
  if (!status) return '—';
  const key = String(status).trim().toUpperCase();
  const entry = STATUS_BADGE_MAP[key];
  if (entry) {
    return lang === 'en' ? entry.en : entry.tr;
  }
  return translateText(String(status), lang);
}

export const EXACT_TR_TO_EN = {
  // === Sol Menü & Üst Bar (Sidebar & Header) ===
  'Yönetici Paneli': 'Executive Dashboard',
  'Numune & Çalışma Takip': 'Sample & Study Tracking',
  'Belge Yükleme': 'Document Upload',
  'Çoklu Çalışma Planlama': 'Multi-Study Planning',
  'Personel İş Yükü': 'Personnel Workload',
  'GLP Çalışmaları': 'GLP Studies',
  'Açık Çakışmalar': 'Open Conflicts',
  'Bugünkü Görevlerim': 'My Tasks Today',
  'Kullanıcı Yönetimi': 'User Management',
  'Sistem Ayarları': 'System Settings',
  'Operasyon & Takip': 'Operations & Tracking',
  'Yönetim': 'Administration',
  'Edirne — GLP Test Tesisi': 'Edirne — GLP Test Facility',
  'Operasyonel Planlama ve Çakışma Yönetimi': 'Operational Planning & Conflict Management',
  'API bağlı': 'API Connected',
  'API bağlantısı yok': 'API Disconnected',
  'İZLEME MODU': 'VIEW ONLY',
  'SALT OKUNUR': 'READ ONLY',
  'Çıkış': 'Sign Out',
  'Güvenli çıkış yap': 'Sign out securely',
  'Üst Yönetim (GM/GMY): İzleme Modu': 'Executive (GM/VP): View-Only Mode',
  'QA Modu: Salt Okunur': 'QA Mode: Read-Only',
  'İzleme Modu (Salt Okunur)': 'View-Only Mode (Read-Only)',
  '(İzleme Modu)': '(View-Only Mode)',
  'GLP Kural Motoru': 'GLP Rule Engine',
  'Biyolojik saatler kilitlidir. Sistem takvimi otomatik kaydırmaz; tüm kararlar SD onayına tabidir.':
    'Biological clocks are locked. The system never shifts schedules automatically; all decisions require SD approval.',
  'Açık Tema': 'Light Mode',
  'Koyu Tema': 'Dark Mode',
  'Temayı Değiştir': 'Toggle Theme',

  // === Giriş Ekranı (Login.jsx) ===
  'GLP · Edirne Test Tesisi': 'GLP · Edirne Test Facility',
  'Nanolab GLP Planlama Sistemi': 'Nanolab GLP Planning System',
  'Nanolab Edirne Test Tesisi kurumsal çalışma ve kaynak yönetimi portalına hoş geldiniz.':
    'Welcome to the Nanolab Edirne Test Facility enterprise study and resource management portal.',
  'Kullanıcı Girişi': 'User Sign In',
  'Devam etmek için kurumsal kullanıcı adınızı ve şifrenizi girin.':
    'Enter your corporate username and password to continue.',
  'Kullanıcı Adı': 'Username',
  'Şifre': 'Password',
  'Şifre *': 'Password *',
  'Şifreyi Göster/Gizle': 'Show/Hide Password',
  'Giriş Yap': 'Sign In',
  'Giriş Yapılıyor…': 'Signing In…',
  'Giriş yapılamadı. Kullanıcı adı veya şifreyi kontrol edin.':
    'Sign in failed. Please check your username and password.',
  'GLP oturum yetkisi doğrulanıyor…': 'Verifying GLP session credentials…',

  // === Roller ve Personel Unvanları (Roles & Titles) ===
  'Sistem Yöneticisi (SYSADMIN)': 'System Administrator (SYSADMIN)',
  'Sistem Yöneticisi': 'System Administrator',
  'Üst Yönetim (GM / GMY)': 'Executive Management (GM / VP)',
  'Satış': 'Sales',
  'TRM Kabul': 'Sample Acceptance (TRM)',
  'TRM Kabul (Test ve Referans Madde Kabul)': 'TRM Acceptance (Test & Reference Item)',
  'Test Tesisi Yöneticisi': 'Test Facility Management (TFM)',
  'Test Tesisi Yöneticisi (TFM)': 'Test Facility Management (TFM)',
  'Çalışma Yöneticisi': 'Study Director',
  'Çalışma Yöneticisi (SD)': 'Study Director (SD)',
  'Çalışma Yöneticisi (Study Director) *': 'Study Director *',
  'Planlama Koordinatörü': 'Planning Coordinator',
  'Planlama Koordinatörü (PK)': 'Planning Coordinator (PC)',
  'Kalite Güvence': 'Quality Assurance',
  'Kalite Güvence (QA)': 'Quality Assurance (QA)',
  'Kalite Güvence Birimi': 'Quality Assurance Unit',
  'Kalite Güvence Uzmanı': 'QA Specialist',
  'In Vivo Teknisyeni': 'In Vivo Technician',
  'In Vivo Teknisyeni 1': 'In Vivo Technician 1',
  'In Vivo Teknisyeni 2': 'In Vivo Technician 2',
  'In Vivo Teknisyeni 3': 'In Vivo Technician 3',
  'Veteriner Hekim': 'Veterinarian',
  'Analist': 'Analyst',
  'Teknisyen': 'Technician',
  'GM / GMY': 'GM / VP',

  // === Ham Durum Kodları ve Rozetleri ===
  'BEKLİYOR': 'PENDING',
  'TAMAMLANDI': 'COMPLETED',
  'DEVAM EDİYOR': 'IN PROGRESS',
  'ONAYLI': 'APPROVED',
  'Onaylı': 'Approved',
  'TASLAK': 'DRAFT',
  'Taslak': 'Draft',
  'AKTİF': 'ACTIVE',
  'PLANLANDI': 'PLANNED',
  'BEKLENEN': 'EXPECTED',
  'DEVAM EDEN': 'ONGOING',
  'İPTAL': 'CANCELLED',
  'KRİTİK': 'CRITICAL',
  'UYARI': 'WARNING',

  // === Numune & Çalışma Takip (SampleTracking.jsx) ===
  'Numune kabulünden final rapora kadar tüm GLP çalışmaları — tek satırda durum, takvim ve 11 adımlı iş akışı.':
    'All GLP studies from sample acceptance to final report — single-row status, schedule, and 11-step workflow.',
  'Excel (.xlsx / .csv) İçe Aktar': 'Import Excel (.xlsx / .csv)',
  'Tüm Planlananları Otomatik Takvimle': 'Auto-Schedule All Planned',
  'Yeni Kayıt': 'New Record',
  'Beklenen Numune': 'Expected Samples',
  'Numune henüz gelmedi': 'Sample not received yet',
  'Planlanan Çalışma': 'Planned Studies',
  'Otomatik planlanacak': 'To be auto-scheduled',
  'Devam Eden Çalışma': 'Ongoing Studies',
  'Test / raporlama sürüyor': 'Testing / reporting in progress',
  'Gecikmiş İş': 'Overdue Items',
  'Numune veya rapor süresi geçti': 'Sample or report deadline passed',
  'Çalışma Yöneticisi Bazında Açık Çalışmalar': 'Open Studies by Study Director',
  'Atanmamış': 'Unassigned',
  'Atanmadı': 'Unassigned',
  'GLP no, test maddesi, sponsor, TI kodu ara…': 'Search GLP code, test item, sponsor, TI code…',
  'Tümü': 'All',
  'Tüm Durumlar': 'All Statuses',
  'Beklenen': 'Expected',
  'Planlanan': 'Planned',
  'Devam eden': 'Ongoing',
  'Devam Ediyor': 'Ongoing',
  'Devam ediyor': 'Ongoing',
  'Biten': 'Completed',
  'İptal': 'Cancelled',
  'Çalışma': 'Study',
  'ÇALIŞMA': 'STUDY',
  'Test maddesi / Sponsor': 'Test Item / Sponsor',
  'Numune': 'Sample',
  'Takvim': 'Schedule',
  'Durum': 'Status',
  'DURUM': 'STATUS',
  'İş akışı': 'Workflow',
  'Aksiyonlar': 'Actions',
  'Yükleniyor…': 'Loading…',
  'Yükleniyor': 'Loading',
  'Filtreye uyan numune / çalışma kaydı yok.': 'No sample or study records match the selected filters.',
  'Bekleniyor': 'Pending',
  'Kabul edildi': 'Accepted',
  'Takvim yok': 'No schedule',
  'tarihler elle girilmiş': 'dates entered manually',
  'Gecikmiş': 'Overdue',
  'yurt dışı': 'abroad',
  'İş Akışı & Takvimi Gör / Planla': 'View Workflow & Schedule',
  'Study Plan İndir (.docx)': 'Download Study Plan (.docx)',
  'Study Plan Taslağı İndir (.docx)': 'Download Draft Study Plan (.docx)',
  'Yeni numune / çalışma kaydı': 'New Sample / Study Record',
  'Kapat': 'Close',
  'Belgeden Doldur (TIIS / CoA / FM.083 PDF)': 'Auto-Fill from Document (TIIS / CoA / FM.083 PDF)',
  'Çalışma Belgelerini (TIIS / CoA / FM.083 PDF) Yükle & Otomatik Doldur':
    'Upload Study Documents (TIIS / CoA / FM.083 PDF) & Auto-Fill',
  "Lot / Seri No, SKT, Üretim Tarihi, Saklama Koşulu, Sponsor, Test Maddesi ve Polar / Apolar çözücüler PDF'ten okunarak çalışma kaydına yazılır. Dosyaları buraya sürükleyin veya seçin.":
    'Lot / Batch No, Expiry Date, Manufacture Date, Storage Condition, Sponsor, Test Item, and Polar / Non-Polar solvents are parsed from PDF into the study record. Drag files here or select.',
  'Vision OCR okuyor…': 'Vision OCR reading…',
  'PDF Seç': 'Select PDF',
  'GLP belgesi': 'GLP document',
  'GLP Belgesi': 'GLP Document',
  'Otomatik doldurulan alanlar': 'Auto-filled fields',
  'Belgelerden doldurulacak yeni bir alan bulunamadı (alanlar zaten dolu veya belgede yok).':
    'No new fields to auto-fill from documents (fields already populated or not present in document).',
  'Kayıt ile belge farklı — ezilmedi': 'Record differs from document — not overwritten',
  '→ belge:': '→ document:',
  'Belgedeki değeri uygula': 'Apply document value',
  'a) Satış Bilgileri': 'a) Sales Information',
  'Satış Bilgileri': 'Sales Information',
  'Bu bölümü Satış rolü düzenler.': 'Edited by the Sales role.',
  'b) Numune Kabul — Test ve Referans Madde': 'b) Sample Acceptance (TRM)',
  'Numune Kabul': 'Sample Acceptance (TRM)',
  'Bu bölümü TRM Kabul rolü düzenler.': 'Edited by the Sample Acceptance (TRM) role.',
  'c) Otomatik Takvim & Rapor Tarihleri': 'c) Automated Schedule & Report Dates',
  'Otomatik Takvim & Rapor Tarihleri': 'Automated Schedule & Report Dates',
  'Tarihler çalışma takvimi oluşturulduğunda sistem tarafından hesaplanır.':
    'Dates are calculated automatically by the system when the study schedule is generated.',
  'd) 11 Adımlı Numune İş Akışı': 'd) 11-Step Sample Workflow',
  '11 Adımlı Numune İş Akışı': '11-Step Sample Workflow',
  'Vazgeç': 'Cancel',
  'Kaydet': 'Save',
  'Kaydediliyor…': 'Saving…',
  'Düzenle': 'Edit',
  'Şablon / ÇY ata': 'Assign Template / SD',
  'Çalışma kodu (GLP No) *': 'Study Code (GLP No) *',
  'Talep edilen analiz': 'Requested Analysis',
  'Test maddesinin adı': 'Test Item Name',
  'Sponsor': 'Sponsor',
  'Fatura edilecek firma': 'Billing Company',
  'Teklif no': 'Quote No',
  'Satış yöneticisi': 'Sales Manager',
  'Sözleşme tarihi': 'Agreement Date',
  'Ödeme durumu': 'Payment Status',
  'Test laboratuvarı': 'Testing Laboratory',
  'Beklenen geliş tarihi': 'Expected Arrival Date',
  'İlgili kişiler': 'Contact Persons',
  'İlgili kişiler (isim ve e-posta)': 'Contact Persons (Name & Email)',
  'Ad Soyad': 'Full Name',
  'e-posta': 'email',
  'Kişiyi kaldır': 'Remove contact',
  '+ Kişi ekle': '+ Add contact',
  'Numune durumu': 'Sample Status',
  'Test madde kodu': 'Test Item Code (TRM)',
  "İstanbul'a geliş tarihi": 'Istanbul Arrival Date',
  'Laboratuvara geliş tarihi': 'Laboratory Arrival Date',
  'Teslim alınan miktar': 'Received Quantity',
  'Lot / seri no': 'Lot / Batch No',
  'SKT': 'Expiry Date',
  'Saklama koşulu': 'Storage Condition',
  'Üretim tarihi': 'Manufacture Date',
  'Polar ekstraksiyon çözücüsü': 'Polar Extraction Solvent',
  'Apolar ekstraksiyon çözücüsü': 'Non-Polar Extraction Solvent',
  'Hayvan / sarf malzeme durumu': 'Animal / Consumable Status',
  'Hayvan / sarf temin tarihi': 'Animal / Consumable Procurement Date',
  'Numune notu': 'Sample Note',
  'Aynı numuneyi kullanan diğer çalışmalar': 'Other studies sharing the same sample',
  'Aynı numuneyi kullanan diğer çalışmalarda da güncelle (': 'Also update other studies sharing the same sample (',
  'Test şablonu': 'Test Template',
  'Analiz adından otomatik belirle': 'Auto-detect from analysis name',
  'Çalışma başlangıç (Gün 0)': 'Study Start (Day 0)',
  'Test bitiş tarihi': 'Test End Date',
  'Taslak rapor teslim (bitiş + 3 gün)': 'Draft Report Due (End + 3d)',
  'Final rapor gönderim (bitiş + 7 gün)': 'Final Report Delivery (End + 7d)',
  'Takvimi Yeniden Hesapla': 'Recalculate Schedule',
  'Otomatik Taslak Takvim Oluştur': 'Generate Automated Draft Schedule',
  'Planlama Ekranında Aç': 'Open in Planning View',
  '+ Tamamlandı': '+ Completed',
  '- Bekliyor': '- Pending',
  'geri al': 'revoke',
  'Geri al': 'Undo',
  'Tamamlandı olarak işaretle': 'Mark as completed',

  // === 11 Adımlı İş Akışı Başlıkları ve Sorumlular (WORKFLOW_STEPS) ===
  'Sponsor sözleşmesinin imzalanması': 'Signing of Sponsor Agreement',
  'Etik kurul başvurusu': 'Ethics Committee Application',
  'Hayvan siparişi ve kabulü': 'Animal Ordering & Reception',
  'Test maddesinin kabulü ve arşiv': 'Test Item Acceptance & Archiving',
  'Taslak çalışma planı': 'Draft Study Plan Preparation',
  'Çalışma planının onayı': 'Study Plan Approval',
  'Çalışmanın başlaması': 'Study Initiation (Day 0)',
  'Çalışmanın bitişi': 'Experimental Completion',
  'Taslak rapor gönderimi': 'Draft Report Submission',
  'Ödemenin tamamlanması': 'Payment Completion',
  'Final rapor gönderimi': 'Final Report Submission',
  'Çalışma yöneticisi': 'Study Director',
  'TRM kabul': 'Sample Acceptance (TRM)',
  'ÇY · KG · TBY': 'SD · QA · TFM',
  'Test başlangıç tarihi': 'Test Start Date',
  'ÇY Onayla': 'Approve (SD)',
  'KG Onayla': 'Approve (QA)',
  'TBY Onayla': 'Approve (TFM)',
  'Çalışma Yöneticisi bekleniyor': 'Awaiting Study Director',
  'Kalite Güvence bekleniyor': 'Awaiting Quality Assurance',
  'Test Tesisi Yöneticisi bekleniyor': 'Awaiting Test Facility Management',

  // === Yönetici Paneli (Dashboard.jsx) ===
  'Laboratuvar operasyonel durumu': 'Laboratory operational status',
  'Yenile': 'Refresh',
  'Aktif Çalışmalar': 'Active Studies',
  'Bekleyen taslak çalışma yok': 'No pending draft studies',
  'Çözülmemiş Kritik Çakışmalar': 'Unresolved Critical Conflicts',
  'Bugünün Görevleri': "Today's Tasks",
  'Bugüne düşen planlı GLP adımı': 'Planned GLP steps scheduled for today',
  'Kritik Ekipman & Su Banyosu Kapasitesi': 'Critical Equipment & Water Bath Capacity',
  'Planlı ekstraksiyon (G4–G7) penceresi bulunmuyor.': 'No planned extraction (D4–D7) window.',
  'Tüm Planlı Biyolojik Kilometre Taşları (Geçmiş / Taslak Dahil)':
    'All Planned Biological Milestones (Including Past / Draft)',
  'Yaklaşan Biyolojik Kilometre Taşları': 'Upcoming Biological Milestones',
  'Önümüzdeki Günler': 'Upcoming Days',
  'Tüm Planlı Görevler (Geçmiş/Taslak Dahil)': 'All Planned Tasks (Past/Draft Included)',
  '7 gün': '7 days',
  '14 gün': '14 days',
  '30 gün': '30 days',
  '90 gün': '90 days',
  'Tüm Planlı Görevler görünümünde sabitle →': 'Pin to All Planned Tasks view →',
  'Sistemde henüz planlanmış biyolojik kilitli görev bulunmuyor.':
    'No biologically locked tasks are currently scheduled in the system.',
  'Zaman': 'Time',
  'ZAMAN': 'TIME',
  'Görev': 'Task',
  'GÖREV': 'TASK',
  'Süre / Tolerans': 'Duration / Tolerance',
  'SÜRE / TOLERANS': 'DURATION / TOLERANCE',
  'Sorumlu': 'Responsible Role',
  'SORUMLU': 'RESPONSIBLE ROLE',
  'Tarih / Saat': 'Date / Time',
  'Gün / Adım': 'Day / Step',
  'Atanan Personel': 'Assigned Personnel',
  'Cihaz / Kilit': 'Equipment / Lock',
  'Biyolojik kilitli': 'Biologically Locked',
  'Biyolojik Kilitli': 'Biologically Locked',
  'Esnek': 'Flexible',
  'Haftalık Master Takvimde Gör →': 'View on Weekly Master Calendar →',
  'Bu çalışmanın takvimini açmak için tıklayın': 'Click to open the schedule for this study',
  'Taslak ve aktif çalışmaları Planlama & Master Takvim ekranında görüntüle / onayla':
    'View / approve draft and active studies in the Planning & Master Calendar screen',
  'Master Operasyon Takvimini aç': 'Open Master Operations Calendar',

  // === Çoklu Çalışma Planlama (Planning.jsx) ===
  'Çoklu Çalışma Planlama & Kalıcı Master Operasyon Takvimi':
    'Multi-Study Planning & Persistent Master Operations Calendar',
  'Kayıtlı taslak ve onaylı çalışmaların takvimleri kalıcı olarak saklanır; çakışma çözümleri, haftalık/günlük akış ve çalışma onayları tek ekrandan yönetilir.':
    'Schedules of draft and approved studies are stored persistently; conflict resolutions, weekly/daily flows, and study approvals are managed from a single screen.',
  'Haftalık/Günlük takvimleri, çakışma detaylarını ve iş yükünü inceleyebilir, Study Plan Taslağı İndir (.docx) butonunu kullanabilirsiniz; planlama ve onaylama işlemleri kapalıdır.':
    'You can inspect weekly/daily schedules, conflict details, and workloads, and download Draft Study Plans (.docx); planning and approval actions are disabled.',
  'Yeni GLP Çalışması Başlat': 'Initiate New GLP Study',
  'Seçili Çalışmanın Başlangıç Tarihini (Gün 0) Değiştir veya Manuel Simülasyon Yap':
    'Change Selected Study Start Date (Day 0) or Run Manual Simulation',
  'Formu Aç': 'Open Form',
  'Saat, süre ve tolerans değerleri sistem varsayılanıdır; protokole göre SD tarafından teyit edilmelidir. Kod sistemde yoksa DRAFT çalışma açılır. Onaylı çalışmalar yeniden planlanamaz.':
    'Time, duration, and tolerance values are system defaults to be confirmed by the SD per protocol. If the code does not exist, a DRAFT study is created. Approved studies cannot be rescheduled.',
  'Çalışma Kodu (Yeni veya Mevcut Taslak)': 'Study Code (New or Existing Draft)',
  'Test Şablonu': 'Test Template',
  'Aklimatizasyon Başlangıcı (Gün 0)': 'Acclimatization Start (Day 0)',
  'Planla ve Analiz Et': 'Schedule & Analyze',
  'GLP kodu, test, sponsor ara...': 'Search GLP code, test, sponsor...',
  'Kritik Çakışmalı': 'Critical Conflicts',
  'Çalışma listesini, arama ve filtreleri açmak için tıklayın': 'Click to expand study list, search, and filters',
  'Paneli daraltmak için tıklayın': 'Click to collapse panel',
  'Göster': 'Expand',
  'Gizle': 'Hide',
  'Arama veya filtre kriterlerine uygun çalışma bulunamadı.': 'No studies match your search or filter criteria.',
  'Aramayı temizle': 'Clear search',
  'Kayıtlı çalışmalar yükleniyor…': 'Loading registered studies…',
  'Forma Aktar': 'Load into Form',
  'Bu taslağın kodunu ve tarihini yukarıdaki forma aktar': 'Load this draft study code and date into the form above',
  'Kapasite Kontrolü': 'Capacity Check',
  'Oda': 'Room',
  'Fiziksel kapasite içinde': 'Within physical capacity',
  'Esneklik payı kullanılıyor': 'Using flexibility margin',
  'Planlama kapasitesi aşıldı': 'Planning capacity exceeded',
  'Cihaz kapasitesi aşıldı': 'Equipment capacity exceeded',
  'eşzamanlı kullanım': 'concurrent usage',
  'Çakışmasız': 'No Conflict',
  'Planı Onayla ve Aktif Çalışmalara Al (APPROVE)': 'Approve Plan & Move to Active Studies (APPROVE)',
  'Çalışma Detay & Gantt': 'Study Detail & Gantt',
  'Haftalık Master Takvim (Pzt–Paz)': 'Weekly Master Calendar (Mon–Sun)',
  'Günlük Saatlik Akış (08:00–18:00)': 'Daily Hourly Flow (08:00–18:00)',
  'Günlük İş Yükü Barları': 'Daily Workload Bars',
  'Önceki Hafta': 'Previous Week',
  'Sonraki Hafta': 'Next Week',
  'Önceki Gün': 'Previous Day',
  'Sonraki Gün': 'Next Day',
  'Bugün': 'Today',
  'Görevli Haftalar:': 'Active Weeks:',
  'Görevli Günler (Hızlı Geçiş):': 'Active Days (Quick Jump):',
  'Hafta sonu': 'Weekend',
  'Planlı görev yok': 'No planned tasks',
  'Bu tarihte atanmış görev yok.': 'No tasks assigned on this date.',
  '08:00 – 18:00 mesai dilimlerinde yürütülen tüm GLP çalışma adımları, süreleri ve personel atamaları.':
    'All GLP study steps, durations, and personnel assignments executed within 08:00–18:00 working hours.',
  'Tüm çalışmaların (Taslak ve Onaylı) Pazartesi–Pazar görev dağılımı ve sorumlu personelleri.':
    'Monday–Sunday task distribution and assigned personnel across all studies (Draft & Approved).',
  'Saat / Süre': 'Time / Duration',
  'Adım Adı': 'Step Name',
  'Cihaz': 'Equipment',
  'Kilit': 'Lock',
  'yok': 'none',
  'Biyolojik Kilitli Adımlar': 'Biologically Locked Steps',
  'Dokunulmayan onaylı çalışmalar:': 'Untouched approved studies:',
  'Kıyaslanan diğer taslaklar:': 'Compared draft studies:',
  'Çakışan adım': 'Conflicting step',
  'Tek tık çözüm seçenekleri': 'One-click resolution options',
  'Takvim kendiliğinden kaydırılmadı; kararınızı aşağıdaki tek tık çözüm seçenekleriyle uygulayın.':
    'Schedule was not shifted automatically; apply your decision using the one-click resolution options below.',
  'GLP kritik çakışması tespit edildi': 'Critical GLP conflict detected',
  'GLP hafta sonu / mesai uyarısı — karar destek seçenekleri':
    'GLP weekend / overtime warning — decision support options',
  'CİHAZ KAPASİTE KİLİDİ': 'EQUIPMENT CAPACITY LOCK',
  'HAFTA SONU NÖBET ONAYI GEREKLİ': 'WEEKEND DUTY APPROVAL REQUIRED',
  'BİYOLOJİK ZAMAN KİLİDİ İHLALİ': 'BIOLOGICAL TIME LOCK VIOLATION',
  'PERSONEL İŞ YÜKÜ / ÇAKIŞMA': 'PERSONNEL WORKLOAD / OVERLAP',
  'ATANACAK PERSONEL YOK': 'NO AVAILABLE PERSONNEL',

  // === GLP Çalışmaları (Studies.jsx) ===
  'GLP Test Çalışmaları (Studies)': 'GLP Test Studies',
  'Nanolab Edirne GLP akreditasyonuna uygun kayıtlı test ve çalışma protokolleri.':
    'Registered test and study protocols compliant with Nanolab Edirne GLP accreditation.',
  'Yeni Çalışma': 'New Study',
  'Yeni GLP Çalışması Tanımla': 'Define New GLP Study',
  'Çalışma Kodu *': 'Study Code *',
  'Çalışma Başlığı *': 'Study Title *',
  'Test Türü / Şablon': 'Test Type / Template',
  'Sponsor / Müşteri': 'Sponsor / Client',
  'Test Maddesi / Örnek *': 'Test Item / Sample *',
  'Lot / Parti No': 'Lot / Batch No',
  'Seçiniz...': 'Select...',
  'Çalışmayı Kaydet': 'Save Study',
  'Kılavuz / Test:': 'Guideline / Test:',
  'Test Maddesi:': 'Test Item:',
  'Sponsor:': 'Sponsor:',
  'Başlangıç (Gün 0)': 'Start Date (Day 0)',
  'Bitiş / Rapor Hedefi': 'End / Report Target',
  'Takvimde Görüntüle': 'View Schedule',
  'Master Planlamada Düzenle': 'Edit in Master Planning',
  'Çalışma takvimi ve biyolojik adımlar yükleniyor…': 'Loading study schedule and biological steps…',
  'Bu çalışma için henüz adım bazlı biyolojik takvim oluşturulmamış.':
    'Step-by-step biological schedule has not been generated for this study yet.',
  'Süre & Kilit': 'Duration & Lock',
  'Gün': 'Day',
  'Tarih': 'Date',
  'Saat': 'Time',
  'Adım': 'Step',

  // === Personel İş Yükü (Personnel.jsx) ===
  'Personel ve İş Yükü Yönetimi': 'Personnel & Workload Management',
  'Yeni Personel': 'New Personnel',
  'GLP Rolü': 'GLP Role',
  'Günlük Maks. Saat': 'Max Daily Hours',
  'Yetkinlikler (virgülle)': 'Competencies (comma-separated)',
  'Personel Ekle': 'Add Personnel',
  'Günlük İş Yükü (9 Saat Sınırı)': 'Daily Workload (9-Hour Limit)',
  'Haftalık İş Yükü Matrisi (Pzt–Paz)': 'Weekly Workload Matrix (Mon–Sun)',
  'Görev Olan Tarihlere Git:': 'Jump to Dates with Tasks:',
  'Görev Olan Haftalar:': 'Weeks with Tasks:',
  'Kayıtlı aktif personel yok.': 'No active personnel found.',
  '9 SAAT AŞIMI': '9-HOUR LIMIT EXCEEDED',
  '9 saatlik GLP üst sınırı aşıldı!': '9-hour GLP daily limit exceeded!',
  '7 günlük (Pzt–Paz) toplam görev süreleri • Hücreye tıklayarak o günün detaylı görev dökümüne geçebilirsiniz.':
    '7-day (Mon–Sun) total task durations • Click any cell to inspect detailed tasks for that day.',
  'Personel / Rol': 'Personnel / Role',
  'Haftalık Toplam': 'Weekly Total',
  '0 dk': '0 min',
  '9 sa (540 dk)': '9 hr (540 min)',

  // === Belge Yükleme (Upload.jsx) ===
  'Belge Yükleme ve Çoklu Belge Dosya Birleştirme (Vision OCR)':
    'Document Upload & Multi-Document Dossier Merging (Vision OCR)',
  'Sözleşme, TIIS, CoA, Hayvan Menşei Sertifikası ve FM.083 belgelerini yükleyin; GPT-4o Vision tüm sayfaları, tabloları ve işaretli kutucukları (':
    'Upload Agreement, TIIS, CoA, Animal Origin Certificate, and FM.083 documents; GPT-4o Vision reads all pages, tables, and checked boxes (',
  '+ Yeni Müşteri Belgeleri Yükle (PDF Seç / Sürükle-Bırak)':
    '+ Upload New Client Documents (Select PDF / Drag & Drop)',
  'MÜŞTERİ / BAŞVURU KLASÖRÜ SEÇİMİ': 'CLIENT / APPLICATION FOLDER SELECTION',
  "Her firmanın başvuru belgeleri kendi klasöründe ayrı tutulur; seçtiğiniz klasördeki PDF'ler otomatik birleştirilir.":
    'Each company’s application documents are isolated in their own folder; PDFs in the selected folder are merged automatically.',
  'Yeni Müşteri Klasörü Aç': 'Create New Client Folder',
  'Yeni Müşteri Klasörü Kodu (Örn: DOSSIER-MEDTECH-2026) *': 'New Client Folder Code (e.g., DOSSIER-MEDTECH-2026) *',
  'Firma / Başvuru Klasörü Açıklaması': 'Company / Application Folder Description',
  'Klasörü Aç ve Seç': 'Create & Select Folder',
  'Müşteri / Başvuru Klasörü Seç': 'Select Client / Application Folder',
  'AI Vision & GLP Denetim Hattı (Agent Pipeline)': 'AI Vision & GLP Audit Pipeline',
  'Yapay zeka okur ve önerir; GLP kararını her zaman SD / TFM onaylar.':
    'AI reads and suggests; GLP decisions are always approved by SD / TFM.',
  'Birleştirilmiş Çalışma Dosyası Özeti (Master Study Profile)': 'Merged Study Dossier Summary (Master Study Profile)',
  'PLANLANACAK ÇALIŞMA KODU SEÇİMİ': 'STUDY CODE SELECTION FOR SCHEDULING',
  'Aktif Kod:': 'Active Code:',
  '1. Sponsor, Sözleşme ve Çalışma Bilgileri': '1. Sponsor, Agreement & Study Information',
  '2. Test Maddesi (TIIS / CoA) ve Ekstraksiyon Parametreleri': '2. Test Item (TIIS / CoA) & Extraction Parameters',
  '3. Test Sistemi (Hayvan Menşei & FM.083 Aklimatizasyon)': '3. Test System (Animal Origin & FM.083 Acclimatization)',
  'Çalışma Direktörü (SD) Eşleştirme ve Devir Kontrolü': 'Study Director (SD) Matching & Handover Control',
  'Master Çalışma Profili & Şablon Hazırlığı': 'Master Study Profile & Template Readiness',
  'Bu Verilerle Çalışma ve Plan Oluştur': 'Create Study & Schedule with These Data',
  'Yeniden Analiz Et': 'Re-Analyze',
  'Belgeyi dosyadan kaldır': 'Remove document from folder',

  // === Açık Çakışmalar (Conflicts) ===
  'Çözülmemiş tüm GLP çakışma kayıtları (en yeni üstte).': 'All unresolved GLP conflict records (newest on top).',
  'Açık çakışma kaydı bulunmuyor.': 'No open conflict records found.',
  'Personel Çakışması / 9 Saat Aşımı': 'Personnel Overlap / 9-Hour Limit Exceeded',
  'Biyolojik Zaman Kilidi İhlali': 'Biological Time Lock Violation',
  'Cihaz Rezervasyon Çakışması': 'Equipment Reservation Overlap',
  'Oda Kapasitesi Aşımı': 'Room Capacity Exceeded',
  'Kalibrasyon Süresi Dolmuş': 'Calibration Expired',
  'Atanacak Personel Yok / Yetkinlik': 'No Available Personnel / Competency Mismatch',

  // === Bugünkü Görevlerim (MyTasks.jsx) ===
  'Bugünkü Görev Programım': 'My Task Schedule',
  'GLP protokollerine göre şahsınıza atanmış günlük uygulama, ekstraksiyon ve gözlem adımları.':
    'Daily application, extraction, and observation steps assigned to you under GLP protocols.',
  'Oturum Açan Yetkili': 'Signed-In Personnel',
  'Görev bulunan tarihler:': 'Dates with assigned tasks:',
  'Görevler yükleniyor…': 'Loading tasks…',
  'Yukarıdaki tarih kısayollarından veya aşağıdaki tüm görevler tablosundan planlı günlerinize geçebilirsiniz.':
    'Use the date shortcuts above or the full task table below to jump to your scheduled days.',
  'Başlat': 'Start',
  'Tamamla': 'Complete',
  '✓ Tamamlandı': '✓ Completed',
  'Tamamlandı': 'Completed',
  'Atandığım Tüm Çalışma Adımları (Takvim Özeti)': 'All Study Steps Assigned to Me (Schedule Summary)',
  'Şu anda üzerinize atanmış aktif bir GLP çalışma adımı bulunmuyor.':
    'There are currently no active GLP study steps assigned to you.',
  'Süre': 'Duration',
  'İşlem': 'Action',

  // === Kullanıcı Yönetimi (UserManagement.jsx) ===
  'Kullanıcı ve Rol Yetkileri Yönetimi': 'User & Role Permissions Management',
  'Kurumsal kullanıcı hesapları, Üst Yönetim (GM / GMY) izleme profilleri ve dinamik sol menü ekran yetki matrisi.':
    'Corporate user accounts, Executive (GM / VP) view-only profiles, and dynamic sidebar menu permission matrix.',
  'Hazır Üst Yönetim (GM/GMY) Ekle': 'Add Preset Executive (GM/VP)',
  'Yeni Kullanıcı Ekle': 'Add New User',
  'Kullanıcı Adı (Username) *': 'Username *',
  'Ad Soyad (Ekranda Görünecek İsim) *': 'Full Name (Display Name) *',
  'Ad Soyad (Görünen İsim)': 'Full Name (Display Name)',
  'Sistem Rolü *': 'System Role *',
  'E-posta (Opsiyonel)': 'Email (Optional)',
  'Yeni Şifre (Değiştirmek istemiyorsanız boş bırakın)': 'New Password (Leave blank to keep unchanged)',
  'Hesap Aktif (Sisteme giriş yapabilir ve görev atanabilir)': 'Account Active (Can sign in and be assigned tasks)',
  'Değişiklikleri Kaydet': 'Save Changes',
  'Kullanıcı Oluştur': 'Create User',
  'Rol Yönetimi ve Sol Menü Ekran Yetki Matrisi (SYSADMIN)':
    'Role Management & Sidebar Menu Permission Matrix (SYSADMIN)',
  '+ Yeni Rol ve Ekran Yetkisi Oluştur': '+ Create New Role & Menu Permissions',
  'Rol Kodu (Büyük Harf) *': 'Role Code (Uppercase) *',
  'Rol Görünen Adı (Türkçe) *': 'Role Display Name *',
  'Salt Okunur (İzleme Modu)': 'Read-Only (View Mode)',
  'Salt Okunur': 'Read-Only',
  'Aktif edilirse bu rol sadece izleme ve Study Plan (.docx) raporu indirme yapabilir; planlama, onaylama veya veri silme yapamaz.':
    'When enabled, this role can only view screens and download Study Plan (.docx) reports; it cannot schedule, approve, or delete data.',
  'Sol Menüde Görebileceği Ekranlar:': 'Allowed Sidebar Menus:',
  'Yeni Rol Oluştur': 'Create New Role',
  'Rolü Oluştur': 'Create Role',
  'Rol Kodu & Görünen Ad': 'Role Code & Display Name',
  'Tam Yetki': 'Full Access',
  'Kayıtlı Kullanıcılar': 'Registered Users',
  'Kullanıcılar yükleniyor…': 'Loading users…',
  'Rol & Yetki Modu': 'Role & Access Mode',
  'Açık Menü Sayısı': 'Allowed Menus',
  'İşlemler': 'Actions',
  'Siz': 'You',
  'Aktif': 'Active',
  'Pasif': 'Inactive',
  'Aktifleştir': 'Activate',
  'Pasife Al': 'Deactivate',
  'Kullanıcıyı Sil': 'Delete User',

  // === Sistem Ayarları, Test Kısıtlama & Kapasite (Settings.jsx, RestrictionManager.jsx, CapacitySettings.jsx) ===
  'Test Kısıtlama ve Uygunluk Takvimi': 'Test Restriction & Availability Calendar',
  'Bir test belirli bir tarihe kadar yapılamıyorsa kaydedin; Gün 0 bu aralığa denk gelen çalışmalar otomatik olarak kısıtlama bitişinden sonraki ilk iş gününe ötelenir.':
    'Record when a test cannot be performed until a specific date; studies whose Day 0 falls within this period are automatically shifted to the first business day after the restriction ends.',
  'Test': 'Test',
  'Kısıtlama başlangıcı': 'Restriction Start',
  'Şu tarihe kadar yapılamaz': 'Restricted Until',
  'Sebep': 'Reason',
  'Ekle': 'Add',
  'Tanımlı test kısıtlaması yok.': 'No active test restrictions defined.',
  'Kısıtlı aralık': 'Restricted Period',
  'Şu an kısıtlı': 'Currently Restricted',
  'Planlı kısıtlama': 'Scheduled Restriction',
  'Süresi doldu': 'Expired',
  'Sil': 'Delete',
  'Tüm Testler': 'All Tests',
  'Tesiste Mevcut Hayvan Stok Bilgisi': 'Facility Available Animal Stock',
  'Hayvan Odaları Kafes Kapasitesi': 'Animal Rooms Cage Capacity',
  'Planlama Kapasitesi = Fiziksel Kafes × (1 + Dr. Anoop Esneklik % / 100)':
    'Planning Capacity = Physical Cages × (1 + Dr. Anoop Flexibility % / 100)',
  'Fiziksel kafes': 'Physical Cages',
  'Dr. Anoop esneklik oranı (%)': 'Dr. Anoop Flexibility (%)',
  'Sistem planlama kapasitesi': 'System Planning Capacity',
  'Tesiste mevcut hayvan': 'Available Animals in Facility',
  'Doluluk (−30 / +120 gün)': 'Occupancy (−30 / +120 days)',
  'Bilgi: esneklik payı kullanılıyor — çalışma engellenmedi':
    'Info: flexibility margin in use — study not blocked',
  '24–72+ Saatlik Darboğaz Cihazlar': '24–72+ Hour Bottleneck Equipment',
  'Yalnızca uzun süreli cihazlar kapasite denetimine alınır (15 dakikalık kısa cihazlar dahil değildir). Çalkalamalı Su Banyosu Polar/Apolar kapasitesi yukarıdaki “Sistem Kalibrasyonu” bölümünde yönetilir.':
    'Only long-duration bottleneck equipment is capacity-checked (short 15-min devices are excluded). Shaking Water Bath Polar/Non-Polar capacities are managed in the “System Calibration” section above.',
  'Eşzamanlı çalışma kapasitesi': 'Concurrent Study Capacity',
  'Sistem Kalibrasyonu (Canlı Veritabanı)': 'System Calibration (Live Database)',
  'Standart görev süreleri, biyolojik toleranslar ve Çalkalamalı Su Banyosu (EQ-WB-001) Polar/Apolar kapasiteleri doğrudan SQLite veritabanından okunur ve zamanlama motorunu (scheduling_engine.py) besler.':
    'Standard task durations, biological tolerances, and Shaking Water Bath (EQ-WB-001) Polar/Non-Polar capacities are read directly from the SQLite database to drive the scheduling engine.',
  'Canlı Veritabanı Bağlantısı Aktif (`/api/v1/planning/calibration`):':
    'Live Database Connection Active (`/api/v1/planning/calibration`):',
  'Elektronik İmza ve Değişiklik Gerekçesi (JWT & GLP AuditLog)':
    'Electronic Signature & Reason for Change (JWT & GLP AuditLog)',
  'Düzenleme açık': 'Editing enabled',
  'GLP Değişiklik Gerekçesi (Kaydet butonlarını aktif etmek için zorunludur)':
    'GLP Reason for Change (Required to enable Save buttons)',
  'Çalkalamalı Su Banyosu 1 (EQ-WB-001) Kapasite Kalibrasyonu':
    'Shaking Water Bath 1 (EQ-WB-001) Capacity Calibration',
  'Polar Ekstraksiyon Kapasitesi (Max Çalışma)': 'Polar Extraction Capacity (Max Studies)',
  'Apolar (Non-Polar) Kapasitesi (Max Çalışma)': 'Non-Polar Extraction Capacity (Max Studies)',
  'Şablon Görev Süreleri ve Biyolojik Toleranslar': 'Template Task Durations & Biological Tolerances',
  'Şablon Filtresi': 'Template Filter',
  'Süre (dk)': 'Duration (min)',
  'Tolerans (±dk)': 'Tolerance (±min)',
  'Tolerans dışına çıkılamaz, saat kaydırılamaz': 'Cannot exceed tolerance; time cannot be shifted',
  'Sistem Kalibrasyonu Değişiklik Geçmişi (Veritabanı AuditLog)':
    'System Calibration Change History (Database AuditLog)',
  'Veritabanında henüz kalibrasyon değişikliği kaydı bulunmuyor.':
    'No calibration change records found in the database yet.',

  // === Hayvan Odaları ve Cihaz Adları ===
  'Tavşan Odası': 'Rabbit Room',
  'Rat Odası': 'Rat Room',
  'Kobay Odası': 'Guinea Pig Room',
  'Fare Odası': 'Mouse Room',
  'Çalkalamalı Su Banyosu 1': 'Shaking Water Bath 1',
  'CO2 İnkübatör (Sitotoksisite 24–72s)': 'CO2 Incubator (Cytotoxicity 24–72h)',
  'Etüv / İnkübatör (37°C Uzun Süreli Ekstraksiyon)': 'Oven / Incubator (37°C Long-Term Extraction)',

  // === Tüm 12 Test Şablonu Başlık, Açıklama, Tür ve Biyolojik Adım Adları (templates.py & DB) ===
  'İntrakütanöz Reaktivite Testi': 'Intracutaneous Reactivity Test',
  'İntrakütanöz Reaktivite Testi (ISO 10993-23)': 'Intracutaneous Reactivity Test (ISO 10993-23)',
  'Polar ve non-polar ekstraktların intradermal uygulaması; 24/48/72. saat gözlem ve skorlama.':
    'Intradermal application of polar and non-polar extracts; 24/48/72h observation and scoring.',
  'Tavşan (NZW) — 3 hayvan / 3 kafes': 'Rabbit (NZW) — 3 animals / 3 cages',
  'Veteriner Muayenesi ve Aklimatizasyona Alma': 'Veterinary Examination & Acclimatization Start',
  '72 Saatlik Ekstraksiyon Kurulumu': '72-Hour Extraction Setup',
  'Tüy Kesimi, İntradermal Uygulama (Polar/Non-Polar) ve 1. Saat Gözlemi':
    'Fur Clipping, Intradermal Injection (Polar/Non-Polar) & 1h Observation',
  '24. Saat Gözlemi ve Skorlama': '24-Hour Observation & Scoring',
  '48. Saat Gözlemi ve Skorlama': '48-Hour Observation & Scoring',
  '72. Saat Gözlemi, Skorlama ve Ötenazi': '72-Hour Observation, Scoring & Euthanasia',

  'In Vitro Sitotoksisite Testi': 'In Vitro Cytotoxicity Test',
  'In Vitro Sitotoksisite Testi (ISO 10993-5)': 'In Vitro Cytotoxicity Test (ISO 10993-5)',
  'L929 memeli fibroblast hücre hattı üzerinde ekstrakt yöntemiyle in vitro sitotoksisite ve MTT canlılık analizi.':
    'In vitro cytotoxicity and MTT cell viability analysis on L929 mammalian fibroblast cell line via extract method.',
  'Hayvan yok — L929 hücre hattı (0 kafes)': 'No animals — L929 cell line (0 cages)',
  'L929 Hücre Kültürü Pasajlama ve 96 Kuyucuklu Plak Ekimi': 'L929 Cell Culture Subculturing & 96-Well Plate Seeding',
  'Ekstraksiyon Kurulumu (ISO 10993-12 Kültür Besiyeri)': 'Extraction Setup (ISO 10993-12 Culture Medium)',
  'Hücrelere Ekstrakt Dozlaması ve CO2 İnkübatörüne Alma': 'Extract Dosing on Cells & CO2 Incubation',
  '24. Saat Mikroskobik Morfoloji Değerlendirmesi ve MTT Spektrofotometrik Okuma':
    '24-Hour Microscopic Morphology Evaluation & MTT Spectrophotometric Reading',

  'Sensitizasyon Testi (GPMT)': 'Sensitization Test (GPMT)',
  'Gecikmiş Tip Aşırı Duyarlılık / Sensitizasyon (ISO 10993-10 GPMT)':
    'Delayed-Type Hypersensitivity / Sensitization (ISO 10993-10 GPMT)',
  'Kobay maksimizasyon testi (GPMT) ile intradermal/topikal indüksiyon, challenge ve 24/48s duyarlılık skorlaması.':
    'Guinea Pig Maximization Test (GPMT) with intradermal/topical induction, challenge, and 24/48h sensitization scoring.',
  'Kobay (Guinea pig) — 15 hayvan (max 30) / 3–5 kafes': 'Guinea pig — 15 animals (max 30) / 3–5 cages',
  'Veteriner Muayenesi ve Aklimatizasyona Alma (Kobay)': 'Veterinary Examination & Acclimatization Start (Guinea Pig)',
  'İndüksiyon Fazı (İntradermal / Topikal Uygulama)': 'Induction Phase (Intradermal / Topical Application)',
  '24. Saat Eritem ve Ödem Skorlama Gözlemi (Magnusson-Kligman)':
    '24-Hour Erythema & Edema Scoring Observation (Magnusson-Kligman)',
  '48. Saat Duyarlılık Gözlemi, Skorlama ve Çalışma Sonlandırma':
    '48-Hour Sensitization Observation, Scoring & Study Termination',

  'Akut Sistemik Toksisite Testi': 'Acute Systemic Toxicity Test',
  'Akut Sistemik Toksisite Testi (ISO 10993-11)': 'Acute Systemic Toxicity Test (ISO 10993-11)',
  'Polar ve apolar ekstraktların sistemik (IV/IP) uygulanması; 4/24/48/72. saat klinik toksisite, tartım ve nekropsi.':
    'Systemic (IV/IP) administration of polar and non-polar extracts; 4/24/48/72h clinical toxicity, body weight, and necropsy.',
  'Kemirgen (Fare / Rat) — 20 hayvan (4 kohort) / 2–4 kafes': 'Rodent (Mouse / Rat) — 20 animals (4 cohorts) / 2–4 cages',
  'Sistemik Dozlama (IV / IP Uygulama) ve 4. Saat Klinik Gözlem':
    'Systemic Dosing (IV / IP Administration) & 4h Clinical Observation',
  '24. Saat Klinik Toksisite ve Vücut Ağırlığı Gözlemi': '24-Hour Clinical Toxicity & Body Weight Observation',
  '48. Saat Klinik Toksisite Gözlemi': '48-Hour Clinical Toxicity Observation',
  '72. Saat Gözlemi, Tartım ve Nekropsi / Terminasyon': '72-Hour Observation, Weighing & Necropsy / Termination',

  'İmplantasyon Testi (Deri Altı / Subkutan)': 'Implantation Test (Subcutaneous)',
  'Subkutan İmplantasyon Testi (ISO 10993-6)': 'Subcutaneous Implantation Test (ISO 10993-6)',
  'Yeni Zelanda tavşanlarında deri altı (subkutan) implantasyon; 24/48/72. saat ve haftalık klinik gözlem, 28. gün terminasyon, nekropsi ve implant bölgesi makroskopik/histopatolojik numune alımı.':
    'Subcutaneous implantation in New Zealand White rabbits; 24/48/72h and weekly clinical observation, Day 28 termination, necropsy, and implant site macroscopic/histopathological sampling.',
  'Tavşan (NZW) / Rat — 3 kafes (4 hafta)': 'Rabbit (NZW) / Rat — 3 cages (4 weeks)',
  'Veteriner Muayenesi ve Aklimatizasyona Alma (Tavşan)': 'Veterinary Examination & Acclimatization Start (Rabbit)',
  'Test Maddesi Hazırlığı, Sterilite Kontrolü ve İmplant Alanı Hazırlığı':
    'Test Item Preparation, Sterility Check & Implant Site Preparation',
  'Tüy Kesimi, Deri Altı İmplantasyon ve 1. Saat Klinik Gözlem':
    'Fur Clipping, Subcutaneous Implantation & 1h Clinical Observation',
  '24. Saat Klinik Gözlem ve İmplant Bölgesi Skorlaması': '24-Hour Clinical Observation & Implant Site Scoring',
  '48. Saat Klinik Gözlem ve İmplant Bölgesi Skorlaması': '48-Hour Clinical Observation & Implant Site Scoring',
  '72. Saat Klinik Gözlem ve İmplant Bölgesi Skorlaması': '72-Hour Clinical Observation & Implant Site Scoring',
  '7. Gün Haftalık Klinik Gözlem ve Vücut Ağırlığı': 'Day 7 Weekly Clinical Observation & Body Weight',
  '14. Gün Haftalık Klinik Gözlem ve Vücut Ağırlığı': 'Day 14 Weekly Clinical Observation & Body Weight',
  '21. Gün Haftalık Klinik Gözlem ve Vücut Ağırlığı': 'Day 21 Weekly Clinical Observation & Body Weight',
  '28. Gün Son Gözlem, Terminal Tartım, Ötenazi, Nekropsi ve Histopatoloji Numune Alımı':
    'Day 28 Final Observation, Terminal Weighing, Euthanasia, Necropsy & Histopathology Sampling',

  'Pirojenite Testi (Tavşan Pirojen Testi)': 'Pyrogenicity Test (Rabbit Pyrogen Test)',
  'Malzeme Kaynaklı Pirojenite Testi (ISO 10993-11 / USP <151>)':
    'Material-Mediated Pyrogenicity Test (ISO 10993-11 / USP <151>)',
  'Yeni Zelanda tavşanlarında polar ekstraktın intravenöz uygulanması; bazal ve 1/2/3. saat rektal vücut sıcaklığı takibi.':
    'Intravenous administration of polar extract in New Zealand White rabbits; basal and 1/2/3h rectal body temperature monitoring.',
  'Tavşan (NZW) — 5 hayvan / 5 kafes': 'Rabbit (NZW) — 5 animals / 5 cages',
  'Pirojensiz Cam Malzeme ve Ekstraksiyon Kurulumu': 'Depyrogenated Glassware & Extraction Setup',
  'Bazal Rektal Sıcaklık Ölçümü, IV Uygulama ve 1–3. Saat Pirojen Takibi':
    'Basal Rectal Temperature Measurement, IV Administration & 1–3h Pyrogen Monitoring',
  '24. Saat Klinik Gözlem ve Çalışma Sonlandırma': '24-Hour Clinical Observation & Study Termination',

  'Hemolitik Etki (Hemoliz) Testi': 'Hemolytic Effect (Hemolysis) Test',
  'Hemoliz Testi — Kan Uyumluluğu (ISO 10993-4)': 'Hemolysis Test — Hemocompatibility (ISO 10993-4)',
  'Tavşan kanı ile doğrudan ve ekstrakt teması yöntemiyle in vitro / ex vivo hemoliz indeksi ve spektrofotometrik hemoglobin tayini.':
    'In vitro / ex vivo hemolysis index and spectrophotometric hemoglobin determination using rabbit blood via direct and extract contact.',
  'Tavşan (Donör Kan) — 3 hayvan / 1 kafes': 'Rabbit (Donor Blood) — 3 animals / 1 cage',
  'Donör Tavşan Veteriner Kontrolü ve Ekstraksiyon Hazırlığı': 'Donor Rabbit Veterinary Check & Extraction Preparation',
  'Tavşan Kanı Alımı, İnkübasyon ve Spektrofotometrik Hemoliz İndeksi Okuması':
    'Rabbit Blood Collection, Incubation & Spectrophotometric Hemolysis Index Reading',

  'Subakut Sistemik Toksisite Testi (14 / 28 Gün)': 'Subacute Systemic Toxicity Test (14 / 28 Days)',
  'Subakut Sistemik Toksisite Testi — 14/28 Gün (ISO 10993-11)':
    'Subacute Systemic Toxicity Test — 14/28 Days (ISO 10993-11)',
  'Kemirgenlerde (Fare/Rat) tekrarlanan dozlama/uygulama sonrası günlük klinik gözlem, haftalık tartım, hematoloji/biyokimya ve tam nekropsi/histopatoloji.':
    'Daily clinical observation, weekly weighing, hematology/biochemistry, and full necropsy/histopathology following repeated dosing in rodents (Mouse/Rat).',
  'Rat / Fare — 40 hayvan (4 kohort) / 4 kafes': 'Rat / Mouse — 40 animals (4 cohorts) / 4 cages',
  'Veteriner Muayenesi ve Aklimatizasyona Alma (Fare / Rat)':
    'Veterinary Examination & Acclimatization Start (Mouse / Rat)',
  'Ekstraksiyon Kurulumu ve Doz Hazırlığı': 'Extraction Setup & Dose Preparation',
  'Subakut Sistemik Dozlama Başlangıcı ve Klinik Gözlem': 'Subacute Systemic Dosing Start & Clinical Observation',
  'Terminal Kan Alımı, Ötenazi, Tam Nekropsi ve Histopatoloji':
    'Terminal Blood Collection, Euthanasia, Full Necropsy & Histopathology',

  'Subkronik Sistemik Toksisite Testi (90 Gün)': 'Subchronic Systemic Toxicity Test (90 Days)',
  'Subkronik Sistemik Toksisite Testi — 90 Gün (ISO 10993-11)':
    'Subchronic Systemic Toxicity Test — 90 Days (ISO 10993-11)',
  'Rat/Farelerde 90 günlük subkronik sistemik maruziyet, haftalık klinik ve tartım takibi, hematoloji, klinik biyokimya ve tam nekropsi/histopatoloji.':
    '90-day subchronic systemic exposure in Rats/Mice, weekly clinical and weight monitoring, hematology, clinical biochemistry, and full necropsy/histopathology.',
  'Rat / Fare — 80 hayvan (4 kohort) / 8 kafes': 'Rat / Mouse — 80 animals (4 cohorts) / 8 cages',
  'Veteriner Muayenesi ve Aklimatizasyona Alma (Rat / Fare)':
    'Veterinary Examination & Acclimatization Start (Rat / Mouse)',
  'Test Maddesi / Ekstrakt Hazırlığı': 'Test Item / Extract Preparation',
  'Subkronik Uygulama Başlangıcı ve 1. Gün Gözlemi': 'Subchronic Administration Start & Day 1 Observation',
  '4. Hafta Ara Klinik Gözlem ve Vücut Ağırlığı': 'Week 4 Interim Clinical Observation & Body Weight',
  '8. Hafta Ara Klinik Gözlem ve Vücut Ağırlığı': 'Week 8 Interim Clinical Observation & Body Weight',
  '90. Gün Terminal Kan Alımı, Ötenazi, Nekropsi ve Organ Ağırlıkları':
    'Day 90 Terminal Blood Collection, Euthanasia, Necropsi & Organ Weights',

  'İmplantasyon Testi (3 Ay / 13 Hafta)': 'Implantation Test (3 Months / 13 Weeks)',
  'Subkutan / Kemik İmplantasyon Testi — 13 Hafta (ISO 10993-6)':
    'Subcutaneous / Bone Implantation Test — 13 Weeks (ISO 10993-6)',
  '13 haftalık (90–100 gün) subkutan/kas içi implantasyon; klinik gözlem, terminal nekropsi ve histopatolojik lokal doku reaksiyonu değerlendirmesi.':
    '13-week (90–100 days) subcutaneous/intramuscular implantation; clinical observation, terminal necropsy, and histopathological local tissue reaction evaluation.',
  'Tavşan / Rat — 10 hayvan (3 ay / 13 hafta) / 4 kafes': 'Rabbit / Rat — 10 animals (3 months / 13 weeks) / 4 cages',
  'Test Maddesi ve İmplant Alanı Hazırlığı': 'Test Item & Implant Site Preparation',
  'Cerrahi İmplantasyon ve 1. Saat Klinik Gözlem': 'Surgical Implantation & 1h Clinical Observation',
  '24. Saat İmplant Bölgesi Gözlemi': '24-Hour Implant Site Observation',
  '4. Hafta Klinik Gözlem ve Vücut Ağırlığı': 'Week 4 Clinical Observation & Body Weight',
  '8. Hafta Klinik Gözlem ve Vücut Ağırlığı': 'Week 8 Clinical Observation & Body Weight',
  '13. Hafta Terminal Gözlem, Ötenazi, Nekropsi ve Histopatoloji':
    'Week 13 Terminal Observation, Euthanasia, Necropsy & Histopathology',

  'İmplantasyon Testi (6 Ay / 26 Hafta)': 'Implantation Test (6 Months / 26 Weeks)',
  'Subkutan / Kemik İmplantasyon Testi — 26 Hafta / 6 Ay (ISO 10993-6)':
    'Subcutaneous / Bone Implantation Test — 26 Weeks / 6 Months (ISO 10993-6)',
  '26 haftalık (180–200 gün) uzun süreli implantasyon; periyodik klinik gözlem, terminal nekropsi ve histopatolojik lokal doku değerlendirmesi.':
    '26-week (180–200 days) long-term implantation; periodic clinical observation, terminal necropsy, and histopathological local tissue evaluation.',
  'Tavşan / Rat — 10 hayvan (6 ay / 26 hafta) / 4 kafes': 'Rabbit / Rat — 10 animals (6 months / 26 weeks) / 4 cages',
  '17. Hafta Klinik Gözlem ve Vücut Ağırlığı': 'Week 17 Clinical Observation & Body Weight',
  '26. Hafta Terminal Gözlem, Ötenazi, Nekropsi ve Histopatoloji':
    'Week 26 Terminal Observation, Euthanasia, Necropsy & Histopathology',

  'Fiziksel-Kimyasal Monogram Testler (Non-GLP)': 'Physicochemical Monograph Tests (Non-GLP)',
  'Fiziksel / Kimyasal Karakterizasyon & Monograf Analizi':
    'Physical / Chemical Characterization & Monograph Analysis',
  'Farmakope (EP/USP) monografına uygun fiziksel-kimyasal analiz, safsızlık/kalıntı tayini ve raporlama (hayvan kullanılmaz).':
    'Physicochemical analysis, impurity/residue determination, and reporting per Pharmacopoeia (EP/USP) monograph (no animals used).',
  'Hayvan yok — Fiziksel-Kimyasal Analiz (0 kafes)': 'No animals — Physicochemical Analysis (0 cages)',
  'Numune Hazırlığı, Çözelti ve Standart Kurulumu': 'Sample Preparation, Solution & Standard Setup',
  'Enstrümantal / Kimyasal Monogram Analizi ve Kromatografik Okuma':
    'Instrumental / Chemical Monograph Analysis & Chromatographic Reading',
  'Veri Değerlendirme, Hesaplama ve Fiziksel-Kimyasal Raporlama':
    'Data Evaluation, Calculation & Physicochemical Reporting',

  'Aklimatizasyon': 'Acclimatization',
  'Hazırlık': 'Preparation',
  'Ekstraksiyon': 'Extraction',
  'Uygulama': 'Application',
  'Gözlem': 'Observation',
  'Gözlem / Terminasyon': 'Observation / Termination',

  // === FAZ 9.2: Çakışma Kategorizasyonu, Eksik Bilgi Rozetleri ve Yeniden Hesaplama ===
  'Gerçek Çakışmalar': 'Confirmed Conflicts',
  'Eksik Bilgi Sebebiyle Çakışmalar': 'Conflicts Due to Missing Info',
  'Başlangıç Tarihi Eksik': 'Missing Start Date',
  'Teknisyen Ataması Varsayılan': 'Default Technician Assignment',
  'TIIS PDF / Cihaz Bilgisi Eksik': 'Missing TIIS PDF / Equipment Info',
  "Eksik Bilgi: Başlangıç Tarihi Girilmedi (Excel'de Boş)":
    'Missing Info: Start Date Not Entered (Empty in Excel)',
  'Eksik Bilgi: Saha Teknisyeni Atanmadı (Varsayılan Teknisyen)':
    'Missing Info: Field Technician Not Assigned (Default Technician)',
  'Eksik Bilgi: TIIS PDF / Cihaz & Saat Teyit Edilmedi':
    'Missing Info: TIIS PDF / Equipment & Time Not Confirmed',
  'Çakışmaları Yeniden Hesapla': 'Recompute Conflicts',
  'Aktif / Bekleyen Görevler': 'Active / Pending Tasks',
  'Aktif & Bekleyen Biyolojik Kilometre Taşları (03.11.2026+)':
    'Active & Pending Biological Milestones (Nov 3, 2026+)',
  'Numune & Çalışma Takip’te Düzenle / PDF Yükle': 'Edit / Upload PDF in Sample & Study Tracking',
  'Planlama & Takvimde Aç': 'Open in Planning & Calendar',
  'Bu kategoride açık çakışma kaydı bulunmuyor.': 'No open conflict records found in this category.',

  // === FAZ 9.3: Sahada Deneyde / Rapor-QA Kırılımı, Hayvan/Sarf, Ödeme, Sözleşme & Excel İndir ===
  'Aktif / Devam Eden Çalışmalar': 'Active / Ongoing Studies',
  'Sahada Deneyde': 'In Experiment',
  'Rapor / QA Aşamasında': 'In Reporting / QA',
  'Taslak Raporu Geciken': 'Overdue Draft Report',
  'Rapor / QA Bekliyor': 'Reporting / QA Pending',
  'Deney Sürüyor': 'Experiment Active',
  '⚠️ Sarf Malzeme Bekleniyor': '⚠️ Consumables Pending',
  'Karantina (+7g)': 'Quarantine (+7d)',
  'Tekrar Kullanım (Vet/HADYEK)': 'Animal Reuse (Vet/IACUC)',
  'Sözleşme Termini Aşılıyor': 'Contract Deadline Exceeded',
  'Müşteri taahhüt tarihi': 'Customer commitment date',
  '📥 Excel (.xlsx) İndir': '📥 Export Excel (.xlsx)',
  'Sıradaki otomatik kod:': 'Next auto code:',
  'Mevcut': 'Available',
  'Mevcut (Karantina)': 'Available (Quarantine)',
  'Mevcut (Tekrar kullanım)': 'Available (Animal Reuse)',
  'Sarf malzemeler bekleniyor.': 'Consumables pending.',
  'Ön ödeme alındı': 'Advance payment received',
  'Ödeme yapılmadı.': 'Payment pending.',
  'Ödeme yapıldı.': 'Payment completed.',
  'Belirtilmedi': 'Not specified',
  'Taslak rapor teslim (bitiş + 3g + 7g karantina)': 'Draft report delivery (end + 3d + 7d quarantine)',
  'Final rapor gönderim (bitiş + 7g + 7g karantina)': 'Final report delivery (end + 7d + 7d quarantine)',
  'Standart TAT süresi': 'Standard TAT duration',
  'Karantina +7g dahil': 'Incl. +7d Quarantine',
  'gün': 'days',
  'Çapraz Kontrol Uyarılarını Göster': 'Show Cross-Check Warnings',
  'Çapraz Kontrol Uyarılarını Gizle': 'Hide Cross-Check Warnings',
  '✓ Kontrol Edildi / Kapat': '✓ Reviewed / Dismiss',
  'Çapraz kontrol detaylarını göster / gizle': 'Show / hide cross-check details',
  'Şifre Değiştir': 'Change Password',
  'Hesap şifrenizi değiştirin': 'Change your account password',
  'Mevcut Şifre': 'Current Password',
  'Yeni Şifre (En az 8 karakter)': 'New Password (Min. 8 characters)',
  'Yeni Şifre (Tekrar)': 'Confirm New Password',
  'Şifreyi Güncelle': 'Update Password',
  'Şifreniz başarıyla güncellendi.': 'Your password has been updated successfully.',
  'Mevcut şifreniz hatalı. Lütfen kontrol edip tekrar deneyin.': 'Your current password is incorrect. Please check and try again.',
  'Yeni şifre en az 8 karakter uzunluğunda olmalıdır.': 'New password must be at least 8 characters long.',
  'Yeni şifre ve şifre tekrarı eşleşmiyor.': 'New password and confirmation do not match.',
};

// Ters sözlük (EN -> TR)
export const EXACT_EN_TO_TR = Object.fromEntries(
  Object.entries(EXACT_TR_TO_EN).map(([tr, en]) => [en, tr])
);

// Dinamik kalıplar (Sayı, tarih, çalışma kodu içeren Türkçe metinleri İngilizceye çevirir)
const REGEX_PATTERNS_TR_TO_EN = [
  [
    /^(\d+)\s+taslak çalışma bekliyor \(Onaylamak için tıkla →\)$/i,
    (_, n) => `${n} draft studies pending (Click to approve →)`,
  ],
  [
    /^(\d+)\s+toplam açık çakışma$/i,
    (_, n) => `${n} total open conflicts`,
  ],
  [
    /^Bugün 0 • Takvimde toplam (\d+) planlı adım \(Takvime Git →\)$/i,
    (_, n) => `0 Today • ${n} total planned steps on calendar (Go to Calendar →)`,
  ],
  [
    /^Aktif \+ taslak (\d+) çalışmanın 72s ekstraksiyon \(G4–G7\) penceresindeki zirve eşzamanlı doluluk\.$/i,
    (_, n) => `Peak concurrent occupancy across ${n} active + draft studies in 72h extraction (D4–D7) window.`,
  ],
  [
    /^Polar \(Maks (\d+) Çalışma\)$/i,
    (_, n) => `Polar (Max ${n} Studies)`,
  ],
  [
    /^Apolar \/ Non-Polar \(Maks (\d+) Çalışma\)$/i,
    (_, n) => `Non-Polar (Max ${n} Studies)`,
  ],
  [
    /^Otomatik planlanacak\s*·\s*(\d+)\s*takvimsiz$/i,
    (_, n) => `To be auto-scheduled · ${n} unscheduled`,
  ],
  [
    /^(\d+)\s*\/\s*(\d+)\s*kayıt · Bir satıra tıklayarak sağdan açılan detay ve 11 adımlı iş akışı çekmecesini görüntüleyin\.$/i,
    (_, a, b) => `${a} / ${b} records · Click a row to open the right-side detail and 11-step workflow drawer.`,
  ],
  [
    /^(\d+)\/11 adım tamamlandı · Onay imzaları basan kişinin adı ve tarihiyle kaydedilir\.$/i,
    (_, n) => `${n}/11 steps completed · Approval signatures are recorded with signer name and date.`,
  ],
  [
    /^(\d+)\s+AÇIK GLP ÇAKIŞMASI$/i,
    (_, n) => `${n} OPEN GLP CONFLICTS`,
  ],
  [
    /^KAYITLI & TASLAK ÇALIŞMALAR \((\d+) \/ (\d+)\)$/i,
    (_, a, b) => `REGISTERED & DRAFT STUDIES (${a} / ${b})`,
  ],
  [
    /^KAYITLI & TASLAK ÇALIŞMALAR \((\d+)\)$/i,
    (_, a) => `REGISTERED & DRAFT STUDIES (${a})`,
  ],
  [
    /^Seçili:\s*(.+)$/i,
    (_, code) => `Selected: ${code}`,
  ],
  [
    /^Otomatik Sıradaki Kodu Ata \((.+)\)$/i,
    (_, code) => `Auto-Assign Next Code (${code})`,
  ],
  [
    /^(\d+)\s+PDF Okundu$/i,
    (_, n) => `${n} PDFs Parsed`,
  ],
  [
    /^(\d+)\s+Çalışma Kodu Tespit Edildi$/i,
    (_, n) => `${n} Study Codes Detected`,
  ],
  [
    /^(\d+)\s+GLP Denetim Uyarısı$/i,
    (_, n) => `${n} GLP Audit Warnings`,
  ],
  [
    /^(\d+)\s+KRİTİK$/i,
    (_, n) => `${n} CRITICAL`,
  ],
  [
    /^(\d+)\s+UYARI$/i,
    (_, n) => `${n} WARNING`,
  ],
  [
    /^(\d+)\s+kritik$/i,
    (_, n) => `${n} critical`,
  ],
  [
    /^(\d+)\s+uyarı$/i,
    (_, n) => `${n} warnings`,
  ],
  [
    /^(\d+)\s+adım$/i,
    (_, n) => `${n} steps`,
  ],
  [
    /^Gün\s+(\d+)$/i,
    (_, d) => `Day ${d}`,
  ],
  [
    /^G(\d+)$/,
    (_, d) => `D${d}`,
  ],
  [
    /^G(\d+)\s*•\s*(.+)$/,
    (_, d, rest) => `D${d} • ${rest}`,
  ],
  [
    /^(\d+)\s+sa\s+(\d+)\s+dk$/i,
    (_, h, m) => `${h} hr ${m} min`,
  ],
  [
    /^(\d+)\s+sa$/i,
    (_, h) => `${h} hr`,
  ],
  [
    /^(\d+)\s+dk$/i,
    (_, m) => `${m} min`,
  ],
  [
    /^±\s*(\d+)\s*dk$/i,
    (_, m) => `±${m} min`,
  ],
  [
    /^(\d+)\s+gün sonra$/i,
    (_, d) => `in ${d} days`,
  ],
  [
    /^(\d+)\s+saat sonra$/i,
    (_, h) => `in ${h} hr`,
  ],
  [
    /^Hedef\s+(.+)$/i,
    (_, d) => `Target ${d}`,
  ],
  [
    /^Gecikti\s*·\s*(.+)$/i,
    (_, d) => `Overdue · ${d}`,
  ],
  [
    /^OTOMATİK TARİH PLANLAMASI:\s*(.+?),\s*'(.+?)'\s*nedeniyle\s*(\d{2}\.\d{2}\.\d{4})\s*tarihine kadar kısıtlı olduğu için başlangıç tarihi otomatik olarak\s*(\d{2}\.\d{2}\.\d{4})\s*tarihine planlanmıştır\.$/i,
    (_, test, reason, untilDate, newDate) =>
      `AUTOMATIC DATE SCHEDULING: Because ${translateText(test, 'en')} is restricted until ${untilDate} due to '${reason}', the start date was automatically scheduled to ${newDate}.`,
  ],
  [
    /^Laboratuvar operasyonel durumu — (.+)$/i,
    (_, dt) => `Laboratory operational status — ${dt}`,
  ],
  [
    /^(.+)\s+bekleniyor$/i,
    (_, role) => `Awaiting ${translateText(role, 'en')}`,
  ],
  [
    /^(\d+)\s+ekran açık$/i,
    (_, n) => `${n} screens enabled`,
  ],
  [
    /^(\d+)\s+kafes$/i,
    (_, n) => `${n} cages`,
  ],
  [
    /^\((\d+)\s+kafes\)$/i,
    (_, n) => `(${n} cages)`,
  ],
  [
    /^Tepe:\s*(\d+)\s*\/\s*(\d+)\s*kafes$/i,
    (_, u, c) => `Peak: ${u} / ${c} cages`,
  ],
  [
    /^Tepe:\s*(\d+)\s*\/\s*(\d+)\s*çalışma$/i,
    (_, u, c) => `Peak: ${u} / ${c} studies`,
  ],
];

// Alt parça (phrase) değişimleri (bileşik metinler için)
const PHRASE_REPLACEMENTS_TR_TO_EN = [
  ['İntrakütanöz Reaktivite Testi', 'Intracutaneous Reactivity Test'],
  ['Subkutan İmplantasyon Testi', 'Subcutaneous Implantation Test'],
  ['Sitotoksisite Testi', 'Cytotoxicity Test'],
  ['Sensitizasyon Testi', 'Sensitization Test'],
  ['Akut Sistemik Toksisite Testi', 'Acute Systemic Toxicity Test'],
  ['Pirojenite Testi', 'Pyrogenicity Test'],
  ['Hemoliz Testi', 'Hemolysis Test'],
  ['Subakut Sistemik Toksisite', 'Subacute Systemic Toxicity'],
  ['Subkronik Sistemik Toksisite', 'Subchronic Systemic Toxicity'],
  ['In Vivo Teknisyeni', 'In Vivo Technician'],
  ['Kalite Güvence Birimi', 'Quality Assurance Unit'],
  ['Kalite Güvence Uzmanı', 'QA Specialist'],
  ['Veteriner Hekim', 'Veterinarian'],
  ['Devam ediyor', 'Ongoing'],
  ['Biyolojik Kilitli', 'Biologically Locked'],
  ['Biyolojik kilitli', 'Biologically Locked'],
  ['Tolerans: ±', 'Tolerance: ±'],
  ['Kabul edildi', 'Accepted'],
  ['Bekleniyor', 'Pending'],
  ['Atanmamış', 'Unassigned'],
  ['Çalışma Yöneticisi', 'Study Director'],
  ['Kalite Güvence', 'Quality Assurance'],
  ['Test Tesisi Yöneticisi', 'Test Facility Management'],
  ['Planlama Koordinatörü', 'Planning Coordinator'],
  ['Sistem Yöneticisi', 'System Administrator'],
  ['Üst Yönetim', 'Executive Management'],
  ['Gerekçe girin (min.', 'Enter reason (min.'],
  ['karakter)', 'chars)'],
  ['kafes', 'cages'],
  [' — filtreyi temizle', ' — clear filter'],
  [' · Gecikmiş', ' · Overdue'],
  ['ÇY:', 'SD:'],
];

let _activeLang = 'tr';

export function getActiveLang() {
  return _activeLang;
}

export function setActiveLang(lang) {
  _activeLang = lang === 'en' ? 'en' : 'tr';
}

/**
 * Verilen metni seçili dile ('tr' | 'en') çevirir.
 */
export function translateText(input, lang = _activeLang) {
  if (input === null || input === undefined) return input;
  const raw = String(input);
  if (!raw.trim()) return raw;

  const trimmed = raw.trim();
  const lead = raw.slice(0, raw.indexOf(trimmed));
  const trail = raw.slice(raw.indexOf(trimmed) + trimmed.length);

  if (lang === 'tr') {
    if (EXACT_EN_TO_TR[trimmed]) {
      return `${lead}${EXACT_EN_TO_TR[trimmed]}${trail}`;
    }
    return raw;
  }

  // lang === 'en'
  if (EXACT_TR_TO_EN[trimmed]) {
    return `${lead}${EXACT_TR_TO_EN[trimmed]}${trail}`;
  }

  for (const [regex, replacer] of REGEX_PATTERNS_TR_TO_EN) {
    const m = trimmed.match(regex);
    if (m) {
      return `${lead}${replacer(...m)}${trail}`;
    }
  }

  let out = trimmed;
  let changed = false;
  for (const [trPhrase, enPhrase] of PHRASE_REPLACEMENTS_TR_TO_EN) {
    if (out.includes(trPhrase)) {
      out = out.split(trPhrase).join(enPhrase);
      changed = true;
    }
  }
  if (changed) {
    return `${lead}${out}${trail}`;
  }

  return raw;
}
