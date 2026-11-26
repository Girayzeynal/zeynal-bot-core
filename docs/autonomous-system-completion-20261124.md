# ZEYNAL — üç başlıkta otonom tamamlama çalışma kaydı

Bu dosya oturum devam noktasıdır. Durum: **2255 PYTHON TESTİ GEÇTİ / DOCKER VE CANLI KABUL AYRI İZLENİYOR**.
Sistemin veya canlı kabulün tamamlandığı iddiası değildir.

## Senkronizasyon ve koruma

- Uzak entegrasyon: `integration/nba-three-axis-release-candidate-20261124`,
  PR [#162](https://github.com/Girayzeynal/zeynal-bot-core/pull/162).
- Başlangıç SHA: `78d2aa7948abc1447c2f381dc66f85a6ffd7119e`.
- Bu SHA için GitHub push CI `45492770602`: unit/Docker başarılı;
  unit logu **2213 passed in 260.73s**. Kullanıcının önceki #2130 referansı
  yerine güncel gerçek log sayısı esas alındı.
- Eski çalışma ağacı `/workspace/zeynal-hybrid-research`, HEAD `712f2fb`,
  temiz ve korundu. Yeni çalışma ağacı `/workspace/zeynal-completion-20261124`.
- Ortak ata `ae52abd`; eski tarafta 1, entegrasyonda 386 ayrı commit var.
  Eski commit topluca cherry-pick/merge edilmedi: beş dakikalık sınır,
  yeni oyuncu/rotasyon hatları, güncel piyasa kapsamı ve Telegram düzeltmeleri
  eski kodla değiştirilmeyecek. Eksik parçalar yalnız karşılaştırılarak taşınır.
- Main/Fly/volume/secrets üzerinde işlem yok. Arşiv silme, reset, force-push yok.

## Durum sözlüğü

`DENETLENDİ`: kaynak ve mevcut test incelendi, canlı başarı anlamına gelmez.
`DOĞRULANDI`: kapsamı ve test/kanıtı bu dosyada belirtilen sonuç.
`KODLANDI_CANLI_DEĞİL`, `KISMİ`, `DIŞ_ENGEL`, `SIRADA`, `BAŞARISIZ`:
tamamlanmış sayılmaz. Her düzeltme neden ve regresyon testiyle kaydedilir.

## 1. Veri sağlayıcıları ve piyasalar

| İş | İlk durum / mevcut kanıt | Sonraki doğrulama |
| --- | --- | --- |
| ESPN / resmî NBA / Avrupa API kimlik, sezon, UTC/TSİ | DENETLENDİ: native recheck ve Avrupa exact katalog kodu mevcut | malformed / partial / çelişki sözleşmeleri |
| The Odds API kapsamı, kredi, kilit, güncellik | DENETLENDİ: core/extended opt-in, kredi ve deadline kontrolü mevcut | eksik zaman, duplicate, hatalı JSON/HTML ve fallback |
| API-Basketball alternatif fiyat hattı | DENETLENDİ: ayrı native makbuz; yayın saati bilinmiyor | hiçbir zaman güncel kabul edilmemesi, kota/fallback |
| Nesine | SIRADA: eski dalda yalnız resmî katalog gözlem adaptörü var; oran/ödeme kanıtı yok | yeni kodla çakışmadan salt-okunur gerçek erişim denetimi |
| Basketball Sphere / Eurohoops / Basketlogy | SIRADA: mevcut Avrupa çok kaynak hattı korunur | robots, partial, tam oyuncu/maç eşleşmesi |
| 82 kulüp | KISMİ: kullanıcı cihazı 60 haber sayfası / 22 engel; sakatlık feed kanıtı değil | URL/robots/redirect/cache ve yeni engellerin sınıflaması |
| Takım/oyuncu/maç çapraz kimlikleri | DENETLENDİ: resmî registry ve exact provider anchor mevcut | belirsizlikte reddetme / sezon dışı kimlik |
| HTTP 403/429/503, timeout, kota | SIRADA | ortak cooldown, Retry-After ve sorgu bütçesi |
| Maç/alternatif/handikap/takım/çeyrek/yarı fiyatları | KISMİ: parser var; tüm liglerde canlı kapsam kanıtı yok | native sözleşme matrisi ve ortak dağılım |
| Oyuncu sayı/ribaund/asist/üçlük/birleşik baremler | KISMİ: NBA label gözlemi var, resmî oyuncu bağlama/model/ödeme ayrı | kimlik ve zaman denetimi; Avrupa katsayısı aktarımı yok |
| Açılış/kapanış/hareket arşivi | KISMİ: native yerel gözlem tarihi var | gerçek opening/closing diye etiketlenmemesi |
| Platforma özgü ödeme / normal süre / OT | KISMİ: pinned RuleBook mevcut | eksik/belirsiz kurallarda kontrat hesabı blokajı |

## 2. Oyuncu etkili model ve simülasyon

| İş | İlk durum / mevcut kanıt | Sonraki doğrulama |
| --- | --- | --- |
| V1/V2/V3 ve Avrupa model kaynakları | SIRADA: mevcut namespace planlarını koru | sayısal fark ve kaynak pinleri envanteri |
| Güncel kadro/katılım/ceza/ilk beş | KISMİ: üç lig bridge, resmî kulüp ve haber gözlemleri | roster kaydı availability sayılmamalı |
| Dakika / yerine geçen rotasyon / hücum-savunma / tempo | KISMİ: player box pilot ve ayrı senaryolar var | geçmişe veri sızıntısı, tam takım dakika bütçesi |
| Rakip/form/ev-dep/dinlenme/seyahat/B2B | KISMİ: V3 ve schedule features var | hangi katsayıların gerçekten fit edildiği |
| Mekanik V1 çeyrek sorunu | KISMİ: üç eksenli stochastic research mevcut | aynı maçta korelasyon/varyans ve hata karşılaştırması |
| 48/40 dakika ve ortak periyot/yarı/takım örnekleri | SIRADA | her ligde toplam tutarlılığı / parametrik sınırlar |
| Ayrı OT örnekleri ve ödeme | DIŞ_ENGEL/KISMİ: doğrulanmış OT yolu yoksa normal süre kontrata çevrilmez | uygulanabilir veriye dayalı aday ve açık kapsam |
| İlk tahmin / güncel değerlendirme ayrımı | DENETLENDİ: korunuyor | kayıpsız sıkıştırma ve backward-compatible okuyucu |
| V3/V2 sıra bağımlılığı | DENETLENDİ: yeni current-first cycle korunuyor | başarısız erken maçların sonraki maçı aç bırakmaması |

## 3. Hata, kalibrasyon ve otomasyon

| İş | İlk durum / mevcut kanıt | Sonraki doğrulama |
| --- | --- | --- |
| n=1 itibarıyla MAE/RMSE/bias/ev-dep/toplam/fark/Q/H | DENETLENDİ: first_forecast_walkforward / three_axis mevcut | eksik çeyrek ve eşleşmiş kohort paydaları |
| Brier/log-loss/reliability/kapsama | DENETLENDİ: tanımlı ham ölçüm; güven endeksi değil | eksik olasılık / eşitlik / OT kapsamı |
| V1/V2/V3 aynı maç ve walk-forward | KISMİ: tarihsel replay var; bağımsız prospective üstünlük yok | sızıntı, model/kohort kimliği, çoklu metrik kabul |
| Ana model yaşı / azami sınır | DENETLENDİ: yeni politikada 24 saat, 6 saatte uyarı | eksik/gelecek/eskimiş parametre testi |
| Otomatik prematch / kaynak / öncelik / beş dakika | DENETLENDİ: yeni beş dakikalık politika korunuyor | T−301 / T−300 / T−299, retry/restart/concurrency |
| Kilit/timeout/toparlanma/telefon ve Fly kaynak sınırı | SIRADA | gerçek cgroup 256 MiB / 1 CPU CI |
| Arşiv kapasitesi ve kayıpsız sıkıştırma | SIRADA: eski commit iyileştirmesi henüz yeni dala taşınmadı | JSON-array belleği ve tekrar native kaynak çoğalması |

## Telegram / UserLAnd / güvenlik kabulü

- SIRADA: dinamik lig/tarih/ev/deplasman parser ve tüm mevcut düğme regresyonu.
- SIRADA: NBA/EuroLeague/EuroCup model-çıktı/piyasa/kadro/kaynak uyumu.
- Gerçek Telegram ve cihaz arşivi bu Cloud ortamında henüz doğrulanmadı.
  Kimlik bilgisi erişimi yalnız yapılandırma durumu olarak kontrol edilir;
  değerler loglanmaz. Sentetik Bot API testleri gerçek teslim sayılmaz.
- SIRADA: Python, Docker, kaynak sözleşmesi, gizli bilgi sızıntısı kontrolleri.
- Beş dakika sınırı, eski kayıtlar, token/API anahtarları, Android başlatıcı,
  main ve Fly koruması her aşamada kabul koşuludur.

## Çalışma günlüğü / sonraki adım

1. Senkronizasyon tamamlandı; eski dal ve tek bağımsız commit korundu.
2. Bu kontrol listesi kod düzeltmelerinden önce oluşturuldu.
3. Sırada: yeni current-assessment koduna uyumlu kayıpsız depolama,
   veri sağlayıcı hata sözleşmeleri ve kaynak/oyuncu/kalibrasyon denetimleri.
4. Nihai sonuçlar, commit SHA'ları, exact CI run/job kimlikleri ve kalan dış
   engeller burada güncellenecek. Aşamalar erken `tamamlandı` işaretlenmez.

### Aşama 1 — eski tamamlanmamış depolama düzeltmesinin seçici uyarlaması

- Neden: 10.000×4×2 yollar `tolist()` ile yazılıyor; `_capture` ve base
  `Registry.record` ilgisiz bütün yayınları tekrar tarıyordu. İlk iki ABSTAIN
  maç, otomatik turda diğer maçları sürekli aç bırakabiliyordu.
- Düzeltme: `assessment_storage.py` kayıpsız byte-order/dtype koruyan gzip
  codec; eski JSON yolları ve düz native makbuzları aynı okuyucuda desteklenir.
  Yeni native makbuzlar hash ile açılıp doğrulanır. Açılmış boyut sınırı vardır.
  Eski ilk kayıt/sürüm/plan dosyaları, 30 dk yenileme, 45 dk güncellik, 24 saat model
  yaşı, **T−300 yayın sınırı** ve mevcut 512 / 256 MiB kapasite politikası
  değiştirilmedi. Önceki veri taşınmaz/silinmez. Başlatıcının zaten var olan
  implementation-SHA namespace kuralı yeni **current-assessment** dizini seçer;
  eski current dizinleri ve sayaçları korunur, otomatik birleştirilmez.
  V1/V2/V3 kapalı deney kaynakları/sayaçları değişmedi. Yeni current kohortu
  eskisiyle karıştırılarak başarı veya kalibrasyon iddiası üretilmez.
- Maç/sürüm doğrudan anahtarından okuma; aynı mevcut durable writer ve ayrı
  post-commit makbuzu korunur. T−299'da biten kayıt diskte kalır ama dışlanır.
  Bekleyen maçlar son deneme sırasına göre ilerler; açık kullanıcı önceliği kalır.
- Birim + gerçek model/registry + Telegram görünümü regresyonu:
  **69 passed in 11.95s**. İlk denemede eski base-class spy testinin yeni
  durable writer'a bağlanması gerektiği görüldü; T−299 dışlama beklentisi
  değiştirilmeden test o yazma noktasına bağlandı ve geçti.
- Durum: **KODLANDI_CANLI_DEĞİL**. Tam regresyon/cgroup ve cihaz kabulü bekler.
  512 kayıt sınırında durma mevcut güvenli davranıştır; sınırsız arşiv denmez.

### Aşama 2 — yeni yeniden üretilmiş kaynak sözleşmesi hataları

`test_provider_partial_contracts.py` düzeltme öncesi: **4 failed, 1 passed**.
Geçerli fiyatın yanındaki null bookmaker/bet tüm cevabı AttributeError ile
düşürebiliyor; hatalı failure payload/cooldown değeri beklemeyi bozuyor;
HTTP-date biçimindeki Retry-After yok sayılıyor. Sırada: asıl nedeni gider,
geçerli bağımsız kanıtı koru; kısmi veriyi tam kapsam diye sunma.

- Düzeltildi: bozuk bağımsız bookmaker/market/bet/value girdileri kapsam
  sınırları içinde ayrı reddedilir. Çelişkili aynı book/market kopyaları
  reddedilir; avantajlı olan seçilmez. Geçerli diğer fiyat ve native makbuz
  korunur. Coverage görünümü de kısmi schema ile çökmemeli.
- Failure payload dict/status sözleşmesi normalize edilir; bozuk bekleme
  değeri en az 30 sn cooldown'ı atlatmaz. HTTP-date / delta Retry-After
  en fazla 3600 sn olarak işlenir. Kota olmayan/bozuk metadata fiyatın
  geçerli kısmını düşürmez; anahtarlar hiçbir sonuca eklenmez.
- Düzeltme sonrası sağlayıcı/kimlik/oyuncu fiyat/yedek/sezon/Avrupa testleri:
  **105 passed in 3.74s**. Son eklenen actual bridge+coverage+journal ve
  bozuk/çelişkili kardeş satır testleri dahil: **7 passed in 0.41s**.
- Durum: **KODLANDI_CANLI_DEĞİL**; authenticated fixture/price kapsamı bu
  sentetik testlerden çıkarsanmaz. Canlı ücretsiz kaynak denetimi ayrı başladı.

### Aşama 3 — ayrı, lig/sezon sınırlı uzatma araştırması

- `overtime_research.py`: Normal süre eşitliği koşulunda geçmişte gerçekten
  tamamlanmış bütün OT dizisini örnekler; her OT sonunda eşitlik olmadıkça
  sonraki OT olamaz. Normal süre/çeyrek/yarı yolları değişmez. 48/40 dakikalık
  ligler ayrı hazırlanır; NBA örnek/katsayısı Avrupa'ya taşınmaz.
- MC ve ayrı base-23 boyutlu randomized Halton; ham ampirik araştırma
  baseline'ıdır. Rakip/oyuncu/tempo düzeltmesi veya kalibrasyon iddiası yoktur.
  Altı native OT maçı sayısal alt sınırdır, doğrulama/üstünlük eşiği değildir.
  Beş dakika ve 24 saat parametre sınırı uygulanır; hedef eğitimde olamaz.
- Native kaynak gözlemi sonrası fit: NBA 210 maçlık korpusta **12 OT**;
  EuroLeague 134 maçlık korpusta **9 OT**. EuroCup 128 maçlık korpusta
  yeterli OT yok: `OVERTIME_SIX_NATIVE_OT_GAMES_REQUIRED`.
- Strict walk-forward: NBA **n=0**, EuroLeague **n=0**. Kaynakların yakalama
  zamanı tarihsel origin'lerden sonra; saatler değiştirilmedi. Modelin
  native sayılarla fit edilmesi geçmişe maç öncesi yayın veya prospective
  iyileşme sayılmaz. Otomatik RuleBook/piyasa admission **kapalı kalır**.
- Test: **6 passed in 0.43s**. Tam diziler, çoklu OT, ortak full/half yolları,
  diğer lig reddi, gelecek etiket dışlaması, T−301/T−300/T−299 ve n=6 disjoint
  sentetik walk-forward denetlendi. Tam regresyon/cgroup bekler.

### Canlı ücretsiz kaynak gözlemi — 24 Kasım

- ESPN günlük scoreboard **200**; EuroLeague E2026 games **200**;
  EuroCup U2026 games **200**. Native JSON ve gerçek gözlem saatleri saklandı.
- Basketball Sphere / Eurohoops: yalnız haber index adayı gözlendi.
  Basketlogy: `SOURCE_ROBOTS_UNAVAILABLE`. Bütün haberler observation-only.
- NBA resmî sezon indexi **301**, otomatik redirect takip edilmedi.
  Nesine native katalog isteği timeout/read bütçesinde tamamlanamadı.
  Bunlar veri yok/oyuncu yok veya NO EDGE anlamına gelmez.
- Ücretli API anahtarları Cloud sürecinde **yok**; authenticated fiyat/
  abonelik testi ve gerçek Telegram teslimi **NOT_VERIFIED**. Değer okunup
  loglanmadı; yapılandırma yalnız enum olarak kontrol edildi.
- 82 kulüp: **142 HTTP**, **75 index gözlemi**, **7 engel**, **0 atlanmış**.
  NBA 29/30, EuroLeague 17/20, EuroCup 29/32. Doğrulanmış injury feed **0**.
  Engeller: Dallas redirect; ASVEL/Paris robots 403; Balkan robots kullanılamaz;
  Panathinaikos, Derthona ve Le Mans news 403. 403/robots kısıtı aşılmadı.
- ESPN'in 30 günlük tek range query denemesi **400** döndürdü; tekrar
  denenmedi. NBA OT fitinde mevcut pinned 18 Kasım native korpusu yeniden
  kullanıldı; gereksiz 30 ayrı günlük sorgu üretilmedi.
- Kanıtlar `docs/evidence/completion-*-20261124.json.gz` içine konur;
  yerel hash bütünlüğü bağımsız sağlayıcı imzası veya ilk tahmin kanıtı değildir.
  Kaynak capture özetinde CLI `preflight()` dönüş değeri None olduğu için
  yalnız özet metadata düzeltildi; native ağ istekleri tekrar edilmedi.

### Aşama 4 — canlı NBA resmî kaynak taşınması (yeni kök neden)

- Resmî sezon indexinin 301 `Location` başlığı **tam olarak** zaten
  allowlist'teki `https://www.nba.com/players/injury-report` adresini gösteriyor.
  Kod yalnız 403 için ikinci kaynağı denediğinden bu gerçek taşınma kadro
  hattını gereksiz durduruyordu.
- Native transport yalnız bu tam hedefe 301/308 kanıtını taşır; requests
  `allow_redirects=False` kalır. Bilinmeyen host, query, 302/307 ve 429
  otomatik takip edilmez. 301→403 iki 403 gibi gösterilip CDN probe izni
  sayılmaz. Önceki 403 ve explicit-report kuralları korunur.
- Canlı GET: eski index 301 → sabit NBA.com index **200** → gerçek
  `Injury-Report_2026-11-24_05_00PM.pdf` bağlantısı. URL/rapor saati doğrulandı.
- Cloud'da opsiyonel pdfplumber eksikti; üretim veya mevcut venv değiştirilmeden
  yalnız `/tmp/zeynal-injury-deps-20261124` hedefine opsiyonel research
  requirements kuruldu. İlk yakalanmış PDF ve kaynak saatleri yeniden kullanıldı;
  yalnız iki eksik ESPN roster kaynağı ayrıca okundu.
- Gerçek **401909314 / DET@ORL** kaynak probe'u: PDF **51** satır ayrıştırdı,
  **12** maç satırı eşleşti, toplam **21** ESPN+PDF gözlemi. Native dizin,
  rapor başlığı/saati ve maç eşleşmesi doğrulandı. İki absence için ESPN
  corroboration yok; kaynak gözlemi oyuncu modeli/ilk beş demek değildir.
- Record class `SOURCE_ACCESS_PROBE_NOT_FORECAST_LINKED`; yeni tahmin veya
  eski maç öncesi kanıt oluşturulmadı, skor/oyuncu etkisi değiştirilmedi.
- Regresyon: **89 passed in 0.87s** (canonical routing, eski 403/CDN,
  roster, player input/minute sözleşmeleri). Ham regex SyntaxWarning da
  davranış değiştirmeden düzeltildi.
- Aşama 1–3 tam Python koşusu: **2231 passed, 1 warning in 212.64s**;
  o uyarı yukarıdaki regex'ti. Aşama 4 sonrası exact-head tam CI bekler.
- Native metadata/probe kanıtları: `completion-nba-canonical-20261124.json.gz`
  ve `completion-nba-roster-source-20261124.json.gz`. Bunlar gerçek Telegram
  teslimi, hazır oyuncu posterioru veya prospective başarı kanıtı değildir.

### CI geri bildirimi — düzeltilen kendi regresyonum

`7de28e3` push CI `45500200779`: **5 failed, 2230 passed**; Docker da aynı
regresyonda durdu. SyntaxWarning düzeltmesindeki girinti hatası, `origin=None`
iken hata mesajı renderer'ında UnboundLocalError yarattı. Beş test silinmedi
veya gevşetilmedi; koşul tekrar doğru origin bloğuna alındı. Diagnostic/cache/
eski source-policy sözleşme testi **41 passed in 2.18s**. Son head tam CI
bekler; bu başarısız run başarılı gösterilmeyecek.

### Aşama 5 — gereksiz ve eşzamanlı public kaynak sorguları

- Eski ControlledTransport başarılı cevabı saklıyor, fakat sağlıklı kaynakta
  aynı adrese her çağrıda yeniden gidiyordu. Yeni `reuse_seconds` varsayılanı
  **0** ile eski revalidation davranışı korunur; izole gerçek launcher açıkça
  **30 sn** reuse seçer. Cache hit'in belge/hash/gözlem/ingestion saatleri
  değişmez; kaynağın yeni kontrol edildiği iddia edilmez.
- Eşzamanlı aynı URL istekleri bir native çağrıda birleşir; diğer çağrı en
  fazla 1 sn bekler. Cache ve in-flight yapısı lock ile korunur; ilgisiz
  URL'lerin network işi global lock altında çalışmaz.
- 429 ve 5xx/outage beklemesi aynı public origin ile paylaşılır; 403 yalnız
  reddedilen endpoint'i durdurur. Public Retry-After en fazla bir gün, ücretli
  erişim client'ının mevcut sınırı bir saat olarak korunur. Invalid native
  response veya istisna dışarı sızmaz; farklı URL cache'i kullanılamaz.
- Cache/phase842/market-contract/engine/autoprematch testleri:
  **91 passed, 1 PTB lifecycle warning in 23.74s**. Uyarı test uygulaması
  çalışmıyorken create_task çağrısıdır; bastırılmadı. Son full koşu bekler.

### Aşama 6 — mevcut oyuncu pilotunun kullanılabilir durumunu bağlama

- Yeni veri sorgusu yapmadan mevcut native korpusta **70** tam geçmiş
  oyuncu-box maçı doğrulandı; mevcut `fit_box_association` gerçekten fit edildi.
  Bunun 100 prospective dakika kaydıyla aynı şey olmadığı gösterildi.
  Strict disjoint holdout: `NO_SUFFICIENT_PRETEST_SOURCE_OBSERVATIONS`.
  Kaynak saatleri geriye alınmadı ve canlı oyuncu etkisi iddia edilmedi.
- `HistoricalPlayerReview` mevcut read-only pilotu serial background işinin
  sonunda en fazla altı saatte bir çalıştırır. Bilinen yayına 15 dk veya daha
  az varsa opsiyonel araştırma ertelenir; **operasyonel yayın sınırı 5 dk kalır**.
  Eksik kaynakta tekrar 5 dk sonradır. Komut handler'ında fit/network yoktur.
- `/test research` ve `/test playerimpact` cached historical fit ile canlı
  prospective dakika/etki kanıtını ayrı gösterir. Henüz okunmayan arşiv 0
  sayılmaz. Sıradan gecikme/okuma hatası diğer güncel model metriklerini
  silmez; `_stage`'in yanlış genel else ataması düzeltildi.
- Oyuncu pilotunda **aynı eşleşmiş test maçları** için home/away/team/total/
  margin MAE/RMSE/bias eklendi. Point-only modelden Brier/log-loss veya güven
  uydurulmaz. Fit ve tahmin formülü değişmedi, terfi yok.
- History/cache/diagnostic/player-pilot bileşenleri: **30 passed in 0.62s**;
  history/research/current-display/old-player-smoke/feature akışı:
  **87 passed in 12.61s**. Gerçek Telegram teslimi halen NOT_VERIFIED.

### Aşama 7 — oyuncu boyutlandırma açığı ve sonuçtan bağımsız aday planı

- Gerçek native fit: **70 maç / 140 skor gözlemi / 419 oyuncu / 481 parametre**.
  Ridge prior çözüm verse de tekil oyuncu etkisi veriyle ayrı ayırt edilmiş
  sayılmaz. Mevcut V1 oyuncu pilotu referans olarak korunacak.
- Gerçek source-clock strict test **n=0**. Açıkça varsayımsal next-day
  availability replay **n=1**; eski oyuncu pilotu toplam MAE **17.3272**,
  aynı kohort takım kontrolü **16.7649**. İyileşme/terfi kanıtı yoktur.
  Kanıt: `completion-native-player-audit-20261124.json.gz`, payload
  `5990f0f9a1109b0342e6d060a701a0ecdf419d8be091f28eaaf876cb8b3c6092`.
- Sonraki ayrı V2 geliştirme adayı için **kod öncesi sabit seçim**: en az
  altı eğitim maçında pozitif dakika; takım/rakip/home nuisance tasarımına
  göre artık dakika RMS en az 1 dakika; outcome kullanmadan pivot/ortogonal
  kontrast seçimi; en çok 64 oyuncu ve `floor((2*n-rank(base)-10)/2)` sınırı.
  Seçim yalnız eğitim exposure özelliklerine bakar, test skorlarına bakmaz.
- Önceki n=1 replay görüldüğü için yeni aynı replay **geliştirme** verisidir;
  bağımsız kabul veya prospective üstünlük diye gösterilemez. Yeni görülmemiş
  maçlar gerekir. NBA katsayısı Avrupa'ya taşınmaz. Savunma/pace/PBP, tam
  güncel availability ve ceza/ilk beş doğrulanmış gibi etiketlenmez.

#### Aşama 7 uygulama ve gerçek veri sonucu

- `player_contrast_research.py`: sabit exposure-only politika uygulandı.
  Geçersiz/sonsuz skor ve dakika, gelecek kaynak saati, diğer lig ve değişen
  model hash'i reddedilir. Statik dakikalar oyuncu bilgisi sayılmaz: ABSTAIN.
  Bütün testler gerçek kaynak erişiminden bağımsızdır; canlı model admission
  eklenmedi. Eski referans `fit_box_association` katsayıları değişmedi.
- Native **70 maç / 140 skor**: **30 seçilmiş oyuncu / 92 parametre**;
  base rank **60**, genişletilmiş rank **90**. Takım/intercept nuisance
  parametrelerinde iki bilinen doğrusal bağımlılık ridge ile tanımlanır;
  oyuncu kontrastlarının rank artışı tam 30'dur. Bu, nedensel veya tekil
  savunma/tempo etkisi tanımlandığı anlamına gelmez.
- Strict test yine **n=0**. Daha önce görülmüş, varsayımsal availability
  geliştirme karşılaştırması **n=1**: aday toplam MAE **16.8044**, takım
  kontrolü **16.7649**. Aday kontrolü geçmedi; **terfi edilmedi**. Eski pilotun
  17.3272 değeriyle kıyaslamak bağımsız test sayılmaz.
- Kanıt `completion-native-player-contrast-20261124.json.gz`, payload SHA
  `ab4331fca48fb0957d428103df9d60eaf476f51ee78769806484b679899e1cac`.
- Yeni/legacy/history testleri **20 passed in 0.55s**. İlk bozuk sonsuz skor
  testinde legacy ön-fit uyarıları görüldü; yeni adayın doğrulaması fit önüne
  taşındı, uyarı bastırılmadı. Ağ kısıtlı sandbox asyncio yerel socket'i
  beklettiğinden o koşu durduruldu; loopback izinli yeniden koşu tamamlandı.

## Güncel kapsam matrisi — başlangıç listesinin karşılığı

Başlangıç tabloları ilk inceleme durumudur. Aşağıdaki matris bu çalışmanın
son kod kapsamını ve açık sınırlarını bildirir. `DOĞRULANDI` yalnız belirtilen
test/kaynak gözlemidir; gerçek Telegram kabulü anlamına gelmez.

### Veri sağlayıcıları / piyasalar

| Kapsam | Durum ve doğrulama | Açık sınır |
| --- | --- | --- |
| ESPN, resmî Avrupa fikstürü, sezon/maç/UTC/TSİ | DOĞRULANDI: native 200 makbuzları; exact kimlik ve sezon/yerel takvim regresyonları | UserLAnd çalışan süreç ve cihaz arşivi burada yok |
| NBA resmî kadro/PDF | DOĞRULANDI: gerçek 301→sabit 200 index, PDF ve DET@ORL eşleşmesi; canonical düzeltme | Kaynak probe'u ilk tahmin veya doğrulanmış dakika değildir |
| The Odds API / API-Basketball | KODLANDI_CANLI_DEĞİL: partial/duplicate, bütçe, timeout, fallback, kredi/UTC-gün reset, provider kimliği ve tarih testleri | Cloud'da iki anahtar da yok; abonelik ve tüm lig fiyat kapsamı NOT_VERIFIED |
| Nesine | DIŞ_ENGEL: anonim resmî katalog isteği timeout/read bütçesi içinde alınamadı | Bu entegrasyonda doğrulanmış native Nesine fiyat/ödeme adaptörü yok; başka book fiyatı Nesine sayılmaz |
| Basketball Sphere / Eurohoops / Basketlogy | KISMİ: ilk ikisinde index adayı, Basketlogy robots engeli | Haber indexi oyuncu durumu/ceza/maç kadrosu doğrulaması değildir |
| 82 kulüp | DOĞRULANDI: 82/82 denendi, 75 index gözlemi, 7 erişim engeli | Injury feed doğrulaması 0; robots/403/redirect kısıtları aşılmadı |
| 403 / 429 / 503 / bağlantı / timeout / bozuk schema | KODLANDI_CANLI_DEĞİL: bounded retry, public origin cooldown, HTTP-date Retry-After, coalescing; native 301 kök nedeni düzeltildi | Bir başarısız provider verisi diğer provider'a aitmiş gibi etiketlenmez |
| Önbellek ve API optimizasyonu | KODLANDI_CANLI_DEĞİL: açık 30 sn public reuse, gerçek source saatleri korunur, aynı URL in-flight tekleşir | Cache yeni kaynak yayını değildir; platform kredisi gerçek erişimde ayrıca ölçülmeli |
| ML / toplam / handikap / takım toplamı | DENETLENDİ: `provider_bridge` core/extended parser + current market/rule sözleşmeleri | Parser desteği canlı sunum veya ödeme doğrulaması değildir |
| 1Q–4Q / 1H–2H, alternatif toplam/handikap/takım toplamı | DENETLENDİ: `EXTRA_MARKETS` ve exact dönem eşleştirme; kapsam requested/returned/admitted ayrı | Ücretli extended sorgu açık opt-in ve kredi bütçesine bağlı |
| Oyuncu sayı/ribaund/asist/üçlük/PRA/PR/PA/RA | KISMİ: NBA paired fiyat label parser mevcut, partial kardeşler korunur | Resmî oyuncu kimliği, dakika, dağılım ve ödeme kanıtı olmadan bahis olasılığı yok; Avrupa prop admission yok |
| Fiyat hareketi / açılış / kapanış | KISMİ: `native_market_history` native saatli yerel fiyat serisi | İlk/son yerel gözlem gerçek piyasa açılışı/kapanışı diye sunulmaz |
| Platform/dönem/market bazlı normal süre ve OT | DENETLENDİ: pinned `RuleBook`, başka book/gelecek/eksik kural ve OT yolu blokajı | Nesine veya başka platform için elde olmayan kural uydurulmaz; yeni OT adayından otomatik admission yok |

### Modeller / oyuncu / ortak simülasyon

| Kapsam | Durum ve doğrulama | Açık sınır |
| --- | --- | --- |
| V1/V2/V3 ve Avrupa referans koruması | DOĞRULANDI: başlangıç SHA'ya göre V1 27, V2 13, V3 9, Avrupa 6, NBA sampler 6 pinned dosyada **0 değişiklik** | V1 frozen araştırma referansıdır; güncel model diye sunulmaz |
| Güncel skor ve model yaşı | DENETLENDİ: current aday 30 dk yenileme / 45 dk güncellik / 24 saat parametre tavanı; 6 saat uyarı | Aday eksikse ilk arşiv canlı güncel tahmin olmaz; V1'in dondurulmuş katsayıları sessizce refit edilmedi |
| Oyuncu kimliği / kadro / katılım / ceza / ilk beş | KISMİ: üç lig source bridge, exact native ID, haber ile availability ayrımı korunur | Tam takımın maç öncesi onaylı availability/ilk beşi her maçta yok |
| Dakika / yerine geçen rotasyon / oyuncu hücum etkisi | KODLANDI_CANLI_DEĞİL: tarihsel association + ayrı rank-bounded dakika-kontrast adayı; 240 dakika bütçesi; ayrı conditional senaryo | Geçmiş gerçek dakika gelecek dakika tahmini değildir; senaryo doğrulanmış sakatlık/yerine geçecek oyuncu demek değildir |
| Oyuncu savunması / tempo / PBP | KISMİ: mevcut modeller bunu uygulanmış saymaz | Native possession sınırları, bağımsız savunma ve tempo etki fit'i doğrulanmadı |
| Rakip / form / ev-dep | DENETLENDİ: mevcut V3 dinamik rank/rate ve current değerlendirme yolu; same-cohort testler | Bağımsız ileriye dönük üstünlük henüz kanıtlanmadı |
| Dinlenme / B2B / seyahat | KISMİ: `nba_schedule_features` ayrı native takvim/gap ve venue-distance ablation | Gerçek yolculuk/uyku/dinlenme ölçümü yok; 30 prospective context etiketi olmadan katsayı yok; current ana skora uygulanmış sayılmaz |
| V1 mekanik çeyrek / korelasyon / varyans | KISMİ: V1 referans korundu; mevcut stochastic V3 ve üç eksenli quarter adayı ayrı | Eski ilk tahmin çeyrekleri yeniden yazılmaz; paired gerçek quarter üstünlüğü yoksa terfi yok |
| MC/RQMC ve ortak Q/H/team/full toplamları | DENETLENDİ: ortak path / sample hash / 48–40 dakika; compressed ve legacy byte eşitliği | Ham olasılık güven endeksi değildir; gerçek PBP/rotasyon uyumu ayrıca gerekir |
| OT | KODLANDI_CANLI_DEĞİL: NBA/EuroLeague native completed-OT block fit; MC ve Halton; normal süre yolları korunur | EuroCup sparse ABSTAIN; strict n=0; live piyasa admission yok |
| V3–V2 sıra bağımlılığı ve retry | KODLANDI_CANLI_DEĞİL: current önce; bağımsız aşama hata izolasyonu; aç kalan maç fairness testi | Veri bağımlılığı ve tek serial fit korunur; opsiyonel player geçmiş işi yakın yayında ertelenir |

### Hata / kalibrasyon / otomasyon ve kabul

| Kapsam | Durum ve doğrulama | Açık sınır |
| --- | --- | --- |
| İlk kayıttan hata, MAE/RMSE/bias/home/away/total/margin/Q/H | DENETLENDİ: mevcut first-forecast/three-axis; oyuncu holdout'a aynı eşleşmiş point metrikleri eklendi | Eksik quarter veya doğrulanmamış eski yayın ayrı dışlanır; 100 beklenmez |
| ML Brier/log-loss, reliability, interval coverage | DENETLENDİ: ham 3 sınıf normal süre ve doğru paydalar | Point-only oyuncu adayı için bu olasılık metrikleri UNSUPPORTED; olasılık uydurulmaz |
| Walk-forward / V1–V2–V3 aynı kohort / kalibrasyon | KISMİ: mevcut ayrık kaynak saati testleri ve kabul red guard'ları korundu | Bağımsız görülmemiş maç/kalibrasyon verisi eksik; çalışma sırasında görülen replay kabul verisi değildir |
| Prematch / otomatik kaynak / öncelik / son 5 dk | DENETLENDİ: T−301/T−300/T−299 ve durable commit saati, replay/restart/lock testleri | Gerçek cihaz saati/süreç yetkili test botunda tekrar doğrulanmalı |
| Kilit / timeout / hata toparlanma | KODLANDI_CANLI_DEĞİL: exact yayın okuma, failed-stage ayrımı, kaynak ve araştırma cache/retry | Son Docker cgroup ve cihaz kabulü ayrı kanıt gerektirir |
| Kayıpsız sıkıştırma / arşiv | KODLANDI_CANLI_DEĞİL: dtype/endianness/sample SHA ve native hash korunur, legacy okuyucu var | **512 current kayıt / 256 MiB** güvenli durma tavanı korunur; sınırsız büyüme veya eski namespace birleşimi yok |
| Dinamik `/analyze` ve düğmeler | DENETLENDİ: dinamik takım/date/lig ayrıştırıcı, tek komut kuralı, Avrupa altı callback ve current/first ayrımı | Bir Telegram mesajına çok komut verilmesi desteklenmez; sabit yeni takım adı eklenmedi |
| Gerçek Telegram `/analyze`, `/accuracy`, `/compare` | DIŞ_ENGEL / NOT_VERIFIED: Cloud test kimliği yok | PTB local HTTP + sentetik provider E2E gerçek Telegram teslimi değildir |
| Android / Docker / güvenlik | DENETLENDİ: bash syntax; mevcut UserLAnd launcher, secrets/fallback contract testleri | Telefon çalışması ve Fly mount/restart bu görevde erişilebilir değil; deploy yapılmadı |

## Koruma ve devam kaydı

- V1/V2/V3/Avrupa/NBA sampler pin kanıtı:
  `docs/evidence/completion-scientific-pins-20261124.json`.
- Eklenen/değişen 35 dosyada bilinen GitHub/AWS/Telegram credential pattern
  taraması: **0 şüpheli dosya**. Bu sınırlı örüntü taraması tam güvenlik
  denetimi diye sunulmaz. Yeni ücretli servis/anahtar/Fly erişimi kullanılmadı.
- Eski branch `712f2fb`, ilk kayıtlar ve deney protokolleri silinmedi.
  Yerel cihaz/üretim diskine erişilmediğinden o diskin native hash ölçümü
  **NOT_VERIFIED**; "üretim verisi kayıpsız doğrulandı" iddiası yok.
- Son kod commit'i `0a2b23e7595f4711edb62c344960b8c3553d45fb`.
  Uzak entegrasyon tek yönde güncellendi; force/main merge/Fly deploy yok.
  Bu kod için full Python ve GitHub Docker/cgroup sonucu aşağıya eklenecek.
- Kalan bağımsız kabul işleri: yetkili test cihazında gerçek üç lig Telegram
  akışları ve çalışan sürüm/namespace kontrolü; gerçek sağlayıcı kapsamı ve
  Nesine fiyat+ödeme delili; prospective dakika/rotasyon ve bağımsız karşılaştırma.
  Bunlar kod/birim test başarısıyla tamamlanmış sayılmaz. Kapasite tavanına
  yaklaşılırsa arşivleri silmeden yeni bounded segment tasarımı ayrıca gerekir.

### Son kod regresyonu

`0a2b23e` koduyla Python 3.12 / tek BLAS thread, tam komut:

```bash
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  python -B -m pytest -q
bash -n scripts/run_isolated_test_bot.sh
git diff --check
```

Sonuç: **2255 passed in 203.32s**, uyarı/skip/xfail yok; exit 0.
Ham log: `docs/evidence/completion-python-regression-20261124.log.gz`.
GitHub Python 3.11 push run `45505150157`, unit job `138838322072`
başarılı; Docker job `138838321644` bu kayıt yazılırken sürüyordu.
PR #162'nin check kayıtları ve açıklaması son exact head sonuçlarıyla ayrıca
güncellenir. Önceki `7de28e3` **5 failed** CI kaydı yukarıda açıkça korunur.
Gerçek Telegram ve yetkili fiyat API testi bu 2255 testin içinde yapılmış
sayılmaz. Üç lig handler/callback testleri local HTTP/sentetik native yanıt
üzerinden çalışır. Main merge, Fly deploy ve otomatik model terfisi yapılmadı.

### Başlık bazında teslim durumu

| Başlık | Tamamlanan ve testle doğrulanan | Kodlandı / canlı doğrulanmadı | Kısmi / başarısız / dış engel | Kalan |
| --- | --- | --- | --- | --- |
| Sağlayıcı / piyasa | Partial JSON, duplicate çatışması, retry/cooldown, exact NBA canonical yönü; üç native fikstür; 82 site denetimi | Public cache/coalescing; authenticated bridge fallback testleri | 7 kulüp erişim engeli, Nesine timeout, ücretli anahtar yok; gerçek opening/closing ve platform kuralları eksik | Yetkili cihazda fiyat/ödeme ve tüm market kapsamı kabulü |
| Oyuncu / model / simülasyon | Eski bilimsel pinler korundu; dakika-kontrast rank/bütçe testi; native 70 maç boyut denetimi; ortak-path kayıpsızlık | Yeni ayrı kontrast ve OT araştırma adayları; history görünümü | Kontrast tek geliştirme maçında kontrolü geçmedi; strict player/OT n=0; prospective dakika/defans/PBP yok | Bağımsız veride model ve oyuncu etkisi testi; uygun veriyle Avrupa OT fit |
| Hata / kalibrasyon / otomasyon | n=1 hata hattı korundu; paired point metrikleri; fairness; ilk tahmin/late commit koruması; 2255 Python | Sıkıştırılmış arşiv, background history ve kaynak optimizasyonu | Önceki CI girinti regresyonu düzeltildi; son Docker burada bekliyor; Telegram/telefon/Fly runtime NOT_VERIFIED | Exact-head cgroup check; gerçek staging kabulü; prospective kalibrasyon ve veri kaybetmeden ileri kapasite segmentleri |

Bu teslim sistemin tamamlandığı veya modelin üstün olduğu onayı değildir.
Erişim gerektirmeyen yeni düzeltmeler kaydedildi; yukarıdaki canlı ve bilimsel
kanıt eksikleri PR kabulünden ve üretim kararından ayrı tutulur.

## 25 Kasım — cihaz kabulü / yanıtsız sağlayıcı tanılaması

- Kullanıcı UserLAnd'da temiz ayrı clone ile `a9ce6a5` başlattı; Telegram
  `/test runtime` aynı release SHA'yı bildirdi. `/features` ve `/test research`
  yanıtları kullanıcı tarafından paylaşıldı. Bu, bütün `/analyze`/callback
  akışının bağımsız Telegram API/journal doğrulaması sayılmaz.
- Paylaşılan ekranda 06:37 ve 06:39 `/test data` mesajlarına yanıt görünmüyor.
  Kaynakta doğrulanmış sözleşme hatası: `ProviderBridge.storage_status()`
  bölüm başına kapasite döndürürken `/test data` kaldırılmış `maximum_files`
  anahtarını okuyor. KeyError reply gönderilmeden önce oluşuyor; genel hata
  handler'ı yalnız journal'a yazdığı için kullanıcıya açıklama ulaşmıyor.
- İkinci kod bulgusu: `ProviderAccess.runtime_status()` eşzamanlı provider
  network isteğinin tuttuğu lock'u event loop üzerinde sınırsız bekleyebilir.
  Telefon ekranı bu ikinci nedenin gerçekleştiğini tek başına kanıtlamıyor.
- Düzeltme planı: kaldırılmış alanı uydurmadan segment kapasitesini doğru
  göster; provider lock'u beklemeyen snapshot; bounded opsiyonel disk okuma;
  yalnız çalışan süreç metadata'sını gösteren `/test providers`. Tanılamada
  yeni API isteği/ücret, anahtar gösterimi veya geçmiş tahmin yazımı yok.
- Önce gerçek PTB handler ve lock-contention regresyonu ile yeniden üret;
  sonra hedefli ve tam Python/Docker kontrolleri. Cihazdaki asıl sağlayıcı
  yetki/kota/fiyat kapsamı bu düzeltme yapılmadan doğrulanmış sayılmaz.

### 25 Kasım düzeltme ve test kanıtı

- Düzeltme öncesi yeni üç regresyon: **2 failed, 1 passed in 1.77s**.
  Gerçek PTB `/test data` handler'ı sıfır yanıt verdi; gerçek provider lock'u
  snapshot'ı 0.20 sn tuttu. Telefon günlüğü alınmadığı için cihazdaki kesin
  traceback görülmedi; kod hatası ve aynı yanıtsız davranış testte üretildi.
- `provider_health.py` mevcut çalışan bridge anahtarının **varlık durumunu**
  gösterir; key değerleri veya environment/private-file içeriği çıkarılmaz.
  `/test providers` dosya taramaz/API çağırmaz. `/test data`, `/test all` ve
  `/test` eski `maximum_files` anahtarını varsaymadan segment kapasitesini
  gösterir. Depo taraması opsiyonel işçi yolunda en fazla 1.5 sn beklenir;
  hata/zaman aşımında anahtar durumu ve açıklama yine gönderilir.
- `runtime_status` kilidi beklemez; busy snapshot sayaç/kotayı **None / bilinmiyor**
  döndürür. Bekleyen API isteği Telegram event loop'unu tutmaz.
- `/test providers check`, yalnız yetkili sohbetin açık isteğiyle, mevcut
  paylaşılan erişim bütçesinde sabit `/v4/sports/` ve `/status` uçlarını kontrol
  eder. Önce ilerleme yanıtı gönderilir; toplam bekleme 7 sn, native çağrı
  başına en fazla 3 sn ve mevcut kredi/cache/lock sınırları korunur. Süre
  dolduktan sonra devam eden thread ikinci sağlayıcıya yeni istek başlatmaz.
  Son sayaçlar tekrar okunur; busy durumda eski sıfır sayaç gösterilmez.
- Katalog/hesap sonucu fiyat, lig/sezon, Nesine ödeme kuralı veya oyuncu
  etkisi doğrulaması değildir. Yerel API probe sonucu yalnız enum/HTTP/hata
  sınıfıdır; native hesap gövdesi, exception metni, URL ve anahtar gönderilmez.
- Yeni/legacy sağlayıcı, actual PTB handler, ayrı worker ve UI hedefli koşusu:
  **85 passed in 11.26s**. Son API/roster/journal hedefli koşusu:
  **25 passed in 10.86s**. Yeni probe testinde farklı fixture gününün native
  makbuz saati kullanılması önce `PROVIDER_RECEIPT_INVALID` verdi; fixture
  saatleri eşleştirildi, gelecek-makbuz reddi değiştirilmedi. Timeout testi
  gerçek 50 ms native-call rezervini koruyarak transport'a girdikten sonra
  200 ms toplam süre aşımını sınar; guard gevşetilmedi.
- Yeni regresyonlar: gerçek segment şemasıyla `/test data`/`all`/varsayılan,
  yetkisiz sohbet, key varlığı/absansı, açık probe ve plan hatası, kota reddi,
  bozuk/okunamayan/yavaş depo, native timeout sonrası ikinci istek yasağı,
  sıradaki `/test runtime` yanıtı, zero API/writes ve secret sızıntı kontrolleri.
- V1 **27**, V2 **13**, V3 **9**, Avrupa **6**, NBA sampler **6** pin dosyası
  `a9ce6a5` ile byte/hash olarak aynı. `current_assessment.py` ve beş dakika
  politikası değişmedi; bu düzeltme yeni current namespace/boş sayaç başlatmaz.
- Tam Python koşusu ve son commit Docker/cgroup kontrolleri sürüyor. Gerçek
  kullanıcı cihazında yeni `/test data` ve `/test providers check` yanıtı
  henüz alınmadı; asıl sağlayıcı bağlantısı halen **NOT_VERIFIED**.

## 25 Kasım — sağlayıcı yanıtı ve fikstürden kopyalanan uzun tire

- Kullanıcı `a714067` güncellemesini başlattı ve `/test providers check`
  çıktısını paylaştı: The Odds API `SPORTS_CATALOG_RECEIVED / HTTP 200`,
  bildirilen kalan 304; API-Basketball `ACCOUNT_STATUS_RECEIVED / HTTP 200`,
  bildirilen kalan 100. İki bridge anahtarı çalışan süreçte yüklü; yerel istek
  sayaçları her biri 1/24. Bu **kullanıcı tarafından paylaşılan temel uç nokta
  kanıtıdır**; tam fiyat/lig/sezon/Nesine/ödeme/oyuncu kapsamı sayılmaz.
- Sonraki ekran: `/nba` bugünün tamamlanmış/canlı maçlarını gösteriyor.
  Kullanıcı görüntülenen `Orlando Magic – Detroit Pistons` takım çiftini
  `/analyze` içine kopyaladı. `main.parse_analyze` yalnız `vs` kabul ettiği
  için hem 25 hem 26 Kasım komutu biçim hatası aldı. Tarihi elle değiştirmek
  resmî bir eşleşme oluşturmaz; tarih/kimlik doğrulaması korunmalı.
- Önce yeniden üretim; düzeltme kapsamı: mevcut explicit `vs` davranışını
  koruyarak tek bağımsız en/em dash token'ını kabul et, takım adlarının
  içindeki tireleri değiştirme. NBA listesinde yeni maç öncesi hedef yoksa
  bir sonraki TSİ gününün **liste komutunu** öner; yeni maç/tahmin üretme.
  Biten/canlı maç için yalnız varsa kayıtlı karşılaştırmaya yönlendir.
- Kullanıcı cihazına komut gönderilmedi. Sağlayıcıya anahtarlı yeni istek,
  ilk tahmin yazımı veya geçmiş tarih değiştirme planlanmadı.

### Uzun tire düzeltmesi / doğrulama

- Düzeltme öncesi: **3 failed, 4 passed in 2.97s**; kullanıcıdaki Unicode
  komut, gerçek PTB route ve bitmiş maç listesinin sonraki güne yönlendirmesi
  yeniden üretildi. Düzeltme sonrası parser/guard/menu/Avrupa kimliği:
  **49 passed in 10.31s**.
- Explicit `vs` (case-insensitive) aynı davranışta kalır; yoksa tam bir
  whitespace token'ı olan tek `–` / `—` ayracı kabul edilir. Takım içi ASCII
  tireler ve ad/tarih metni değiştirilmez. Birden fazla Unicode aday sınırında
  tahmin yürütülmez. Batch komutlar hâlâ servise ulaşmadan reddedilir.
- NBA fikstür listesi bitmiş/canlı maçta yalnız `/compare NBA <native_id>`
  gösterir; kayıt yoksa bu komut yeni tahmin oluşturmaz. Başlamamış maç
  görünmüyorsa bir sonraki TSİ gününün `/nba YYYY-MM-DD` liste komutu vardır.
  Sonraki güne yeni maç, takım çifti veya tahmin uydurulmaz; ilave otomatik
  provider sorgusu yapılmaz. Ay/yıl sınırı bir sonraki takvim günüdür.
- İki farklı tarihle aynı Unicode takım çiftinin servise **aynı verilen
  tarihle** tek kez ulaşması ve eski arşivin byte eşitliği sınandı. Bu parser
  testi, yanlış günün maç kimliğinin native serviste kabul edildiği anlamına
  gelmez; resmî fixture/time kontrolleri ve beş dakika sınırı değişmedi.
- Ayrı salt-okunur ESPN scoreboard gözlemi: 26 Kasım 01:00 TSİ Philadelphia
  76ers–Miami Heat, native `401909317`, `STATUS_SCHEDULED`. Kullanıcıya bu
  mevcut `vs` komutuyla gerçek Piyasa panelini paylaşması soruldu. Bu gözlem
  tahmin, bahis çizgisi, ödeme sözleşmesi veya ilk yayın kanıtı değildir.
- Tam Python ve exact-head Docker/cgroup sonuçları PR #162'de izlenir.

## 25 Kasım · Telegram mobil kartları

Philadelphia–Miami için paylaşılan cihaz ekranında kullanıcı skordan önce uzun
arşiv açıklamasını okuyordu. Periyot görünümünde her satırın ayrı blok olarak
sayfalanması fazladan boşluk oluşturuyordu.

- NBA özetinde maç, normal süre skoru, toplam ve ortadaki %50 aralık önce
  gösterilir. Doğrulanmış maç toplamı fiyatı varsa şirket, barem, erişim
  zamanı ve ham model yönü aynı bölümde yer alır. Fiyat eskidiğinde bu bölüm
  arşiv olarak etiketlenir. Adayın geçerlilik süresi ayrıca denetlenir.
- Sayısal düğmeler kaydedilmiş adayın periyotlarını bir sayfada, dağılım
  aralıklarını üç kısa sayfada sunar. İlk V1 kaydının kendi arşiv düğmesi,
  eğitim ve kaynak saatlerinin Model / Kaynak görünümü korunur.
- Kısa V3 yanıtının Telegram teslim kaydındaki ilk üretim ve ilk arşiv
  zamanları ayrıca sınandı. Sentetik teslim testi ile telefondaki gerçek
  görünümün kabulü ayrı izlenir.
- Tam regresyonda eski fiyat kartının “önceki kontrol” bilgisini isteyen
  test, kısaltılmış uyarıda bu bilginin eksildiğini gösterdi. Bilgi kart
  metnine geri eklendi. İlgili iki arşiv uyarısı testi geçti.

## 25 Kasım · Ana giriş noktasından izole cihaz kabulü

Üretim imajı `python -u main.py` ile açılır. Test botu Avrupa servislerini
ve Telegram düğmelerini kendi başlatıcısında kuruyordu. Önceki cihaz
çıktıları bu servislerin ana giriş noktasında da kurulduğunu göstermiyordu.

- [x] `main.py --staging` aynı aday servislerini ve PTB düğmelerini kurar.
  Telegram test hesabının kimliği ve webhook durumu arka plan işleri ve
  polling öncesinde kontrol edilir. UserLAnd başlatıcısı iki modda da aynı
  süreç kilidini, model SHA’sını ve izole arşiv yollarını kullanır.
  Staging sağlık uçları yalnız cihazın loopback adresinde dinler.
- [x] `tests/test_main_staging.py` yerel Bot API üzerinden polling açar.
  NBA, EuroLeague ve EuroCup arşiv maçlarına komut gönderir. İkinci
  açılışta önceki EuroCup kartının Periyotlar düğmesini kullanır ve
  Avrupa paketindeki JSON dosyalarının SHA değerlerini karşılaştırır.
  Bu testte zamanlanmış veri toplama işleri bekletilir.
- [ ] Gerçek Telegram ve UserLAnd kabulü. Çalışan izole botu kendi
  terminalinde Ctrl+C ile durdurup entegrasyon kopyasında
  `bash scripts/run_isolated_test_bot.sh --staging` çalıştır.
  Telegram’da `/test runtime` ile `MAIN_STAGING` ve beklenen commit’i
  kontrol et. NBA, EuroLeague ve EuroCup menülerinden birer fikstür seç.
  Analiz, periyot, piyasa, kadro, karşılaştırma ve sonuç yanıtlarını maç
  kimliğiyle kaydet. Aynı komutla bir kez yeniden başlatıp eski kartı aç.
- [ ] Bu sürüm için canlı fiyatın sağlayıcı/maç/ödeme sözleşmesiyle eşleşmesi,
  oyuncu katkısının hangi aday skora uygulandığı ve ileri performans ayrı
  kabul maddeleridir. Staging kaydı üretim dağıtım onayı vermez.

GitHub Actions çalıştırmaları ve test sonuçları [PR #162](https://github.com/Girayzeynal/zeynal-bot-core/pull/162) üzerinde ilgili commit’e bağlıdır.

## 26 Kasım · İddaa bülteni ve toplam hata incelemesi

- [x] Nesine'nin incelenen bültenindeki 131 maçın piyasa listeleri
  boştu. Bilyoner ve Misli incelemesinde maç, barem, oran ve yayın
  zamanı birlikte doğrulanamadı. İddaa'nın genel basketbol bülteninde
  maç ve ilk yarı toplamları okundu. 26 Kasım 03.44 TSİ kontrolünde
  beş NBA maçı bulundu. Golden State – Sacramento için maç toplamı
  215,5, ilk yarı toplamı 110,5'ti. EuroLeague ve EuroCup için o anda
  uygun maç öncesi toplam baremi bulunamadı.
  [İddaa basketbol bülteni](https://www.iddaa.com/program/basketbol)
- [x] İzole botta `/barem NBA`, `/barem EUROLEAGUE` ve
  `/barem EUROCUP` bülteni açar. Gelecekteki bir maçla tekil eşleşme
  sağlandığında Piyasa menüsündeki İddaa düğmesinde ilk tahmin ile
  ilk yarı baremi arasındaki sayı farkı gösterilir. İddaa maç toplamı
  uzatmayı içerir. Karşılaştırma yalnız ilk yarı kapsamına uygulanır.
- [x] Barem kaydında kaynak belgelerinin SHA-256 özetleri, erişim zamanı,
  platform, lig, maç ve piyasa kimlikleri saklanır. İlk açılış ve
  fiyatın yayın zamanı belirsizdir. Güncel fiyat kabulü, sağlayıcının
  yayın zamanı kanıtını gerektirir. Yayın saati eksik eski fiyatlar
  arşiv etiketiyle okunabilir.
- [x] Çalışan izole süreçte ilk yarı denetimi 30 dakikada bir
  gerçekleşir. İlk okuma için yaklaşık bir dakika beklenir.
  `ZEYNAL_TEST_IDDAA_AUTO_ENABLED=0` otomatik denetimi kapatır.
  Aynı maç için otomatik kontrolde ilk kayıt muhafaza edilir.
  Karşılaştırmaya alınacak bülten kaydı maçtan beş dakikadan daha önce
  arşivlenmiş olmalıdır. İlk tahminin de maç öncesi kalıcı kayıt
  kanıtı gerekir. İki kaydın farklı saatlerde alınabildiği raporda
  belirtilir. Karşılaştırma, doğrulanmış ilk iki periyodun toplamından
  aynı maç için model ve bülten MAE'sini üretir.
- [x] `/accuracy all`, normal süre toplamı için tahmin eksi sonuç
  hatası −2 ile +3 arasında kalan ve mutlak hata en az 25 olan maçları
  doğrulanmış model grubu başına sayar.
- [x] Arşivdeki aynı maçlar üzerinde medyan sapma düzeltmesi denendi.
  Her test diliminde yalnız önceki test dilimlerinin, kesitten önce
  doğrulanmış etiketleriyle düzeltme hesaplandı. Aşağıdaki rakamlar
  arşiv raporundan yeniden üretilebilir.
- [ ] İddaa için gerçek UserLAnd ve Telegram kabulü, Avrupa liglerinde
  aktif maç kapsaması ve ilk yarı baremiyle eşleşmiş saha performansı
  bekleniyor. Kaynak doğrulaması Codex Cloud'dan gerçekleştirildi.
  Sağlayıcının açılış fiyatı yayın saati ve uzatma dahil ödeme
  doğrulaması eksik olduğundan tam maç bahis olasılığı veya avantaj
  hesaplamak için yeterli kanıt yok.

| Kronolojik Bayes QMC karşılaştırması | Maç | İlk model toplam MAE | Düzeltme toplam MAE | −2…+3 ilk → düzeltme |
| --- | ---: | ---: | ---: | ---: |
| EuroLeague aynı maçlar | 54 | 12,29 | 12,50 | 8 → 3 |
| NBA aynı maçlar | 3 | 5,34 | 15,23 | 1 → 0 |
| EuroCup uygun dilim | 0 | — | — | — |

EuroLeague arşivinin tamamında 77 maçta toplam MAE 11,83 ve toplam
RMSE 15,66. 13 maç −2…+3 bandında, 7 maç en az 25 sayı sapmıştır.
NBA'deki yedi arşiv maçında toplam MAE 10,65. Medyan düzeltmesi iki
ligde de eşleştirilmiş örnekte hatayı artırdığı için reddedildi.
Yerel inceleme `python -m hybrid_engine.total_bias_study docs/hybrid-phase845-walk-forward-20261113.json.gz` ile tekrarlanabilir.

## 26 Kasım · Telegram cihaz geri bildirimi ve yeni düzeltme

Cihazdan bildirilen çalışan sürüm `1dd714f`. Kullanıcının `/results all`
çıktısı NBA 74, EuroLeague 29, EuroCup 13 sonuç eşleşmesi bildiriyor.
Telefonun SQLite dosyası, genişletilmiş SQLite hata kodu ve bu test botunun
kimlik bilgileri Cloud ortamında bulunmadı.

### P0 · Rapor okuma ve teslim

- [x] Bir önceki SQLite okuyucu, sorgu imlecini açık tuttuğu sürede Python
  tarafındaki JSON, SHA ve kaynak doğrulamasını da aynı bir saniyeye dahil
  ediyordu. 74 kayıtlı yerel deneyde satır doğrulamasına gecikme eklenince
  `SQLITE_INTERRUPT/9` üretildi. Telefon logundaki yalın
  `OperationalError` söz konusu hatanın cihazda da aynı kodla
  gerçekleştiğini doğrulamak için yeterli değil.
- [x] Yeni çalışma zamanı okuyucusu veri okumasını doğrulamadan ayırır.
  Mevcut bileşik birincil anahtarlarla bağlanan sorgu aynı SQL süre
  sınırına sahiptir. Boyut ve satır sınırları uygulanır. JSON ve native
  doğrulama salt okunur SQLite işlemi kapandıktan sonra yapılır.
  Önceki kalite kartı yalnız ilgili fit ve tahmin zamanına kadar
  arşivlenmiş sonuçlu satırları denetler. Deneylerin sabitlenmiş
  okuyucusu kendi dosyasında kalır.
- [x] Yerel deneyde kilit için `SQLITE_BUSY/5`, geçersiz dosya için
  `SQLITE_NOTADB/26` ayrı doğrulandı. Loglar SQLite'ın birincil
  sınıfını, genişletilmiş adını ve sayısal kodunu kaydeder. Erişim,
  G/Ç, kesinti ve bütünlük sınıfları ayrıdır.
- [x] `/accuracy all` ligleri, güncel aday ve İddaa bölümlerini bağımsız
  değerlendirir. Bir lig veya aday okuyucusu hata verirse başarılı
  liglerin sonuçları teslim edilir. Başarısız lig sıfır örnek göstermez.
  Sağlayıcı zaman aşımı ayrı kodla ve süreyle raporlanır.
- [x] Telegram HTTP 502 yanıtı doğrulanmamış teslim olarak kaydedilir.
  HTML hata gövdesi teslim JSON'u gibi ayrıştırılmaz. İstek
  kütüphanesinin HTTP hata işlemesi devam eder.
- [ ] Cihazda `/accuracy all` tekrar kabulü ve telefon SQLite kodu.
  Yerel PTB testi kontrollü Bot API ile gerçekleştirilir.

### P1 · Model hatası ve kronolojik eşleştirme

Kullanıcı tarafından bildirilen cihaz örneklerinde NBA V2'nin dört
maçında V1 MAE 18,91. Sabit tempo 21,41, tahmini tempo 21,78, güncel
takım 21,62 ve aynı box kohortundaki takım kontrolü 21,27. EuroLeague
on maçında V1 11,31, tahmini tempo 11,95 ve sabit tempo 12,14. Bir NBA
güncel aday eşleşmesinde V1 12,08 ve V3 26,13. Bunlar ilk teşhis için
yeterli gözlemler. Tekil oyuncu, rakip veya parametre katkısını edinmek
için eşleşen tahmin ve kaynak kayıtlarına ihtiyaç var.

- [x] `paired_dynamic_replay` gelecekte erişilen etiket ve box-score
  verilerini dışlayarak gün bazında yeniden fit dener. Hesabın gerçek
  hazırlanma zamanı saklanır. Geçmiş replay ile yeni maç öncesi yayın
  ayrı sözleşmelerdir. Her iki modelin başarılı tahmin ettiği maçlar
  aynı normal süre sonuçlarıyla değerlendirilir.
- [x] Arşivdeki 100 ESPN belgesiyle sıkı koşu 210 final adayı inceledi.
  174 maçta origin öncesi 30 doğrulanmış sonuç koşulu sağlanmadı. 36
  maçta takımların doğrulanmış origin geçmişi yetersizdi. Eşleşmiş
  V1/V3 test skoru üretilmedi. Paket özeti `d13222a535342062a95acf94635b97045ea3e5a15cc5aec9722d9ad5067d2ba3`.
- [x] Önceden tanımlı 24 saat kaynak erişim varsayımlı keşif replay'i aynı
  64 maçta Bayes V1 çekirdeği toplam MAE 14,48 / RMSE 17,55 ve
  güncellenmiş takım çekirdeği 14,28 / 17,63 verdi. Box temponun aynı
  beş maçlık çekirdek denemesinde sabit tempo MAE 17,07 ve güncel
  tempo MAE 16,07. Bulgular küçük örnek ve farklı erişim koşullarına
  bağlıdır. Saha verisi güncel temponun NBA örneğinde ters yönde
  hareket ettiğini gösteriyor.
- [x] İleri aday raporu eşleşen maçlarda puan kaymasının yönünü, toplam
  hata varyasyonunu, fit yaşını, mevcut box tempo tahminini ve kayıt
  varsa çeyrek hatasını ölçer. V3'te 14 günlük yarı ömür ve son on
  maçtan tahmini tempo skor ortalamasına doğrudan girer. Küçültülmüş
  kovaryans ve parametre belirsizliği örnek yollarını ve aralıkları
  etkiler. Bu ölçümler etki nedenini tek başına kanıtlamaz.
- [ ] Telefonun 116 eşleşme tabanında ve ayrı V2/V3 artefaktlarında
  bağımsız karşılaştırma. Kadro, ölçülmüş tempo, gerçek piyasa ve
  rakip etkisine tekil nedensel hata payı atanmadı.

Sıkı replay komutu:

```bash
python -m hybrid_engine.paired_dynamic_replay --receipts-directory /tmp/zeynal-p1-native --year 2026
```

### P2 · Oyuncu kimliği ve rotasyon

- [x] `CURRENT_PLAYER_WITHOUT_PRIOR_ROTATION_HISTORY` koşulu mevcut
  kadrodaki bir kimlik için son altı uygun aynı takım box-score
  maçında satır bulunmadığında ve iki kaynaktan doğrulanmış OUT kaydı
  da bulunmadığında oluşur. Tarihsel fit oyuncu sayısı, bugün oynanacak
  maçtaki dakika kanıtını sağlamaz.
- [x] Sınırlı ek geçmiş yolu, son altı maçta bulunmayan oyuncu için
  geçerli maç raporunda açık `Available`, kesin ESPN kimliği ve aynı
  takımda en az üç doğrulanmış pozitif dakika kaydı gerektirir. Altı
  eski box-score adayı en fazla 30 günlük geçmişten seçilir. Kullanılan
  ham dakika, kaynak saati ve SHA ile tekrar denetlenir. Kadro ve
  rapor saatleri yeniden kontrol edilir. Önceki takımdaki dakikalar
  taşınmaz. Yakın maçta ek kaynak işi başlatılmaz ve beş dakikalık
  kalıcı kayıt sınırı geçilemez.
- [x] Eksik kimlik denetimi daha eski aynı takım satırı, incelenen
  box'larda başka takım satırı ve incelenen box'larda hiç satır
  olmaması şeklinde kanıtı gösterir.
- [ ] Telefonun gerçek blokajına yol açan kimlikler, ilk saha dakika
  yayını ve bağımsız hücum, rakip savunması ve tempo ölçümü. Mevcut
  oyuncu adayının sayısal kapsamı kendi takımının sayı katkısıdır.

### P3 · Araştırma sırası

- [x] Güncel skor üretimi hazırlık ve V2 işlerinden önce çalışır.
  Kayıtlı V3 deneyinin kendi turunda skor işi gölge fitinden önce
  çalışır. 100 örnek gereksinimi yalnız gölge kalibrasyona uygulanır.
  Sonuç okuma hatasında adayın yayın bilgisi ve hedef maç durumu
  raporda kalır. Aşamalar işlem süresi ve kuyruk beklemesini ayrı
  ölçer. Beş dakika kuralı ve kayıt sırası korunur.
- [x] Yeni araştırma kaynak pinleri ayrı protokol dizinlerine gider.
  Önceki planlar, yayınlar ve dakika arşivi kendi kayıtlarıyla durur.
  Önceki ve yeni protokol sayaçları ortak ileri deney gibi sayılmaz.
- [ ] Android ve gerçek Telegram üzerinde yeni sürümün kuyruk süreleri,
  otomatik maç öncesi skor kaydı ve teslim kabulü.

### 26 Kasım · Cihazda performans raporu kabulü

- [x] İzole Telegram'da `/accuracy all` yanıtı, çalışan sürüm SHA'sı
  ve beklenen bölüm sayısıyla teslim günlüğüne bağlanır. Gönderim yarıda
  kalırsa Telegram'ın döndürdüğü bölüm sayısı kalır. Her bölüm için yetkili
  sohbet, bot, güncelleme, içerik ve Bot API kabulü denetlenir.
- [x] `/test acceptance` aynı çalışan süreçte son `/accuracy all`
  isteğinin kısa kanıtını döndürür. Lig başına doğrulanmış benzersiz
  sonuç eşleşmesi ve ilk yayın kanıtıyla ölçüme uygun eşleşme sayısı
  ayrı gösterilir. Bir lig okunamazsa sayı yerine hata sınıfı ve varsa
  genişletilmiş SQLite kodu gösterilir. Aday ve İddaa raporları
  bağımsız bölüm durumuna sahiptir.
- [x] Özel kimlikler, komut metni, API gövdesi ve arşiv yolları
  kabul özetine çıkmaz. Tam resmi API makbuzu, yerel teslim günlüğü
  kanıtıdır. Loopback yanıtı teslim kanıtına yükseltilmez.
- [x] Yeniden başlatmadan önceki kayıt gerekirse
  `bash scripts/run_isolated_test_bot.sh --verification-review TAM_SHA`
  aynı SHA'ya ilişkin son `/accuracy all` teslimini arşivden okur.
  Salt okunur SQLite işlemi JSON ve SHA doğrulaması öncesinde kapanır.
- [ ] Telefon kabulü. Güncel sürümü mevcut UserLAnd çalışma
  kopyasından başlatıp Telegram'da `/accuracy all` ve ardından
  `/test acceptance` gönder. SHA, `THREE_LEAGUES_READ` ve
  `LOCAL_OFFICIAL_API_RECEIPTS_VERIFIED` alanlarını kontrol et.
  Tam kabul için dönen yerel özet gerekir. Bu ölçüm modeli terfi ettirmez.

### 26 Kasım · Telefonda üç lig kabulü ve Avrupa arşiv okuma maliyeti

- [x] Kullanıcının Telegram çıktısı, `139e978` ile `MAIN_STAGING`
  sürecinde `/accuracy all` için `THREE_LEAGUES_READ` ve
  `LOCAL_OFFICIAL_API_RECEIPTS_VERIFIED` gösterdi. Beklenen ve
  doğrulanan bölüm sayısı 1/1. NBA 83/83, EuroLeague 29/24,
  EuroCup 13/13 doğrulanmış sonuç eşleşmesi / ölçüme uygun maç.
  Toplam 125 eşleşme, 120 ölçüme uygun maç. Aday ve İddaa ilk yarı
  bölümlerinin ikisinde de o anda eşleşmiş sonuç yoktu.
- [x] Cihazın lig bazında rapor okuma süreleri NBA 474 ms,
  EuroLeague 24.395 ms ve EuroCup 10.651 ms. Avrupa okuyucusu bir
  rapor boyunca aynı doğrulanmış kaynak belgesini bir kez
  çözümleyip sezon fikstürü için indeksler. İlk yayın, kaynak
  özeti, kimlik, saat, sonuç, normal süre ve uzatma denetimleri
  uygulanır. Dosya kimliği değişirse yeniden okunur.
- [x] Her iki Avrupa liginde aynı belgeleri paylaşan iki maçlık
  test raporu önceki okuyucuyla aynıdır. Ortak fikstür ve sonuç
  katalogları toplam iki kez çözülür. Yeni kaynak çağrısı
  yapılmaz. Kaydı değiştirilmiş kaynak reddedilir.
- [ ] Yeni okuyucu için telefonda süre karşılaştırması. Yukarıdaki
  24.395/10.651 ms değerleri kabulü alınan önceki sürüme aittir.
