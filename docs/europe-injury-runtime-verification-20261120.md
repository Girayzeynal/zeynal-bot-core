# EuroLeague sakatlık adaptörü — çalışma durumu ve sınırlar (20 Kasım 2026)

Bu değişiklik **sakatlık adaptörünü otomatik olarak açmaz**, abonelik veya API
anahtarı sağlamaz ve maç skorlarına sayısal etki uygulamaz. Mevcut isteğe bağlı
RotoWire EuroLeague bağlantısının gerçek durumunu, Telegram'da yanıltıcı
"bağlı değil" ifadesi olmadan gösterir.

## Uygulama yolu

- Android izole botu `hybrid_engine.test_bot` çalıştırır ve yalnız
  `ZEYNAL_ROTOWIRE_ADVISORY_ENABLED=1` **ve** geçerli
  `ZEYNAL_ROTOWIRE_API_KEY` varsa `AdvisoryClient` kurar.
- `/features` **hiçbir sağlayıcı sorgusu yapmadan** üç ayrı bilgiyi verir:
  opt-in/kimlik durumu, son gerçek HTTP/sağlayıcı durumu (varsa),
  skor/dakika modeline bağlı olmama bilgisi.
- Maç başlamadan önce arşivlenmiş uygun bir EuroLeague tahmininde
  `Kadro / Sakatlık` düğmesi ayrı bir güncel ikincil sağlayıcı sorgusu
  yapabilir. 429/erişilemez/yetersiz kimlik durumunda doğrulanmamış
  oyuncu veya sağlıklı kabulü üretilmez. Kaynak başarılı olsa bile resmî
  sezon oyuncu ID'siyle birebir eşleşmeyen satır reddedilir.
- Başlamış maçlar için geçmişe dönük sorgu yapılmaz. Tahminler,
  kalibrasyon, arşiv, disk, eski kayıtlar ve ana sayısal model değiştirilmez.

## Kurulum ve gerçek canlı kanıt

RotoWire için yasal/verilmiş erişim yoksa hiçbir API çağrısı yapılmamalıdır.
Mevcut güvenli ortam yapılandırmasıyla yetkili operatör bu iki değişkeni
**bot işleminin ortamına** aktarabilir; değerler GitHub'a,
Telegram mesajlarına veya arşive yazılmamalıdır:

- `ZEYNAL_ROTOWIRE_ADVISORY_ENABLED=1`
- `ZEYNAL_ROTOWIRE_API_KEY` = sağlayıcının verdiği geçerli özel anahtar.

Telefon üzerindeki güncel test botu yeniden başlatıldıktan sonra:

1. Telegram'da `/features` gönder; `CONFIGURED_UNVERIFIED` ancak
   gerçekten yapılandırılmışsa görünür.
2. Henüz başlamamış bir EuroLeague maçının kayıtlı analizinden
   `Kadro / Sakatlık` düğmesini aç.
3. `/features` komutunu yeniden gönder; son kaynak sonucu
   `RECEIVED`, `HTTP 429`, `KEY_INVALID` vb. açıkça görünür.
   `RECEIVED` yalnız HTTP/veri seviyesinde alımdır; maça özgü
   uygunluk ve model etkisini kanıtlamaz.
4. Gerçek Telegram teslimi, resmi oyuncu ID eşleşmesi, süreç SHA'sı
   ve kaynak erişimini cihazda ayrı ayrı doğrula.

## Üretim mimarisi

Fly.io'nun mevcut `Dockerfile` komutu `python -u main.py` çalıştırır.
Bu, `hybrid_engine.test_bot` ile kurulan ayrı
`EuropeanDataReview`/RotoWire yolunu kendi başına yüklemez. Sadece
`main` merge veya Docker CI başarısı **üretim adaptörünü çalışır hale
getirmez**. Fly.io'ya güvenli geçiş için süreç düzeni, tek Telegram poller,
secrets erişimi, snapshot/volume ve gerçek Telegram E2E doğrulanmalıdır.

## Doğrulama kapsamı

Testler gerçek API üyeliği olmadan sahte HTTP/Telegram örnekleriyle
bağlı/bağlı-değil, HTTP 429, resmi sezon oyuncu kimliği, kaynak zaman sınırı
ve hesaplamaya girmeme sözleşmesini denetler. Test başarısı canlı kaynak
bağlantısı veya doğrulanmış oyuncu etkisi demek değildir.
