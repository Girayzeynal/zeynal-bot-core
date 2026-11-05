# FAZ39: pencere öncesi hazırlık ve korumalı kayıt

PR #14 için güncel gecikme ölçümleri, schema v2 taşınabilir receipt ve kurtarma
kuralları: [inceleme düzeltmeleri](faz39-pr14-review.md).

FAZ38'de ilk saat kontrolü 2026-11-05 20:04:44 UTC, çalıştırma kapısı
20:05:12.151697 UTC idi. 20:00–20:05 kesiti kaçırıldı; gerçek tahmin sayısı
sıfırdı. Koruma doğru biçimde yazmayı reddetti, ancak uzak kontrollerin
pencere içinde yapılması zamanında kayıt hedefini engelledi.

FAZ39, `feature/faz39-time-guarded-prospective` dalında ayrı bir geliştirme
giriş noktasıdır. FAZ13/22/23/28 katsayıları, FAZ24 kayıtları ve FAZ29–38
kanıtları değiştirilmez. Zamanlayıcı kurulmaz, üretim dağıtımı yapılmaz.

## İki aşamalı çalışma

1. `prepare`, kesitten önceki 120 saniye içinde çalıştırılır. Temiz yerel
   commit ve FAZ39 geliştirme dalı; GitHub uzak dal SHA'sı; aynı SHA'nın
   en yeni Python workflow push çalıştırması ve başarılı `unit-tests` /
   `docker-build` işleri zorunludur. Bekleyen, başarısız, atlanmış veya başka
   SHA'ya ait CI reddedilir. Başarılı önceki bir çalıştırmaya geri düşülmez.
2. ESPN özeti, takım kimlikleri ve NBA resmî maç sayfasındaki ev/deplasman,
   normal sezon, maç durumu ve UTC başlangıcı eşleşmelidir. NBA verisi yoksa,
   resmî sayfa HTTP 200 dönse bile hazırlık reddedilir. HTTP 403/429, zaman aşımı
   ve bağlantı hatası açık hata durumlarıdır; erişim engeli aşılmaz.
3. Mevcut FAZ33 geçmiş veri içe aktarıcısı kullanılır. Kaynak gözlem ve ingestion
   zamanları ayrı korunur; iki takım için de en az altı doğrulanmış ve pace
   kanıtı bulunan geçmiş maç gerekir. Aynı maçın tekrarları, hash çelişkisi,
   gelecekteki ingestion ve 45 günlük pencere dışındaki veriler reddedilir.
   Yeterli geçmiş veriyi daha önce toplamak hazırlık gecikmesi riskini azaltır.
4. HTTPS üzerinden `timeapi.io` UTC yanıtı zorunludur. Yanıt gövdesi, adresi,
   SHA-256'sı, istek/gözlem zamanları ve monotonik istek süresi saklanır.
   İstek süresi veya yerel saat farkı iki saniyeyi aşarsa kayıt yetkisi verilmez.
   Bu, kriptografik zaman damgası hizmeti değildir; kaynak/yerel ortam güveni
   hâlâ gereklidir. Önbellekten eski bir saat yanıtı kabul edilmez.
5. Hazırlık, kesitten en az beş saniye önce bitmelidir. Kaynak yanıtları,
   CI bilgisi, model SHA'sı, konfigürasyon hash'i ve dondurulmuş tarihsel
   gözlemler `faz39_ready` tablosuna tek işlemle eklenir. Kayıt SHA-256 ile
   adreslenir. UPDATE, DELETE ve REPLACE SQL tetikleyicileriyle yasaktır.
6. `arm`, hazır kayıt hash'iyle **pencere açılmadan** başlatılır. Yerel SHA,
   kaynak kanıtları ve yeni bağımsız UTC yanıtı pencere öncesinde doğrulanır.
   Süreç ön planda, en fazla 120 saniyelik planlı beklemeyle çalışır; sonra
   konservatif UTC belirsizliği için birkaç saniye daha gerekebilir.
   Pencere açılınca uzaktan SHA/CI/schedule kontrolü veya geçmiş veri indirmesi
   yapılmaz. Yalnızca bellekteki doğrulanmış ve dondurulmuş veriler kullanılır.
7. UTC/monotonik saat sapması, ileri/geri saat sıçraması, yerel SHA/kod değişimi,
   300 saniyeden eski kanıt veya pencere aşımı yazmayı reddeder. İki saniyelik
   UTC belirsizliği ve ölçülen ağ süresi pencere sınırlarında konservatif
   kullanılır; belirsiz erken/geç sınırda tahmin üretilmez. Yerel SHA kontrolü
   gecikirse saat **kontrol bittikten sonra tekrar** okunur.
8. Mevcut FAZ33 üretimi `refresh=False` ile çağrılır. FAZ13/22/23, FAZ28
   simülasyonu ve FAZ31 `NO_MODEL_AVAILABLE` durumu aynı paket içindedir.
   Hazır kayıt ve `arm` UTC kanıtı tahmin paketine hash ile bağlanır.
   SQLite `BEGIN IMMEDIATE`, son INSERT öncesi saat kapısı ve mevcut değişmez
   kayıt tetikleyicileri korunur. FAZ39 bağlantısına özel TEMP tetikleyici,
   SQL parametreleri serileştirildikten sonra SQLite içinde saati tekrar denetler.
   Kaydedilen saniye güncel değilse de yazmayı reddeder; eski tablo şeması veya
   kayıtları değişmez. İşlem sırasında süre dolarsa maç kimliği
   kaydı dahil işlem geri alınır.
9. Aynı veritabanı için mevcut dosya kilidi kullanılır. SQLite benzersiz
   `(fixture_id,horizon)` anahtarı ve takım/başlangıç çakışması denetimi ikinci
   kaydı engeller. Tekrar çağrı mevcut kaydı değiştirmeden `ALREADY_RECORDED`
   döndürür. `audit`, özgün kayıt anındaki kanıtları salt okunur yeniden doğrular.

## Geliştirme kullanımı

Önce yeni bir FAZ39 veritabanı hedefi ve erişilebilir geçmiş veri deposu için
`config/faz39-local.example.json` kopyasını düzenleyin. Üst dizinleri önceden
oluşturun. Eski FAZ24 veritabanlarını bu konfigürasyona taşımayın veya üzerine
yazmayın. Kod commit edilip bu yeni dalın CI kontrolleri başarılı olmadan
gerçek hazırlık çalıştırılamaz.

```sh
python -m faz39 prepare /absolute/pilot-config.json ESPN_ID --horizon T6H
python -m faz39 arm /absolute/pilot-config.json --receipt-sha256 READY_SHA256
python -m faz39 audit /absolute/prospective.sqlite
```

`arm` çağrısını kesitten en az beş saniye önce yapın; hazırlık tamamlanınca
hemen başlatılması tercih edilir. Pencere içinde ilk kez başlatılan `arm`,
20:04:44 olsa bile uzak kontrollere başlamaz ve yazma yetkisi vermez.
Kesinti sonrası geç kalmış bir süreç yeniden yetkilendirilmez. Kaçırılmış
FAZ38 T−6 kaydı bu mekanizmayla geri doldurulamaz.

## Doğrulama ve sınırlar

- `tests/test_faz39.py`: sentetik saatli tam akış, atomik kayıt, hash bağlama,
  idempotency, iki işçinin aynı kilit için yarışması, SQLite yazıcı kilidi,
  işlem kesilmesi, sınırı geçen doğrulama ve FAZ38 20:04:44→20:05:12 regresyonu.
  Başarılı örnekler yalnızca `SYNTHETIC_TEST` veritabanındadır; gerçek tahmin
  sayısı veya gerçek model doğruluğu olarak raporlanmaz.
- Başarılı CI ve resmî takvim **hazırlık anının** kanıtlarıdır. Sonraki bir
  sağlayıcı değişikliği, ağ çağrısı yapılmadan bilinemez. Kanıtların 300 saniyelik
  son kullanma süresi pencereyi daha da daraltabilir. Her beş dakikanın tamamında
  kayıt yetkisi verilmesi garanti edilmez.
- Ücretsiz GitHub API limitleri, timeapi.io/NBA/ESPN erişimi ve hazırlık süresi
  engel olabilir. Hiçbir kaynak hatası varsayılan veya uydurma veriyle aşılmaz.
- Yerel dosya kilidi tek dosya sistemi kapsamındadır; dağıtık kilit değildir.
  Harici kalıcı depolama, ayrı Cloud runtime kurtarması ve zamanında süreç
  başlatma hâlâ operasyonel gereksinimlerdir. Bunlar bu değişiklikle hazır olmaz.
- Hazır verinin SHA-256'sı yerel bütünlük sağlar; dışarıdan imzalı zaman kanıtı
  veya yetkisiz bir işletim sistemi yöneticisine karşı güvence değildir.
- Yeterli gerçek prospektif sonuç birikmedi; performans/kalibrasyon üstünlüğü
  veya üretime hazır olma iddiası yoktur. Canlı zamanlayıcı etkinleştirilmez.
