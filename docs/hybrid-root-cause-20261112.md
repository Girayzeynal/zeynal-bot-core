# PR #84 — sıfır örnek kök nedeni ve gerçek walk-forward, 12 Kasım 2026

**Karar: kabul engelli. Faz13 varsayılan kalır; main merge ve production deploy yapılmaz.**
`962e16d` üzerinden başlayan araştırmanın `09e044e` sonrası devamıdır.
Skor formülleri, mevcut skor dağılımları, dar bantlar ve V1 Telegram routing'i değiştirilmedi.

## Sıfır neden oluşuyordu?

640 tamamlanmış maçın bulunması, geçmiş tahmin zamanında hangi alanların erişilebilir
olduğunu kanıtlamıyordu. Skor ve box kayıtları hedef maçlardan sonra topluca indirilmişti.
Sıkı özellik filtresi bu saatleri doğru biçimde reddediyordu. Ayrıca hedef fikstürünün
cutoff öncesi kimlik/saat kaydı yalnızca aynı geç indirilen native catalog'da aranıyordu.
İlk hata olarak yalnızca fikstür engeli raporlanınca geçmiş özellik engeli görünmüyordu.
İki filtre artık bağımsız sayılıyor; güvenlik filtresi gevşetilmedi.

Düzeltme yerel gözlem/ingestion saatlerini geriye taşımak değildir. Doğrulanmış arşiv
sürümünün **yalnızca içerdiği alanlara** ayrı erişilebilirlik kanıtı eklenir:

- NBA: hoopR deposundaki immutable Git blob'u; SHA-1/byte boyutu, kaynak commit'i,
  aynı head commit'ini taşıyan GitHub Actions run'ının server `created_at` saati ve
  native API metadata'sı karşılaştırılır. Commit author tarihi kullanılmaz.
- EuroLeague: Wikipedia'nın immutable revision ID, native SHA-1, revision timestamp
  ve tam wikitext'i karşılaştırılır. Resmi report URL'sindeki `E2025/gameCode` ile
  sezon/maç, iki takım ve tam UTC başlangıcı eşleştirilir. CET/CEST için
  `Europe/Berlin` kullanılır; yaz saati dönüşümü testlidir. Fuzzy takım eşleştirmesi yoktur.
- Arşiv kanıtı identity, alan değerleri ve yerel saatlerin digest'ine bağlıdır.
  Sıradan JSON'daki `archive_evidence` iddiası yetki sağlamaz; native decoder'ın
  doğruladığı runtime nesnesi gerekir. Alan değişirse kanıt reddedilir.
- Geçmişte birden fazla sonuç sürümü varsa özellikler en son **o cutoff'ta erişilebilir**
  sürümü seçer. Train/validation etiketi de fit zamanında bilinen sürümdür;
  test değerlendirmesi güncel native nihai sonuca karşı yapılır. A→B→A geri düzeltmesi korunur.
  Güncel düzeltilmiş sonuca eski timestamp yapıştırılmaz.

NBA dosya adı `2027`, 2026/27 sezonunu ifade eder; regular season `season_type=2`
ile ayrılır. NumPy-repr çeyrek string'leri güvenli `literal_eval` ile çözülür.
TBD Cup slotları (-1/-2 takım ID) alınmaz. Top kaybı toplamı tutarsız
`401909962` maçının bir arşiv box satırı dışlandı; skor geçmişi bundan etkilenmedi.

ESPN `meta.lastUpdatedAt` / son oyun saati, haberler/odds dahil tüm belgenin geçmiş
yayın kanıtı sayılmadı. Güncel native clock, dosya mtime'ı ve start+24h de kullanılmadı.

## Veri envanteri ve filtre hunisi

Çalışma ortamının geçici diski yenilendiği için önceki yerel ham dosyalar artık yoktu.
GitHub'daki kod ve önceki 424 testin CI kanıtı korundu. Native kaynaklar yeni, gerçek
indirme saatleriyle tekrar alındı. Önceki envanter **640**, yeni kısmi envanter **652**
(170 NBA, 102 güncel EuroLeague, 380 önceki EuroLeague); bunlar aynı veri kesiti diye sunulmaz.
Önceki ham box dosyalarının saatleri veya içerikleri yeniden uydurulmadı.

| Lig/sezon | Tamamlanmış | Önceden bilinen fikstür | Yeterli geçmiş | İkisi birlikte | OOS test |
|---|---:|---:|---:|---:|---:|
| EuroLeague 2025/2026 | 380 | 267 | 300 | 254 | 77 |
| EuroLeague 2026/2027 | 102 | 14 | 10 | 0 | 0 |
| NBA 2026/2027 | 170 | 169 | 71 | 71 | 7 |

Arşiv tanıklarını devre dışı bırakan ablation, **aynı 652 maçta** iki filtre için de
0 verir. Tanıklarla 325 aday açılır; bunların tamamı test değildir. Kronolojik
train/validation ve label availability purge sonrasında **84 bağımsız test maçı** kalır.
EuroLeague 2025/26 test blokları 23/28/25/1 maç; NBA 4/3 maçtır. İki NBA fold'u
boş validation nedeniyle atlanır. Fold ID'leri ve purged fit etiketi pin'leri tam rapordadır.

35 public arşiv girişi (8 schedule, 7 NBA box, 8 aynı quote blob'u, 2 Euro oyuncu CSV,
10 Wiki revision) doğrulandı. Kaynak sayısı bağımsız maç sayısı değildir.
Arşiv NBA box kapsamı 159/170; EuroLeague için oyuncu toplamlarından eksik takım
turnover/rebound alanları sıfır varsayılarak box üretilmedi. Bu yüzden EL possession
çıkarmıyor. Bir Wiki isteği HTTP 429 verdi; zorlanmadan durduruldu ve veri boşluğu korundu.

Başlangıç saati native nihai kayıtla uyuşmayan 233 arşiv satırı, aynı-gün nihai durumu
kanıtlanamayan 12 Wiki satırı, 3 skor/periyot uyuşmazlığı ve 21 takım alias uyuşmazlığı
reddedildi. Bunlar sürüm/satır sayılarıdır, benzersiz maç sayısı değildir. Örnek ID,
ikili saat/değerler ve kaynak URL'leri `sampled_exclusions` içinde saklandı.

Wiki'nin ayrı final-status bayrağı bulunmadığından gün içi sonuçlar kabul edilmez;
eski skor/periyotların native nihai sonuçla aynı olması aranır. Bu, sonradan değer
kopyalamaz fakat uzlaşan bir altküme seçerek selection bias yaratabilir; sonuçlar
bütün sezon veya gerçek zamanlı bot performansı diye genellenemez.

## Aynı maçlarda modeller

Aşağıdaki her panel kendi içinde **aynı maçları** kullanır. Brier/log loss normal süre
EV/EŞİTLİK/DEP üç sınıfı içindir; daha düşük daha iyidir. Skor MAE/RMSE iki takım
üzerinden ortalamadır. Ayrı paneller arasında sayı karşılaştırıp sıralama yapılmaz.

### EuroLeague: dağılımlar ve basit baseline

| Model | n | MAE | RMSE | Brier | Log loss |
|---|---:|---:|---:|---:|---:|
| FAZ13_MC | 77 | 7.8403 | 10.1195 | 0.4941 | 0.7888 |
| FAZ13_QMC | 77 | 7.8403 | 10.1195 | 0.4912 | 0.7842 |
| FAZ13_ANALYTIC | 77 | 7.8403 | 10.1195 | 0.4912 | 0.7843 |
| BAYES_QMC | 77 | 7.6371 | 9.6262 | 0.4736 | 0.7686 |
| LEAGUE_MEAN | 77 | 8.2613 | 10.6216 | 0.5370 | 0.8351 |
| RECENT_POINTS_FOR | 77 | 8.3117 | 10.5351 | 0.4643 | 0.7591 |

### EuroLeague: öğrenilmiş modeller, ortak 53 maç

| Model | n | MAE | RMSE | Brier | Log loss |
|---|---:|---:|---:|---:|---:|
| FAZ13_MC | 53 | 8.0000 | 10.2477 | 0.5282 | 0.8591 |
| BAYES_QMC | 53 | 7.6114 | 9.5973 | 0.4780 | 0.8084 |
| LIGHTGBM | 53 | 8.6049 | 10.7822 | 0.5015 | 0.8330 |
| CATBOOST | 53 | 8.4140 | 10.4299 | 0.4726 | 0.7965 |
| ENSEMBLE | 53 | 7.8435 | 9.7287 | 0.4739 | 0.8041 |
| VALIDATION_SELECTED | 53 | 7.9269 | 9.8769 | 0.4608 | 0.7852 |

### NBA: possession, yalnızca 7 maç

| Model | n | MAE | RMSE | Brier | Log loss |
|---|---:|---:|---:|---:|---:|
| FAZ13_MC | 7 | 7.3303 | 8.4926 | 0.4130 | 0.6273 |
| POSSESSION_MC | 7 | 7.4916 | 8.5454 | 0.4337 | 0.6479 |
| POSSESSION_ANALYTIC | 7 | 7.4916 | 8.5454 | 0.4322 | 0.6453 |

LightGBM/CatBoost toplam skor coverage'ı 54 maçtır; son fold'da yeterli residual
kalibrasyonu bulunmadığı için dağılım/ensemble ortak paneli 53'e düşer. İki sayıyı
aynı örneklem diye karşılaştırmıyoruz. NBA ML ve EuroLeague possession için ortak
karşılaştırma yapılamadı. Sekiz talep edilen modelin tamamına ortak örneklem **0**;
uygun altpaneller ve Faz13 ile eşleşmiş ikili karşılaştırmalar ayrıca raporlandı.

Ensemble yalnızca geçmiş validation'dan öğrenir. EL fold 1'de 30 validation ile
Bayes 0.8093 / CatBoost 0.1907; fold 2'de 40 validation ile Bayes 0.5683 /
CatBoost 0.1792 / üç Faz13 dağılımının her biri yaklaşık 0.0842 ağırlık alır.
Diğer fold'larda yeterli validation yoktur; ağırlık uydurulmaz. Validation-selected
adaylar sırasıyla CatBoost/Bayes'tir; test skorları seçim veya ağırlık fit'inde kullanılmaz.

### Belirsizlik ve kabul

EL Bayes MAE farkı **−0.2032**, gün-küme bootstrap aralığı **[−1.0199, +0.6241]**.
RMSE farkı −0.4933, aralığı [−1.1626, +0.1251]. Ensemble'ın eşleşmiş 53 maçta
MAE farkı −0.1565, aralığı [−0.8905, +0.7337]. Önceden validation ile seçilen
adayın MAE farkı −0.0731, aralığı [−1.0147, +1.0475]; yalnızca 16 gün kümesi vardır.
Hiçbiri güvenilir üstünlük kanıtlamaz. NBA 7 maç, güvenilir çıkarım için yetersizdir;
yeterli gün kümesi olmadığında aralık hesaplanmış gibi gösterilmez.

Bunlar TSİ maç-günü kümelerini birlikte yeniden örnekler; 7 karşılaştırma/endpoint
ailesinde Bonferroni ayarı vardır. Market aralıklarında 18 barem hücresi ailesi kullanılır;
bütün modeller ve piyasalar için tek bir global hata kontrolü iddia edilmez.
Günler arası aynı takım bağımlılığı tamamen modellenmemiştir. Daha önce incelenmiş
sezonun yeni saat kanıtıyla tekrar değerlendirilmesi yeni kör/prospektif holdout değildir.

## Piyasa baremleri ve kalibrasyon

Mevcut dar bantlar korunur: 1Q merkez ±2.5, diğerleri merkez ±5.0; her piyasa için
merkez dahil üç çizgi. Bunlar cutoff öncesi Faz13 referansından üretilen **senaryo**
çizgileridir. 1Q, 1H, toplam, ev/deplasman toplamı ve ev handikabı ayrı değerlendirilir.
Handikap H için evin kapsama eşiği ev−dep > −H'dir. ALT/İADE/ÜST normalize edilir.

Aşağıdaki tablo EL 77 aynı maçta merkez çizgisi için ham OOS Brier/log loss verir.
Bu tablo kalibre edilmiş güven veya gerçek bookmaker kârlılığı değildir.

| Piyasa | Faz13 Brier | Bayes Brier | Brier fark aralığı | Faz13 log loss | Bayes log loss |
|---|---:|---:|---|---:|---:|
| 1Q | 0.5403 | 0.4569 | [-0.1670, +0.0028] | 0.7735 | 0.6761 |
| 1H | 0.5342 | 0.4764 | [-0.1792, +0.0642] | 0.7299 | 0.6708 |
| TOTAL | 0.4974 | 0.4397 | [-0.1279, +0.0217] | 0.6921 | 0.6308 |
| HOME | 0.5017 | 0.5103 | [-0.0662, +0.0951] | 0.6997 | 0.7088 |
| AWAY | 0.5112 | 0.4538 | [-0.1477, +0.0193] | 0.7237 | 0.6660 |
| HOME_HANDICAP | 0.5046 | 0.4664 | [-0.1287, +0.0499] | 0.6989 | 0.6604 |

Her model/piyasa/çizginin ALT ve ÜST kalibrasyon eğrileri, 10 bin sayıları ve Wilson
%95 aralıkları tam JSON'dadır. [Örnek eğri görseli](hybrid-market-calibration-20261112.svg)
aynı 77 maçta Faz13/Bayes karşılaştırır. Seyrek binler açıkça gösterilir.
Kalibratör test etiketleriyle fit edilmedi; grafik ham OOS olasılık denetimidir.

Bulunan 7.942 NBA quote kaydı 30 Temmuz 2020–14 Haziran 2026 aralığındadır.
2026/27 cohort maç ID'leriyle eşleşme **0**. Eski sezon quote'ları veya maç sonu
`snapshot` sütunu yeni maçlar için geçmiş erişim kanıtı sayılmaz.
Gerçek piyasa baremleri üzerinde performans/kazanç doğrulaması **eksiktir**.

Doğrulanmış aynı-model/aynı-barem kalibrasyon profili **0**. 100 geçmiş fit +
sonraki 100 bağımsız audit koşulu gevşetilmedi. Kadro/sakatlık kanıtı da eksiktir;
yeni motorda doğrulanmamış yüksek güven yüzdesi gösterilmez. V1 çıktısı değiştirilmedi.

## Testler, kaynak bütçesi ve güvenlik

**437/437 yerel test başarılı:** önceki 424 + 13 yeni arşiv/etiket/kanıt regresyonu.
Native ML backend'leri kurulu yerel ortamda test edildi; mevcut V1 Telegram regresyonları geçti.
734 fit etiketi sürümü, 732 tahmin trace'i (model/politika satırları) ve 13.140
normalize piyasa çizgisi denetlendi. Bunlar 84 bağımsız maçtan fazla veri varmış
anlamına gelmez. Label cut, fold/ensemble ID ayrımı ve predictor cut hatada durur.

Çalışma süresi yaklaşık **76.08 saniye**, offline eğitim dahil tepe RSS **298.28 MiB**.
Bu ağır araştırma işi Telegram isteğinde çalıştırılmadı ve 256 MiB runtime başarısı
diye sunulmaz. Tek BLAS/OpenMP thread kullanıldı; bu koşuda kernel CPU/RAM sınırı
uygulanmadı. Model bazında p50/p95 süreleri tam sonuç dosyasındadır.

`09e044e` üzerindeki önceki portable Telegram + ML testi (143.04 MiB,
kernel RLIMIT_AS 256 MiB, 1 CPU, 32 native payload, 21 yerel API-double komutu)
korunur. Güncel head üzerinde aynı birleşik kaynak testi yeniden yapılmadı;
önceki sonucu güncel image sertifikası gibi göstermiyoruz. Gerçek Fly image / Telegram
internet teslimatı bu araştırma turunda test edilmedi. Üretim zaten Faz13'te kalır.

Skor motoru, dağılımlar, V1 sampler, piyasa güven politikası, production requirements,
Dockerfile, fly.toml ve komut routing'i `09e044e` ile byte-identical kontrol edildi.
Fly, production SQLite, volume, snapshot ve secret'lara erişilmedi/değiştirilmedi.
Main ve deploy yetkisi kullanılmadı. Ham kaynaklar public repoya eklenmedi;
kaynak erişim/eğitim izni sözleşmesel olarak doğrulanmış sayılmaz.

## Kanıt ve tekrar çalıştırma

- [Özet, pin'ler ve arşiv kaynak listesi](hybrid-root-cause-evidence-20261112.json)
- [Tam walk-forward tahminleri, fold'lar, metrikler](hybrid-walkforward-20261112.json.gz)
- [Filtre ablation, aynı maç panelleri, quote denetimi](hybrid-root-cause-20261112.json.gz)
- Girdi kapsülü: `/workspace/research-artifacts/hybrid-rca-inputs-20261112.tar.gz`.
  74 dosya / yaklaşık 2.97 MB. SHA-256 özet JSON'dadır. Capsule yalnızca araştırma
  kaynakları içerir; manifest dosyaları `/workspace/scratch` altındaki özgün yolları gösterir.

```sh
python -m pip install -r requirements.txt -r requirements-hybrid-research.txt
# Girdi kapsülünü /workspace/scratch altına açtıktan sonra:
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m hybrid_engine.acceptance \
  --manifest /workspace/scratch/rca-public/witnessed-manifest.json \
  --output-directory /workspace/scratch/replayed-reports
# Üretilen strict-acceptance JSON yolu ile:
python -m hybrid_engine.root_cause \
  --manifest /workspace/scratch/rca-public/witnessed-manifest.json \
  --backtest-report /absolute/path/strict-acceptance-result.json \
  --output /workspace/scratch/replayed-root-cause.json
python -m unittest discover -s tests -v
```

**Kalan kabul engelleri:** istatistiksel üstünlük, daha geniş NBA/EL güncel OOS,
EL possession için geçmiş tam takım box istatistikleri, gerçek barem/quote erişim
kanıtı, bağımsız kalibrasyon/audit örnekleri, maç öncesi kadro ve güncel image kaynak
sınırı. Başarılı test ve kök neden düzeltmesi bunların yerine geçmez.
