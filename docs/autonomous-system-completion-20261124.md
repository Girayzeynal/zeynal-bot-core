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
