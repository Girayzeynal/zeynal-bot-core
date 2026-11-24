# ZEYNAL — üç başlıkta otonom tamamlama çalışma kaydı

Bu dosya oturum devam noktasıdır. Durum: **DENETİM / GELİŞTİRME SÜRÜYOR**.
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
  İlk kayıt, sürüm, plan SHA, 30 dk yenileme, 45 dk güncellik, 24 saat model
  yaşı, **T−300 yayın sınırı** ve mevcut 512 / 256 MiB kapasite politikası
  değiştirilmedi. Önceki veri taşınmaz/silinmez ve deney sıfırlanmaz.
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
