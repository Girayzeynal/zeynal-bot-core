# PR #84 — üç lig arşivi, piyasa gözlemleri ve Telegram hazırlığı

**Karar: teknik doğrulama ilerledi; hibrit modelin üretim kabulü hâlâ BLOCKED. Faz13 varsayılan kalır.**
Başlangıç `9a020b120f967711d906160f54832a9ec8cd9e8b`; aynı araştırma dalında devam edildi.
Main merge, registry push ve production deploy yapılmadı. Fly yönetim API'sine,
üretim SQLite/volume/snapshot'larına veya secret değerlerine erişilmedi.

## Veri kapsamı ve zaman kanıtı

| Lig / sezon | Tamamlanmış RS maç | Periyot | Takım box | Oyuncu box | Cutoff öncesi fikstür + yeterli geçmiş | OOS test |
|---|---:|---:|---:|---:|---:|---:|
| NBA 2026/27 | 170 | 170 | 170 | 32 | 71 | 7 |
| EuroLeague 2025/26 | 380 | 380 | 380 | 380 | 254 | 77 |
| EuroLeague 2026/27 | 102 | 102 | 102 | 102 | 0 | 0 |
| EuroCup 2025/26 | 180 | 180 | 180 | 180 | 0 | 0 |
| EuroCup 2026/27 | 111 | 111 | 111 | 111 | 7 | 0 |
| **Toplam** | **943** | **943** | **943** | **805** | **332** | **84** |

Önceki 652 maç korunarak 291 EuroCup maçı eklendi. Önceki 640 maçlık kesit farklı
indirme zamanına aittir; bu sayılar aynı arşiv kesiti diye birleştirilmez.
805 yeni native box belgesi (32 NBA + 482 EL + 291 EuroCup) başarıyla normalize edildi.
NBA'nın diğer takım istatistikleri önceki GitHub arşiv sürümlerinden korunur.
Oyuncu box dakikaları maç sonu gerçeğidir; maç öncesi kadro/rotasyon sayılmaz.

EuroCup 2025/26'da `8F/4F/2F/Final` playoff kodları, E yarışmasının `PI/PO/FF`
kodlarından farklıydı. Regular-season filtresi bu nedenle duruyordu. U yarışmasına
özel whitelist ile düzeltildi; E davranışı ve eski catalog pin replay'i korundu.
Playoff belgeleri raw catalog'da korunur, RS öğrenme kohortuna karıştırılmaz.
Native sezon katılımcıları 2025'te 20, 2026'da 32 takımdır; fikstür takım kodlarıyla
bilinmeyen takım farkı **0**. Box URI ve oyuncu sezon kimlikleri U/E ayrımını korur.
Maç sayısından bağımsız tam sezon arşivi veya tüm tarihsel sezon kapsamı iddia edilmez.

Yeni istatistikler gerçek 12 Kasım indirme saatlerini taşır. Bu saatler geçmişe
çekilmedi; geçmiş maç öncesi feature/possession verisi olarak kabul edilmedi.
Native box ile eski arşiv box sürümleri birlikte tutulur; cutoff'a göre en son uygun
sürüm seçilir. Yerel geç indirme, eski geçerli arşiv sürümünü silmez.

EuroCup Wiki isteği HTTP 403 verdi; tekrar zorlanmadı. Alternatif public kaynak
[EuroCup Hub](https://github.com/tomlebedev-cloud/eurocup) için immutable JS blob'u,
Git blob SHA-1'i ve [GitHub server run head](https://github.com/tomlebedev-cloud/eurocup/actions/runs/42908379933)
bağlandı: `fd46a45a48f4383d43346c53db15694fbc3c7a9b`, 10 Kasım 2026 21:47:08 UTC.
Yalnızca JSON `SEASON/GAMES` alanları çözülür. JS **çalıştırılmaz**; üçüncü tarafın
`pred/MODEL`, sezon ortalamaları ve oyuncu projeksiyonları içeri alınmaz.

Resmi U maç kodu, iki takım, tam UTC saat, final/periyot aritmetiği ve native son
kayıt eşleşir. Ayrı final-status bayrağı olmadığından aynı UTC günündeki final
iddiaları reddedilir; native final uzlaşması aranır. Böylece 7 güncel EuroCup hedefi
sıkı feature koşulunu sağlar. **Bunlar OOS test değildir:** benzersiz kickoff sayısı
walk-forward için gereken 20'nin altındadır. Eski EuroCup sezonuna timestamp taşınmaz.
Native final uzlaşması ve saat değişikliği elemesi seçilmiş bir altküme yaratabilir;
yaygın sezon performansı olarak genellenemez. Receipt'ler pinned API gözlemleridir,
kripto imzalı bağımsız zaman damgaları değildir.

## Faz13 karşılaştırması

Kronolojik fold'lar, fit zamanında erişilebilir etiket sürümleri, validation-only
ensemble ve testten önce aday seçimi korunur. Yeni veriyle tam sıkı backtest yeniden
çalıştı. **Önceki 732 model/politika satırının skorları, winner olasılıkları ve tüm
barem grid'leri birebir aynı kaldı.** Bunlar 732 bağımsız maç değil, 84 test maçıdır.
Veri miktarı arttı diye yeni test isabeti veya iyileşme iddia edilmedi.

V1 skor/sampler/renderer dosyaları, dağılımlar ve mevcut piyasa güven politikası
`9a020b1` ile byte-identical kaldı. Mevcut grid mantığı 1Q için merkez ±2.5,
diğerleri için merkez ±5.0 olarak korundu. Main'de yalnızca iki readonly rapor
komutu kaydedildi; `/nba` ve `/analyze` yanıt biçimi ve varsayılan motoru korunur.

| Aynı maç paneli | n | Model | Takım MAE | RMSE | Normal süre winner Brier |
|---|---:|---|---:|---:|---:|
| EL skor / dağılım | 77 | Faz13 MC | 7.8403 | 10.1195 | 0.4941 |
| EL skor / dağılım | 77 | Bayesian QMC | 7.6371 | 9.6262 | 0.4736 |
| EL öğrenilmiş ortak panel | 53 | Faz13 MC | 8.0000 | 10.2477 | 0.5282 |
| EL öğrenilmiş ortak panel | 53 | LightGBM | 8.6049 | 10.7822 | 0.5015 |
| EL öğrenilmiş ortak panel | 53 | CatBoost | 8.4140 | 10.4299 | 0.4726 |
| EL öğrenilmiş ortak panel | 53 | Ensemble | 7.8435 | 9.7287 | 0.4739 |
| NBA possession paneli | 7 | Faz13 MC | 7.3303 | 8.4926 | 0.4130 |
| NBA possession paneli | 7 | Possession MC | 7.4916 | 8.5454 | 0.4337 |

Farklı n panelleri arasında sıralama yapılmaz. EL Bayesian MAE farkı −0.2032,
maç-günü küme aralığı **[−1.0199, +0.6241]**; ensemble farkı −0.1565,
**[−0.8905, +0.7337]**. Validation-selected aday için fark −0.0731,
**[−1.0147, +1.0475]**. Sıfır dışlanmadığından güvenilir üstünlük gösterilmedi.
NBA n=7 ile güvenilir üstünlük veya kalibrasyon sonucu çıkarılamaz.

MC/QMC/analitik, 1Q/1H/toplam/takım toplamı/handikap MAE-RMSE, Brier/log loss,
ALT/ÜST kalibrasyon binleri, Wilson aralıkları ve eşleşmiş fark aralıkları tam JSON'dadır.
[Önceki kalibrasyon görseli](hybrid-market-calibration-20261112.svg) aynı 77 maç için
geçerliliğini korur. Gaussian Faz13 analitik yöntemi ile orijinal V1 gamma periyot
yasası ayrı modellerdir. Korelasyonlu Bayesian analitik lattice desteklenmez;
Bayes QMC kullanır. Bu eksik, hesaplanmış analitik başarı gibi sunulmaz.
Günler arası aynı takım bağımlılığı ve eski sezona önceki araştırma maruziyeti sınırlardır.

## Gerçek piyasa gözlemleri

ESPN'nin DraftKings olarak etiketlediği **4 yaklaşan NBA maçı / 8 gerçek çizgi**
(4 toplam + 4 ev handikabı) native belge hash'i, sağlayıcı/maç kimliği, iki yön fiyatı
ve gerçek indirme saatiyle donduruldu. 13 native fikstürün 9'unda quote yoktu;
1Q, 1H veya takım toplamı baremi uydurulmadı. Son gözlemler 12 Kasım 2026
**20:25:42–43 TSİ**, izole araştırma kayıtları 20:25:56 TSİ'de oluşturuldu.

| ESPN maç ID | Toplam çizgisi | Ev handikabı |
|---|---:|---:|
| 401909976 | 223.5 | −8.5 |
| 401909977 | 220.5 | +10.5 |
| 401909978 | 226.5 | −5.5 |
| 401909979 | 214.5 | −6.5 |

Bu, doğrudan bookmaker'dan icra edilebilir fiyat veya upstream quote yaşı kanıtı
değildir. Native `close` alanı kesin kapanış zamanı diye yorumlanmaz.
Dört maç için Faz13/Bayes/possession **12 izole prospektif araştırma projeksiyonu**
kaydedildi; production SQLite veya Telegram'a aktarılmadı. Model kimliği, veri
kimliğinden ayrıdır; aynı modelin hash'i maç değişti diye değişmez. Eğitim/feature
cutoff, gerçek oluşturma saati, kaynak pin'leri ve model sürümü ayrı saklanır.

ALT/ÜST koşullu yönü model olasılık kütlesinden çıkarılır; bahis önerisi değildir.
Bu modeller normal süre içindir; kaynak quote'un uzatma settlement kapsamı açıkça
kanıtlanmadı. Kadro, bağımsız kalibrasyon ve doğrulanmış model uyumu da eksiktir.
Bu yüzden **24 model/çizgi değerlendirmesinin tamamı ABSTAIN**; öneri, güven endeksi
ve doğrulanmış düşük risk etiketi üretilmedi. Raw normal-süre olasılığı, gerçek bahis
settlement olasılığına eşit gösterilmez.

Önceki 7.942 tarihsel NBA quote'u bu OOS kohortuyla hâlâ eşleşmez. Yeni 8 gözlem
gelecekteki 4 maç içindir; geçmiş testlere eklenmedi. Gerçek bookmaker OOS n=0,
doğrulanmış aynı-model/aynı-barem kalibrasyon profili n=0. 100 fit + sonraki 100
audit koşulu gevşetilmedi. Şu anda kârlılık/edge veya yüksek güven kanıtı yoktur.

## Telegram komutları ve kayıt bütünlüğü

`/accuracy [NBA|EUROLEAGUE|EUROCUP]` ve `/compare NBA maç_kimliği` kayıtlı değildi;
araştırma dalına eklendi. Compare canonical hash veya provider maç ID kabul eder.
Mevcut `/start`, `/nba` ve `/analyze` biçimi değiştirilmedi.

Raporlar SQLite'ı `mode=ro` + `query_only` ile açar; dosya/schema oluşturmaz, sonuç
indirmez, fit çalıştırmaz. Yalnızca commit receipt'i doğrulanan canlı tahminler ve
native finali tekrar doğrulanan aynı maç/normal süre sonuçları değerlendirilir.
Backtestler, unconfirmed kayıtlar ve provenance'sız legacy sonuçlar başarıya katılmaz.
Henüz sonuç yoksa oran uydurulmaz; tek model varsa karşılaştırılacak ikinci model
olmadığı söylenir. Legacy tahmin ve sonuç tabloları değiştirilmedi.

Sonuç uzlaştırması mevcut doğrulanmış analiz akışında gerçekleştiğinde rapor
güncellenir. Bu komutlar tüm maçlar için yeni otomatik sonuç-toplama scheduler'ı
etkinleştirmez. Yeni komutlar henüz çalışan üretim botuna dağıtılmadı.

## Birleşik 256 MiB / 1 CPU testi

Yerel Docker imajı üretim Dockerfile'ından oluşturuldu: Python 3.11.18 / NumPy 1.26.4.
Konteyner ağı kapalı, root filesystem salt okunur; yalnızca izole temp SQLite yazılır.
Gerçek PTB polling/HTTP, main `build_app`, legacy motor nesneleri, health/ready,
V1 native analiz/preflight/idempotence/renderer, yeni rapor komutları ve frozen
portable LightGBM/CatBoost + Bayesian + possession + orijinal Faz13 MC aynı süreçtedir.
ML eğitimi istek sırasında yapılmaz; SciPy/sklearn/native LightGBM/CatBoost yüklenmedi.

- **25 komut / 25 yanıt:** 1 NBA listeleme, 20 aynı NBA analizi, 1 EL analizi,
  1 desteklenmeyen EuroCup analizi, 1 accuracy, 1 compare.
- **21 başarılı V1 analiz yanıtı**, EuroCup için doğru `LEAGUE_MODEL_NOT_CONFIGURED` abstention.
- Tekrarlanan NBA istekleri için **1** snapshot; NBA + EL toplamı **2 snapshot / 2 receipt**.
  SQLite integrity `ok`, unconfirmed 0; legacy satır korundu. Accuracy/compare öncesi
  ve sonrası DB byte hash'i aynı.
- V1 cache'te **32 native payload / 15,768,035 serialized byte**, cache replacement yolu dahil.
- Tek CPU affinity; **kernel RLIMIT_AS = 268,435,456 byte**; tepe RSS **159.46 MiB**.
  Analiz hesaplama p95 yaklaşık **353 ms**. Bu internet Telegram teslimat süresi değildir.

İlk birleşik kontrol sert adres-alanı sınırında Bayesian covariance GEMM yolunda
ilerlemedi; traceback o yolu gösterdi. İsteğe bağlı bounded-workspace çıkarımı aynı
posterior quadratic form'u BLAS scratch buffer'ı istemeyen `einsum` ile hesaplar.
Varsayılan skor algoritması değiştirilmedi. Skor/periyot ve piyasa olasılıkları
iki yol arasında 1e−12 toleransla doğrulandı; eski OOS çıktıları da birebir korundu.
Docker'da BLAS/OpenMP thread sayısı 1'e sabitlendi.

Yerel daemon cgroup memory limit'i desteklemiyor. Gerçek zorlanan sınır **uygulama
sürecinin RLIMIT_AS** sınırıdır; Docker `--memory` uygulandı diye iddia edilmez.
Bu bir kaynak stresi ve yerel Telegram HTTP taklididir; gerçek internet Telegram
mesaj teslimatı veya Fly üzerinde tam-container ölçümü değildir. Bu workload dışında
sınırsız eşzamanlı kullanıcı yükü kanıtlanmadı. Main'in production modeli Faz13'tür;
hibritler bu testte kaynak yükü olarak çalışır, V1 yanıtını değiştirmez.

## Test ve kabul durumu

**472/472 yerel test başarılı: mevcut 437 + 35 yeni regresyon/entegrasyon testi.**
Yeni testler: U/E faz/ID ayrımı, native/arşiv box sürümleri, JS'den tahmin içeri almama,
readonly SQLite, sahte hash ile native sonuç değişikliğinin reddi, commit receipt,
komut routing'i, gerçek quote kontratı, uzatma kapsamı/kalibrasyonda abstention,
stabil model kimliği ve bounded posterior eşdeğerliğidir.
Native optional ML backend'leri kurulu yerel testlerde kullanıldı; base CI'daki
bağımsız portable oracle testleri de korunur. Exact-head CI sonucu PR açıklamasındadır.

**Geçenler:** veri normalizasyonu, kaynak/clock ve sızıntı mekanik denetimleri,
aynı maçlarda backtest, 472 test, yerel Docker build ve ölçülen birleşik kaynak testi.
**Üretim kabulünü geçemeyenler:** Faz13'e güvenilir üstünlük ve doğrulanmış güven profili.
**Eksikler:** daha geniş NBA/EuroCup OOS, eski EL possession için zamanında yayınlanmış
team box, geçmiş gerçek bookmaker çizgileri ve settlement kapsamı, bağımsız kalibrasyon,
maç öncesi kadro, gerçek üretim Telegram teslimatı ve Fly toplam-container ölçümü.
Bu nedenle üretim hazırlığı tamamlandı veya yeni motor daha iyi diye raporlanmaz.

## Kanıt ve yeniden çalıştırma

- [Özet, source/code pin'leri ve karar](hybrid-preparation-evidence-20261112.json)
- [Tam walk-forward](hybrid-preparation-walkforward-20261112.json.gz)
- [Ablation, aynı-maç panelleri ve kaynak redleri](hybrid-preparation-panels-20261112.json.gz)
- [Gerçek quote / izole prospektif kayıtlar](hybrid-preparation-markets-20261112.json.gz)
- [Docker birleşik runtime ve mesaj örnekleri](hybrid-preparation-runtime-20261112.json)
- Yerel raw-input capsule: `/workspace/research-artifacts/hybrid-preparation-inputs-20261112.tar.gz`
  (**907 dosya / 9,173,435 byte**, SHA-256 özet JSON'da). Ham kaynaklar public repoya eklenmedi.

```sh
python -m pip install -r requirements.txt -r requirements-hybrid-research.txt
# Kapsülü /workspace/scratch altına açın; manifest orijinal absolute yolları içerir.
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m hybrid_engine.acceptance \
  --manifest /workspace/scratch/continuation-20261112/witnessed-final-manifest.json \
  --runtime-report /workspace/scratch/continuation-20261112/runtime-verified.json \
  --output-directory /workspace/scratch/replayed-acceptance
python -m hybrid_engine.runtime_probe \
  --fixture /workspace/scratch/continuation-20261112/runtime/fixture.json --exercise-v1
python -m unittest discover -s tests -v
```

Runtime report ayrı commit'li dosyada da bulunur; capsule raw kaynak/fixture/model
JSON'larını taşır. Quote preparation CLI daha sonra başlamış maçlar için yeni
prospektif kayıt oluşturmayı reddeder; eski oluşturma zamanı uydurmaz.
Üretim modeli değiştirilmedi; main merge ve production deploy bu çalışmada yapılmadı;
üretim kabulü ve ayrı açık onay olmadan geçiş yapılmaz.
