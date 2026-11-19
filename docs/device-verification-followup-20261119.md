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

## Uygulanan devam ve kullanım

`hybrid_engine/device_verification.py` mevcut `quality_report.report()` ve
`comparison_summary()` çıktısını tekrar kullanır. Yeni tahmin motoru veya
ikinci settlement yolu yoktur. `--verification-review` launcher'da poller
kilidi, Git güncellemesi ve token kontrolünden önce çalışır:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --verification-review
```

Komut yalnız bu PR dalının kodu cihazda mevcutsa kullanılabilir. Botu
yeniden başlatmaz, Telegram mesajı göndermez, kaynak sorgulamaz. Terminal
çıktısı `nba.quality_groups`, aynı maçlardaki `nba.comparison`, kaynak/girdi
kanıt sayısı ve `telegram` teslim özeti içerir. Ham sohbet/bot/message/update
kimlikleri, komut metni, token, URL ve kişisel dosya yolları dışa aktarılmaz.
Native SQLite bulunmazsa oluşturulmaz; eksik input asset'leri sahte sıfır
hata veya tam kaynak doğrulaması sayılmaz. Bekleyenler başlamış/başlamamış
olarak ayrı kalır; başarı paydasına eklenmez.

`telegram_evidence` çıktısı artık `TELEGRAM_LAYERED_EVIDENCE_V2_HASH_BOUND`:
aynı yetkili sohbet ve doğrulanmış bot için `/start`, `/nba`, `/analyze`,
`/accuracy`, `/compare` gereklidir. Komut SHA'sı, analysis sidecar SHA'sı,
API isteğinin metin SHA'sı, update/message kimliği, parça sıra/sayısı ve
server/ack saatleri bağlanır. Çelişen update/message kayıtları reddedilir;
aynı delivery tekrarı sayıyı artırmaz. Yeni gelen olaylara bot kimliği ve
komut SHA'sı eklenir, eski günlükler geriye dönük doldurulmaz. Eksik eski
kayıtlar tekil teslim kanıtı olabilir ama tamamlanmış takım sayılmaz.

Yerel günlük, bağımsız Telegram sunucusu imzası değildir. Teknik komut
cevabı da modelin doğru sonuç verdiğinin kanıtı değildir:
`application_result_correctness_verified=false` korunur. Çalışan model
kimliği için ayrıca gerçek Telegram `/test runtime` yanıtı gereklidir.
Araç her durumda otomatik terfiyi kapalı ve `NO_GO` tutar; gelecekteki
kayıtlı model karşılaştırma kapısının yerine geçmez.

## Bu Cloud ortamında gerçekten yapılanlar

- Tam yerel regresyon: **1608 test / 167.208 saniye / OK**. Son metadata
  bağlama değişiklikleri için PTB/bootstrap/kanıt testleri ayrıca koşuldu.
- Kaynak sürümü, mesaj/komut/clock çelişkisi, iki bot/sohbetten takım
  birleştirme, tekrarlı parçalar, eski eksik kanıt, fiziksel read-only SQLite,
  hash bozulması, okuma bütçesi, symlink ve offline launcher: 16 yeni test.
  Test olayları açıkça sentetiktir; dış Telegram teslimi kanıtı değildir.
- Korunmuş özgün Philadelphia–Indiana PREMATCH paketinin geçici kopyası:
  1 özgün girdi doğrulandı, aynı maça ait donmuş-model hata -33.211082 ve
  yayımlanmamış son-N referans hata -34.95 çıktı. Güncel cihazdaki 23 maç
  burada çalıştırılmış sayılmadı. Kaynak tar ve view öncesi/sonrası SQLite
  byte içeriği aynı kaldı. Hazırlıkta yalnız geçici kopyaya ESPN finali
  eşlendi; yeni inceleme aracı hiçbir sonuç işlemedi.
- Cloud'da gerçek cihaz yolu yok: `NOT_PRESENT`, Telegram `NOT_PRESENT`,
  `REVIEW_COMPLETED_WITH_GAPS`; eksik dizin oluşturulmadı.
- V1 27, V2 13, V3 9, Avrupa 6 ve NBA sampler 6 kaynak pini `8cee0a9` ile
  aynı. FAZ13, yeni/eski modeller, tahmin arşivleri, `zeynal_data`, secrets
  ve üretim değiştirilmedi. Main merge/deploy yapılmadı.
- İlk yeni testte legacy sentetik fixture'ın input/generation kanıtı var
  sanılmıştı; testin beklentisi düzeltildi. Kod bu kaydı doğru biçimde
  strict karşılaştırmaya katmıyordu. Hatalı ilk test başarı diye gösterilmedi.

Son GitHub CI durumu ve kesin ham test çıktıları PR #98'de ayrıca
paylaşılır. Gerçek UserLAnd 23-maç karşılaştırması ve gerçek Telegram E2E
**NOT_VERIFIED**; erişim olmayan kontroller tamamlanmış gösterilmedi.
