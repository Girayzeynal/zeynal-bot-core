# Issue #90 / PR #98 — cihaz doğrulamasında kalan açık

Başlangıç: `8cee0a9`, PR #98. Önceki 1592 test ve GitHub Docker/resource
kontrolleri başarılı; yeni Issue #90 yorumu yok. UserLAnd dosyaları ve özel
Telegram kimlik bilgileri bu Cloud ortamında mevcut değil. Mevcut PR #95
sonuç ingest/üç lig raporunu; #97 kulüp haber kaynaklarını yürütüyor.
Bu işler tekrar yazılmayacak.

## Kodda bulunan ek kanıt bütünlüğü sorunu

`telegram_evidence.evidence_report()` parçalı analiz cevabını yalnız
`telegram_message_id` kümesine göre tamamlanmış sayıyor. Analiz sidecar'ının
mesaj SHA'sı API isteğinin SHA'sıyla karşılaştırılmıyor. Aynı update ID'li
çelişen komutlar sözlükte sonuncuyla eziliyor; farklı sohbetlerdeki farklı
komutlar tek tam komut takımı sayılabiliyor. Bunlar hesaplama/model hatası
kanıtı değildir; teknik E2E kanıtının yanlış birleştirilmesi riskidir.

Düzeltme: gönderim/komut/hash/zaman/sıra bağını ve tek sohbet kapsamını
kontrol etmek. İleriye dönük komut günlüğüne yalnız tam komut SHA'sı eklemek;
eski olayları değiştirmemek. Eksik bağ taşıyan eski olaylar teslim kanıtı
olabilir, fakat eksiksiz analiz takımı olarak gösterilmeyecek.

## Cihazda gerekli somut devam

Mevcut native kalite raporu ve teslim günlüğünü tek salt-okunur komutta
inceleyen `--verification-review`. Veritabanı yoksa oluşturulmayacak; token,
raw mesaj/sohbet, URL veya dosya yolu dışa aktarılmayacak. Salt-okunur
SQLite transaction, kayıt/SHA/okuma sınırları ve dosya parmak izi kullanılır.
Bu araç kaynak isteği, fit, yeni PREMATCH, sonuç ingest, poller başlatma,
Git update, model terfisi veya deploy yapmayacak. `NO_GO` korunur.

Bu teşhis kod değişikliğinden önce kaydedildi. Test ve gerçek cihaz/E2E
sonuçları ayrı belirtilecek; Cloud'da çalıştırılmayan cihaz işlemleri
`NOT_VERIFIED` kalacak.
