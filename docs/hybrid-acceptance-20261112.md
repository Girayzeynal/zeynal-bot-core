# PR #84 — sıkı kabul denetimi, 12 Kasım 2026

> Bu önceki 640 maçlık kesitin raporudur. Sonraki [kök neden ve arşiv tanığı çalışması](hybrid-root-cause-20261112.md),
> yeni 652 maçlık kesitte 84 gerçek OOS test maçı açtı. Üstünlük kanıtlanmadı; kabul hâlâ engelli.

**Karar: kabul engelli; Faz13 varsayılan kalır. Main merge/deploy yapılmaz.**
Başlangıç commit'i `962e16d0d9b748bf877e89f6d34935a4ddea7f11`.
Bu çalışma yalnızca araştırma dalını günceller; main, V1 komut kayıtları,
production requirements, Fly, volume, SQLite veya secret değiştirmez.

## Gerçek veri denetimi

| Lig / sezon | Gerçek tamamlanmış maç | Periyot + box | Uzatma | Tahmin öncesi fikstür kanıtı | Sıkı geçmiş koşulu |
|---|---:|---:|---:|---:|---:|
| NBA 2026/27 | 160 | 160 | 8 | 0 | 0 |
| EuroLeague 2026/27 | 100 | 100 | 4 | 0 | 0 |
| EuroLeague 2025/26 | 380 | 380 | 15 | 0 | 0 |

İki daha eski native catalog da SHA pin'leriyle denetime eklendi; benzersiz
tamamlanmış maç sayısı 640 kaldı. Yerel eski araştırma kayıtları da tarandı;
geçerli catalog/provenans bulunmayan türetilmiş baseline veya dosya mtime'ı,
geçmiş veri erişim zamanı kabul edilmedi. Tam sezon kapsamı, yalnızca maç
sayısından varsayılmadı. NBA ve güncel EuroLeague kapsamı kısmi sezondur.

NBA hedeflerinin son başlangıcı 11 Kasım 07:00 TSİ; en erken skor kaynağı
gözlemi aynı gün 19:13 TSİ. Güncel EuroLeague hedeflerinin son başlangıcı
6 Kasım 22:45 TSİ; skor gözlemleri 11 Kasım 19:13 TSİ. Önceki EuroLeague
sezonu skorları sezon bittikten sonra 11 Kasım 21:37 TSİ'de gözlendi.
640 box score'un tamamı 12 Kasım yaklaşık 09:13–09:39 TSİ'de gözlendi.
Bu saatler korunur; start+24h veya geçmiş dosya tarihiyle değiştirilmez.
Kaynak saatleri pinned yerel receipt kanıtıdır; bağımsız zaman otoritesi değildir.

Oyuncuların maç sonu dakikaları vardır; doğrulanmış maç öncesi kadro/rotation,
sakatlık ve etiketli possession bağlamı yoktur. Uzatmalı maçların toplam box
istatistikleri normal süre possession eğitimine alınmaz. Tarihsel bookmaker
baremi/quote gözlemi bulunmaz; değerlendirme çizgileri bunun yerine önceden
belirlenen model referans senaryoları olarak açıkça etiketlenir.

## Walk-forward ve sızıntı önlemleri

Yeni giriş noktası `python -m hybrid_engine.acceptance` yalnızca
`PIT_PROVEN_BACKTEST` çalıştırır. Varsayımlı zaman seçeneği yoktur.
Her hedef için cutoff öncesinde gözlenmiş aynı sezon, takım ve başlangıç
kimliğine sahip fikstür kaydı da zorunludur. Sadece geçmiş sonuçların erişimi
kontrol edilip hedef fikstür bilgisi sonradan öğrenilmiş sayılmaz.

Benzersiz başlangıç saatleri üzerinde genişleyen train, geride kalan validation
ve sonraki test blokları vardır. Validation genişliği %20, ilk test %70,
test adımı %10'dur. Etiketi henüz erişilemeyen train/validation satırları purged
edilir. Aynı başlangıç saatindeki maçlar ayrılmaz; test blokları örtüşmez.
Bayesian ve boosting parametreleri validation başlamadan dondurulur;
residual ölçeği ve ensemble yalnızca testten önce bitmiş validation'ı kullanır.
Validation ile seçilen aday, test sonuçları görülmeden kaydedilir.

**Gerçek arşivde uygun sıkı test örneği: 0.** Bu, programın walk-forward
mekaniğinin uygulanmadığı anlamına gelmez; mevcut verinin bu mekanizmaya
kabul edilmediği anlamına gelir. Sentetik testler zaman ayrımını ve gelecek
etiketlerini değiştirince eski tahminlerin değişmediğini doğrular; gerçek
isabet/kalibrasyon kanıtı sayılmaz.

İzlenebilirlik hatası da düzeltildi: önceki input digest yalnızca iki takımın
yakın geçmiş kaynaklarını kapsıyordu; rakip/lig düzeltmesindeki diğer geçmiş
katkıları kapsamıyordu. Artık kullanılan tüm geçmiş, hesaplanan özellikler,
cutoff sınıfı ve hedef kimliği hash kapsamındadır. Her değerlendirilen tahmin
model sürümü, eğitim artifact'i, kod SHA'ları, kaynaklar, veri zamanı,
cutoff, fikstür kanıtı ve input digest taşır.

## Piyasalar, olasılık ve güven

Possession MC/analitik, Bayesian QMC, LightGBM, CatBoost ve Faz13'ün mevcut MC,
QMC ve analitik karşılıkları ayrı tutulur. Her piyasa için ortak maç kümesi
ve aynı barem üzerinde karşılaştırma yapılır; coverage tabloları sıralanamaz.
İlk çeyrek, ilk yarı, maç toplamı, iki takım toplamı ve ev handikabı ayrı
değerlendirilir. Ev handikabı H için kapsama olayı `ev − deplasman > −H`'dir.

Her referans çizgisinde üç senaryo baremi vardır; ALT/İADE/ÜST olasılığı
hesaplanır. Bunlar bookmaker çizgisi, edge veya kazanç iddiası değildir.
Faz13 MC için production dosyasını değiştirmeden, mevcut sampler'ın döndürdüğü
gerçek periyot yolları araştırma adaptöründe izlenir. RNG dizisi ve çıktılar
korunur; adaptör işlemi sonunda orijinal allocator geri yüklenir. Bu adaptör
yalnızca offline/sandbox içindir, üretim isteğine bağlanmaz.
Faz13'ün mevcut gamma-18 periyot belirsizliği ile raporlanan tarihsel nokta
profili aynı şey değildir; bu eski davranış yeni model başarısı gibi sunulmaz.
Gaussian analitik yöntemde çeyrek/yarı olasılıkları aynı integer allocation'ın
tam dağılım dönüşümüyle hesaplanır; periyotların beklenen değerleri de bu yasadan
türetilir. Tüm seviyelerde skor toplamları tutarlıdır; uzatma modellenmez.

Güven yüzdesi ham model olasılığından üretilmez. Yeni kalibrasyon profili
aynı model digest'i, aynı piyasa ve **aynı barem** için en az 100 geçmiş
kalibrasyon ve daha sonra 100 bağımsız audit kaydı ister. Eğitim/test örtüşmesi,
gelecek etiket, yanlış rol veya cutoff geçişi reddedilir. Yeterli audit hücresi,
Wilson aralığı ve audit Brier koşulu olmadan profil doğrulanmış sayılmaz.
Güven endeksi, doğrulanmış hücredeki geçmiş audit frekansının alt sınırıdır;
gelecekteki gerçek kazanma olasılığının ispatı değildir. Bağımlı maçlar için
ek sağlamlık denetimi gerekir; mevcut gerçek profillerin sayısı zaten **0**.

Eksik doğrulanmış girdi, bilinmeyen kadro, doğrulanmamış model uyumu veya
yüksek olasılık uyuşmazlığı halinde çıktı ABSTAIN olur. Araştırma Telegram
metni bu durumda ham yüksek yüzde veya güven endeksi göstermez. Bu render yolu
V1'in mevcut komutlarına kayıt edilmedi; default routing korunur.

MAE/RMSE, Brier, doğal-log log loss, ALT/ÜST kalibrasyon eğrileri ve bin
sayıları raporlanır. Eğri hücrelerinde Wilson aralıkları vardır. Karşılaştırma
aralıkları takım satırları yerine TSİ maç günü kümelerini birlikte bootstrap
eder; az gün kümesinde başarı iddiasından kaçınılır. Önceden belirlenmiş
market/endpoint ailelerinde Bonferroni düzeltmesi uygulanır; bütün modeller
birlikte tek bir family-wise üstünlük iddiası yapılmaz. Günler arası ortak
takım bağımlılığı tamamen çözülmüş sayılmaz.

## Faz13 karşılaştırması ve kabul

| Model | Yeni sıkı OOS n | MAE / RMSE / Brier / log loss / güven aralığı |
|---|---:|---|
| Faz13 MC, QMC, analitik | 0 | Hesaplanamaz |
| Possession MC, analitik | 0 | Hesaplanamaz |
| Bayesian QMC | 0 | Hesaplanamaz |
| LightGBM / CatBoost | 0 | Hesaplanamaz |
| Validation ensemble | 0 | Hesaplanamaz |

`962e16d` raporundaki 66 maçlık varsayımlı EuroLeague deneyinde Faz13 MAE
7.7473, ensemble 7.7789 idi; ensemble Brier farkı güven aralığı sıfırı içeriyordu.
Bu sayılar eski retrospektif bağlamdır; yeni sıkı test sonucu olarak yeniden
sunulmaz. Eski test dönemine model ayarlayıp yeni bağımsız test denmedi.

## Telegram + ML birleşik kaynak testi

Production dosyalarına yazmadan main'in gerçek `build_app`, komut handler'ları,
PTB polling, HTTPX, aiohttp health/ready, legacy motor nesneleri, geçici SQLite,
portable LightGBM/CatBoost, Bayesian, possession ve gerçek Faz13 MC aynı süreçte
çalıştırıldı. Yerel HTTP Telegram API taklidi üzerinden 1 `/nba` + 20 `/analyze`
işlendi ve cevapları alındı. İnternet Telegram teslimatı veya gerçek Fly testi değildir.

Mevcut V1 cache kodu 32 gerçek native payload ile dolduruldu: **16,457,497 byte**
serialized veri resident kaldı; analizlerde yeni payload/cache eviction yolu da
çalıştı. Payload replay zamanı yalnızca sentetik bellek fixtürüdür; geçmiş
erişilebilirlik kanıtı olarak hiçbir backtest'e eklenmedi.

Ölçülen son koşu: Python 3.12.14 / NumPy 1.26.4, tek CPU affinity,
**kernel RLIMIT_AS = 268,435,456 byte**, tepe RSS **143.04 MiB**,
analiz işlemi p95 yaklaşık **263 ms**, health/ready başarılı.
Bu p95 internet mesaj teslimatı süresi değildir. Yalnızca bu workload test edildi;
sınırsız kullanıcı yükü veya production image'ın birebir ölçümü iddia edilmez.

Yerel Docker rootless/cgroup-driver=none olduğundan Docker `--memory` bayrağı
sınırı uygulamıyor. Son koşu ağsız, source mount'ları salt okunur küçük bir
konteynerde yapıldı; gerçek sınır Python sürecinin kernel RLIMIT_AS'idir.
Adres alanı sınırı RSS sınırından daha katıdır; bu sınır altında ölçüm geçti.
Native ML kütüphanelerini yükleme negatif kontrolü aynı adres alanı sınırında
MemoryError verdi; bundan tek başına native backend RSS'inin 256 MiB'ı aştığı
sonucu çıkarılmaz. İstek sırasında SciPy/sklearn/LightGBM/CatBoost yüklenmez.

Portable modeller yeni bir tahmin algoritması değildir: offline öğrenilmiş
numeric ağaçların bounded çıkarımıdır. Pickle veya online fit yoktur; model
digest/cutoff/feature kontrolleri vardır. Native iki backend ile 48'er heldout
sentetik vektörde en büyük skor farkı **0** oldu. Ayrıca bağımsız native oracle
fixtürü, optional ML paketleri olmayan CI'da da iki backend'i doğrular.
Sentetik eğitim/etiketler performans veya kalibrasyon kanıtına karıştırılmadı.

## Doğrulama / yeniden çalıştırma

**424 yerel test geçti.** Bunlara mevcut V1 Telegram regresyonları, zaman
sızıntısı, piyasa/handikap işareti, dönem tutarlılığı, trace restorasyonu,
portable-native eşdeğerlik ve belirsizlikte yüzde göstermeme dahildir.
Son commit'in CI sonuçları PR açıklamasında ayrıca kaydedilir.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m hybrid_engine.acceptance \
  --manifest /absolute/path/acceptance-manifest.json \
  --output-directory /absolute/path/reports \
  --runtime-report /absolute/path/runtime-acceptance-final.json
python -m unittest discover -s tests -v
```

Birleşik bellek fixtürü `hybrid_engine.runtime_fixture.prepare(directory,
cache_sources=...)` ile offline üretilir; yalnızca sentetik eğitim kullanır.
`python -m hybrid_engine.runtime_probe --fixture .../fixture.json` kernel
sınırını kendisi uygular. Yerel loopback soket izni gerekir. Eğitim için
optional araştırma requirements'ı gerekir; portable çıkarım için gerekmez.

Tam yerel raporların SHA-256'ları, kaynak kod pin'leri, ölçüm, test log hash'i
ve eksik metrikler `hybrid-acceptance-evidence-20261112.json` içindedir.
Kalan engeller: gerçek cutoff öncesi arşivle yeterli bağımsız OOS maç,
karşılaştırılabilir gerçek piyasa çizgileri, gerçek kalibrasyon/audit örnekleri,
maç öncesi kadro kanıtı ve production image üzerinde son kaynak doğrulaması.
**Başarılı altyapı/test sonuçları, eksik gerçek performans kanıtının yerine geçmez.**
