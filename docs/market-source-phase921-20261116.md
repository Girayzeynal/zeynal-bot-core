# FAZ 92.1 — kaynak bağımsız piyasa gözlemleri

PR [#89](https://github.com/Girayzeynal/zeynal-bot-core/pull/89), aynı
`feature/hybrid-market-roster-evidence-20261114` dalı.
Başlangıç: `17e31528c079e58d59e0c02dd1041770bd400fc2`.
Bu aşama onaylanan kaynak bağımsız piyasa yapısı ve güvenli araştırma gösterimidir.
Bir Nesine API bağlantısı, otomatik OCR, kalibrasyon veya bahis önerisi değildir.

## Değişiklikler

- `market_observations.py`: platforma bağlı olmayan gözlem şeması; publisher ve
  bookmaker ayrı. Mevcut ESPN/DraftKings kayıtları orijinal native receipt'e
  tekrar bağlanır. Kullanıcı ekran görüntüsü PNG/JPEG/WebP olarak SHA-256 ile
  ayrı araştırma dizinine eklenir. Fiyatlar kullanıcı tarafından aktarılır;
  **USER_TRANSCRIPTION_NOT_INDEPENDENTLY_VERIFIED** etiketi değişmez.
- Aynı kaynak görüntüsündeki alternatif baremler korunur. Her satırda dönem,
  piyasa türü, gerçek girilmiş barem ve mevcut tarafların ondalık oranları vardır.
  Eksik karşı taraf oranı üretilmez. Farklı platformların teklifleri birleştirilmez.
  Eski bir kaynak görüntüsünün sonradan değişen ana çizgisi alternatifmiş gibi
  yeniden etiketlenmez; görüntü/kayıt sınırları korunur.
- Kaynak yayın zamanı, bildirilen yakalama zamanı, gerçek yerel erişilebilirlik
  zamanı, orijinal tahmin zamanı ve değerlendirme zamanı ayrıdır. Yakalama saati
  bilinmiyorsa `null` kalır. Manuel ithalat zamanı geriye alınamaz. Aynı görüntü
  ve veri tekrar içe alınırsa ilk erişilebilirlik zamanı korunur.
- Eklemeli JSON kayıtları ve görüntü kanıtı mevcut forecast SQLite'ından ayrıdır.
  Constructor/read dizin veya tablo yaratmaz. Aynı görüntüye çelişen aktarım
  otomatik seçilmez/üzerine yazılmaz; açık çatışma hatası verir. Bu ilk sürümde
  çelişkili manuel aktarım için otomatik düzeltme/supersession akışı yoktur.
- `market_views.py`: aynı dondurulmuş model ve girdilerden örnekler tekrar
  üretilir; arşivdeki **sample SHA** ve ham skor/periyot değerleri eşleşmelidir.
  Eğitim, yeni veri çekme, forecast kaydı veya eski tahmin değişikliği yapılmaz.
  Yalnızca quantile özetinden her barem için olasılık uydurulmaz.
- Maç ve takım toplamları, 1Q–4Q, 1H/2H, ev handikapı ve normal süre kazananı
  aynı tutarlı senaryolardan türetilir. Handikapta ev marjı + ev baremi kullanılır.
  Alt/Üst/eşit skor kütlesi ayrı gösterilir; eşit skor otomatik olarak bir bahis
  platformunun iade kuralı kabul edilmez.
- Native normal süre olasılıkları, ödeme kapsamı bilinmese de **ham koşullu model
  frekansı** olarak görünür. Gerçek piyasa kazanma olasılığı, model güven endeksi
  veya öneri olarak sunulmaz. Hiçbir kaynak yoksa barem üretilmez; skor görünür kalır.
- Mevcut `RuleEvidence` ve karar koruması kaldırılmadı. Native fiyat, tam eşleşen
  ödeme kuralı ve geçerli saatler varsa kütüphane düzeyinde mevcut ham EV / iade
  dışı başa baş hesabı kullanılır. `NO_EDGE` ham sayıları gizlemez. Negatif EV veya
  yüksek ham olay olasılığı otomatik seçim oluşturmaz.
- Eski quote tahmin anında güncel olsa bile gösterim/karar anında 300 saniyeyi
  geçmişse yeni fiyat avantajı hesabına alınmaz. Sonradan gözlenen fiyat eski
  tahminin girdisi gibi gösterilmez. Maç sonrası ekran yalnızca arşiv incelemesidir.
- Manuel kaynak, bilinmeyen OT kapsamı, doğrulanmamış fiyat/ödeme kuralları ve
  desteklenmeyen Asian çeyrek baremleri gerçek EV/öneri üretmez. %0/%100 örnek
  frekansının kesinlik anlamına gelmediği belirtilir.

## Telegram bağlantısı

İzole NBA `/analyze` özetinde **Piyasa düğmesindeki gözlem/barem sayısı** belirtilir.
Düğme, mevcut native gözlemleri ve isteğe bağlı manuel gözlemleri ayrı kaynak
kayıtları halinde gösterir. Uzun bölümler Telegram'ın mevcut bölme akışını kullanır.
Piyasa dosyası, görüntü hash'i veya örnek tekrarı başarısızsa skor raporu korunur ve
`MARKET_PANEL_UNAVAILABLE` görünür; başarısızlık sessizce pozitif karara çevrilmez.

EuroLeague için eski donmuş arşiv ve mevcut `ForwardRegistry` kayıtlarına manuel
piyasa bölümü bağlanmıştır. İleri kayıtta aynı hazırlanmış artefakt, kaydedilmiş
girdi ve örnek SHA kontrol edilir. Eski arşivde ayrı ilk üretim/ilk kalıcı kayıt
kanıtı olmayan durum açıkça belirtilir; tarihsel kayıt yeni PREMATCH olmaz.
EuroCup kimliği şemada desteklenir; bu aşamada EuroCup Telegram servis bağlantısı
ve gerçek OOS kabulü tamamlandı denmez.

Bu sürüm yeni bir doğrulanmış ödeme kuralı beslemesi yapılandırmaz. Dolayısıyla
mevcut ESPN kapsamı belirsiz teklifler ve manuel Nesine ekranları için gerçek
piyasa EV'sinin hâlâ bulunmaması beklenen korumadır.

## Manuel aktarım

Yeni izole kaynak dizini, mevcut test veri kökünün altında:

`/home/userland/zeynal-test-isolated/data/market-observations`

Önce arşivdeki bir maçı kaynak kimliğine hatasız bağlamak için salt okunur lookup:

```bash
cd /home/userland/zeynal-hybrid-844
PYTHONDONTWRITEBYTECODE=1 python3 -m hybrid_engine.market_observations \
  --show-fixture \
  --ledger /home/userland/zeynal-test-isolated/data/live-nba/nba-hybrid.sqlite \
  --fixture-id 401909993
```

Bu komut yalnızca arşivdeki maç kimliğini verir; piyasa çizgisi veya tahmin üretmez.
Örnekteki maç sonradan başlamış/tamamlanmışsa lookup tarihsel kimlik kontrolüdür.

Gerçek görüntüden hazırlanacak JSON alanları:

| Alan | İçerik |
|---|---|
| `fixture` | Lookup çıktısındaki `fixture` nesnesi; başka maçın kimliği kullanılmaz |
| `bookmaker` | Görüntüde gerçekten bulunan platformun `id` ve `name` alanları |
| `source` | `provider_id`, `provider_name`, `url`, `captured_at_utc`, `published_at_utc`; bilinmeyen URL/saat `null` |
| `quotes` | Aynı görüntüdeki satırlar: `period`, `market`, sayısal `line`, `prices` |

Dönemler: `FULL`, `1Q`, `2Q`, `3Q`, `4Q`, `1H`, `2H`.
Piyasalar: `TOTAL`, `HOME`, `AWAY`, `HOME_HANDICAP`, `WINNER`.
`prices` sadece gerçekten okunan `under` / `over` taraflarını içerir; bilinmiyorsa
`{}`. Handikapta `over` evin handikabı karşılaması, `under` deplasmanın karşılaması;
kazanan piyasasında `over` ev, `under` deplasmandır. `WINNER` çizgisi 0'dır.
Bu alan listesi gerçek quote örneği değildir; görüntüsüz oran/barem dosyası üretilmedi.

İthalat (girdi/görüntü yolları operatörün gerçekten hazırladığı dosyalardır):

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m hybrid_engine.market_observations \
  --input /tam/yol/gercek-piyasa.json \
  --screenshot /tam/yol/gercek-ekran.png \
  --output-directory /home/userland/zeynal-test-isolated/data/market-observations
```

Sonuç `IMPORTED_MANUAL_UNVERIFIED` olur; API tarafından doğrulandı denmez.
Dosya aynı görüntüdeki alanlarla bağımsız karşılaştırılmadan güvenilir quote
kabul edilmez. Kod OCR yapmaz; gerçek Nesine görüntüsü bu oturumda sağlanmadı.
Kaynak dosyasının içeriği değiştirilmez. İthalat model/forecast veritabanını açmaz.
URL'de kullanıcı/parola veya anahtar/token parametreleri kabul edilmez.

## Test ve kanıt

- Yerel tam paket: **942 geçti / 0 başarısız**; önceki **888** korundu, **54** yeni.
- Native kaynak bağı, farklı platform fiyatlarının karıştırılması, manuel
  aktarımın API gibi etiketlenememesi, alternatif baremler, integer iade kütlesi,
  handikap işareti, EV/iade aritmetiği ve `NO_EDGE` altında sayısal görünürlük test edildi.
- 28 dönem/piyasa kombinasyonu aynı örnek matrisiyle doğrulandı. Üretimden sonra
  gelen quote, eski karar zamanı, stale quote, post-tipoff ve bilinmeyen saat testleri var.
- Görüntü/JSON bozulması, path/symlink, kaynak boyutu, disk hatası, idempotence ve
  değişmezlik testleri geçti. Görüntü hash'i transkripsiyonun doğruluğu diye sunulmadı.
- Gerçek PTB dispatch + **yerel HTTP double** üzerinden analiz özeti ve Piyasa
  callback'i, çok parçalı yanıt ve manuel alternatifler test edildi. Bu gerçek
  Telegram teslimi değildir.
- Gerçek donmuş NBA ve eski/ileri EuroLeague girdileri eğitim/ağ erişimi olmadan
  yeniden üretildi; kayıt digest'i ve örnek hash'i korundu.
- Yerel native kaynak replay'i: **14 komut / 14 yanıt**, yaklaşık **101,20 MiB RSS**,
  tek CPU affinity / 256 MiB adres alanı limiti. Bu host cgroup doğrulaması değildir;
  son HEAD gerçek Docker cgroup sonucu PR kontrollerinde ayrıca verilir.
- Başlangıçtaki **51** arşiv/kanıt dosyası byte düzeyinde aynı. Faz13, altı
  sabitlenmiş veri/model kaynağı, `main.py`, mühürlü karar ve kalibrasyon politikaları
  değiştirilmedi. Cloud'daki ayrı Philadelphia kaydının SQLite kontrolü `ok`,
  veritabanı dosyası önce/sonra aynı. UserLAnd'ın canlı 10 kayıtlık DB'si Cloud'a
  aktarılmadığı için bu yeni sürümde uzaktan yeniden denetlendi denmez.

JSON kanıt: [market-source-phase921-evidence-20261116.json](market-source-phase921-evidence-20261116.json).
Bu dosya CI öncesi üretildi; kesin HEAD'in CI kanıtı PR gövdesine eklenir.

## Gerçek ortam ve kabul sınırı

Önceki sürümde kullanıcının `/predictions`, `/accuracy`, `/health`, `/compare`,
`/nba` ve Sacramento arşiv `/analyze` teslimleri önceki kanıt olarak korunur.
**Bu yeni sürümün** gerçek Telegram Piyasa düğmesi ve gerçek Nesine görüntüsü
ithalatı **BLOCKED / henüz yapılmadı**. Yerel HTTP testi bunun yerine sayılmaz.

UserLAnd'da mevcut araştırma dalı güncellendikten sonra mevcut izole bot
oturumu kapatılıp kullanıcının bildirdiği aynı başlatıcı kullanılır:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh
```

Cloud bu yerel scripti çalıştırmadı; token/API anahtarı istenmedi. Birden fazla
polling süreci başlatılmaz. Gerçek `/nba` çıktısından henüz başlamamış maça ait
geçerli `/analyze` komutu seçilip Piyasa düğmesi açılarak yeni sürüm doğrulanmalıdır.

**Production NO-GO.** Bu kaynak/gösterim entegrasyonu modelin doğruluğunu artırdığı
kanıtı değildir. Dört sonuç kalibrasyon veya Faz13 üstünlüğü için yeterli değil;
periyot dağılımının bilinen ortak hareket sınırlaması sürüyor. Tam yeni-maç
üretimi E2E, gerçek manuel kaynak alan doğrulaması, piyasa ödeme kuralları ve
ileri OOS kabulü ayrıca bekliyor. Main merge, production deploy, ücretli kaynak,
secret, kalıcı disk ve snapshot değişikliği yapılmadı.
