# FAZ33 — prospektif NBA veri toplama kesitleri

FAZ32 tabanı: `bd8871f8d9c29fa69e108926f6502808e8f78b92`. Açık/taslak
PR #12, `feature/nba-command-20261104` dalı. Başlangıçta bu SHA için push ve
PR `unit-tests` / `docker-build` başarıları GitHub üzerinden doğrulandı.

## Sezon ve dinamik keşif

İki resmî NBA.com kaynağı HTTP 200 ile doğrulandı:

- https://www.nba.com/news/key-dates
- https://www.nba.com/news/2026-27-nba-regular-season-schedule

Normal sezon 20 Ekim 2026'da başlar, 11 Nisan 2027'de biter. Resmî günler
America/New_York takvimine göre işlenir: UTC kabul aralığı
`[2026-10-20T04:00:00Z, 2027-04-12T04:00:00Z)`; son ABD akşamındaki UTC
ertesi güne taşan maçlar dahil edilir. ESPN `season.year=2027` ve `type=2`
zorunludur. Genel ESPN sezon başlangıç/bitiş tarihleri hazırlık/playoff
aralığını da kapsadığından normal sezon sınırı olarak kullanılmaz. Kaynak
zamanları, HTML hash'leri ve ilgili metin kesitleri
[resmî sezon kanıtında](evidence/faz33-official-season-20261105.json) saklanır.
NBA CDN HTTP 403 döndü; CDN doğrulaması iddia edilmez.

`faz33.Runner.discover` gerçek saatin New York gününden başlayarak üç günlük
ESPN takvimini dinamik okur. Takım diziniyle ID doğrular; ID, ev/deplasman,
başlangıç ve çelişkili tekrarları denetler. Başlamış, ertelenmiş, iptal edilmiş,
saati geçersiz/TBD, başka sezon/tür veya bilinmeyen takımlı olayları reddeder.
Aynı takım ve aynı başlangıç için farklı sağlayıcı kimliği varsa bütün keşif
partisi reddedilir; ilk bulunan kaydı rastgele seçmez.

## Kesitler ve ortak bilgi sınırı

| Kesit | Planlanan an | Kayıt penceresi |
|---|---|---|
| T24H | Başlangıç − 86400 saniye | Planlanan andan sonraki en çok 300 saniye |
| T6H | Başlangıç − 21600 saniye | Aynı |
| T60M | Başlangıç − 3600 saniye | Aynı |

Erken kesit `NOT_DUE`, geçmiş pencere `MISSED_CUT` olur. Kaçırılmış kesit
sonradan eski saate yazılmaz. Kaynak toplama/hesaplama sırasında pencere
veya maç başlangıcı aşılırsa kayıt reddedilir. Saatler değiştirilmez.

Gerçek bilgi kesimi `cutoff_utc`, planlanan kesim, FAZ13 gerçek üretim zamanı,
özellik oluşturulma zamanı ve SQLite kayıt zamanı ayrı tutulur. FAZ31 özelliği
kesim anında oluşturulur. FAZ13 birkaç saniye sonra ortak donmuş kaynak kümesinin referans modeline uygun altkümesini
okuyabilir; kendi üretim damgası aynen korunur. Her iki modelin girdileri ortak
`reference_input_cutoff_utc` öncesinde gözlenmiş ve ingestion edilmiş olmalıdır.
Model SHA, takım dizini gözlem/ingestion kanıtı, kaynak URL/hash ve kaynak kimlikleri
pakette bulunur. Maç takvimi hesaplama öncesinde ve commit öncesinde tekrar
sorgulanır; kimlik/zaman/durum değişikliği reddedilir. Takvim kanıtı en çok
300 saniyelik olabilir; son kontrolün zamanı model girdisi sayılmaz.

Yeni dönem gözlemleri gerçek materyalizasyon zamanı taşır. Gerekirse gerçek
saatin bir sonraki saniyesi beklenir; eski materyalizasyon zamanı üretilmez.
Aynı sezonun son 45 günlük, zaman açısından uygun maçları kullanılır.
FAZ13 referansı, her takımın son altı doğrulanmış maçından mevcut motorla
üretilir. Altı maç yoksa `REFERENCE_MIN_6_VERIFIED_GAMES` ile tahmin reddedilir;
sezon başındaki az örneklem başka sezondan veri veya sahte ortalamayla doldurulmaz.
FAZ31 hücum/savunma, rakip formu, tempo ve ev/deplasman kapsamasını ayrı denetler.

## Atomik ve değişmez depolama

Mevcut FAZ24 tablosu maç başına tek tahmin içindir. Eski tabloyu veya geçmiş
kayıtları dönüştürmek yerine ayrı `faz33_cuts` tablosu kullanılır; anahtar
`(fixture_id, horizon)` olur. Paket tek transaction içinde şunları saklar:

- Özgün FAZ13 girdi kopyası ve FAZ13/22/23 aşama çıktıları.
- FAZ28 referans çıktısı, Monte Carlo/normal süre kapsamı ve sınırlamaları.
- FAZ31 gerçek kesim özellik paketi ve gölge model durumu.
- Ortak kaynak kesimi, model SHA, iki takvim gözlemi ve kaynak bağları.

FAZ24 aşama doğrulaması ortak bir işlev olarak tekrar kullanılır; eski insert
korumaları kaldırılmaz. FAZ13/FAZ28 katsayıları değiştirilmez. Referans ile
özelliklerin aynı kaynak özetlerini kullandığı yeniden doğrulanır. Referans ve
özellik üretim zamanları birbirine eşitmiş gibi gösterilmez.

Gölge model yoksa **`NO_MODEL_AVAILABLE`**, sayısal gölge tahmini `null` olur.
Varsa fakat özellikler yetersizse `FEATURES_UNAVAILABLE`; eğitim/erişim zamanı
uygunsuzsa `MODEL_UNAVAILABLE_AT_CUTOFF`. Araştırmaya özel FAZ32 modelleri canlı
FAZ31 yolu tarafından reddedilmeye devam eder. Kalibrasyon kurulmuş sayılmaz.

Tekrar çalıştırma önce var olan kesiti kontrol eder; yeniden hesaplamaz.
Değişik paketin eski kesitin üzerine yazılması reddedilir. UPDATE/DELETE ve
SQL INSERT OR REPLACE engelleri vardır. Aynı maçın üç kesiti üç farklı maç veya
üç bağımsız eğitim örneği sayılmaz. Varsayılan eğitim ihracı **T60M**'dir;
başka kesit açıkça seçilebilir, kesitler sessizce birleştirilmez. FAZ31 eğitimi
ayrıca yinelenen maç kimliğini reddeder.

Final sonuçlar `faz33_evaluations` tablosuna ayrı yazılır. FINAL, kimlik,
başlangıç, skorlar ve çeyrek/uzatma toplamları doğrulanır. Sonuç yeniden
alındığında eski doğrulama zamanı korunur; çelişkili final reddedilir. Tahmin
satırları değiştirilmez. Eksik/bozuk final ve henüz bitmemiş maç ayrılır.

## Gerçek çalışma — 5 Kasım 2026

| Gösterge | Sonuç |
|---|---:|
| Üç günde yaklaşan doğrulanmış karşılaşma | 18 |
| Hesaplanan kesit durumu | 54 |
| Henüz gelmemiş kesit | 52 |
| Kaçırılmış kesit | 2 |
| Kayıt penceresinde kesit | 0 |
| Yeni gerçek prospektif tahmin kesiti / farklı maç | **0 / 0** |
| Yeni doğrulanmış final çifti | **0** |
| Uygun özgün FAZ31 canlı eğitim örneği | **0** |
| Yeni geçmiş kaynak gözlemi | 13 |
| Araştırma kopyasındaki farklı tamamlanmış maç | 81 |
| Araştırma kopyasındaki toplam gözlem | 120 |

Gerçek ESPN takım takvimi ve özetleriyle 13 gözlem alındı; önceki 75 maça altı
yeni farklı maç eklendi. Bunlar sonradan alınmış tarihsel gözlemdir, canlı
tahmin değildir. Eski FAZ32 SQLite dosyası salt okunur yedekten kopyalandı;
yenileme sadece ayrı FAZ33 araştırma kopyasına yazıldı. Eski FAZ32'nin üç
retrospektif araştırma çifti canlı eğitim sayısına eklenmedi. Eğitim veya
katsayı optimizasyonu yapılmadı, yeni MAE/RMSE/Brier/log-loss üretilmedi.

İlk sonraki planlanan kesit: **2026-11-05 20:00 UTC / 23:00 Türkiye**.
Bu, sorgu anındaki ESPN takvimine bağlıdır; zamanlayıcı kurulmadı. Tek seferlik
çalıştırma gelecekte kendi başına uyanmaz ve tüm sezon kapsaması garantisi vermez.

## Sağlayıcı hataları ve veri eksikleri

ESPN takım takviminin gerçek skoru `{value, displayValue}` nesnesi olabilir.
Yeni `nba_history_contract` iki alanı karşılaştırarak ayrıştırır; eksik veya
çelişkili sayıyı doldurmaz. Takvim olayının sezon yılı ile yanıtın açık sezon
türü birlikte doğrulanır; sezon türü tahmin edilmez. Final özetindeki açık
sezon/tür, ID, zaman ve skorlar ayrıca kontrol edilir. Üretim adaptörünün
mevcut genel ayrıştırıcısı değiştirilmedi.

`HTTP_403`, `HTTP_429`, `TIMEOUT`, `NETWORK_UNAVAILABLE`,
`NETWORK_OR_PROVIDER_UNAVAILABLE`, geçersiz takvim/veri, eksik baseline ve
uygunsuz final durumları açık raporlanır. Adaptörün sınırlı deneme ve
Retry-After politikası korunur; bekleme süresi operasyon günlüğüne kaydedilir
ve sonraki süreçte de uygulanır. Dry-run da mevcut bekleme süresine uyar.
Hata/deneme sayısı eğitim örneği sayısı değildir.

Doğrulanmış sakatlık, kadro, piyasa ve toparlanma bilgisi yoktur. Paket bunları
ayrı eksik alanlar olarak işaretler; varmış gibi özellik üretilmez. Tempo
0.44 katsayılı kutu skoru tahminidir; ölçülmüş pozisyon sayısı değildir.
Gölge model hâlâ gerçek verilerle eğitilmemiştir. Kesit pencereleri için düzenli
geliştirme çalıştırması, yeterli takım/rakip kapsamı ve sağlayıcı erişimi gerekir.

## Yedek, temiz süreç ve Codex Cloud sınırı

`research_recovery` SQLite online backup, SHA-256 manifesti, 0600 erişim,
üzerine yazmama ve güvenli geri yüklemeyi tekrar kullanır. FAZ33 tabloları için
geri yüklemede paketler ve sonuçlar anlamsal olarak yeniden doğrulanır.
`faz33_restore_check` Python kaynaklarını temiz bir dizine kopyalar; izole
Python (`-I`) alt sürecinde yedeği açar. Özgün çalışma alanından modül alınmadığı
kontrol edilir. Gerçek beş veritabanı ve testte üç sentetik kesit + ayrı final
paketi bu yöntemle başarıyla doğrulandı. Eski tahmin/kanıt dosyalarının yedi
korunan hash'i değişmedi.

**Gerçek yeni Codex Cloud oturumunda geri yükleme yapılmadı.** Kullanılabilir
ortam araçları mevcut ortamı inceleyebiliyor; yeni Cloud makinesi/oturumu
oluşturamıyor. Temiz alt süreç aynı makinededir. Ortamlar arası SQLite kalıcılığı
ve harici saklama kanıtlanmış sayılmaz. Harici yedek yüklemesi yapılmadı.
Kurtarma paketi oturum dışında saklanmalı; yeni Cloud ortamında aynı kontrol
tekrar yürütülmelidir. Ön commit yedek kanıtının SHA'sı taban commit'i gösterir;
nihai commit'e bağlı paket çalışma çıktısında ayrıca oluşturulur.

```sh
# Mevcut FAZ32 veritabanını doğrudan yazma hedefi yapmayın; önce ayrı kopya alın.
python -m faz25 backup FAZ32_RESEARCH.sqlite FAZ33_HISTORY.sqlite

# Temiz geliştirme checkout'unda keşif; kesit/tahmin yazmaz.
python -m faz33 tick FAZ33_CUTS.sqlite FAZ33_HISTORY.sqlite --dry-run

# Açıkça çağrılan tek geliştirme turu; üretim zamanlayıcısı kurmaz.
python -m faz33 tick FAZ33_CUTS.sqlite FAZ33_HISTORY.sqlite
python -m faz33 report FAZ33_CUTS.sqlite --horizon T60M

# İsteğe bağlı yerel geliştirme döngüsü: 60 tur, 60 saniye aralık.
# Burada başlatılmadı; varsayılan --ticks değeri 1, üst sınır 1440.
python -m faz33 watch FAZ33_CUTS.sqlite FAZ33_HISTORY.sqlite --ticks 60 --interval 60

# Yeni oturumda paket kullanılabilir hale geldikten sonra:
python -m faz33_restore_check RECOVERY.tar.gz
```

CLI temiz kaynak commit'ini ve geliştirme dalını denetler. Uzun döngüde SHA/dal
veya çalışma ağacı değişirse kayıt reddedilir; yeni SHA ile yeniden başlatmak gerekir.

Geliştirme ortamında yaklaşık dakikada bir tick çağrısı planlanabilir; burada
cron, GitHub schedule, Fly.io veya Telegram üretim zamanlayıcısı etkinleştirilmedi.
Varsayılan tur en çok dört kesit işler; yoğun eş zamanlı program/sağlayıcı
gecikmesinde pencere kaçabilir. Kaçırılan kesit raporlanır, geçmişe yazılmaz.

## Test sonucu ve kanıtlar

**673 regresyon testi başarılı**, 32.491 saniye; 27 yeni FAZ33 testi.
Sentetik saat simülasyonu üç kesit → tek maç → ayrı final → tek seçili eğitim
örneği zincirini doğrular; bu sonuçlar gerçek performans değildir. İsteğe bağlı
sınırlı geliştirme döngüsünün otomatik tekrar edip durması ve kaynak SHA
değişikliğinde kayıt reddi de test edilir. Ağ biçimleri,
403/429 ve kalıcı bekleme, timeout/kesinti, atomik rollback, saat/sezon/kimlik
retleri, veri sızıntısı, kaynak bağları, SQL değişmezliği, idempotency, dry-run
ve temiz süreçte geri yükleme kapsanır. Compileall ve diff denetimi ayrıca
çalıştırılır. Docker başarısı yalnızca nihai GitHub CI sonucuyla raporlanır.

- [Gerçek dinamik takvim ve kaynak zamanları](evidence/faz33-real-discovery-20261105.json)
- [Gerçek geçmiş yenilemesi](evidence/faz33-real-history-refresh-20261105.json)
- [Prospektif sayı ve test raporu](evidence/faz33-real-status-20261105.json)
- [Eski dosya hash koruması](evidence/faz33-original-preservation-20261105.json)
- [Temiz süreç geri yükleme kanıtı](evidence/faz33-clean-restore-20261105.json)
