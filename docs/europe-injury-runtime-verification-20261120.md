# EuroLeague sakatlık adaptörü — doğrulanmış çalışma durumu (20 Kasım 2026)

## Önemli düzeltme: RotoWire güvenlik kilidi aktif

Bu belgenin önceki sürümü, `ZEYNAL_ROTOWIRE_ADVISORY_ENABLED=1` ve
`ZEYNAL_ROTOWIRE_API_KEY` tanımlanınca test botunun RotoWire'a bağlanacağını
söylüyordu. **Bu bilgi güncel kod için yanlıştı.**

Doğrulanmış kod yolu:
- `hybrid_engine/test_bot.py` içinde `advisory_getter=None`,
  `europe_injury_advisory_setup_status='SECURITY_HOLD_ROTOWIRE'` ve
  `europe_injury_advisory_enabled=False` zorunlu olarak atanır.
- `hybrid_engine/europe_injury_advisory.py:fetch` geçerli anahtar sağlansa bile
  `INJURY_PROVIDER_SECURITY_HOLD` döndürür; HTTP isteği oluşturmaz.
- Bu nedenle **ortam değişkenlerini ayarlamak bu kaynağı açmaz**. Kullanıcıdan
  bu amaçla API anahtarı istenmemeli, anahtar GitHub'a veya Telegram'a yazılmamalıdır.
- `/features` içinde güvenlik kilidi görünmesi beklenir; RotoWire'dan
  `RECEIVED` veya `HTTP 429` sonucu beklenmemelidir.

## Gerçekten etkin olan yollar

- `/sourceplayers`: Resmî EuroLeague sezon oyuncu kimlik dizinini okur;
  bu **sakatlık, maça özgü kadro, ilk beş veya dakika doğrulaması değildir**.
- `/injurynews`: Her iki botta yalnız kamuya açık kulüp/haber kaynaklarını
  gözlemsel olarak inceleyebilir; bir indeks sayfası oyuncu yokluğu kanıtı değildir.
- `Kadro / Sakatlık` düğmesi: Mevcut kaynakları ayrı kanıt düzeylerinde
  gösterebilir; RotoWire güvenlik kilidini aşmaz.
- `ZEYNAL_PUBLIC_EURO_NEWS_ENABLED=1` sadece robots.txt denetimli anonim
  haber indekslerini etkinleştirir; kesin sakatlık durumu sağlamaz.
- `hybrid_engine/player_minutes.py` yalnız NBA için geçmiş maçlardan
  projeksiyon üretir; EuroLeague dakika/oyuncu etkisi olarak sunulmamalıdır.

## Canlı doğrulama ve üretim

- Test dalının CI başarısı telefondaki UserLAnd sürecinin yeniden başladığı
  anlamına gelmez. Telegram üzerinden süreç SHA'sı, `/features`,
  `/sourceplayers` ve `/injurynews` ayrıca doğrulanmalıdır.
- Fly.io `main.py` ile çalışır; izole `test_bot` içindeki tüm
  `EuropeanDataReview` bağlantılarının üretimde otomatik etkin olduğu
  varsayılmamalıdır.
- Resmî sezon kaydı, kaynak haberi, doğrulanmış maç kadrosu ve sayısal model
  etkisi **dört farklı kanıt düzeyidir**. Doğrulanmayan oyuncu için
  `OUT`, `AVAILABLE`, dakika veya skor etkisi uydurulmaz.
- Tahminler, kalibrasyon, arşiv, eski kayıtlar, `zeynal_data` ve mevcut
  model ağırlıkları bu dokümantasyon düzeltmesinden etkilenmez.

## RotoWire için ileride açılma şartı

Ayrı yetkili erişim, güvenli kimlik doğrulama yöntemi, gizli anahtarların
URL/log sızıntısı denetimi, kaynak zaman damgası, resmî oyuncu ID eşleşmesi
ve gerçek Telegram uçtan uca testi tamamlanmadan güvenlik kilidi kaldırılmaz.
Canlı erişim sağlansa bile geçmiş tahminlere geriye dönük oyuncu etkisi eklenmez.
