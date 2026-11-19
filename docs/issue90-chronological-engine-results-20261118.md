# Issue #90 — kaynak, model ve sonuç zinciri: ek denetim sonuçları

Önceki iş: PR #89–94 korunmuştur. Bu değişiklik #94 (`93f8bbf`) üzerine
ayrı dalda hazırlanmıştır. İlk kök neden raporu kod değişikliklerinden önce
`e0caca2` ile kaydedildi; son cihaz notları `d6a99b9` ile eklendi.
İlgili rapor: [kök nedenler](issue90-p0-followup-root-cause-20261118.md).

## Karar

**NO_GO.** Yeni model üstünlüğü, kalibrasyon veya üretime hazırlık kanıtlanmadı.
Mevcut FAZ13, donmuş Bayes V1, kayıtlı V2/V3 protokolleri değiştirilmedi.
Yeni araştırma replay'leri canlı `/accuracy` veya 100 maç / 20 TSİ günü /
%80 kapsam kabul kohortuna eklenmedi. Kaynak kullanım izni bu çalışma ile
ayrıca doğrulanmış değildir.

## Giderilen ve açıklığa kavuşturulan noktalar

- `research_history_union.py`: aynı gerçek maçın scoreboard ve summary
  belgelerindeki ek `team_statistics` farkı artık yeni araştırma görünümünde
  sahte sonuç çelişkisi üretmiyor. Kimlik, tarih, ev/deplasman, final ve
  periyot çelişkileri reddediliyor. Her belge sürümü kendi SHA ve erişim
  saatinde korunuyor. Bu, birleşik tarihsel replay düzeltmesidir; mevcut
  V2 `FeatureStore` zaten kataloğu tek tek okuduğu için çalışan V2'nin bu
  nedenle bozulduğu iddia edilmiyor. Eski yayınlar yeniden imzalanmadı.
- `runtime_identity.py`, `main.py`, `test_bot.py`: yüklenen servis zinciri,
  bildirilen release SHA ve gerçekten handler'a dönen son raporun model ve
  snapshot digestleri gözlemlenebilir. Yeni salt-okunur `/analysis-runtime`
  HTTP yolu ve yetkili test botunda `/test runtime`. `/ready` sözleşmesi
  korunuyor. İlk analiz yapılmadan model kullanıldı denmiyor. Bu gözlem
  Telegram teslim kaydı değildir; ledger yolu, anahtar ve ham kaynak metni
  dışa aktarılmıyor. Üretime dağıtılmadı.
- `quality_report.py`: mevcut `--error-review` artık raporda zaten hesaplanan
  eşlenmiş donmuş-model / yayımlanmamış-baseline MAE/RMSE karşılaştırmasını,
  ilk üç vakada iki signed error değerini, model/snapshot/maç kimliklerini,
  UTC/İstanbul saatini, fit yaşını ve OT dışlanan sayıyı terminalde gösteriyor.
  Bekleyenler başlamış / başlamamış / saati bilinmeyen olarak ayrılıyor.
  Profil yoksa baseline `null`, örnek sayısı 0; sahte başarı yok.

`verified_analysis.py`, `faz13_engine`, `prematch_monte_carlo.py`,
`hybrid_engine/models.py`, `forecast_error_review.py` ve `quality_monitor.py`
kaynakları incelendi; eski model semantiği ve protokol pinleri korunarak
referans bırakıldı. Farklı tarihlerdeki TOR–NYK / MIN–POR maçları isimden
birleştirilmedi. Normal süre beraberliği uzatmalı final ile karıştırılmadı.

## Gerçek kaynak ve kronolojik deney

[Kanıt indeksi](evidence/issue90-engine-study-index-20261118.json) paket,
rapor ve kaynak dosyası SHA'larını içerir. 20 Ekim–17 Kasım 2026 için 29
ESPN günlük isteği HTTP 200 ile alındı: 210 maç. Korunmuş paketten 71 eski
native summary belgesi değişmeden eklendi. Toplam 100 native receipt,
281 çekirdek sonuç sürümü, 71 box'lı maç; box doğrulama reddi 0.
İlk tarih-aralığı denemesi HTTP 400 verdi; bu başarısız istek eğitim kaydı
olarak kullanılmadı. Sonra desteklenen günlük sorgular kullanıldı. Ücretli
servis, kota/anahtar değişikliği veya 429 aşma işlemi yapılmadı.

İki ayrı koşu:

1. **STRICT / PIT_PROVEN_BACKTEST:** geçmiş origin'den önce bilinen yeterli
   kaynak yok. `ABSTAIN_INSUFFICIENT_PRE_ORIGIN_TRAINING`; hiçbir performans
   skoru veya kalibrasyon uydurulmadı.
2. **AVAILABILITY_ASSUMED_RESEARCH:** mevcut açık 24 saat tarihsel erişim
   varsayımı. Receipt saatleri değiştirilmedi. Bu yalnız keşif replay'idir;
   özgün maç öncesi yayın veya yeni doğrulayıcı holdout değildir. Bütün TSİ
   günleri 50/20/30 ayrıldı; validation başlangıcı 3 Kasım 00:00 UTC, test
   başlangıcı 10 Kasım 00:00 UTC. İlk fit 90, test öncesi güncel fit 141 maç.
   Testteki 64 maçın sonuçları tüm test bloğunda fit ve özniteliklerden
   dışlandı. 9 TSİ günü var; kabul için gereken 20 gün değildir.

Aşağıdaki bütün ana satırlar **aynı 64 normal süre maçı** üzerindedir.
V1 satırı aynı donmuş çekirdeğin yeniden fit edilmiş araştırma replay'idir;
kullanıcının özgün yayımlanmış V1 tahminleri yerine geçmez. V2 satırları
mevcut hiyerarşinin güncellenmiş takım çekirdeğidir; tam scheduled V2
box/kadro pipeline'ı veya yeni yayımlanmış V2 tahmini değildir.

| Araştırma yolu | Toplam MAE | Toplam RMSE | Toplam bias | ML Brier | ML log loss | %90 bant kapsama |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FAZ13 native referans | 14.4371 | 17.7372 | -2.1930 | 0.5112 | 0.8610 | 57/64 |
| Yalnız skor, MC | 14.4371 | 17.7372 | -2.1930 | 0.5114 | 0.8636 | 56/64 |
| + rakip gücü düzeltmesi | 14.2058 | 17.5527 | -2.3111 | 0.5063 | 0.8614 | 55/64 |
| Donmuş Bayes V1, MC | 14.4761 | 17.5460 | -1.4537 | 0.5156 | 0.8677 | 59/64 |
| Donmuş Bayes V1, RQMC | 14.4761 | 17.5460 | -1.4537 | 0.5153 | 0.8674 | 61/64 |
| Güncellenmiş takım çekirdeği, MC | 14.2803 | 17.6279 | -2.2564 | 0.5145 | 0.8660 | 58/64 |
| Güncellenmiş takım çekirdeği, RQMC | 14.2803 | 17.6279 | -2.2564 | 0.5141 | 0.8669 | 58/64 |

Brier üç sınıflı ev/normal-süre-eşitliği/deplasman kare hata toplamı
ortalamasıdır (0–2); ikili bahis galibi Brier'ı değildir. Kalibre edilmiş
olasılık ve güven endeksi yok. Kapsama burada yalnız betimsel frekanstır.

Güncellenmiş çekirdeğin FAZ13'e karşı toplam MAE farkı -0.1568; TSİ günü
kümeli, 13 metrik için düzeltilmiş keşif aralığı **[-0.5331, +0.1807]**.
Sıfırı içeriyor. Tekrarlanan takımların günler arası bağımlılığı tam
modellenmedi; çok model denemesinden seçilmiş üstünlük iddiası yapılamaz.

### Periyot ve ilk yarı

| Yol | Takım MAE | Takım 1H MAE | Q1 / Q2 / Q3 / Q4 toplam MAE |
| --- | ---: | ---: | --- |
| FAZ13 | 9.7364 | 6.4862 | 6.3447 / 6.3734 / 7.0074 / 6.7629 |
| Donmuş Bayes RQMC | 9.7326 | 6.4509 | 6.4235 / 6.4186 / 6.9378 / 6.6836 |
| Güncel takım RQMC | 9.7033 | 6.4659 | 6.3154 / 6.3868 / 6.9921 / 6.7754 |

Tam raporda takım/periyot, çeyrek toplam, iki yarı ve fark MAE/RMSE/bias,
ham reliability bins, kapsama ve ortak-fixture karşılaştırmaları bulunur.

### Box verimliliği / tempo ablasyonu: ayrı küçük kohort

Yalnız **5 eşleşen test maçı, 2 TSİ günü** için yeterli eski box ve takım
geçmişi vardı. Aynı rate girdileri ve aynı maçlar üzerinde:

| Yol | Toplam MAE | Toplam RMSE | ML Brier |
| --- | ---: | ---: | ---: |
| FAZ13, yalnız bu aynı 5 maç | 14.8089 | 16.6261 | 0.5734 |
| Aynı verimlilik + sabit lig pace tahmini | 17.0732 | 18.3537 | 0.5507 |
| Aynı verimlilik + yakın takım pace tahmini | 16.0702 | 17.4668 | 0.5512 |

Yakın pace sabit pace'e göre bu küçük örnekte daha iyi; ikisi de aynı
maçlardaki FAZ13 toplam MAE'sinden kötü. `INSUFFICIENT_DAY_CLUSTERS_FOR_CLAIM`.
Bunlar **FGA + 0.44 FTA − ORB + TOV box tahmini**, PBP'den ölçülmüş
pozisyon sayısı değildir. OT maçları bu rate fit'ine alınmadı. Önceden
kanıtlı oyuncu dakika maruziyeti, rotasyon, bağımsız seyahat/dinlenme
katsayısı, native ödeme sözleşmeli bookmaker fiyatı ve yayımlanmış V3
karşılaştırması burada yok: ilgili karşılaştırmalar **ABSTAIN / NOT_VERIFIED**.
Mevcut V3 kodu tekrar yazılmadı veya bu replay adıyla yeniden paketlenmedi.

### Simülasyon ve piyasa sınırı

Her destekli MC/RQMC yolu gerçek 10.000 tamsayı senaryosu ile sınandı.
Senaryo SHA, örnek ortalaması, nokta/örnek farkı, takım korelasyonu ve
çeyrek toplam korelasyonu raporlandı. Bayes V1 paylaştırması ortalama
çeyrek korelasyonunu yaklaşık **0.988** yapıyor; FAZ13 Gamma izinde
**-0.078**. Bunlar model yapısı tanısıdır, gerçek maç/PBP korelasyonunun
öğrenildiği iddiası değildir. Örnek sayısını artırmak bu sınırı çözmez.

Gerçek bookmaker Brier/edge karşılaştırması **NOT_VERIFIED, n=0**.
Bütün modellerde aynı önceden tanımlanmış FAZ13 referans baremi kullanıldı;
O/U Brier açıkça `NOT_BOOKMAKER` senaryosudur. Örneğin FAZ13 0.5030,
güncel takım RQMC 0.4963. Eksik fiyat saatleri, uzatma kuralları, kadro
veya kalibrasyon uydurulmadı. Yeni kalibrasyon eğitilmedi; eski PR'lerdeki
ayrı aday/eğitim/holdout ve reddetme kapıları korunuyor.

## Özgün maç öncesi kanıt: Philadelphia–Indiana

Native kaynak → fixture → öznitelikler → model → kovaryans → 10k → arşiv →
final zinciri [ayrı kanıtta](evidence/issue90-prospective-trace-20261118.json.gz).

- ESPN `401909985`, canonical
  `2295e83b287fc5084e916c78226c2f05e06ae299a3299f4fb807495f9e12fabf`.
- Özgün snapshot SHA
  `30e32e06461cc83123fcc99b46a79d9dbaf1be3b0f2c5ebc6448341ed25a5343`.
- Üretim ve ilk arşiv 15.11.2026 **11:14:05 UTC**, başlangıç **18:00 UTC**
  / **21:00 TSİ**. Bu, telefon metnindeki farklı dakika/yuvarlamadan ayrı
  native paket kanıtıdır.
- 170 eğitim maçı, fit yaşı 215144 saniye. Native kaynaklar ve girdiler
  özgün tahmin saatinden önce; tam skor ortalaması donmuş katsayılardan.
- Tahmin toplamı 221.788918; normal süre gerçek 131–124 = 255;
  hata **-33.211082**. Aynı önceden dondurulmuş son-N girdilerinin hiç
  yayımlanmamış referansı 220.05; hata **-34.95**. Bu maçta basit referans
  daha iyi değil. Bir maçtan neden veya üstünlük çıkarılamaz.
- Predictive covariance
  `[[168.2147143,-0.3148931],[-0.3148931,168.2140001]]`.
- RQMC 10000 örneğin SHA'sı
  `68bee56e5eaccdc3835cf0a3240cf7ebb3f5290710a53538d31d91d9eff797a6`
  tam yeniden üretildi. Fit/yeni tahmin yapılmadı.
- Resmî native final yalnız **geçici SQLite kopyasına** işlendi. Bütün
  özgün tahmin satırlarının byte içeriği ve kaynak tar paketi SHA'sı aynı;
  kaynak/model audit bulgusu 0. Gerçek UserLAnd/Fly verisine yazılmadı.
- Bu örnekte bookmaker ödeme/fiyat kanıtı eksik; tam piyasa edge zinciri
  **NOT_VERIFIED**. 23 cihaz sonucunun tamamına erişildiği iddiası yok.

## Gerçek çalışma durumu ve Telegram

Üretim `/ready` salt-okunur GET: HTTP 200, `ready=true`, bildirilen SHA
`dacec114341edd08bd54d631f1128f0624eccf2a`. Model digest/servis kimliği bu
eski endpoint'ten görülemiyor; **üretim motorunun gerçek analiz kimliği
NOT_VERIFIED**. Yeni runtime endpoint'i üretime dağıtılmadı.

Cloud `python -m hybrid_engine.test_bot --preflight`:
`NOT_CONFIGURED`; özel test token/ID/username/chat eksik.
Gerçek Telegram `/analyze`, `/accuracy`, `/compare` teslimi **NOT_VERIFIED**.
Yerel PTB handler/Bot API double ve localhost HTTP kontrolü bu eksikliği
kapatmış sayılmadı. Mevcut anahtarlar okunup başka botta kullanılmadı.

Cihazda bu dal güncellendikten sonra, her Telegram komutunu **ayrı mesaj**
olarak gönderin; terminal `/test` komutunu çalıştırmaz:

```text
/test runtime
/test data
/analyze NBA 2026-11-17 Boston Celtics vs Orlando Magic
/accuracy NBA
/compare NBA 401909994
/predictions EUROLEAGUE
/predictions EUROCUP
```

Arşivdeki Boston komutu yeni tahmin üretmemeli. `/test runtime` ilk analizden
önce `SERVICE_LOADED_ANALYSIS_NOT_OBSERVED`, sonra handler'a dönen son raporun
kaynak kimliğini göstermeli; başarı yalnız gerçek Telegram cevabı/teslim
kaydıyla doğrulanabilir. Güncel yeni maç testi için botun resmî `/nba`
listesindeki başlamamış bir maç seçilmeli; geçmiş maça yeni PREMATCH yok.

Cihazda 23 maçın mevcut girdilerinden eşlenmiş karşılaştırmayı görmek için:

```bash
bash ~/zeynal-hybrid-844/scripts/run_isolated_test_bot.sh --error-review
```

Bu offline mod botu durdurmaz, Git pull/Telegram/source sorgusu yapmaz;
veritabanını salt-okunur inceler, ayrı quality raporu oluşturur. Özet artık
iki modelin aynı-maç MAE/RMSE'sini ve ilk üç vakanın signed error'larını
basar. Cihaz çıktısındaki 39/23/16 sayıları kullanıcı bildirimi olarak
korundu; burada yeni çalıştırılmış 23-maç karşılaştırması gösterilmedi.

## Tekrar üretme

```bash
mkdir -p /tmp/zeynal-issue90-native
tar -xzf docs/evidence/issue90-chronological-native-20261118.tar.gz -C /tmp/zeynal-issue90-native
.venv/bin/python -B -m hybrid_engine.chronological_engine_study --receipts-directory /tmp/zeynal-issue90-native --year 2026 --output-directory /tmp/zeynal-issue90-strict
.venv/bin/python -B -m hybrid_engine.chronological_engine_study --receipts-directory /tmp/zeynal-issue90-native --year 2026 --assumed-research --output-directory /tmp/zeynal-issue90-assumed
```

Çıktı hash'i gerçek çalışma saati/runtime ölçümleri nedeniyle değişebilir;
aynı kaynak, fit ve sabit seed'li tahmin yolları değişmemelidir. Test verisi
sızıntısı testi, tüm test skorlarını değiştirip bütün tahmin/fit/girdi/sample
SHA'larının aynı kaldığını doğrular. Kaynak tarihleri geri alınmaz.

## Doğrulama ve korunma

- Tam yerel regresyon: **1592 test, 181.198 s, OK**. 23 yeni test:
  kaynak/kimlik çelişkisi ve erişim sürümü; gün bazlı ayrım/leakage;
  aynı-barem/eşlenmiş-kohort; box seçimi/OT; runtime proxy/HTTP/PTB;
  baseline görünürlüğü ve bekleyenlerin doğru ayrımı.
- Korumalı kaynak pinleri base #94 ile aynı: V1 27, V2 13, V3 9,
  Avrupa 6, canlı NBA sampler 6 dosya. Özgün native paket değişmedi.
- `git diff --check` temiz. Ana/Avrupa motoru, tarihsel skor, tahmin ledger'ı,
  model artifact'i ve kabul protokolü yeniden yazılmadı.
- Yerel Docker `--require-cgroup-limits` denemesi açıkça durdu:
  `PROVIDER_PROBE_REQUIRES_256MIB_ONE_CPU_CGROUP`. Bu Cloud Docker ortamı
  içeride 8 GiB / 2 CPU üst cgroup'unu gösteriyor; 256 MiB/1 CPU sert sınırı
  doğrulandı denmiyor. Ağsız/salt-okunur mevcut imajda sınır kontrolü hariç
  regresyon ayrıca koşuldu: **611 test, 94.159 s, OK**, peak process RSS
  124.215 MiB. `cgroup_limits_verified=false`; bu ölçüm sert limit kanıtı
  değildir. Gerçek ham loglar kanıt indeksinde SHA ile bağlıdır.
- İlk yeni test denemelerindeki fixture URL filtresi, runtime ölçüm alanı
  karşılaştırması ve test Bot API alan adı hataları düzeltildi; son 1592
  koşusunda failure/error yok. Enjekte edilmiş kaynak/timeout/lock hata
  logları negatif test senaryolarıdır, bastırılmadı.
- Gerçek cihaz arşivi ve Telegram: **NOT_VERIFIED**. Mevcut üretim diski
  `zeynal_data`, anahtarlar, Fly release ve snapshot'lara müdahale yok.
  Main merge, deploy, yeni ücretli hizmet ve otomatik promotion yapılmadı.
